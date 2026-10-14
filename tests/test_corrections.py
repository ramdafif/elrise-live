import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook

from app.db import execute, query
from app.migrations import CORRECTION_MIGRATION, correction_schema_ready, migrate_database
from app.utils.attendance import attendance_source, effective_record
from app.utils.validation import now
from tests.conftest import attendance_payload, consent, form_post, login, submit

@pytest.fixture
def workflow(app, records):
    employee, admin, other_admin, other_employee = (app.test_client() for index in range(4))
    for browser, address in ((employee, "rani@nusantara.test"), (admin, "admin@nusantara.test"),
            (other_admin, "admin@cakrawala.test"), (other_employee, "bima@cakrawala.test")):
        assert login(browser, address).status_code == 302
    return {**records, "browser": employee, "admin": admin, "other_admin": other_admin,
        "other_browser": other_employee, "date": now().date() - timedelta(days=1)}

def payload(workflow, **overrides):
    return {"work_date": str(workflow["date"]), "kind": "missing_attendance", "check_in": "08:30",
        "check_out": "17:30", "reason": "Lupa mencatat kehadiran, mohon verifikasi HR.",
        "request_key": secrets.token_hex(16), **overrides}

def create_request(app, workflow, **overrides):
    response = form_post(workflow["browser"], "/employee/corrections/new", payload(workflow, **overrides))
    assert response.status_code == 302, response.get_data(as_text=True)
    with app.app_context():
        record = query("SELECT * FROM attendance_corrections WHERE client_id=%s ORDER BY id DESC LIMIT 1",
            (workflow["client"]["id"],), one=True)
    return record

def review(workflow, correction_id, status="approved", note="Sudah diverifikasi HR."):
    return form_post(workflow["admin"], f"/admin/corrections/{correction_id}/review", {"status": status, "admin_note": note})

def original_attendance(app, workflow, complete=True):
    work_date = workflow["date"]
    check_in, check_out = datetime.combine(work_date, time(10)), datetime.combine(work_date, time(16)) if complete else None
    with app.app_context():
        attendance_id = execute("""INSERT INTO attendances
            (client_id,employee_id,office_id,work_date,status,late_minutes,office_name,office_latitude,office_longitude,
             office_radius_m,office_max_accuracy_m,scheduled_start,scheduled_end,check_in_at,check_in_latitude,
             check_in_longitude,check_in_accuracy,check_in_distance,check_in_device_at,check_in_photo,check_out_at)
            SELECT e.client_id,e.id,o.id,%s,'late',60,o.name,o.latitude,o.longitude,o.radius_m,o.max_accuracy_m,
                o.start_time,o.end_time,%s,o.latitude,o.longitude,8,0,%s,'qa-original.jpg',%s
            FROM employees e JOIN office_locations o ON o.id=e.office_id AND o.client_id=e.client_id WHERE e.id=%s""",
            (work_date, check_in, check_in, check_out, workflow["employee"]["id"])).lastrowid
        return query("SELECT * FROM attendances WHERE id=%s", (attendance_id,), one=True)

def effective(app, workflow):
    with app.app_context():
        return effective_record(workflow["client"]["id"], workflow["employee"]["id"], workflow["date"])

def test_missing_attendance_end_to_end_and_consistent_export(app, workflow):
    record = create_request(app, workflow)
    correction_id = record["id"]
    assert effective(app, workflow) is None
    queue = workflow["admin"].get("/admin/corrections").get_data(as_text=True)
    assert "Rani Prameswari" in queue and "1 menunggu review" in queue
    assert "Rani Prameswari" not in workflow["other_admin"].get("/admin/corrections").get_data(as_text=True)
    assert review(workflow, correction_id).status_code == 302
    result = effective(app, workflow)
    assert result["id"] is None and result["correction_id"] == correction_id
    assert result["status"] == "present" and result["late_minutes"] == 0
    assert all(result[key] is None for key in ("check_in_photo", "check_in_latitude", "check_out_longitude", "original_check_in_at"))
    period = f"?start={workflow['date']}&end={workflow['date']}"
    for path in ("/employee/history" + period, "/employee/", f"/employee/corrections/{correction_id}"):
        response = workflow["browser"].get(path)
        assert response.status_code == 200 and "08:30" in response.get_data(as_text=True)
    detail = workflow["admin"].get(f"/admin/attendance/employee/{workflow['employee']['id']}/{workflow['date']}")
    assert detail.status_code == 200 and "tanpa selfie" in detail.get_data(as_text=True)
    exported = workflow["admin"].get("/admin/attendance/export.xlsx" + period)
    assert exported.status_code == 200
    rows = list(load_workbook(BytesIO(exported.data)).active.values)
    assert rows[1][5:9] == ("Hadir", "08:30:00", "17:30:00", 0)
    assert all(value is None for value in rows[1][9:17])
    assert rows[1][18] == correction_id and rows[1][19:] == (None, None)
    assert workflow["admin"].get("/admin/").status_code == 200
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendances", one=True)["total"] == 0
        audit = query("SELECT * FROM attendance_correction_audit ORDER BY id")
        assert [event["action"] for event in audit] == ["submitted", "approved"]
        assert audit[0]["actor_id"] == workflow["employee"]["user_id"]

