import math
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from mysql.connector import IntegrityError

from app.db import execute, query, transaction
from app.utils.auth import client_available, roles_required
from app.utils.attendance import attendance_source, effective_record
from app.utils.geofence import validate_location
from app.utils.photos import decode_selfie, private_path, remove_selfie, save_selfie
from app.utils.validation import JAKARTA, ValidationError, day, now, number, pagination, sql_time, text

bp = Blueprint("employee", __name__, url_prefix="/employee")


def today_attendance(work_date=None):
    return query("SELECT * FROM attendances WHERE employee_id=%s AND client_id=%s AND work_date=%s", (g.employee["id"], g.client["id"], work_date or now().date()), one=True)


def office_for(employee, attendance=None, lock=False):
    office_id = attendance["office_id"] if attendance else employee["office_id"]
    office = query("SELECT * FROM office_locations WHERE id=%s AND client_id=%s" + (" FOR UPDATE" if lock else ""), (office_id, g.client["id"]), one=True) if office_id else None
    if not office or not office["is_active"]:
        raise ValidationError("Kantor belum ditetapkan atau tidak aktif. Hubungi Admin PT.")
    if attendance:
        office.update(name=attendance["office_name"], latitude=attendance["office_latitude"], longitude=attendance["office_longitude"], radius_m=attendance["office_radius_m"], max_accuracy_m=attendance["office_max_accuracy_m"], start_time=attendance["scheduled_start"], end_time=attendance["scheduled_end"])
    return office


def require_privacy():
    if not g.employee["privacy_accepted_at"] or g.employee["privacy_version"] != current_app.config["PRIVACY_VERSION"]:
        raise ValidationError("Baca dan setujui pemberitahuan privasi sebelum absensi.", 403)


def serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="elrise-attendance")


@bp.get("/")
@roles_required("employee")
def dashboard():
    today = now().date()
    record = effective_record(g.client["id"], g.employee["id"], today)
    office = query("SELECT * FROM office_locations WHERE id=%s AND client_id=%s", (g.employee["office_id"], g.client["id"]), one=True)
    source = attendance_source()
    stats = query(f"SELECT COUNT(*) AS total,COALESCE(SUM(status='late'),0) AS late FROM {source} effective WHERE employee_id=%s AND client_id=%s AND work_date BETWEEN %s AND %s", (g.employee["id"], g.client["id"], today.replace(day=1), today), one=True)
    recent = query(f"SELECT * FROM {source} effective WHERE employee_id=%s AND client_id=%s ORDER BY work_date DESC LIMIT 4", (g.employee["id"], g.client["id"]))
    return render_template("employee/dashboard.html", employee=g.employee, office=office, attendance=record, stats=stats, recent=recent)


@bp.route("/privacy", methods=["GET", "POST"])
@roles_required("employee")
def privacy():
    if request.method == "POST":
        if request.form.get("consent") != "1":
            raise ValidationError("Persetujuan eksplisit diperlukan sebelum menggunakan absensi GPS/selfie.")
        execute("UPDATE employees SET privacy_accepted_at=%s,privacy_version=%s WHERE id=%s AND client_id=%s AND user_id=%s", (now(), current_app.config["PRIVACY_VERSION"], g.employee["id"], g.client["id"], g.user["id"]))
        flash("Persetujuan tersimpan. GPS dan kamera hanya digunakan saat Anda mengaktifkan absensi.", "success")
        return redirect(url_for("employee.attendance"))
    return render_template("employee/privacy.html", employee=g.employee)


@bp.get("/attendance")
@roles_required("employee")
def attendance():
    if not g.employee["privacy_accepted_at"] or g.employee["privacy_version"] != current_app.config["PRIVACY_VERSION"]:
        return redirect(url_for("employee.privacy"))
    record = today_attendance()
    try:
        office = office_for(g.employee, record)
        error = None
    except ValidationError as issue:
        office, error = None, str(issue)
    office_data = {"name": office["name"], "latitude": float(office["latitude"]), "longitude": float(office["longitude"]), "radius_m": office["radius_m"], "max_accuracy_m": office["max_accuracy_m"]} if office else None
    effective = effective_record(g.client["id"], g.employee["id"], now().date())
    if effective and effective["correction_id"]:
        record = effective
    return render_template("employee/attendance.html", attendance=record, office=office, office_data=office_data, error=error)


