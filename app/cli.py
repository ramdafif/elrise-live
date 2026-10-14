import re
from datetime import timedelta

import click
from flask import current_app
from werkzeug.security import generate_password_hash

from app.config import ROOT
from app.db import connect, execute, query, transaction
from app.migrations import TABLES, correction_schema_ready, feature_schema_ready, migrate_database
from app.utils.features import initialize_client_features
from app.utils.photos import remove_selfie
from app.utils.validation import ValidationError, now, password


def initialize_database():
    name = current_app.config["MYSQL_DATABASE"]
    if not re.fullmatch(r"elrise_[a-zA-Z0-9_]+", name):
        raise click.ClickException("Nama database wajib berawalan elrise_ dan hanya huruf/angka/underscore.")
    connection = connect(database=False)
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s", (name,))
        existing = {row[0] for row in cursor.fetchall()}
        if existing - TABLES:
            raise click.ClickException("Database sudah berisi aplikasi lain. Tidak ada schema/data yang diubah; gunakan database Elrise kosong.")
        if existing:
            cursor.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='users'", (name,))
            if not {"client_id", "role", "session_version", "must_change_password"} <= {row[0] for row in cursor.fetchall()}:
                raise click.ClickException("Schema existing bukan versi Elrise ini. Diperlukan audit/migrasi terpisah.")
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cursor.execute(f"USE {name}")
        schema = (ROOT / "database" / "schema.sql").read_text(encoding="utf-8")
        for statement in schema.split(";"):
            statement = statement.strip()
            if statement and not statement.startswith(("CREATE DATABASE", "USE ")):
                cursor.execute(statement)
    finally:
        cursor.close()
        connection.close()

    if not existing:
        migrate_database(apply=True)