@pytest.mark.parametrize("kind,complete,changes,expected", [
    ("check_in", True, {"check_in": "08:45", "check_out": ""}, ("08:45", "16:00", 0)),
    ("check_out", True, {"check_in": "", "check_out": "17:45"}, ("10:00", "17:45", 60)),
    ("missing_checkout", False, {"check_in": "", "check_out": "17:45"}, ("10:00", "17:45", 60)),
])
def test_time_corrections_preserve_all_original_evidence(app, workflow, kind, complete, changes, expected):
    original = original_attendance(app, workflow, complete)
    record = create_request(app, workflow, kind=kind, **changes)
    assert review(workflow, record["id"]).status_code == 302
    result = effective(app, workflow)
    assert (result["check_in_at"].strftime("%H:%M"), result["check_out_at"].strftime("%H:%M"), result["late_minutes"]) == expected
    with app.app_context():
        assert query("SELECT * FROM attendances WHERE id=%s", (original["id"],), one=True) == original
    detail = workflow["admin"].get(f"/admin/attendance/{original['id']}")
    assert detail.status_code == 200 and "Bukti absensi asli" in detail.get_data(as_text=True)

def test_correction_chain_has_one_effective_day_and_replay_does_not_reopen(app, workflow):
    first = create_request(app, workflow)
    assert review(workflow, first["id"]).status_code == 302
    second = create_request(app, workflow, kind="check_in", check_in="09:00:01", check_out="")
    assert second["base_correction_id"] == first["id"]
    assert review(workflow, second["id"]).status_code == 302
    result = effective(app, workflow)
    assert result["correction_id"] == second["id"] and result["late_minutes"] == 1
    assert result["check_out_at"].strftime("%H:%M") == "17:30"
    replay = payload(workflow, request_key=first["request_key"])
    assert form_post(workflow["browser"], "/employee/corrections/new", replay).status_code == 409
    with app.app_context():
        assert query(f"SELECT COUNT(*) AS total FROM {attendance_source()} effective", one=True)["total"] == 1

def test_reject_cancel_and_resubmit_keep_audit(app, workflow):
    first = create_request(app, workflow)
    assert review(workflow, first["id"], "rejected", "   ").status_code == 400
    assert review(workflow, first["id"], "rejected", "Tanggal perlu diverifikasi.").status_code == 302
    assert effective(app, workflow) is None
    assert "Tanggal perlu diverifikasi." in workflow["browser"].get(f"/employee/corrections/{first['id']}").get_data(as_text=True)
    second = create_request(app, workflow)
    cancel_path = f"/employee/corrections/{second['id']}/cancel"
    assert form_post(workflow["browser"], cancel_path).status_code == 302
    assert form_post(workflow["browser"], cancel_path).status_code == 409
    assert review(workflow, second["id"]).status_code == 409
    third = create_request(app, workflow)
    assert review(workflow, third["id"]).status_code == 302
    assert form_post(workflow["browser"], f"/employee/corrections/{third['id']}/cancel").status_code == 409
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_correction_audit", one=True)["total"] == 6

@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_submission_is_single_pending_request(app, workflow, same_key):
    second = app.test_client()
    login(second, "rani@nusantara.test")
    data = payload(workflow)
    calls = [(workflow["browser"], data), (second, data if same_key else payload(workflow))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda call: form_post(call[0], "/employee/corrections/new", call[1]).status_code, calls))
    assert sorted(statuses) == [302, 409]
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_corrections", one=True)["total"] == 1
        assert query("SELECT COUNT(*) AS total FROM attendance_correction_audit", one=True)["total"] == 1

