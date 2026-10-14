import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from flask import abort, current_app, g, jsonify, redirect, request, session, url_for

from app.db import execute, query, transaction
from app.utils.validation import now


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def dashboard_url():
    return url_for(f"{g.user['role']}.dashboard")


def client_available(client):
    today = now().date()
    return bool(client and client["is_active"] and client["service_start"] <= today <= client["service_end"])


def load_identity():
    g.user, g.client, g.employee = None, None, None
    if not session.get("user_id"):
        return None
    user = query("SELECT * FROM users WHERE id = %s", (session["user_id"],), one=True)
    if not user or not user["is_active"] or user["session_version"] != session.get("session_version"):
        session.clear()
        return None
    g.user = user
    if user["role"] != "superadmin":
        g.client = query("SELECT * FROM clients WHERE id = %s", (user["client_id"],), one=True)
        if not client_available(g.client):
            session.clear()
            abort(403, description="Perusahaan tidak aktif atau masa layanan belum berlaku/sudah berakhir.")
    if user["role"] == "employee":
        g.employee = query("SELECT * FROM employees WHERE user_id = %s AND client_id = %s", (user["id"], user["client_id"]), one=True)
        if not g.employee or not g.employee["is_active"]:
            session.clear()
            abort(403, description="Akun karyawan tidak aktif.")
    if user["must_change_password"] and request.endpoint not in {"auth.password_change", "auth.logout", "auth.login", "auth.health"}:
        if request.is_json:
            return jsonify(ok=False, message="Ganti password awal terlebih dahulu."), 403
        return redirect(url_for("auth.password_change"))
    return None


def roles_required(*roles):
    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not g.user:
                if request.is_json:
                    return jsonify(ok=False, message="Sesi berakhir. Silakan login kembali."), 401
                return redirect(url_for("auth.login"))
            if g.user["role"] not in roles:
                abort(403, description="Anda tidak memiliki akses ke halaman ini.")
            return function(*args, **kwargs)
        return wrapped
    return decorator


def reserve_login(email_address):
    current = now()
    account = hashlib.sha256(("account:" + email_address).encode()).hexdigest()
    address = hashlib.sha256(("ip:" + (request.remote_addr or "unknown")).encode()).hexdigest()
    buckets = sorted([(account, 5), (address, 40)])
    with transaction():
        for bucket, limit in buckets:
            execute("INSERT IGNORE INTO login_limits (bucket, attempts, window_started_at) VALUES (%s, 0, %s)", (bucket, current))
            record = query("SELECT * FROM login_limits WHERE bucket = %s FOR UPDATE", (bucket,), one=True)
            if record["window_started_at"] <= current - timedelta(minutes=15):
                execute("UPDATE login_limits SET attempts = 0, window_started_at = %s WHERE bucket = %s", (current, bucket))
                record["attempts"] = 0
            if record["attempts"] >= limit:
                return None
        for bucket, limit in buckets:
            execute("UPDATE login_limits SET attempts = attempts + 1 WHERE bucket = %s", (bucket,))
    return account


def login_success(user, account_bucket):
    execute("DELETE FROM login_limits WHERE bucket = %s", (account_bucket,))
    address_bucket = hashlib.sha256(("ip:" + (request.remote_addr or "unknown")).encode()).hexdigest()
    execute("UPDATE login_limits SET attempts=GREATEST(0,attempts-1) WHERE bucket=%s", (address_bucket,))
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["session_version"] = user["session_version"]
    csrf_token()
