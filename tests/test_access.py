import pytest
from mysql.connector import IntegrityError

from app.db import execute, query, transaction
from app.utils.validation import now
from tests.conftest import attendance_payload, consent, form_post, login, submit, token


@pytest.mark.parametrize("email,path", [("owner@elrise.test", "/superadmin/"), ("admin@nusantara.test", "/admin/"), ("rani@nusantara.test", "/employee/")])
def test_login_each_role(app, email, path):
    client = app.test_client()
    response = login(client, email)
    assert response.status_code == 302 and response.location.endswith(path)
    page = client.get(path)
    assert page.status_code == 200
    assert "Content-Security-Policy" in page.headers
    assert page.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("address,paths", [
    ("rani@nusantara.test", ["/admin/", "/admin/employees", "/superadmin/", "/superadmin/clients"]),
    ("admin@nusantara.test", ["/superadmin/", "/superadmin/clients", "/employee/", "/employee/history"]),
    ("owner@elrise.test", ["/admin/", "/employee/"]),
])
def test_roles_cannot_access_other_workspaces(app, address, paths):
    client = app.test_client()
    assert login(client, address).status_code == 302
    for path in paths:
        assert client.get(path).status_code == 403


def test_csrf_on_login_forms_and_json(app):
    client = app.test_client()
    client.get("/login")
    assert client.post("/login", data={"email": "owner@elrise.test", "password": "wrong"}).status_code == 400
    login(client, "rani@nusantara.test")
    assert client.post("/employee/privacy", data={"consent": "1"}).status_code == 400
    assert client.post("/employee/attendance/submit", json={}).status_code == 400
    assert client.post("/logout").status_code == 400


def test_login_rate_limit_persists_between_clients(app):
    first = app.test_client()
    for attempt in range(5):
        assert login(first, "rani@nusantara.test", "wrong-password").status_code == 401
    second = app.test_client()
    response = login(second, "rani@nusantara.test", "wrong-password")
    assert response.status_code == 429 and response.headers["Retry-After"] == "900"


def test_successful_logins_do_not_exhaust_shared_office_ip(app):
    client = app.test_client()
    for attempt in range(45):
        assert login(client, "rani@nusantara.test").status_code == 302
        assert form_post(client, "/logout").status_code == 302


def test_admin_cannot_read_or_write_other_tenant(app, records):
    client = app.test_client()
    login(client, "admin@nusantara.test")
    foreign_employee = records["other_employee"]["id"]
    foreign_office = records["other_employee"]["office_id"]
    assert "Bima Adiputra" not in client.get("/admin/employees").get_data(as_text=True)
    for path in [f"/admin/employees/{foreign_employee}/edit", f"/admin/offices/{foreign_office}/edit"]:
        assert client.get(path).status_code == 404
        assert form_post(client, path, {}).status_code == 404
    assert form_post(client, f"/admin/employees/{foreign_employee}/delete").status_code == 404
    assert form_post(client, f"/admin/employees/{foreign_employee}/reset", {"password": "Reset-Password!2026"}).status_code == 404
    assert form_post(client, f"/admin/offices/{foreign_office}/delete").status_code == 404
    assert client.get(f"/admin/attendance?office_id={foreign_office}").status_code == 404


def test_composite_fk_rejects_cross_tenant_office(app, records):
    with app.app_context(), pytest.raises(IntegrityError), transaction():
        execute("UPDATE employees SET office_id=%s WHERE id=%s AND client_id=%s", (records["other_employee"]["office_id"], records["employee"]["id"], records["client"]["id"]))