def register_cli(app):
    @app.cli.command("init-db")
    def init_db():
        """Initialize only an empty or compatible Elrise database; never reset data."""
        initialize_database()
        click.echo(f"Schema siap: {current_app.config['MYSQL_DATABASE']} (tanpa DROP/TRUNCATE).")

    @app.cli.command("migrate-db")
    @click.option("--apply", is_flag=True, help="Terapkan migrasi; default hanya dry run.")
    @click.option("--database", "target_database", help="Nama target harus sama dengan konfigurasi aplikasi.")
    @click.option("--backup-confirmed", is_flag=True, help="Konfirmasi backup/pemulihan siap; tidak membuat backup otomatis.")
    def migrate_db(apply, target_database, backup_confirmed):
        """Inspect or explicitly apply additive, versioned migrations."""
        name = current_app.config["MYSQL_DATABASE"]
        if apply and target_database != name:
            raise click.ClickException("Sebutkan --database yang sama dengan MYSQL_DATABASE sebelum menerapkan migrasi.")
        if apply and not backup_confirmed:
            raise click.ClickException("Siapkan backup dan pemulihan terlebih dahulu, lalu sertakan --backup-confirmed.")
        versions = migrate_database(apply=apply)
        click.echo(f"{'Apply' if apply else 'Dry run (tanpa perubahan)'}: {name}")
        for version in versions:
            click.echo(f"{'Diterapkan' if apply else 'Pending'}: {version}")
        if not versions:
            click.echo("Tidak ada migrasi pending.")

    @app.cli.command("create-superadmin")
    @click.option("--email", "address", prompt=True)
    @click.option("--name", prompt=True)
    def create_superadmin(address, name):
        from app.utils.validation import email, text

        try:
            address = email({"email": address})
            name = text({"name": name}, "name", "Nama")
            initial = password(click.prompt("Password", hide_input=True, confirmation_prompt=True))
        except ValidationError as error:
            raise click.ClickException(str(error)) from None
        if query("SELECT id FROM users WHERE email=%s", (address,), one=True):
            raise click.ClickException("Email sudah terdaftar.")
        execute("INSERT INTO users (name,email,password_hash,role,must_change_password) VALUES (%s,%s,%s,'superadmin',0)", (name, address, generate_password_hash(initial)))
        click.echo("Superadmin dibuat.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Create two independent tenants and real accounts in a development database."""
        if current_app.config["APP_ENV"] != "development":
            raise click.ClickException("Seed demo hanya tersedia di APP_ENV=development.")
        try:
            initial = password(current_app.config["DEMO_PASSWORD"])
        except ValidationError as error:
            raise click.ClickException("Atur DEMO_PASSWORD minimal 12 karakter khusus development.") from error
        if query("SELECT id FROM users LIMIT 1", one=True):
            raise click.ClickException("Seed dibatalkan: database sudah berisi akun. Data existing tidak diubah.")
        today = now().date()
        hashed = generate_password_hash(initial)
        with transaction():
            execute("INSERT INTO users (name,email,password_hash,role,must_change_password) VALUES ('Elrise Owner','owner@elrise.test',%s,'superadmin',0)", (hashed,))
            for code, company, admin_email, employee_email, employee_name in [
                ("NUSA", "PT Nusantara Digital", "admin@nusantara.test", "rani@nusantara.test", "Rani Prameswari"),
                ("CAKRA", "PT Cakrawala Kreasi", "admin@cakrawala.test", "bima@cakrawala.test", "Bima Adiputra"),
            ]:
                client_id = execute("INSERT INTO clients (name,code,email,address,is_active,employee_limit,service_start,service_end) VALUES (%s,%s,%s,'Jakarta, Indonesia',1,50,%s,%s)", (company, code, admin_email, today - timedelta(days=1), today + timedelta(days=365))).lastrowid
                if feature_schema_ready():
                    initialize_client_features(client_id)
                execute("INSERT INTO users (client_id,name,email,password_hash,role,must_change_password) VALUES (%s,'Admin HR',%s,%s,'admin',0)", (client_id, admin_email, hashed))
                office_id = execute("INSERT INTO office_locations (client_id,name,address,latitude,longitude) VALUES (%s,'Kantor Jakarta','Jakarta Pusat',-6.2000000,106.8166660)", (client_id,)).lastrowid
                user_id = execute("INSERT INTO users (client_id,name,email,password_hash,role,must_change_password) VALUES (%s,%s,%s,%s,'employee',0)", (client_id, employee_name, employee_email, hashed)).lastrowid
                execute("INSERT INTO employees (client_id,user_id,office_id,employee_number,name,department,job_title,join_date) VALUES (%s,%s,%s,'EMP-001',%s,'Product & Technology','Product Designer',%s)", (client_id, user_id, office_id, employee_name, today - timedelta(days=1)))
        click.echo("Seed development: owner@elrise.test, admin@nusantara.test, rani@nusantara.test, admin@cakrawala.test, bima@cakrawala.test. Password dari DEMO_PASSWORD; tidak ada absensi/foto palsu.")

    @app.cli.command("purge-data")
    @click.option("--apply", is_flag=True, help="Actually delete expired data; otherwise only count it.")
    def purge_data(apply):
        current = now()
        photo_count, attendance_count, leave_count = 0, 0, 0
        companies = query("SELECT id,photo_retention_days FROM clients")
        for company in companies:
            days = company["photo_retention_days"] or current_app.config["PHOTO_RETENTION_DAYS"]
            photos = query("SELECT * FROM attendances WHERE client_id=%s AND work_date<%s AND (check_in_photo IS NOT NULL OR check_out_photo IS NOT NULL)", (company["id"], (current - timedelta(days=days)).date()))
            photo_count += sum(bool(record[key]) for record in photos for key in ("check_in_photo", "check_out_photo"))
            if apply:
                for record in photos:
                    remove_selfie(record["check_in_photo"])
                    remove_selfie(record["check_out_photo"])
                    execute("UPDATE attendances SET check_in_photo=NULL,check_out_photo=NULL WHERE id=%s AND client_id=%s", (record["id"], company["id"]))
        attendance_cutoff = (current - timedelta(days=current_app.config["ATTENDANCE_RETENTION_DAYS"])).date()
        preserved = " AND NOT EXISTS (SELECT 1 FROM attendance_corrections c WHERE c.client_id=attendances.client_id AND c.employee_id=attendances.employee_id AND c.work_date=attendances.work_date)" if correction_schema_ready() else ""
        records = query("SELECT id,client_id,check_in_photo,check_out_photo FROM attendances WHERE work_date<%s" + preserved, (attendance_cutoff,))
        attendance_count = len(records)
        if apply:
            for record in records:
                remove_selfie(record["check_in_photo"])
                remove_selfie(record["check_out_photo"])
                execute("DELETE FROM attendances WHERE id=%s AND client_id=%s", (record["id"], record["client_id"]))
        leave_cutoff = (current - timedelta(days=current_app.config["LEAVE_RETENTION_DAYS"])).date()
        leave_count = query("SELECT COUNT(*) AS total FROM leave_requests WHERE end_date<%s", (leave_cutoff,), one=True)["total"]
        if apply:
            execute("DELETE FROM leave_requests WHERE end_date<%s", (leave_cutoff,))
            execute("DELETE FROM login_limits WHERE window_started_at<%s", (current - timedelta(days=1),))
        click.echo(f"{'Dihapus' if apply else 'Dry run'}: {photo_count} foto, {attendance_count} absensi, {leave_count} pengajuan.")
        if correction_schema_ready():
            click.echo("Koreksi, audit, dan catatan absensi terkait dipertahankan; retensinya memerlukan kebijakan terpisah. Retensi foto tetap berlaku.")

    @app.cli.command("erase-employee")
    @click.option("--client-id", type=int, required=True)
    @click.option("--employee-id", type=int, required=True)
    @click.confirmation_option(prompt="Hapus permanen akun dan seluruh riwayat karyawan nonaktif ini setelah kewajiban retensi dinilai?")
    def erase_employee(client_id, employee_id):
        with transaction():
            query("SELECT id FROM clients WHERE id=%s FOR UPDATE", (client_id,), one=True)
            employee = query("SELECT * FROM employees WHERE id=%s AND client_id=%s FOR UPDATE", (employee_id, client_id), one=True)
            if not employee or employee["is_active"]:
                raise click.ClickException("Karyawan harus ada dalam tenant tersebut dan sudah nonaktif.")
            if correction_schema_ready() and query("SELECT id FROM attendance_corrections WHERE employee_id=%s AND client_id=%s LIMIT 1", (employee_id, client_id), one=True):
                raise click.ClickException("Karyawan memiliki audit koreksi. Penghapusan ditahan sampai kebijakan retensi koreksi disetujui.")
            records = query("SELECT check_in_photo,check_out_photo FROM attendances WHERE employee_id=%s AND client_id=%s", (employee_id, client_id))
            execute("DELETE FROM leave_requests WHERE employee_id=%s AND client_id=%s", (employee_id, client_id))
            execute("DELETE FROM attendances WHERE employee_id=%s AND client_id=%s", (employee_id, client_id))
            execute("DELETE FROM employees WHERE id=%s AND client_id=%s", (employee_id, client_id))
            execute("DELETE FROM users WHERE id=%s AND client_id=%s AND role='employee'", (employee["user_id"], client_id))
        for record in records:
            remove_selfie(record["check_in_photo"])
            remove_selfie(record["check_out_photo"])
        click.echo("Data karyawan dihapus. Pastikan backup mengikuti kebijakan penghapusan yang sama.")
