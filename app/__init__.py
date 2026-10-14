import secrets
from pathlib import Path

from flask import Flask, abort, g, jsonify, render_template, request, session
from mysql.connector import Error as DatabaseError
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import ROOT, load_config
from app.db import close_db, query
from app.migrations import correction_schema_ready, feature_schema_ready
from app.utils.auth import csrf_token, load_identity
from app.utils.features import client_features
from app.utils.validation import ValidationError, now, sql_time


def create_app(test_config=None):
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.config.update(load_config())
    if test_config:
        app.config.update(test_config)
    secret = app.config["SECRET_KEY"]
    if not secret or len(secret) < 32 or secret.startswith("replace-"):
        raise RuntimeError("Atur SECRET_KEY acak minimal 32 karakter di .env.")
    if app.config["APP_ENV"] == "production" and not app.config["PRIVACY_CONTACT"]:
        raise RuntimeError("Atur PRIVACY_CONTACT sebelum deployment production.")
    for setting in ("PHOTO_RETENTION_DAYS", "ATTENDANCE_RETENTION_DAYS", "LEAVE_RETENTION_DAYS"):
        if app.config[setting] < 1:
            raise RuntimeError(f"{setting} harus positif.")
    upload_dir = Path(app.config["PRIVATE_UPLOAD_DIR"])
    if not upload_dir.is_absolute():
        upload_dir = ROOT / upload_dir
    upload_dir = upload_dir.resolve()
    if upload_dir == (ROOT / "static") or (ROOT / "static") in upload_dir.parents:
        raise RuntimeError("Selfie wajib disimpan di luar folder static.")
    app.config["PRIVATE_UPLOAD_DIR"] = str(upload_dir)
    upload_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    hops = app.config["TRUST_PROXY_HOPS"]
    if hops:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)

    @app.before_request
    def security_checks():
        if request.endpoint == "static":
            filename = (request.view_args or {}).get("filename", "")
            if filename.startswith("uploads/"):
                abort(404)
            return None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not supplied or not expected or not secrets.compare_digest(supplied, expected):
                abort(400, description="Sesi form tidak valid. Muat ulang halaman lalu coba lagi.")
        return load_identity()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(self), geolocation=(self), microphone=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        if app.config["SESSION_COOKIE_SECURE"]:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.context_processor
    def context():
        def page_link(page):
            from flask import url_for

            arguments = request.args.to_dict()
            arguments.update(request.view_args or {})
            arguments["page"] = page
            return url_for(request.endpoint, **arguments)
        company = getattr(g, "client", None)
        user = getattr(g, "user", None)
        corrections_enabled, pending_corrections = False, 0
        if company and user and user["role"] in {"admin", "employee"} and feature_schema_ready() and correction_schema_ready():
            corrections_enabled = client_features(company["id"])["attendance_corrections"]
            if corrections_enabled and user["role"] == "admin":
                pending_corrections = query("SELECT COUNT(*) AS total FROM attendance_corrections WHERE client_id=%s AND status='pending'",
                    (company["id"],), one=True)["total"]
        return {"csrf_token": csrf_token, "page_link": page_link, "server_now": now(), "user": user, "client": company,
            "corrections_enabled": corrections_enabled, "pending_corrections": pending_corrections}

    @app.template_filter("clock")
    def clock(value):
        return sql_time(value).strftime("%H:%M") if value else "--:--"

    @app.template_filter("date_id")
    def date_id(value):
        return value.strftime("%d %b %Y") if value else "-"

    @app.template_filter("label")
    def label(value):
        return {"present": "Hadir", "late": "Terlambat", "absent": "Belum hadir", "leave": "Izin / cuti", "off": "Libur", "pending": "Menunggu", "approved": "Disetujui", "rejected": "Ditolak", "canceled": "Dibatalkan"}.get(value, value)

    @app.errorhandler(ValidationError)
    def validation_error(error):
        return respond_error(error.status, str(error))

    @app.errorhandler(HTTPException)
    def http_error(error):
        return respond_error(error.code, error.description)

    @app.errorhandler(DatabaseError)
    def database_error(error):
        app.logger.exception("Database request failed")
        return respond_error(503, "Layanan database belum tersedia. Hubungi administrator.")

    @app.errorhandler(500)
    def internal_error(error):
        return respond_error(500, "Terjadi gangguan internal. Silakan coba lagi.")

    def respond_error(status, message):
        if request.is_json or request.path.endswith("/challenge"):
            return jsonify(ok=False, message=message), status
        return render_template("error.html", status=status, message=message), status

    from app.routes import admin, auth, corrections, employee, superadmin
    from app.cli import register_cli

    for blueprint in (auth.bp, superadmin.bp, admin.bp, employee.bp, corrections.bp):
        app.register_blueprint(blueprint)
    app.teardown_appcontext(close_db)
    register_cli(app)
    return app
