import base64
import secrets
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app import create_app
from app.cli import initialize_database
from app.db import connect, execute, query

TEST_PASSWORD = "Testing-Password!2026"


@pytest.fixture(scope="session")
def application(tmp_path_factory):
    database_name = "elrise_test_" + secrets.token_hex(6)
    app = create_app({"TESTING": True, "APP_ENV": "development", "SECRET_KEY": secrets.token_hex(32),
        "MYSQL_DATABASE": database_name, "SESSION_COOKIE_SECURE": False, "DEMO_PASSWORD": TEST_PASSWORD,
        "PRIVATE_UPLOAD_DIR": str(tmp_path_factory.mktemp("elrise-photos")), "TRUSTED_HOSTS": ["localhost", "127.0.0.1"]})
    with app.app_context():
        connection = connect(database=False)
        cursor = connection.cursor()
        cursor.execute("SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s", (database_name,))
        assert cursor.fetchone() is None, "Tests refuse to reuse any existing database."
        cursor.close()
        connection.close()
        initialize_database()
    yield app
    with app.app_context():
        assert app.config["MYSQL_DATABASE"] == database_name and database_name.startswith("elrise_test_")
        connection = connect(database=False)
        cursor = connection.cursor()
        cursor.execute(f"DROP DATABASE {database_name}")
        cursor.close()
        connection.close()


@pytest.fixture
def app(application):
    with application.app_context():
        for table in ("attendances", "leave_requests", "employees", "office_locations", "users", "clients", "login_limits"):
            execute(f"DELETE FROM {table}")
    result = application.test_cli_runner().invoke(args=["seed-demo"])
    assert result.exit_code == 0, result.output
    with application.app_context():
        execute("UPDATE office_locations SET working_days='1,2,3,4,5,6,7'")
    return application


@pytest.fixture
def records(app):
    with app.app_context():
        return {
            "client": query("SELECT * FROM clients WHERE code='NUSA'", one=True),
            "other_client": query("SELECT * FROM clients WHERE code='CAKRA'", one=True),
            "employee": query("SELECT * FROM employees WHERE client_id=(SELECT id FROM clients WHERE code='NUSA')", one=True),
            "other_employee": query("SELECT * FROM employees WHERE client_id=(SELECT id FROM clients WHERE code='CAKRA')", one=True),
        }


@pytest.fixture(scope="session")
def selfie():
    output = BytesIO()
    image = Image.new("RGB", (640, 640), color=(160, 190, 180))
    exif = Image.Exif()
    exif[270] = "untrusted client metadata"
    image.save(output, format="JPEG", exif=exif)
    return "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()


def token(client):
    with client.session_transaction() as session:
        return session["csrf_token"]


def form_post(client, path, data=None, **kwargs):
    values = {"csrf_token": token(client), **(data or {})}
    return client.post(path, data=values, **kwargs)


def login(client, address, initial=TEST_PASSWORD):
    client.get("/login")
    return form_post(client, "/login", {"email": address, "password": initial})


def consent(client):
    response = form_post(client, "/employee/privacy", {"consent": "1"})
    assert response.status_code == 302


def attendance_payload(client, selfie_data, **overrides):
    challenge = client.get("/employee/attendance/challenge")
    assert challenge.status_code == 200, challenge.get_data(as_text=True)
    data = challenge.get_json()
    payload = {"action": data["action"], "challenge": data["challenge"], "latitude": -6.2, "longitude": 106.816666,
        "accuracy": 8, "device_time": data["server_time"], "location_time": data["server_time"], "selfie": selfie_data}
    payload.update(overrides)
    return payload


def submit(client, payload):
    return client.post("/employee/attendance/submit", json=payload, headers={"X-CSRF-Token": token(client)})