@pytest.mark.parametrize("race", ["approve", "reject", "cancel"])
def test_concurrent_decisions_have_one_terminal_effect(app, workflow, race):
    record = create_request(app, workflow)
    second = app.test_client()
    login(second, "rani@nusantara.test" if race == "cancel" else "admin@nusantara.test")
    first_path = f"/admin/corrections/{record['id']}/review"
    second_path = f"/employee/corrections/{record['id']}/cancel" if race == "cancel" else first_path
    calls = [(workflow["admin"], first_path, {"status": "approved"}),
        (second, second_path, {"status": "rejected" if race == "reject" else "approved", "admin_note": "Decision QA"})]
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(lambda call: form_post(call[0], call[1], call[2]).status_code, calls))
    assert sorted(statuses) == [302, 409]
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_correction_audit", one=True)["total"] == 2

@pytest.mark.parametrize("changes", [
    {"kind": "unknown"}, {"reason": " "}, {"reason": "x" * 1001}, {"request_key": "bad"},
    {"check_in": "25:00"}, {"check_out": ""}, {"check_out": "08:00"}, {"check_out": "08:30"},
    {"check_in": "9:00"}, {"work_date": "2026-02-30"}, {"work_date": "2099-01-01"},
    {"work_date": "2000-01-01"}, {"kind": "check_in"}, {"kind": "missing_checkout"},
])
def test_invalid_submission_has_no_side_effects(app, workflow, changes):
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow, **changes)).status_code == 400
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_corrections", one=True)["total"] == 0

def test_tenant_role_csrf_ownership_and_html_escaping(app, workflow):
    record = create_request(app, workflow, reason='<script>alert("test")</script>', employee_id=workflow["other_employee"]["id"], client_id=workflow["other_client"]["id"])
    correction_id = record["id"]
    assert record["employee_id"] == workflow["employee"]["id"] and record["client_id"] == workflow["client"]["id"]
    assert workflow["other_browser"].get(f"/employee/corrections/{correction_id}").status_code == 404
    assert workflow["other_admin"].get(f"/admin/corrections/{correction_id}").status_code == 404
    assert form_post(workflow["other_admin"], f"/admin/corrections/{correction_id}/review", {"status": "approved"}).status_code == 404
    assert form_post(workflow["other_browser"], f"/employee/corrections/{correction_id}/cancel").status_code == 404
    assert workflow["browser"].get("/admin/corrections").status_code == 403
    assert workflow["admin"].get("/employee/corrections/new").status_code == 403
    assert form_post(workflow["browser"], f"/admin/corrections/{correction_id}/review", {"status": "approved"}).status_code == 403
    assert workflow["browser"].post(f"/employee/corrections/{correction_id}/cancel").status_code == 400
    assert workflow["admin"].post(f"/admin/corrections/{correction_id}/review", data={"status": "approved"}).status_code == 400
    html = workflow["admin"].get(f"/admin/corrections/{correction_id}").get_data(as_text=True)
    assert "&lt;script&gt;" in html and '<script>alert("test")</script>' not in html

def test_disabled_feature_blocks_operations_but_not_approved_attendance(app, workflow):
    record = create_request(app, workflow)
    assert review(workflow, record["id"]).status_code == 302
    before = effective(app, workflow)
    with app.app_context():
        execute("UPDATE client_features SET is_enabled=0 WHERE client_id=%s AND feature_key='attendance_corrections'", (workflow["client"]["id"],))
    for browser, path in ((workflow["browser"], "/employee/corrections"), (workflow["browser"], "/employee/corrections/new"),
            (workflow["browser"], f"/employee/corrections/{record['id']}"), (workflow["admin"], "/admin/corrections"),
            (workflow["admin"], f"/admin/corrections/{record['id']}")):
        assert browser.get(path).status_code == 403
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow)).status_code == 403
    assert review(workflow, record["id"]).status_code == 403
    assert form_post(workflow["browser"], f"/employee/corrections/{record['id']}/cancel").status_code == 403
    assert "Koreksi absensi</span>" not in workflow["browser"].get("/employee/").get_data(as_text=True)
    assert effective(app, workflow) == before
    assert workflow["other_admin"].get("/admin/corrections").status_code == 200
    with app.app_context():
        execute("UPDATE client_features SET is_enabled=1 WHERE client_id=%s AND feature_key='attendance_corrections'", (workflow["client"]["id"],))
    assert workflow["browser"].get(f"/employee/corrections/{record['id']}").status_code == 200

