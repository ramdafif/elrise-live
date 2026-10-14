import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import create_app
from app.db import connect, execute, query
from app.migrations import FEATURE_MIGRATION, feature_schema_ready, migrate_database
from app.utils.features import FEATURES, client_features, feature_required
from tests.conftest import form_post, login


@pytest.fixture
def guard_app(app):
    guarded = create_app(dict(app.config))
    for key in FEATURES:
        guarded.add_url_rule(f"/feature-test/{key}", endpoint=f"feature_test_{key}", view_func=feature_required(key)(lambda: "allowed"))
    return guarded


@pytest.fixture
def legacy_app(app):
    with app.app_context():
        assert app.config["MYSQL_DATABASE"].startswith("elrise_test_")
        for table in ("attendance_correction_audit", "attendance_corrections", "feature_audit_logs", "client_features", "schema_migrations"):
            execute(f"DROP TABLE {table}")
    try:
        yield app
    finally:
        with app.app_context():
            migrate_database(apply=True)


def owner_client(app):
    browser = app.test_client()
    assert login(browser, "owner@elrise.test").status_code == 302
    return browser


def test_defaults_and_client_detail(app, records):
    with app.app_context():
        assert feature_schema_ready()
        assert client_features(records["client"]["id"]) == {"payroll": False, "attendance_corrections": True, "gajiku": False}
        assert query("SELECT COUNT(*) AS total FROM client_features", one=True)["total"] == 6
    response = owner_client(app).get(f"/superadmin/clients/{records['client']['id']}")
    assert response.status_code == 200
    assert "Fitur &amp; integrasi" in response.get_data(as_text=True)
    assert "Gajiku: Nonaktif" in response.get_data(as_text=True)


def test_update_audit_idempotent_and_tenant_isolation(app, records):
    owner = owner_client(app)
    target = records["client"]["id"]
    path = f"/superadmin/clients/{target}/features"
    data = {"payroll": "1", "attendance_corrections": "1", "gajiku": "1"}
    assert form_post(owner, path, data).status_code == 302
    assert form_post(owner, path, data).status_code == 302
    with app.app_context():
        assert all(client_features(target).values())
        assert not client_features(records["other_client"]["id"])["payroll"]
        logs = query("SELECT a.*,u.role FROM feature_audit_logs a JOIN users u ON u.id=a.changed_by ORDER BY a.id")
        assert len(logs) == 2
        assert {row["feature_key"] for row in logs} == {"payroll", "gajiku"}
        assert all(row["old_enabled"] == 0 and row["new_enabled"] == 1 and row["role"] == "superadmin" for row in logs)
    assert "Gajiku: Belum dikonfigurasi" in owner.get(f"/superadmin/clients/{target}").get_data(as_text=True)
    assert form_post(owner, path, {"attendance_corrections": "1"}).status_code == 302
    with app.app_context():
        assert not client_features(target)["payroll"]
        assert query("SELECT COUNT(*) AS total FROM feature_audit_logs", one=True)["total"] == 4


@pytest.mark.parametrize("data", [{"gajiku": "1"}, {"payroll": "true"}, {"payroll": ["1", "1"]}])
def test_invalid_settings_do_not_change_data(app, records, data):
    path = f"/superadmin/clients/{records['client']['id']}/features"
    assert form_post(owner_client(app), path, data).status_code == 400
    with app.app_context():
        assert not client_features(records["client"]["id"])["payroll"]
        assert query("SELECT COUNT(*) AS total FROM feature_audit_logs", one=True)["total"] == 0


@pytest.mark.parametrize("address", ["admin@nusantara.test", "admin@cakrawala.test", "rani@nusantara.test"])
def test_only_superadmin_can_manage_features(app, records, address):
    browser = app.test_client()
    login(browser, address)
    path = f"/superadmin/clients/{records['client']['id']}/features"
    assert form_post(browser, path, {"payroll": "1"}).status_code == 403
    assert browser.get(f"/superadmin/clients/{records['client']['id']}").status_code == 403


