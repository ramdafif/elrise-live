import secrets

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app.db import query
from app.utils.attendance import effective_record
from app.utils.auth import roles_required
from app.utils.corrections import (CORRECTION_KINDS, CORRECTION_STATUSES, attendance_version, correction_record,
    decide_correction, original_record, require_correction_schema, submit_correction)
from app.utils.features import feature_required
from app.utils.validation import ValidationError, day, pagination, text

bp = Blueprint("corrections", __name__)

def request_list(employee=False):
    require_correction_schema()
    page, limit, offset = pagination()
    status = request.args.get("status", "" if employee else "pending")
    if status and status not in CORRECTION_STATUSES:
        raise ValidationError("Status koreksi tidak valid.")
    where, params = "c.client_id=%s", [g.client["id"]]
    if employee:
        where += " AND c.employee_id=%s"
        params.append(g.employee["id"])
    if status:
        where += " AND c.status=%s"
        params.append(status)
    total = query(f"SELECT COUNT(*) AS total FROM attendance_corrections c WHERE {where}", tuple(params), one=True)["total"]
    records = query(f"""SELECT c.*,e.name,e.employee_number FROM attendance_corrections c
        JOIN employees e ON e.id=c.employee_id AND e.client_id=c.client_id WHERE {where}
        ORDER BY c.id DESC LIMIT %s OFFSET %s""", tuple(params) + (limit, offset))
    return render_template("corrections/list.html", corrections=records, status=status, page=page,
        limit=limit, total=total, kinds=CORRECTION_KINDS)

def request_detail(correction_id):
    require_correction_schema()
    record = correction_record(correction_id)
    original = original_record(record["employee_id"], record["work_date"])
    effective = effective_record(g.client["id"], record["employee_id"], record["work_date"])
    baseline = tuple(record[key] for key in ("source_attendance_id", "source_check_in_at", "source_check_out_at",
        "base_correction_id", "base_check_in_at", "base_check_out_at"))
    stale = record["status"] == "pending" and baseline != attendance_version(original, effective)
    audit = query("""SELECT a.*,u.name AS actor_name FROM attendance_correction_audit a JOIN users u
        ON u.id=a.actor_id AND u.client_id=a.client_id WHERE a.client_id=%s AND a.correction_id=%s ORDER BY a.id""",
        (g.client["id"], correction_id))
    return render_template("corrections/detail.html", correction=record, original=original, effective=effective,
        stale=stale, audit=audit, kinds=CORRECTION_KINDS)

@bp.get("/employee/corrections")
@roles_required("employee")
@feature_required("attendance_corrections")
def employee_requests():
    return request_list(employee=True)

@bp.route("/employee/corrections/new", methods=["GET", "POST"])
@roles_required("employee")
@feature_required("attendance_corrections")
def new_request():
    require_correction_schema()
    if request.method == "POST":
        correction_id = submit_correction(request.form)
        flash("Koreksi dikirim ke Admin PT. Kehadiran berubah hanya setelah disetujui.", "success")
        return redirect(url_for("corrections.employee_detail", correction_id=correction_id))
    work_date = day(request.args, "work_date") if request.args.get("work_date") else None
    effective = effective_record(g.client["id"], g.employee["id"], work_date) if work_date else None
    return render_template("corrections/form.html", kinds=CORRECTION_KINDS, work_date=work_date,
        effective=effective, employee=g.employee, request_key=secrets.token_hex(16))

@bp.get("/employee/corrections/<int:correction_id>")
@roles_required("employee")
@feature_required("attendance_corrections")
def employee_detail(correction_id):
    return request_detail(correction_id)

@bp.post("/employee/corrections/<int:correction_id>/cancel")
@roles_required("employee")
@feature_required("attendance_corrections")
def cancel(correction_id):
    require_correction_schema()
    decide_correction(correction_id, "canceled")
    flash("Pengajuan koreksi dibatalkan.", "success")
    return redirect(url_for("corrections.employee_detail", correction_id=correction_id))

@bp.get("/admin/corrections")
@roles_required("admin")
@feature_required("attendance_corrections")
def admin_requests():
    return request_list()

@bp.get("/admin/corrections/<int:correction_id>")
@roles_required("admin")
@feature_required("attendance_corrections")
def admin_detail(correction_id):
    return request_detail(correction_id)

@bp.post("/admin/corrections/<int:correction_id>/review")
@roles_required("admin")
@feature_required("attendance_corrections")
def review(correction_id):
    require_correction_schema()
    status = request.form.get("status")
    if status not in {"approved", "rejected"}:
        raise ValidationError("Keputusan koreksi tidak valid.")
    note = text(request.form, "admin_note", "Catatan keputusan", 500, status == "rejected")
    decide_correction(correction_id, status, note)
    flash("Keputusan dan audit koreksi tersimpan.", "success")
    return redirect(url_for("corrections.admin_detail", correction_id=correction_id))
