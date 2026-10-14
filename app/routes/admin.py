from collections import Counter
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash

from app.db import execute, query, transaction
from app.utils.auth import roles_required
from app.utils.excel import IMPORT_HEADERS, read_employees, workbook_bytes
from app.utils.reports import report_data
from app.utils.validation import ValidationError, day, email, integer, now, number, pagination, password, text, time_value

bp = Blueprint("admin", __name__, url_prefix="/admin")


def employee_record(employee_id, lock=False):
    record = query("SELECT e.*,u.email FROM employees e JOIN users u ON u.id=e.user_id AND u.client_id=e.client_id WHERE e.id=%s AND e.client_id=%s" + (" FOR UPDATE" if lock else ""), (employee_id, g.client["id"]), one=True)
    if not record:
        abort(404)
    return record


def office_record(office_id):
    record = query("SELECT * FROM office_locations WHERE id=%s AND client_id=%s", (office_id, g.client["id"]), one=True)
    if not record:
        abort(404)
    return record


def lock_client_capacity(adding):
    company = query("SELECT * FROM clients WHERE id=%s FOR UPDATE", (g.client["id"],), one=True)
    count = query("SELECT COUNT(*) AS total FROM employees WHERE client_id=%s AND is_active=1", (company["id"],), one=True)["total"]
    if count + adding > company["employee_limit"]:
        raise ValidationError("Batas karyawan aktif perusahaan tercapai. Hubungi Elrise untuk menambah kapasitas.")


def employee_values(data):
    name = text(data, "name", "Nama karyawan")
    address = email(data)
    number_id = text(data, "employee_number", "Nomor karyawan", 32)
    department = text(data, "department", "Departemen", 120, False)
    job = text(data, "job_title", "Jabatan", 120, False)
    phone = text(data, "phone", "Telepon", 32, False)
    join_date = day(data, "join_date")
    office_id = integer(data, "office_id", 1, 2147483647)
    office = office_record(office_id)
    if not office["is_active"]:
        raise ValidationError("Pilih kantor yang aktif.")
    return name, address, number_id, department, job, phone, join_date, office_id


