import math
import re
from datetime import datetime, timedelta

from flask import abort, current_app, g, session
from mysql.connector import IntegrityError

from app.db import execute, query, transaction
from app.migrations import correction_schema_ready
from app.utils.attendance import effective_record
from app.utils.auth import client_available
from app.utils.features import client_features
from app.utils.validation import ValidationError, day, now, sql_time, text

CORRECTION_KINDS = {
    "check_in": "Salah jam masuk",
    "check_out": "Salah jam pulang",
    "missing_checkout": "Lupa check-out",
    "missing_attendance": "Lupa absensi (belum ada catatan)",
}
CORRECTION_STATUSES = {"pending", "approved", "rejected", "canceled"}

def require_correction_schema():
    if not correction_schema_ready():
        abort(503, description="Koreksi absensi belum dirilis pada database ini. Hubungi Superadmin.")

def lock_scope(employee_id):
    company = query("SELECT * FROM clients WHERE id=%s FOR UPDATE", (g.client["id"],), one=True)
    employee = query("SELECT * FROM employees WHERE id=%s AND client_id=%s FOR UPDATE", (employee_id, g.client["id"]), one=True)
    account = query("SELECT * FROM users WHERE id=%s AND client_id=%s FOR UPDATE", (g.user["id"], g.client["id"]), one=True)
    if not client_available(company) or not account or not account["is_active"] or account["role"] != g.user["role"] or account["session_version"] != session.get("session_version"):
        raise ValidationError("Akun atau layanan tidak lagi aktif. Login kembali.", 403)
    if not employee or (account["role"] == "employee" and employee["user_id"] != account["id"]):
        abort(404)
    if account["role"] == "employee" and not employee["is_active"]:
        abort(403)
    if not client_features(company["id"])["attendance_corrections"]:
        raise ValidationError("Fitur belum diaktifkan untuk perusahaan Anda.", 403)
    return employee

def correction_record(correction_id):
    record = query("""SELECT c.*,e.name,e.employee_number,u.name AS reviewer_name FROM attendance_corrections c
        JOIN employees e ON e.id=c.employee_id AND e.client_id=c.client_id
        LEFT JOIN users u ON u.id=c.reviewed_by AND u.client_id=c.client_id
        WHERE c.id=%s AND c.client_id=%s""", (correction_id, g.client["id"]), one=True)
    if not record or (g.user["role"] == "employee" and record["employee_id"] != g.employee["id"]):
        abort(404)
    return record

def audit(correction_id, action, note):
    execute("""INSERT INTO attendance_correction_audit (client_id,correction_id,actor_id,action,note)
        VALUES (%s,%s,%s,%s,%s)""", (g.client["id"], correction_id, g.user["id"], action, note))

def original_record(employee_id, work_date):
    return query("SELECT * FROM attendances WHERE client_id=%s AND employee_id=%s AND work_date=%s",
        (g.client["id"], employee_id, work_date), one=True)

def attendance_version(original, effective):
    return ((original or {}).get("id"), (original or {}).get("check_in_at"), (original or {}).get("check_out_at"),
        (effective or {}).get("correction_id"), (effective or {}).get("check_in_at"), (effective or {}).get("check_out_at"))

def ensure_no_leave(employee_id, work_date):
    leave = query("""SELECT id FROM leave_requests WHERE client_id=%s AND employee_id=%s
        AND status IN ('pending','approved') AND start_date<=%s AND end_date>=%s LIMIT 1""",
        (g.client["id"], employee_id, work_date, work_date), one=True)
    if leave:
        raise ValidationError("Selesaikan atau batalkan izin/cuti pada tanggal ini sebelum koreksi absensi.", 409)

def proposed_time(data, key, work_date):
    value = str(data.get(key, ""))
    if not re.fullmatch(r"[0-9]{2}:[0-9]{2}(:[0-9]{2})?", value):
        raise ValidationError("Jam usulan wajib diisi dalam format HH:MM atau HH:MM:SS.")
    try:
        return datetime.combine(work_date, datetime.strptime(value, "%H:%M:%S" if len(value) == 8 else "%H:%M").time())
    except ValueError:
        raise ValidationError("Jam usulan tidak valid.") from None

