from functools import wraps

from flask import abort, g

from app.db import execute, query
from app.migrations import feature_schema_ready
from app.utils.auth import roles_required
from app.utils.validation import ValidationError

FEATURES = {
    "payroll": {"label": "Payroll", "default": False, "description": "Hak akses payroll mandiri; modul payroll dibangun pada tahap berikutnya."},
    "attendance_corrections": {"label": "Koreksi absensi", "default": True, "description": "Pengajuan karyawan, review Admin PT, dan audit koreksi tanpa mengubah bukti absensi asli."},
    "gajiku": {"label": "Integrasi Gajiku", "default": False, "description": "Izin integrasi opsional. Memerlukan payroll aktif dan belum menyambungkan Gajiku Live."},
}


def client_features(client_id):
    settings = {key: definition["default"] for key, definition in FEATURES.items()}
    for row in query("SELECT feature_key,is_enabled FROM client_features WHERE client_id=%s", (client_id,)):
        if row["feature_key"] in settings:
            settings[row["feature_key"]] = bool(row["is_enabled"])
    return settings


def initialize_client_features(client_id):
    for key, definition in FEATURES.items():
        execute("INSERT IGNORE INTO client_features (client_id,feature_key,is_enabled) VALUES (%s,%s,%s)",
            (client_id, key, int(definition["default"])))


def parse_features(form):
    settings = {}
    for key in FEATURES:
        values = form.getlist(key)
        if len(values) > 1 or (values and values[0] != "1"):
            raise ValidationError("Nilai pengaturan fitur tidak valid.")
        settings[key] = bool(values)
    if settings["gajiku"] and not settings["payroll"]:
        raise ValidationError("Aktifkan payroll terlebih dahulu sebelum mengizinkan integrasi Gajiku.")
    return settings


def save_client_features(client_id, settings, actor_id):
    initialize_client_features(client_id)
    previous = client_features(client_id)
    changed = 0
    for key, enabled in settings.items():
        if previous[key] == enabled:
            continue
        execute("UPDATE client_features SET is_enabled=%s,updated_by=%s,updated_at=CURRENT_TIMESTAMP WHERE client_id=%s AND feature_key=%s",
            (int(enabled), actor_id, client_id, key))
        execute("""INSERT INTO feature_audit_logs (client_id,feature_key,old_enabled,new_enabled,changed_by)
            VALUES (%s,%s,%s,%s,%s)""", (client_id, key, int(previous[key]), int(enabled), actor_id))
        changed += 1
    return changed


def feature_required(key):
    if key not in FEATURES:
        raise ValueError("Fitur tidak dikenal.")

    def decorator(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not feature_schema_ready():
                abort(503, description="Fitur belum dirilis pada database ini. Hubungi Superadmin.")
            settings = client_features(g.client["id"])
            if not settings[key] or (key == "gajiku" and not settings["payroll"]):
                abort(403, description="Fitur belum diaktifkan untuk perusahaan Anda.")
            return function(*args, **kwargs)
        return roles_required("admin", "employee")(wrapped)
    return decorator