@pytest.mark.parametrize("with_original", [True, False])
def test_stale_original_blocks_approval_but_can_be_rejected(app, workflow, with_original):
    if with_original:
        original_attendance(app, workflow, complete=False)
    record = create_request(app, workflow, **({"kind": "missing_checkout", "check_in": ""} if with_original else {}))
    if with_original:
        with app.app_context():
            execute("UPDATE attendances SET check_out_at=%s WHERE employee_id=%s", (datetime.combine(workflow["date"], time(18)), workflow["employee"]["id"]))
    else:
        original_attendance(app, workflow)
    assert review(workflow, record["id"]).status_code == 409
    assert "Persetujuan diblokir" in workflow["admin"].get(f"/admin/corrections/{record['id']}").get_data(as_text=True)
    assert review(workflow, record["id"], "rejected").status_code == 302

def test_audit_failure_rolls_back_submission_and_decision(app, workflow, monkeypatch):
    import app.utils.corrections as corrections

    original_audit = corrections.audit
    def fail_audit(*args):
        raise RuntimeError("audit unavailable")
    monkeypatch.setattr(corrections, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        form_post(workflow["browser"], "/employee/corrections/new", payload(workflow))
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_corrections", one=True)["total"] == 0
    monkeypatch.setattr(corrections, "audit", original_audit)
    record = create_request(app, workflow)
    monkeypatch.setattr(corrections, "audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        review(workflow, record["id"])
    assert effective(app, workflow) is None
    with app.app_context():
        assert query("SELECT status FROM attendance_corrections", one=True)["status"] == "pending"

def test_approved_partial_correction_allows_real_checkout(app, workflow, selfie, monkeypatch):
    fixed_now = datetime.combine(now().date(), time(20))
    monkeypatch.setattr("app.routes.employee.now", lambda: fixed_now)
    monkeypatch.setattr("app.utils.corrections.now", lambda: fixed_now)
    workflow["date"] = fixed_now.date()
    original_attendance(app, workflow, complete=False)
    record = create_request(app, workflow, kind="check_in", check_in="08:30", check_out="")
    assert review(workflow, record["id"]).status_code == 302
    consent(workflow["browser"])
    response = submit(workflow["browser"], attendance_payload(workflow["browser"], selfie))
    assert response.status_code == 200, response.get_data(as_text=True)
    result = effective(app, workflow)
    assert result["check_in_at"].strftime("%H:%M") == "08:30"
    assert result["check_out_at"] == fixed_now and result["original_check_out_at"] == fixed_now

def test_complete_correction_blocks_real_attendance_and_leave(app, workflow, monkeypatch):
    fixed_now = datetime.combine(now().date(), time(20))
    monkeypatch.setattr("app.routes.employee.now", lambda: fixed_now)
    monkeypatch.setattr("app.utils.corrections.now", lambda: fixed_now)
    workflow["date"] = fixed_now.date()
    record = create_request(app, workflow)
    assert review(workflow, record["id"]).status_code == 302
    consent(workflow["browser"])
    assert workflow["browser"].get("/employee/attendance/challenge").status_code == 409
    assert form_post(workflow["browser"], "/employee/leaves", {"kind": "izin", "reason": "test", "start_date": str(workflow["date"]), "end_date": str(workflow["date"])}).status_code == 400

@pytest.mark.parametrize("status", ["pending", "approved"])
def test_correction_cannot_conflict_with_leave(app, workflow, status):
    with app.app_context():
        execute("INSERT INTO leave_requests (client_id,employee_id,kind,start_date,end_date,reason,status) VALUES (%s,%s,'izin',%s,%s,'QA',%s)",
            (workflow["client"]["id"], workflow["employee"]["id"], workflow["date"], workflow["date"], status))
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow)).status_code == 409

def test_previous_schema_remains_readable_and_migration_preserves_data(app, workflow):
    original = original_attendance(app, workflow)
    with app.app_context():
        assert app.config["MYSQL_DATABASE"].startswith("elrise_test_")
        execute("DROP TABLE attendance_correction_audit")
        execute("DROP TABLE attendance_corrections")
        execute("DELETE FROM schema_migrations WHERE version=%s", (CORRECTION_MIGRATION,))
    try:
        assert workflow["browser"].get("/employee/").status_code == 200
        assert workflow["admin"].get("/admin/attendance").status_code == 200
        assert workflow["browser"].get("/employee/corrections").status_code == 503
        with app.app_context():
            assert migrate_database() == [CORRECTION_MIGRATION]
            assert not correction_schema_ready()
            assert query("SELECT * FROM attendances WHERE id=%s", (original["id"],), one=True) == original
    finally:
        with app.app_context():
            migrate_database(apply=True)
    with app.app_context():
        assert correction_schema_ready() and migrate_database() == []
        assert query("SELECT * FROM attendances WHERE id=%s", (original["id"],), one=True) == original