def insert_employee(values, hashed):
    name, address, number_id, department, job, phone, join_date, office_id = values
    user_id = execute("INSERT INTO users (client_id,name,email,password_hash,role) VALUES (%s,%s,%s,%s,'employee')", (g.client["id"], name, address, hashed)).lastrowid
    return execute("""INSERT INTO employees (client_id,user_id,name,employee_number,department,job_title,phone,join_date,office_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (g.client["id"], user_id, name, number_id, department, job, phone, join_date, office_id)).lastrowid


@bp.get("/")
@roles_required("admin")
def dashboard():
    today = now().date()
    rows, start, end = report_data({"start": today.isoformat(), "end": today.isoformat()})
    counts = Counter(row["status"] for row in rows)
    stats = {"employees": query("SELECT COUNT(*) AS total FROM employees WHERE client_id=%s AND is_active=1", (g.client["id"],), one=True)["total"],
             "present": counts["present"] + counts["late"], "late": counts["late"], "absent": counts["absent"], "leave": counts["leave"]}
    pending = query("SELECT COUNT(*) AS total FROM leave_requests WHERE client_id=%s AND status='pending'", (g.client["id"],), one=True)["total"]
    chart = query("SELECT work_date,COUNT(*) AS total,SUM(status='late') AS late FROM attendances WHERE client_id=%s AND work_date BETWEEN %s AND %s GROUP BY work_date ORDER BY work_date", (g.client["id"], today - timedelta(days=6), today))
    mapped = {entry["work_date"]: entry for entry in chart}
    week = [{"date": today - timedelta(days=offset), **mapped.get(today - timedelta(days=offset), {"total": 0, "late": 0})} for offset in range(6, -1, -1)]
    return render_template("admin/dashboard.html", stats=stats, pending=pending, rows=rows[:8], week=week)


@bp.route("/company", methods=["GET", "POST"])
@roles_required("admin")
def company():
    if request.method == "POST":
        name = text(request.form, "name", "Nama PT", 160)
        address = text(request.form, "address", "Alamat", 500)
        contact = email(request.form)
        phone = text(request.form, "phone", "Telepon", 32, False)
        retention = integer(request.form, "photo_retention_days", 1, 365) if request.form.get("photo_retention_days") else None
        execute("UPDATE clients SET name=%s,address=%s,email=%s,phone=%s,photo_retention_days=%s WHERE id=%s", (name, address, contact, phone, retention, g.client["id"]))
        flash("Profil perusahaan disimpan.", "success")
        return redirect(url_for("admin.company"))
    return render_template("admin/company.html")


@bp.get("/employees")
@roles_required("admin")
def employees():
    page, limit, offset = pagination()
    search = text(request.args, "q", "Pencarian", 100, False)
    active = request.args.get("active", "")
    if active not in {"", "0", "1"}:
        raise ValidationError("Filter karyawan tidak valid.")
    where = "e.client_id=%s AND (e.name LIKE %s OR e.employee_number LIKE %s OR u.email LIKE %s)"
    params = [g.client["id"], *([f"%{search}%"] * 3)]
    if active:
        where += " AND e.is_active=%s"
        params.append(int(active))
    joins = "FROM employees e JOIN users u ON u.id=e.user_id AND u.client_id=e.client_id LEFT JOIN office_locations o ON o.id=e.office_id AND o.client_id=e.client_id"
    total = query(f"SELECT COUNT(*) AS total {joins} WHERE {where}", tuple(params), one=True)["total"]
    records = query(f"SELECT e.*,u.email,o.name AS office_name {joins} WHERE {where} ORDER BY e.name,e.id LIMIT %s OFFSET %s", tuple(params) + (limit, offset))
    return render_template("admin/employees.html", employees=records, page=page, limit=limit, total=total, search=search, active=active)


@bp.route("/employees/new", methods=["GET", "POST"])
@bp.route("/employees/<int:employee_id>/edit", methods=["GET", "POST"])
@roles_required("admin")
def employee_form(employee_id=None):
    record = employee_record(employee_id) if employee_id else None
    offices = query("SELECT * FROM office_locations WHERE client_id=%s AND is_active=1 ORDER BY name", (g.client["id"],))
    if request.method == "POST":
        values = employee_values(request.form)
        hashed = generate_password_hash(password(request.form.get("password"))) if not record else None
        active = int(request.form.get("is_active") == "1") if record else 1
        try:
            with transaction():
                lock_client_capacity(0)
                if record:
                    locked = employee_record(employee_id, lock=True)
                    if active and not locked["is_active"]:
                        lock_client_capacity(1)
                    name, address, number_id, department, job, phone, join_date, office_id = values
                    execute("UPDATE users SET name=%s,email=%s,is_active=%s,session_version=session_version+1 WHERE id=%s AND client_id=%s AND role='employee'", (name, address, active, locked["user_id"], g.client["id"]))
                    execute("""UPDATE employees SET name=%s,employee_number=%s,department=%s,job_title=%s,phone=%s,
                        join_date=%s,office_id=%s,is_active=%s WHERE id=%s AND client_id=%s""", (name, number_id, department, job, phone, join_date, office_id, active, employee_id, g.client["id"]))
                else:
                    lock_client_capacity(1)
                    insert_employee(values, hashed)
        except IntegrityError:
            raise ValidationError("Email atau nomor karyawan sudah digunakan. Tidak ada perubahan yang disimpan.") from None
        flash("Data dan akun login karyawan berhasil disimpan.", "success")
        return redirect(url_for("admin.employees"))
    return render_template("admin/employee_form.html", employee=record, offices=offices)


@bp.post("/employees/<int:employee_id>/reset")
@roles_required("admin")
def reset_employee(employee_id):
    record = employee_record(employee_id)
    hashed = generate_password_hash(password(request.form.get("password")))
    execute("UPDATE users SET password_hash=%s,session_version=session_version+1,must_change_password=1 WHERE id=%s AND client_id=%s AND role='employee'", (hashed, record["user_id"], g.client["id"]))
    flash("Password karyawan direset; sesi lama dicabut.", "success")
    return redirect(url_for("admin.employee_form", employee_id=employee_id))


@bp.post("/employees/<int:employee_id>/delete")
@roles_required("admin")
def delete_employee(employee_id):
    with transaction():
        lock_client_capacity(0)
        record = employee_record(employee_id, lock=True)
        attended = query("SELECT id FROM attendances WHERE employee_id=%s AND client_id=%s LIMIT 1", (employee_id, g.client["id"]), one=True)
        leave = query("SELECT id FROM leave_requests WHERE employee_id=%s AND client_id=%s LIMIT 1", (employee_id, g.client["id"]), one=True)
        if attended or leave:
            raise ValidationError("Karyawan memiliki riwayat. Nonaktifkan akun melalui Edit; penghapusan mengikuti kebijakan retensi.")
        execute("DELETE FROM employees WHERE id=%s AND client_id=%s", (employee_id, g.client["id"]))
        execute("DELETE FROM users WHERE id=%s AND client_id=%s AND role='employee'", (record["user_id"], g.client["id"]))
    flash("Karyawan dan akun login dihapus.", "success")
    return redirect(url_for("admin.employees"))


@bp.route("/employees/import", methods=["GET", "POST"])
@roles_required("admin")
def import_employees():
    if request.method == "POST":
        parsed = read_employees(request.files.get("file"))
        prepared, seen_emails, seen_numbers = [], set(), set()
        for line, data in parsed:
            try:
                values = employee_values(data)
                initial = password(data.get("password"))
                if values[1] in seen_emails or values[2] in seen_numbers:
                    raise ValidationError("Email atau nomor karyawan duplikat di file.")
                seen_emails.add(values[1])
                seen_numbers.add(values[2])
                prepared.append((values, generate_password_hash(initial)))
            except ValidationError as error:
                raise ValidationError(f"Baris {line}: {error}") from None
        try:
            with transaction():
                lock_client_capacity(len(prepared))
                for values, hashed in prepared:
                    insert_employee(values, hashed)
        except IntegrityError:
            raise ValidationError("Import dibatalkan: email/nomor karyawan sudah terdaftar. Seluruh import di-rollback.") from None
        flash(f"{len(prepared)} karyawan dan akun berhasil diimport. Password awal wajib diganti saat login.", "success")
        return redirect(url_for("admin.employees"))
    offices = query("SELECT id,name FROM office_locations WHERE client_id=%s AND is_active=1 ORDER BY name", (g.client["id"],))
    return render_template("admin/import.html", offices=offices)


@bp.get("/employees/template.xlsx")
@roles_required("admin")
def import_template():
    return send_file(workbook_bytes(IMPORT_HEADERS, [], "Karyawan"), as_attachment=True, download_name="elrise-template-karyawan.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.get("/offices")
@roles_required("admin")
def offices():
    records = query("SELECT o.*,(SELECT COUNT(*) FROM employees e WHERE e.office_id=o.id AND e.client_id=o.client_id AND e.is_active=1) AS employee_count FROM office_locations o WHERE o.client_id=%s ORDER BY o.id", (g.client["id"],))
    return render_template("admin/offices.html", offices=records)


@bp.route("/offices/new", methods=["GET", "POST"])
@bp.route("/offices/<int:office_id>/edit", methods=["GET", "POST"])
@roles_required("admin")
def office_form(office_id=None):
    office = office_record(office_id) if office_id else None
    if request.method == "POST":
        name = text(request.form, "name", "Nama kantor")
        address = text(request.form, "address", "Alamat", 500)
        latitude = number(request.form, "latitude", -90, 90)
        longitude = number(request.form, "longitude", -180, 180)
        radius = integer(request.form, "radius_m", 10, 5000, 100)
        accuracy = integer(request.form, "max_accuracy_m", 1, 200, 50)
        start, end = time_value(request.form, "start_time"), time_value(request.form, "end_time")
        if end <= start:
            raise ValidationError("Jam pulang harus setelah jam masuk. Shift lintas hari belum didukung.")
        working = sorted(set(request.form.getlist("working_days")))
        if not working or any(value not in {"1", "2", "3", "4", "5", "6", "7"} for value in working):
            raise ValidationError("Pilih setidaknya satu hari kerja yang valid.")
        active = int(request.form.get("is_active") == "1")
        values = (name, address, latitude, longitude, radius, accuracy, start.strftime("%H:%M:%S"), end.strftime("%H:%M:%S"), ",".join(working), active)
        if office:
            execute("UPDATE office_locations SET name=%s,address=%s,latitude=%s,longitude=%s,radius_m=%s,max_accuracy_m=%s,start_time=%s,end_time=%s,working_days=%s,is_active=%s WHERE id=%s AND client_id=%s", values + (office_id, g.client["id"]))
        else:
            execute("INSERT INTO office_locations (name,address,latitude,longitude,radius_m,max_accuracy_m,start_time,end_time,working_days,is_active,client_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", values + (g.client["id"],))
        flash("Kantor, geofence, dan jadwal kerja disimpan.", "success")
        return redirect(url_for("admin.offices"))
    return render_template("admin/office_form.html", office=office)


@bp.post("/offices/<int:office_id>/delete")
@roles_required("admin")
def delete_office(office_id):
    office_record(office_id)
    try:
        execute("DELETE FROM office_locations WHERE id=%s AND client_id=%s", (office_id, g.client["id"]))
    except IntegrityError:
        raise ValidationError("Kantor masih terhubung dengan karyawan/absensi. Nonaktifkan melalui Edit, jangan hapus riwayat.") from None
    flash("Kantor dihapus.", "success")
    return redirect(url_for("admin.offices"))


@bp.get("/attendance")
@roles_required("admin")
def attendance():
    page, limit, offset = pagination()
    rows, start, end = report_data(request.args)
    offices = query("SELECT id,name FROM office_locations WHERE client_id=%s ORDER BY name", (g.client["id"],))
    return render_template("admin/attendance.html", rows=rows[offset:offset + limit], total=len(rows), page=page, limit=limit, start=start, end=end, offices=offices)


@bp.get("/attendance/<int:attendance_id>")
@roles_required("admin")
def attendance_detail(attendance_id):
    record = query("SELECT a.*,e.name,e.employee_number FROM attendances a JOIN employees e ON e.id=a.employee_id AND e.client_id=a.client_id WHERE a.id=%s AND a.client_id=%s", (attendance_id, g.client["id"]), one=True)
    if not record:
        abort(404)
    return render_template("admin/attendance_detail.html", attendance=record)


@bp.get("/attendance/export.xlsx")
@roles_required("admin")
def export_attendance():
    rows, start, end = report_data(request.args)
    labels = {"present": "Hadir", "late": "Terlambat", "absent": "Belum hadir", "leave": "Izin/cuti", "off": "Libur"}
    headers = ["Tanggal WIB", "NIK", "Nama", "Departemen", "Kantor", "Status", "Masuk WIB", "Pulang WIB", "Terlambat (menit)", "Lat masuk", "Lng masuk", "Akurasi masuk (m)", "Jarak masuk (m)", "Lat pulang", "Lng pulang", "Akurasi pulang (m)", "Jarak pulang (m)"]
    values = []
    for row in rows:
        employee = row["employee"]
        record = row["attendance"] or {}
        values.append([row["date"].isoformat(), employee["employee_number"], employee["name"], employee["department"], record.get("office_name") or employee["assigned_office"], labels[row["status"]],
            record["check_in_at"].strftime("%H:%M:%S") if record.get("check_in_at") else "", record["check_out_at"].strftime("%H:%M:%S") if record.get("check_out_at") else "", record.get("late_minutes", 0),
            *[float(record[key]) if record.get(key) is not None else "" for key in ("check_in_latitude", "check_in_longitude", "check_in_accuracy", "check_in_distance", "check_out_latitude", "check_out_longitude", "check_out_accuracy", "check_out_distance")]])
    return send_file(workbook_bytes(headers, values, "Absensi"), as_attachment=True, download_name=f"elrise-absensi-{start}-{end}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.get("/leaves")
@roles_required("admin")
def leaves():
    page, limit, offset = pagination()
    status = request.args.get("status", "pending")
    if status not in {"", "pending", "approved", "rejected", "canceled"}:
        raise ValidationError("Status pengajuan tidak valid.")
    where = "l.client_id=%s"
    params = [g.client["id"]]
    if status:
        where += " AND l.status=%s"
        params.append(status)
    total = query(f"SELECT COUNT(*) AS total FROM leave_requests l WHERE {where}", tuple(params), one=True)["total"]
    records = query(f"SELECT l.*,e.name,e.employee_number FROM leave_requests l JOIN employees e ON e.id=l.employee_id AND e.client_id=l.client_id WHERE {where} ORDER BY l.id DESC LIMIT %s OFFSET %s", tuple(params) + (limit, offset))
    return render_template("admin/leaves.html", leaves=records, total=total, page=page, limit=limit, status=status)


@bp.post("/leaves/<int:leave_id>/review")
@roles_required("admin")
def review_leave(leave_id):
    status = request.form.get("status")
    if status not in {"approved", "rejected"}:
        raise ValidationError("Keputusan pengajuan tidak valid.")
    note = text(request.form, "admin_note", "Catatan", 500, False)
    record = query("SELECT * FROM leave_requests WHERE id=%s AND client_id=%s", (leave_id, g.client["id"]), one=True)
    if not record:
        abort(404)
    with transaction():
        query("SELECT id FROM employees WHERE id=%s AND client_id=%s FOR UPDATE", (record["employee_id"], g.client["id"]), one=True)
        record = query("SELECT * FROM leave_requests WHERE id=%s AND client_id=%s FOR UPDATE", (leave_id, g.client["id"]), one=True)
        if record["status"] != "pending":
            raise ValidationError("Pengajuan sudah diproses.", 409)
        if status == "approved":
            existing = query("SELECT id FROM attendances WHERE employee_id=%s AND client_id=%s AND work_date BETWEEN %s AND %s LIMIT 1", (record["employee_id"], g.client["id"], record["start_date"], record["end_date"]), one=True)
            if existing:
                raise ValidationError("Tanggal pengajuan sudah memiliki absensi. Tidak dapat disetujui.")
        execute("UPDATE leave_requests SET status=%s,admin_note=%s,reviewed_by=%s,reviewed_at=%s WHERE id=%s AND client_id=%s", (status, note, g.user["id"], now(), leave_id, g.client["id"]))
    flash("Pengajuan berhasil diproses.", "success")
    return redirect(url_for("admin.leaves"))