def test_feature_form_csrf_and_missing_client(app):
    owner = owner_client(app)
    assert owner.post("/superadmin/clients/999999/features", data={"payroll": "1"}).status_code == 400
    assert form_post(owner, "/superadmin/clients/999999/features", {"payroll": "1"}).status_code == 404


def test_new_client_gets_persisted_feature_defaults(app, records):
    company = records["client"]
    response = form_post(owner_client(app), "/superadmin/clients/new", {
        "name": "PT Feature QA", "code": "FEATURE-QA", "email": "feature@qa.test", "employee_limit": "20",
        "service_start": str(company["service_start"]), "service_end": str(company["service_end"]),
    })
    assert response.status_code == 302
    with app.app_context():
        created = query("SELECT id FROM clients WHERE code='FEATURE-QA'", one=True)
        assert query("SELECT COUNT(*) AS total FROM client_features WHERE client_id=%s", (created["id"],), one=True)["total"] == 3
        assert client_features(created["id"]) == {"payroll": False, "attendance_corrections": True, "gajiku": False}


def test_failed_audit_rolls_back_feature_update(app, records, monkeypatch):
    from app.utils import features

    original = features.execute

    def fail_audit(sql, params=()):
        if "INSERT INTO feature_audit_logs" in sql:
            raise RuntimeError("audit unavailable")
        return original(sql, params)

    monkeypatch.setattr(features, "execute", fail_audit)
    owner = owner_client(app)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        form_post(owner, f"/superadmin/clients/{records['client']['id']}/features", {"payroll": "1"})
    with app.app_context():
        assert not client_features(records["client"]["id"])["payroll"]
        assert query("SELECT COUNT(*) AS total FROM feature_audit_logs", one=True)["total"] == 0


def test_backend_guard_revalidates_features_each_request(guard_app, records):
    admin, other, employee = (guard_app.test_client() for index in range(3))
    login(admin, "admin@nusantara.test")
    login(other, "admin@cakrawala.test")
    login(employee, "rani@nusantara.test")
    assert admin.get("/feature-test/payroll").status_code == 403
    assert admin.get("/feature-test/attendance_corrections").status_code == 200
    target = records["client"]["id"]
    owner = owner_client(guard_app)
    path = f"/superadmin/clients/{target}/features"
    assert form_post(owner, path, {"payroll": "1"}).status_code == 302
    assert admin.get("/feature-test/payroll").status_code == 200
    assert employee.get("/feature-test/payroll").status_code == 200
    assert other.get("/feature-test/payroll").status_code == 403
    assert admin.get("/feature-test/attendance_corrections").status_code == 403
    assert form_post(owner, path, {}).status_code == 302
    assert admin.get("/feature-test/payroll").status_code == 403
    assert owner.get("/feature-test/payroll").status_code == 403
    assert guard_app.test_client().get("/feature-test/payroll").status_code == 302
    with guard_app.app_context():
        execute("UPDATE client_features SET is_enabled=1 WHERE client_id=%s AND feature_key='gajiku'", (target,))
    assert admin.get("/feature-test/gajiku").status_code == 403


def test_concurrent_updates_have_one_audit_entry(app, records):
    browsers = [owner_client(app), owner_client(app)]
    path = f"/superadmin/clients/{records['client']['id']}/features"
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda browser: form_post(browser, path, {"payroll": "1", "attendance_corrections": "1"}), browsers))
    assert all(response.status_code == 302 for response in responses)
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM feature_audit_logs", one=True)["total"] == 1


def test_legacy_database_is_usable_and_dry_run_does_not_write(legacy_app, records):
    owner = owner_client(legacy_app)
    assert owner.get("/superadmin/").status_code == 200
    response = owner.get(f"/superadmin/clients/{records['client']['id']}")
    assert response.status_code == 200 and "Management fitur belum dirilis" in response.get_data(as_text=True)
    assert form_post(owner, f"/superadmin/clients/{records['client']['id']}/features", {"payroll": "1"}).status_code == 503
    result = legacy_app.test_cli_runner().invoke(args=["migrate-db"])
    assert result.exit_code == 0 and FEATURE_MIGRATION in result.output
    assert legacy_app.test_cli_runner().invoke(args=["init-db"]).exit_code == 0
    with legacy_app.app_context():
        assert not feature_schema_ready()
        assert query("SELECT COUNT(*) AS total FROM users", one=True)["total"] == 5
        assert query("SELECT COUNT(*) AS total FROM clients", one=True)["total"] == 2
        assert not query("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME='schema_migrations'", (legacy_app.config["MYSQL_DATABASE"],))


