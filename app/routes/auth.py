from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import execute, query, transaction
from app.utils.auth import client_available, dashboard_url, login_success, reserve_login, roles_required
from app.utils.validation import ValidationError, now, password

bp = Blueprint("auth", __name__)
DUMMY_HASH = generate_password_hash("not-a-valid-account-password")


@bp.get("/")
def index():
    return redirect(dashboard_url() if g.user else url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(dashboard_url())
    if request.method == "POST":
        email_address = request.form.get("email", "").strip().lower()[:190]
        supplied_password = request.form.get("password", "")
        bucket = reserve_login(email_address)
        if not bucket:
            response = render_template("login.html", error="Terlalu banyak percobaan. Tunggu 15 menit sebelum mencoba lagi.")
            return response, 429, {"Retry-After": "900"}
        account = query("SELECT * FROM users WHERE email = %s", (email_address,), one=True)
        valid_password = len(supplied_password) <= 128 and check_password_hash(account["password_hash"] if account else DUMMY_HASH, supplied_password)
        available = bool(account and account["is_active"])
        if available and account["role"] != "superadmin":
            company = query("SELECT * FROM clients WHERE id = %s", (account["client_id"],), one=True)
            available = client_available(company)
        if available and account["role"] == "employee":
            employee = query("SELECT * FROM employees WHERE user_id = %s AND client_id = %s", (account["id"], account["client_id"]), one=True)
            available = bool(employee and employee["is_active"])
        if not valid_password or not available:
            return render_template("login.html", error="Email/password tidak sesuai, atau akun/layanan tidak aktif."), 401
        login_success(account, bucket)
        g.user = account
        return redirect(url_for("auth.password_change") if account["must_change_password"] else dashboard_url())
    return render_template("login.html")


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@roles_required("superadmin", "admin", "employee")
def password_change():
    if request.method == "POST":
        current_password = request.form.get("current_password", "")
        new_password = password(request.form.get("new_password"))
        if new_password != request.form.get("confirm_password"):
            raise ValidationError("Konfirmasi password tidak sama.")
        if new_password == current_password:
            raise ValidationError("Gunakan password berbeda dari password lama.")
        with transaction():
            account = query("SELECT * FROM users WHERE id = %s FOR UPDATE", (g.user["id"],), one=True)
            if len(current_password) > 128 or not check_password_hash(account["password_hash"], current_password):
                raise ValidationError("Password saat ini tidak sesuai.")
            execute("UPDATE users SET password_hash = %s, session_version = session_version + 1, must_change_password = 0 WHERE id = %s", (generate_password_hash(new_password), account["id"]))
        session.clear()
        flash("Password diubah. Silakan login kembali; seluruh sesi lama sudah dicabut.", "success")
        return redirect(url_for("auth.login"))
    return render_template("password.html")


@bp.get("/health")
def health():
    query("SELECT 1 AS ok", one=True)
    return jsonify(ok=True, server_time=now().isoformat() + "+07:00")
