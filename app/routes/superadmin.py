import re
from datetime import timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from mysql.connector import IntegrityError
from werkzeug.security import generate_password_hash

from app.db import execute, query, transaction
from app.migrations import feature_schema_ready
from app.utils.auth import roles_required
from app.utils.attendance import attendance_source
from app.utils.features import FEATURES, client_features, initialize_client_features, parse_features, save_client_features
from app.utils.validation import ValidationError, day, email, integer, now, pagination, password, text

bp = Blueprint("superadmin", __name__, url_prefix="/superadmin")


def get_client(client_id, lock=False):
    company = query("SELECT * FROM clients WHERE id = %s" + (" FOR UPDATE" if lock else ""), (client_id,), one=True)
    if not company:
        abort(404)
    return company


@bp.get("/")
@roles_required("superadmin")
def dashboard():
    today = now().date()
    stats = query("SELECT COUNT(*) AS total, COALESCE(SUM(is_active = 1 AND service_start <= %s AND service_end >= %s), 0) AS active FROM clients", (today, today), one=True)
    stats["employees"] = query("SELECT COUNT(*) AS total FROM employees WHERE is_active = 1", one=True)["total"]
    source = attendance_source()
    stats["attendance"] = query(f"SELECT COUNT(*) AS total FROM {source} effective WHERE work_date = %s", (today,), one=True)["total"]
    summaries = query(f"""SELECT c.*, (SELECT COUNT(*) FROM employees e WHERE e.client_id=c.id AND e.is_active=1) AS employee_count,
        (SELECT COUNT(*) FROM {source} a WHERE a.client_id=c.id AND a.work_date=%s) AS attendance_count
        FROM clients c ORDER BY c.created_at DESC, c.id DESC LIMIT 8""", (today,))
    return render_template("superadmin/dashboard.html", stats=stats, companies=summaries)


@bp.get("/clients")
@roles_required("superadmin")
def clients():
    page, limit, offset = pagination()
    search = text(request.args, "q", "Pencarian", 100, False)
    pattern = f"%{search}%"
    total = query("SELECT COUNT(*) AS total FROM clients WHERE name LIKE %s OR code LIKE %s", (pattern, pattern), one=True)["total"]
    companies = query(f"""SELECT c.*, (SELECT COUNT(*) FROM employees e WHERE e.client_id=c.id AND e.is_active=1) AS employee_count,
        (SELECT COUNT(*) FROM {attendance_source()} a WHERE a.client_id=c.id AND a.work_date=%s) AS attendance_count
        FROM clients c WHERE c.name LIKE %s OR c.code LIKE %s ORDER BY c.id DESC LIMIT %s OFFSET %s""", (now().date(), pattern, pattern, limit, offset))
    return render_template("superadmin/clients.html", companies=companies, page=page, total=total, limit=limit, search=search)