@pytest.mark.parametrize("target", ["employee", "user", "client", "expired", "not_started"])
def test_unavailable_accounts_cannot_login(app, records, target):
    with app.app_context():
        if target == "employee":
            execute("UPDATE employees SET is_active=0 WHERE id=%s", (records["employee"]["id"],))
        elif target == "user":
            execute("UPDATE users SET is_active=0 WHERE id=%s", (records["employee"]["user_id"],))
        elif target == "client":
            execute("UPDATE clients SET is_active=0 WHERE id=%s", (records["client"]["id"],))
        elif target == "expired":
            execute("UPDATE clients SET service_start='2000-01-01',service_end='2001-01-01' WHERE id=%s", (records["client"]["id"],))
        else:
            execute("UPDATE clients SET service_start='2099-01-01',service_end='2100-01-01' WHERE id=%s", (records["client"]["id"],))
    assert login(app.test_client(), "rani@nusantara.test").status_code == 401


@pytest.mark.parametrize("target", ["employee", "client", "expired", "reset"])
def test_existing_sessions_revalidate_on_every_request(app, records, target):
    client = app.test_client()
    login(client, "rani@nusantara.test")
    consent(client)
    with app.app_context():
        if target == "employee":
            execute("UPDATE employees SET is_active=0 WHERE id=%s", (records["employee"]["id"],))
        elif target == "client":
            execute("UPDATE clients SET is_active=0 WHERE id=%s", (records["client"]["id"],))
        elif target == "expired":
            execute("UPDATE clients SET service_start='2000-01-01',service_end='2001-01-01' WHERE id=%s", (records["client"]["id"],))
        else:
            execute("UPDATE users SET session_version=session_version+1 WHERE id=%s", (records["employee"]["user_id"],))
    response = client.get("/employee/")
    assert response.status_code in {302, 403}
    assert not client.get("/employee/attendance/challenge").status_code == 200


def test_session_role_field_is_not_trusted(app):
    client = app.test_client()
    login(client, "rani@nusantara.test")
    with client.session_transaction() as session:
        session["role"] = "superadmin"
        session["client_id"] = 999999
    assert client.get("/superadmin/").status_code == 403


def test_photo_is_private_to_owner_and_same_tenant_admin(app, selfie):
    employee = app.test_client()
    login(employee, "rani@nusantara.test")
    consent(employee)
    response = submit(employee, attendance_payload(employee, selfie))
    assert response.status_code == 200
    attendance_id = response.get_json()["attendance_id"]
    path = f"/employee/photos/{attendance_id}/in"
    assert employee.get(path).status_code == 200
    for address, expected in [("admin@nusantara.test", 200), ("admin@cakrawala.test", 404), ("bima@cakrawala.test", 404), ("owner@elrise.test", 403)]:
        browser = app.test_client()
        login(browser, address)
        photo = browser.get(path)
        assert photo.status_code == expected
        if expected == 200:
            assert photo.mimetype == "image/jpeg" and "no-store" in photo.headers["Cache-Control"]
    with app.app_context():
        photo_path = query("SELECT check_in_photo FROM attendances WHERE id=%s", (attendance_id,), one=True)["check_in_photo"]
    assert employee.get("/static/uploads/attendance/" + photo_path).status_code == 404
    assert app.test_client().get(path).status_code == 302


def test_employee_cannot_view_colleague_photo_in_same_tenant(app, records, selfie):
    employee = app.test_client()
    login(employee, "rani@nusantara.test")
    consent(employee)
    attendance_id = submit(employee, attendance_payload(employee, selfie)).get_json()["attendance_id"]
    from werkzeug.security import generate_password_hash
    from tests.conftest import TEST_PASSWORD

    with app.app_context(), transaction():
        user_id = execute("INSERT INTO users (client_id,name,email,password_hash,role,must_change_password) VALUES (%s,'Colleague','colleague@nusantara.test',%s,'employee',0)", (records["client"]["id"], generate_password_hash(TEST_PASSWORD))).lastrowid
        execute("INSERT INTO employees (client_id,user_id,office_id,employee_number,name,join_date) VALUES (%s,%s,%s,'COLLEAGUE','Colleague',%s)", (records["client"]["id"], user_id, records["employee"]["office_id"], now().date()))
    colleague = app.test_client()
    login(colleague, "colleague@nusantara.test")
    assert colleague.get(f"/employee/photos/{attendance_id}/in").status_code == 404