def submit_correction(data):
    work_date = day(data, "work_date")
    kind = data.get("kind")
    if kind not in CORRECTION_KINDS:
        raise ValidationError("Jenis koreksi tidak valid.")
    reason = text(data, "reason", "Alasan", 1000)
    request_key = text(data, "request_key", "Token pengajuan", 32)
    if not re.fullmatch(r"[a-f0-9]{32}", request_key):
        raise ValidationError("Token pengajuan tidak valid. Muat ulang formulir.")
    try:
        with transaction():
            employee = lock_scope(g.employee["id"])
            current = now()
            cutoff = current.date() - timedelta(days=current_app.config["ATTENDANCE_RETENTION_DAYS"])
            if work_date < max(employee["join_date"], cutoff) or work_date > current.date():
                raise ValidationError("Tanggal harus sejak mulai kerja, dalam retensi absensi, dan tidak di masa depan.")
            duplicate = query("""SELECT id FROM attendance_corrections WHERE client_id=%s AND employee_id=%s
                AND ((work_date=%s AND status='pending') OR request_key=%s) LIMIT 1""",
                (g.client["id"], employee["id"], work_date, request_key), one=True)
            if duplicate:
                raise ValidationError("Pengajuan sudah dikirim atau masih menunggu review untuk tanggal ini.", 409)
            ensure_no_leave(employee["id"], work_date)
            original = original_record(employee["id"], work_date)
            effective = effective_record(g.client["id"], employee["id"], work_date)
            if kind == "missing_attendance":
                if effective:
                    raise ValidationError("Catatan kehadiran sudah ada. Pilih koreksi jam masuk/pulang.")
                office = query("SELECT * FROM office_locations WHERE id=%s AND client_id=%s FOR UPDATE",
                    (employee["office_id"], g.client["id"]), one=True)
                if not office or not office["is_active"]:
                    raise ValidationError("Kantor aktif belum ditetapkan. Hubungi Admin PT.")
                office_id, office_name = office["id"], office["name"]
                scheduled_start, scheduled_end = sql_time(office["start_time"]), sql_time(office["end_time"])
                check_in = proposed_time(data, "check_in", work_date)
                check_out = proposed_time(data, "check_out", work_date)
            else:
                if not effective:
                    raise ValidationError("Belum ada kehadiran pada tanggal ini. Pilih lupa absensi.")
                office_id, office_name = effective["office_id"], effective["office_name"]
                scheduled_start, scheduled_end = sql_time(effective["scheduled_start"]), sql_time(effective["scheduled_end"])
                check_in, check_out = effective["check_in_at"], effective["check_out_at"]
                if kind == "check_in":
                    check_in = proposed_time(data, "check_in", work_date)
                    unchanged_key, unchanged_time = "check_out", check_out
                else:
                    if (kind == "missing_checkout") != (check_out is None):
                        raise ValidationError("Pilih lupa check-out jika jam pulang belum ada, atau salah jam pulang jika sudah ada.")
                    check_out = proposed_time(data, "check_out", work_date)
                    unchanged_key, unchanged_time = "check_in", check_in
                if data.get(unchanged_key) and proposed_time(data, unchanged_key, work_date) != unchanged_time:
                    raise ValidationError("Isi hanya jam yang dikoreksi; jam lainnya tetap mengikuti catatan efektif.")
                if (check_in, check_out) == (effective["check_in_at"], effective["check_out_at"]):
                    raise ValidationError("Jam usulan sama dengan catatan efektif.")
            if check_in > current or (check_out and check_out > current):
                raise ValidationError("Jam usulan tidak boleh di masa depan (WIB).")
            if check_out and check_out <= check_in:
                raise ValidationError("Jam pulang harus setelah jam masuk pada tanggal yang sama.")
            late_minutes = math.ceil(max(0, (check_in - datetime.combine(work_date, scheduled_start)).total_seconds()) / 60)
            correction_id = execute("""INSERT INTO attendance_corrections
                (client_id,employee_id,work_date,kind,request_key,reason,source_attendance_id,source_check_in_at,
                 source_check_out_at,base_correction_id,base_check_in_at,base_check_out_at,proposed_check_in_at,
                 proposed_check_out_at,office_id,office_name,scheduled_start,scheduled_end,late_minutes,submitted_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (g.client["id"], employee["id"], work_date, kind, request_key, reason, *attendance_version(original, effective),
                 check_in, check_out, office_id, office_name, str(scheduled_start), str(scheduled_end), late_minutes, g.user["id"])).lastrowid
            audit(correction_id, "submitted", reason)
            return correction_id
    except IntegrityError:
        raise ValidationError("Pengajuan bertabrakan dengan data yang sudah tersimpan. Muat ulang halaman.", 409) from None

def decide_correction(correction_id, status, note=""):
    initial = correction_record(correction_id)
    with transaction():
        lock_scope(initial["employee_id"])
        record = query("SELECT * FROM attendance_corrections WHERE id=%s AND client_id=%s FOR UPDATE",
            (correction_id, g.client["id"]), one=True)
        if not record:
            abort(404)
        if record["status"] != "pending":
            raise ValidationError("Pengajuan sudah diproses; keputusan tidak dapat diulang atau diubah.", 409)
        if status == "approved":
            original = original_record(record["employee_id"], record["work_date"])
            effective = effective_record(g.client["id"], record["employee_id"], record["work_date"])
            baseline = tuple(record[key] for key in ("source_attendance_id", "source_check_in_at", "source_check_out_at",
                "base_correction_id", "base_check_in_at", "base_check_out_at"))
            if baseline != attendance_version(original, effective):
                raise ValidationError("Catatan kehadiran berubah sejak pengajuan. Tolak atau batalkan, lalu ajukan ulang.", 409)
            ensure_no_leave(record["employee_id"], record["work_date"])
        execute("""UPDATE attendance_corrections SET status=%s,reviewed_by=%s,reviewed_at=%s,admin_note=%s
            WHERE id=%s AND client_id=%s AND status='pending'""",
            (status, g.user["id"], now(), note, correction_id, g.client["id"]))
        audit(correction_id, status, note)
