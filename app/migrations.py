import hashlib
import re

import click
from flask import current_app

from app.config import ROOT
from app.db import connect, query

CORE_TABLES = {"clients", "users", "employees", "office_locations", "attendances", "leave_requests", "login_limits"}
TABLES = CORE_TABLES | {"schema_migrations", "client_features", "feature_audit_logs", "attendance_corrections", "attendance_correction_audit"}
FEATURE_MIGRATION = "0001_client_features"
CORRECTION_MIGRATION = "0002_attendance_corrections"


def validate_schema(cursor, complete=True):
    name = current_app.config["MYSQL_DATABASE"]
    if not re.fullmatch(r"elrise_[a-zA-Z0-9_]+", name):
        raise click.ClickException("Nama database wajib berawalan elrise_ dan hanya huruf/angka/underscore.")
    cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (name,))
    existing = {row[0] for row in cursor.fetchall()}
    if existing - TABLES:
        raise click.ClickException("Database sudah berisi aplikasi lain. Tidak ada schema/data yang diubah; gunakan database khusus Elrise.")
    required_columns = {
        "users": {"client_id", "role", "session_version", "must_change_password"},
        "clients": {"code", "employee_limit", "service_start", "service_end"},
        "employees": {"client_id", "user_id", "employee_number", "privacy_version"},
    }
    for table, expected in required_columns.items():
        if table in existing:
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s", (name, table))
            if not expected <= {row[0] for row in cursor.fetchall()}:
                raise click.ClickException("Schema existing bukan versi Elrise ini. Diperlukan audit/migrasi terpisah.")
    if complete and not CORE_TABLES <= existing:
        raise click.ClickException("Schema inti Elrise belum lengkap. Inisialisasi database kosong khusus Elrise terlebih dahulu.")
    return existing


def migration_files():
    migrations = []
    for path in sorted((ROOT / "database" / "migrations").glob("*.sql")):
        if not re.fullmatch(r"[0-9]{4}_[a-z0-9_]+", path.stem):
            raise click.ClickException("Nama file migrasi tidak valid.")
        sql = path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
        if any(not statement.startswith(("CREATE TABLE IF NOT EXISTS ", "INSERT IGNORE INTO ")) for statement in statements):
            raise click.ClickException("Migrasi MVP hanya boleh menambah tabel dan mengisi default tanpa menimpa data.")
        migrations.append((path.stem, hashlib.sha256(sql.encode()).hexdigest(), statements))
    return migrations


def pending_migrations(cursor, existing):
    migrations = migration_files()
    applied = {}
    if "schema_migrations" in existing:
        cursor.execute("SELECT version, checksum FROM schema_migrations")
        applied = dict(cursor.fetchall())
    known = {version for version, checksum, statements in migrations}
    if applied.keys() - known:
        raise click.ClickException("Database memiliki versi migrasi yang tidak dikenal oleh rilis ini. Jangan downgrade tanpa audit.")
    for version, checksum, statements in migrations:
        if version in applied and applied[version] != checksum:
            raise click.ClickException(f"Checksum migrasi {version} berbeda. Jangan mengubah migrasi yang sudah diterapkan.")
    return [migration for migration in migrations if migration[0] not in applied]


def migrate_database(apply=False):
    connection = connect()
    cursor = connection.cursor()
    name = current_app.config["MYSQL_DATABASE"]
    lock_name = "elrise:migrate:" + hashlib.sha256(name.encode()).hexdigest()[:32]
    locked = False
    try:
        if apply:
            cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
            locked = cursor.fetchone()[0] == 1
            if not locked:
                raise click.ClickException("Migrasi database ini sedang dijalankan oleh proses lain.")
        existing = validate_schema(cursor)
        pending = pending_migrations(cursor, existing)
        if apply and pending:
            cursor.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(64) NOT NULL PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB""")
            for version, checksum, statements in pending:
                for statement in statements:
                    cursor.execute(statement)
                cursor.execute("INSERT INTO schema_migrations (version,checksum) VALUES (%s,%s)", (version, checksum))
        return [version for version, checksum, statements in pending]
    finally:
        if locked:
            cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
            cursor.fetchone()
        cursor.close()
        connection.close()


def feature_schema_ready():
    tables = query("""SELECT TABLE_NAME AS name FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ('schema_migrations','client_features','feature_audit_logs')""",
        (current_app.config["MYSQL_DATABASE"],))
    if {row["name"] for row in tables} != {"schema_migrations", "client_features", "feature_audit_logs"}:
        return False
    return bool(query("SELECT version FROM schema_migrations WHERE version=%s", (FEATURE_MIGRATION,), one=True))

def correction_schema_ready():
    tables = query("""SELECT TABLE_NAME AS name FROM information_schema.TABLES
        WHERE TABLE_SCHEMA=%s AND TABLE_NAME IN ('schema_migrations','attendance_corrections','attendance_correction_audit')""",
        (current_app.config["MYSQL_DATABASE"],))
    if {row["name"] for row in tables} != {"schema_migrations", "attendance_corrections", "attendance_correction_audit"}:
        return False
    return bool(query("SELECT version FROM schema_migrations WHERE version=%s", (CORRECTION_MIGRATION,), one=True))