@bp.get("/attendance/challenge")
@roles_required("employee")
def attendance_challenge():
    require_privacy()
    current = now()
    record = today_attendance(current.date())
    effective = effective_record(g.client["id"], g.employee["id"], current.date())
    if effective and effective["correction_id"] and effective["check_out_at"]:
        raise ValidationError("Kehadiran hari ini sudah lengkap melalui koreksi yang disetujui.", 409)
    if record and record["check_out_at"]:
        raise ValidationError("Absensi hari ini sudah lengkap.", 409)
    office = office_for(g.employee, record)
    action = "check_out" if record else "check_in"
    nonce = secrets.token_urlsafe(24)
    session["attendance_nonce"] = nonce
    token = serializer().dumps({"user_id": g.user["id"], "client_id": g.client["id"], "office_id": office["id"], "date": current.date().isoformat(), "action": action, "nonce": nonce})
    return jsonify(ok=True, challenge=token, action=action, server_time=current.replace(tzinfo=JAKARTA).timestamp() * 1000)


@bp.post("/attendance/submit")
@roles_required("employee")
def submit_attendance():
    require_privacy()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Kirim data absensi dalam format JSON.")
    token = data.get("challenge", "")
    if not isinstance(token, str) or len(token) > 4096:
        raise ValidationError("Sesi pengambilan selfie tidak valid.")
    try:
        challenge = serializer().loads(token, max_age=120)
    except (BadSignature, SignatureExpired):
        raise ValidationError("Sesi selfie berakhir. Perbarui GPS dan ambil ulang selfie.") from None
    current = now()
    if challenge.get("user_id") != g.user["id"] or challenge.get("client_id") != g.client["id"] or challenge.get("date") != current.date().isoformat() or challenge.get("action") != data.get("action") or not session.get("attendance_nonce") or not secrets.compare_digest(challenge.get("nonce", ""), session["attendance_nonce"]):
        raise ValidationError("Sesi selfie tidak sesuai. Ambil ulang selfie.")
    device_ms = number(data, "device_time", 0, 32503680000000)
    location_ms = number(data, "location_time", 0, 32503680000000)
    official_ms = current.replace(tzinfo=JAKARTA).timestamp() * 1000
    if abs(device_ms - official_ms) > 300000:
        raise ValidationError("Jam perangkat berbeda lebih dari 5 menit. Aktifkan tanggal/jam otomatis.")
    if not -5000 <= device_ms - location_ms <= 60000:
        raise ValidationError("Lokasi GPS kedaluwarsa. Perbarui lokasi lalu ambil ulang selfie.")
    relative = None
    try:
        with transaction():
            company = query("SELECT * FROM clients WHERE id=%s FOR UPDATE", (g.client["id"],), one=True)
            employee = query("SELECT * FROM employees WHERE id=%s AND client_id=%s AND user_id=%s FOR UPDATE", (g.employee["id"], g.client["id"], g.user["id"]), one=True)
            account = query("SELECT * FROM users WHERE id=%s AND client_id=%s FOR UPDATE", (g.user["id"], g.client["id"]), one=True)
            if not client_available(company) or not employee or not employee["is_active"] or not account["is_active"] or account["session_version"] != session.get("session_version"):
                raise ValidationError("Akun atau layanan tidak lagi aktif. Login kembali.", 403)
            if not employee["privacy_accepted_at"] or employee["privacy_version"] != current_app.config["PRIVACY_VERSION"]:
                raise ValidationError("Persetujuan privasi tidak lagi berlaku.", 403)
            record = today_attendance(current.date())
            effective = effective_record(company["id"], employee["id"], current.date())
            if effective and effective["correction_id"] and effective["check_out_at"]:
                raise ValidationError("Kehadiran hari ini sudah lengkap melalui koreksi yang disetujui.", 409)
            action = data["action"]
            if action == "check_in" and record:
                raise ValidationError("Anda sudah check-in hari ini.", 409)
            if action == "check_out" and (not record or record["check_out_at"]):
                raise ValidationError("Check-out memerlukan check-in dan hanya boleh sekali.", 409)
            if employee["join_date"] > current.date():
                raise ValidationError("Tanggal mulai kerja belum berlaku.", 403)
            office = office_for(employee, record, lock=True)
            if challenge["office_id"] != office["id"]:
                raise ValidationError("Penetapan kantor berubah. Muat ulang halaman absensi.")
            if action == "check_in":
                if str(current.isoweekday()) not in office["working_days"].split(","):
                    raise ValidationError("Hari ini bukan hari kerja kantor Anda.")
                leave = query("SELECT id FROM leave_requests WHERE employee_id=%s AND client_id=%s AND status='approved' AND start_date<=%s AND end_date>=%s LIMIT 1", (employee["id"], company["id"], current.date(), current.date()), one=True)
                if leave:
                    raise ValidationError("Anda memiliki izin/cuti yang disetujui hari ini.")
            latitude, longitude, accuracy, distance = validate_location(data, office)
            content = decode_selfie(data.get("selfie"), current, latitude, longitude)
            relative = save_selfie(content, company["id"], employee["id"])
            device_at = datetime.fromtimestamp(device_ms / 1000, JAKARTA).replace(tzinfo=None)
            if action == "check_in":
                scheduled = datetime.combine(current.date(), sql_time(office["start_time"]))
                late_seconds = max(0, (current - scheduled).total_seconds())
                late_minutes = math.ceil(late_seconds / 60)
                attendance_id = execute("""INSERT INTO attendances
                    (client_id,employee_id,office_id,work_date,status,late_minutes,office_name,office_latitude,office_longitude,
                     office_radius_m,office_max_accuracy_m,scheduled_start,scheduled_end,check_in_at,check_in_latitude,
                     check_in_longitude,check_in_accuracy,check_in_distance,check_in_device_at,check_in_photo)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (company["id"],employee["id"],office["id"],current.date(),"late" if late_seconds else "present",late_minutes,office["name"],
                     office["latitude"],office["longitude"],office["radius_m"],office["max_accuracy_m"],str(sql_time(office["start_time"])),str(sql_time(office["end_time"])),
                     current,latitude,longitude,accuracy,distance,device_at,relative)).lastrowid
            else:
                if current < record["check_in_at"]:
                    raise ValidationError("Jam server berubah. Hubungi administrator.")
                attendance_id = record["id"]
                execute("UPDATE attendances SET check_out_at=%s,check_out_latitude=%s,check_out_longitude=%s,check_out_accuracy=%s,check_out_distance=%s,check_out_device_at=%s,check_out_photo=%s WHERE id=%s AND client_id=%s AND employee_id=%s AND check_out_at IS NULL", (current,latitude,longitude,accuracy,distance,device_at,relative,attendance_id,company["id"],employee["id"]))
    except BaseException as error:
        remove_selfie(relative)
        if isinstance(error, IntegrityError):
            raise ValidationError("Absensi hari ini sudah tercatat.", 409) from None
        raise
    session.pop("attendance_nonce", None)
    return jsonify(ok=True, message=f"{'Check-in' if data['action'] == 'check_in' else 'Check-out'} berhasil pada {current:%H:%M} WIB.", attendance_id=attendance_id, distance=round(distance, 2), server_time=current.isoformat() + "+07:00")


@bp.get("/history")
@roles_required("employee")
def history():
    page, limit, offset = pagination()
    from app.utils.validation import date_range

    start, end = date_range(request.args)
    params = (g.employee["id"], g.client["id"], start, end)
    source = attendance_source()
    total = query(f"SELECT COUNT(*) AS total FROM {source} effective WHERE employee_id=%s AND client_id=%s AND work_date BETWEEN %s AND %s", params, one=True)["total"]
    records = query(f"SELECT * FROM {source} effective WHERE employee_id=%s AND client_id=%s AND work_date BETWEEN %s AND %s ORDER BY work_date DESC LIMIT %s OFFSET %s", params + (limit, offset))
    return render_template("employee/history.html", attendances=records, total=total, page=page, limit=limit, start=start, end=end)


@bp.get("/photos/<int:attendance_id>/<phase>")
@roles_required("admin", "employee")
def photo(attendance_id, phase):
    if phase not in {"in", "out"}:
        abort(404)
    record = query("SELECT * FROM attendances WHERE id=%s AND client_id=%s", (attendance_id, g.client["id"]), one=True)
    if not record or (g.user["role"] == "employee" and record["employee_id"] != g.employee["id"]):
        abort(404)
    relative = record["check_in_photo" if phase == "in" else "check_out_photo"]
    if not relative:
        abort(404, description="Foto telah dihapus sesuai kebijakan retensi atau belum tersedia.")
    path = private_path(relative)
    if not path.is_file():
        abort(404, description="Foto tidak tersedia.")
    response = send_file(path, mimetype="image/jpeg", conditional=False, etag=False)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/leaves", methods=["GET", "POST"])
@roles_required("employee")
def leaves():
    if request.method == "POST":
        kind = request.form.get("kind")
        if kind not in {"izin", "cuti", "sakit"}:
            raise ValidationError("Jenis pengajuan tidak valid.")
        start, end = day(request.form, "start_date"), day(request.form, "end_date")
        if start < now().date() or end < start or (end - start).days > 89:
            raise ValidationError("Tanggal pengajuan dimulai hari ini/ke depan, maksimal 90 hari.")
        reason = text(request.form, "reason", "Alasan", 1000)
        with transaction():
            query("SELECT id FROM employees WHERE id=%s AND client_id=%s FOR UPDATE", (g.employee["id"], g.client["id"]), one=True)
            existing = query("SELECT id FROM leave_requests WHERE employee_id=%s AND client_id=%s AND status IN ('pending','approved') AND start_date<=%s AND end_date>=%s LIMIT 1", (g.employee["id"], g.client["id"], end, start), one=True)
            attendance_exists = query(f"SELECT employee_id FROM {attendance_source()} effective WHERE employee_id=%s AND client_id=%s AND work_date BETWEEN %s AND %s LIMIT 1", (g.employee["id"], g.client["id"], start, end), one=True)
            if existing or attendance_exists:
                raise ValidationError("Tanggal bertabrakan dengan pengajuan atau absensi yang sudah ada.")
            execute("INSERT INTO leave_requests (client_id,employee_id,kind,start_date,end_date,reason) VALUES (%s,%s,%s,%s,%s,%s)", (g.client["id"], g.employee["id"], kind, start, end, reason))
        flash("Pengajuan dikirim ke Admin PT.", "success")
        return redirect(url_for("employee.leaves"))
    page, limit, offset = pagination()
    params = (g.employee["id"], g.client["id"])
    total = query("SELECT COUNT(*) AS total FROM leave_requests WHERE employee_id=%s AND client_id=%s", params, one=True)["total"]
    records = query("SELECT * FROM leave_requests WHERE employee_id=%s AND client_id=%s ORDER BY id DESC LIMIT %s OFFSET %s", params + (limit, offset))
    return render_template("employee/leaves.html", leaves=records, page=page, limit=limit, total=total)


@bp.post("/leaves/<int:leave_id>/cancel")
@roles_required("employee")
def cancel_leave(leave_id):
    result = execute("UPDATE leave_requests SET status='canceled' WHERE id=%s AND employee_id=%s AND client_id=%s AND status='pending'", (leave_id, g.employee["id"], g.client["id"]))
    if not result.rowcount:
        abort(404)
    flash("Pengajuan dibatalkan.", "success")
    return redirect(url_for("employee.leaves"))


@bp.get("/profile")
@roles_required("employee")
def profile():
    office = query("SELECT name FROM office_locations WHERE id=%s AND client_id=%s", (g.employee["office_id"], g.client["id"]), one=True)
    return render_template("employee/profile.html", employee=g.employee, office=office)


@bp.post("/privacy/withdraw")
@roles_required("employee")
def withdraw_privacy():
    execute("UPDATE employees SET privacy_accepted_at=NULL,privacy_version=NULL WHERE id=%s AND client_id=%s AND user_id=%s", (g.employee["id"], g.client["id"], g.user["id"]))
    session.pop("attendance_nonce", None)
    flash("Persetujuan ditarik; absensi GPS/selfie dinonaktifkan. Hubungi HR untuk alternatif absensi dan permohonan terkait data yang telah tersimpan.", "success")
    return redirect(url_for("employee.profile"))