def test_employee_delete_and_privacy_erase_preserve_correction_audit(app, workflow):
    create_request(app, workflow)
    assert form_post(workflow["admin"], f"/admin/employees/{workflow['employee']['id']}/delete").status_code == 400
    with app.app_context():
        execute("UPDATE employees SET is_active=0 WHERE id=%s", (workflow["employee"]["id"],))
    result = app.test_cli_runner().invoke(args=["erase-employee", "--client-id", str(workflow["client"]["id"]), "--employee-id", str(workflow["employee"]["id"]), "--yes"])
    assert result.exit_code != 0 and "audit koreksi" in result.output
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_correction_audit", one=True)["total"] == 1

def test_other_employee_in_same_tenant_cannot_view_or_cancel(app, workflow):
    from tests.test_workflows import employee_data

    record = create_request(app, workflow)
    data = employee_data(workflow["employee"]["office_id"], "CORRECTION-PEER")
    assert form_post(workflow["admin"], "/admin/employees/new", data).status_code == 302
    with app.app_context():
        execute("UPDATE users SET must_change_password=0 WHERE email=%s", (data["email"],))
    peer = app.test_client()
    login(peer, data["email"], data["password"])
    assert peer.get(f"/employee/corrections/{record['id']}").status_code == 404
    assert form_post(peer, f"/employee/corrections/{record['id']}/cancel").status_code == 404
    assert "Lupa mencatat kehadiran" not in peer.get("/employee/corrections").get_data(as_text=True)

@pytest.mark.parametrize("target", ["employee", "client", "expired"])
def test_inactive_identity_or_service_cannot_submit(app, workflow, target):
    with app.app_context():
        if target == "employee":
            execute("UPDATE employees SET is_active=0 WHERE id=%s", (workflow["employee"]["id"],))
        elif target == "client":
            execute("UPDATE clients SET is_active=0 WHERE id=%s", (workflow["client"]["id"],))
        else:
            execute("UPDATE clients SET service_end=%s WHERE id=%s", (workflow["date"], workflow["client"]["id"]))
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow)).status_code == 403

def test_same_day_future_time_is_rejected(app, workflow, monkeypatch):
    monkeypatch.setattr("app.utils.corrections.now", lambda: datetime.combine(workflow["date"], time(12)))
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow)).status_code == 400

@pytest.mark.parametrize("changes", [
    {"kind": "check_in", "check_in": "10:00", "check_out": ""},
    {"kind": "check_in", "check_in": "08:30", "check_out": "17:30"},
    {"kind": "missing_checkout", "check_in": "", "check_out": "17:30"},
    {"kind": "missing_attendance"},
])
def test_kind_and_unchanged_fields_are_validated(app, workflow, changes):
    original_attendance(app, workflow)
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow, **changes)).status_code == 400

def test_retention_does_not_erase_correction_audit_or_original(app, workflow, monkeypatch):
    original = original_attendance(app, workflow)
    create_request(app, workflow, kind="check_in", check_in="08:30", check_out="")
    monkeypatch.setattr("app.cli.now", lambda: now() + timedelta(days=5))
    monkeypatch.setitem(app.config, "ATTENDANCE_RETENTION_DAYS", 1)
    result = app.test_cli_runner().invoke(args=["purge-data", "--apply"])
    assert result.exit_code == 0 and "dipertahankan" in result.output
    with app.app_context():
        assert query("SELECT * FROM attendances WHERE id=%s", (original["id"],), one=True) == original
        assert query("SELECT COUNT(*) AS total FROM attendance_correction_audit", one=True)["total"] == 1

def test_entitlement_is_rechecked_under_lock(app, workflow, monkeypatch):
    import app.utils.corrections as corrections

    original_lock = corrections.lock_scope
    def disable_before_lock(employee_id):
        execute("UPDATE client_features SET is_enabled=0 WHERE client_id=%s AND feature_key='attendance_corrections'", (workflow["client"]["id"],))
        return original_lock(employee_id)
    monkeypatch.setattr(corrections, "lock_scope", disable_before_lock)
    assert form_post(workflow["browser"], "/employee/corrections/new", payload(workflow)).status_code == 403
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendance_corrections", one=True)["total"] == 0