@bp.route("/clients/new", methods=["GET", "POST"])
@bp.route("/clients/<int:client_id>/edit", methods=["GET", "POST"])
@roles_required("superadmin")
def client_form(client_id=None):
    company = get_client(client_id) if client_id else None
    if request.method == "POST":
        name = text(request.form, "name", "Nama perusahaan", 160)
        code = text(request.form, "code", "Kode perusahaan", 32).upper()
        if not re.fullmatch(r"[A-Z0-9_-]{2,32}", code):
            raise ValidationError("Kode PT: 2-32 huruf, angka, tanda hubung atau underscore.")
        contact_email = email(request.form)
        phone = text(request.form, "phone", "Telepon", 32, False)
        address = text(request.form, "address", "Alamat", 500, False)
        cap = integer(request.form, "employee_limit", 1, 100000)
        start, end = day(request.form, "service_start"), day(request.form, "service_end")
        if end < start:
            raise ValidationError("Akhir layanan harus setelah awal layanan.")
        retention = integer(request.form, "photo_retention_days", 1, 365) if request.form.get("photo_retention_days") else None
        active = int(request.form.get("is_active") == "1")
        values = (name, code, contact_email, phone, address, cap, start, end, retention, active)
        try:
            with transaction():
                if company:
                    get_client(client_id, lock=True)
                    count = query("SELECT COUNT(*) AS total FROM employees WHERE client_id = %s AND is_active = 1", (client_id,), one=True)["total"]
                    if cap < count:
                        raise ValidationError(f"Batas tidak boleh lebih kecil dari {count} karyawan aktif.")
                    execute("""UPDATE clients SET name=%s, code=%s, email=%s, phone=%s, address=%s,
                        employee_limit=%s, service_start=%s, service_end=%s, photo_retention_days=%s, is_active=%s WHERE id=%s""", values + (client_id,))
                else:
                    client_id = execute("""INSERT INTO clients (name,code,email,phone,address,employee_limit,service_start,service_end,photo_retention_days,is_active)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values).lastrowid
                    if feature_schema_ready():
                        initialize_client_features(client_id)
        except IntegrityError:
            raise ValidationError("Kode perusahaan sudah digunakan.") from None
        flash("Informasi perusahaan berhasil disimpan.", "success")
        return redirect(url_for("superadmin.client_detail", client_id=client_id))
    return render_template("superadmin/client_form.html", company=company, default_start=now().date(), default_end=now().date() + timedelta(days=365))


@bp.get("/clients/<int:client_id>")
@roles_required("superadmin")
def client_detail(client_id):
    company = get_client(client_id)
    admins = query("SELECT id,name,email,is_active FROM users WHERE client_id=%s AND role='admin' ORDER BY id", (client_id,))
    count = query("SELECT COUNT(*) AS total FROM employees WHERE client_id=%s AND is_active=1", (client_id,), one=True)["total"]
    attendance = query(f"SELECT work_date, COUNT(*) AS total, SUM(status='late') AS late FROM {attendance_source()} effective WHERE client_id=%s GROUP BY work_date ORDER BY work_date DESC LIMIT 14", (client_id,))
    ready = feature_schema_ready()
    settings = client_features(client_id) if ready else {}
    audit = query("""SELECT a.*,u.name AS actor_name FROM feature_audit_logs a JOIN users u ON u.id=a.changed_by
        WHERE a.client_id=%s ORDER BY a.id DESC LIMIT 20""", (client_id,)) if ready else []
    return render_template("superadmin/client_detail.html", company=company, admins=admins, employee_count=count, attendance=attendance,
        feature_management_ready=ready, feature_definitions=FEATURES, feature_settings=settings, feature_audit=audit)


@bp.post("/clients/<int:client_id>/features")
@roles_required("superadmin")
def update_features(client_id):
    if not feature_schema_ready():
        abort(503, description="Management fitur belum dirilis. Jalankan migrasi terverifikasi di lingkungan yang sesuai.")
    settings = parse_features(request.form)
    with transaction():
        get_client(client_id, lock=True)
        changed = save_client_features(client_id, settings, g.user["id"])
    flash("Pengaturan fitur dan audit berhasil disimpan." if changed else "Tidak ada perubahan pengaturan fitur.", "success")
    return redirect(url_for("superadmin.client_detail", client_id=client_id))


@bp.post("/clients/<int:client_id>/toggle")
@roles_required("superadmin")
def toggle_client(client_id):
    get_client(client_id)
    execute("UPDATE clients SET is_active = NOT is_active WHERE id=%s", (client_id,))
    flash("Status perusahaan diperbarui.", "success")
    return redirect(url_for("superadmin.client_detail", client_id=client_id))


@bp.post("/clients/<int:client_id>/admins")
@roles_required("superadmin")
def create_admin(client_id):
    get_client(client_id)
    name = text(request.form, "name", "Nama admin")
    address = email(request.form)
    hashed = generate_password_hash(password(request.form.get("password")))
    try:
        execute("INSERT INTO users (client_id,name,email,password_hash,role) VALUES (%s,%s,%s,%s,'admin')", (client_id, name, address, hashed))
    except IntegrityError:
        raise ValidationError("Email sudah digunakan oleh akun lain.") from None
    flash("Admin PT dibuat. Berikan password awal melalui kanal aman; wajib diganti saat login pertama.", "success")
    return redirect(url_for("superadmin.client_detail", client_id=client_id))


@bp.post("/clients/<int:client_id>/admins/<int:user_id>/reset")
@roles_required("superadmin")
def reset_admin(client_id, user_id):
    hashed = generate_password_hash(password(request.form.get("password")))
    result = execute("UPDATE users SET password_hash=%s, session_version=session_version+1, must_change_password=1 WHERE id=%s AND client_id=%s AND role='admin'", (hashed, user_id, client_id))
    if not result.rowcount:
        abort(404)
    flash("Password admin direset dan seluruh sesi lama dicabut.", "success")
    return redirect(url_for("superadmin.client_detail", client_id=client_id))