def test_missing_selected_env_does_not_fall_back_to_demo(monkeypatch):
    monkeypatch.setenv("ELRISE_ENV_FILE", "missing-feature-qa-env-file")
    with pytest.raises(RuntimeError, match="fallback"):
        create_app()


def test_session_cookie_name_can_be_isolated_from_demo(monkeypatch):
    from app.config import load_config

    monkeypatch.setenv("SESSION_COOKIE_NAME", "elrise_feature_qa_session")
    assert load_config()["SESSION_COOKIE_NAME"] == "elrise_feature_qa_session"


def test_apply_requires_target_and_backup_then_preserves_existing_data(legacy_app):
    runner = legacy_app.test_cli_runner()
    database = legacy_app.config["MYSQL_DATABASE"]
    for args in (["migrate-db", "--apply"], ["migrate-db", "--apply", "--database", database], ["migrate-db", "--apply", "--database", "elrise_flask_dev", "--backup-confirmed"]):
        assert runner.invoke(args=args).exit_code != 0
    result = runner.invoke(args=["migrate-db", "--apply", "--database", database, "--backup-confirmed"])
    assert result.exit_code == 0, result.output
    with legacy_app.app_context():
        assert feature_schema_ready()
        assert query("SELECT COUNT(*) AS total FROM users", one=True)["total"] == 5
        assert query("SELECT COUNT(*) AS total FROM client_features", one=True)["total"] == 6
        execute("UPDATE client_features SET is_enabled=1 WHERE feature_key='payroll'")
        execute("DELETE FROM schema_migrations WHERE version=%s", (FEATURE_MIGRATION,))
        migrate_database(apply=True)
        assert query("SELECT SUM(is_enabled) AS total FROM client_features WHERE feature_key='payroll'", one=True)["total"] == 2
        assert migrate_database(apply=True) == []


def test_migration_refuses_foreign_tables_and_checksum_changes(app):
    with app.app_context():
        execute("CREATE TABLE foreign_app (id INT PRIMARY KEY)")
    try:
        result = app.test_cli_runner().invoke(args=["migrate-db"])
        assert result.exit_code != 0 and "aplikasi lain" in result.output
    finally:
        with app.app_context():
            execute("DROP TABLE foreign_app")
    with app.app_context():
        checksum = query("SELECT checksum FROM schema_migrations WHERE version=%s", (FEATURE_MIGRATION,), one=True)["checksum"]
        execute("UPDATE schema_migrations SET checksum=%s WHERE version=%s", ("0" * 64, FEATURE_MIGRATION))
    try:
        result = app.test_cli_runner().invoke(args=["migrate-db"])
        assert result.exit_code != 0 and "Checksum" in result.output
    finally:
        with app.app_context():
            execute("UPDATE schema_migrations SET checksum=%s WHERE version=%s", (checksum, FEATURE_MIGRATION))


def test_migration_lock_blocks_concurrent_apply(app):
    with app.app_context():
        connection = connect()
    cursor = connection.cursor()
    lock_name = "elrise:migrate:" + hashlib.sha256(app.config["MYSQL_DATABASE"].encode()).hexdigest()[:32]
    cursor.execute("SELECT GET_LOCK(%s, 0)", (lock_name,))
    assert cursor.fetchone()[0] == 1
    try:
        result = app.test_cli_runner().invoke(args=["migrate-db", "--apply", "--database", app.config["MYSQL_DATABASE"], "--backup-confirmed"])
        assert result.exit_code != 0 and "proses lain" in result.output
    finally:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
        cursor.fetchone()
        cursor.close()
        connection.close()
