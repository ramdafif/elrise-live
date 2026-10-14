import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from app.db import execute, query
from app.routes.employee import serializer
from app.utils.geofence import haversine
from app.utils.validation import now
from tests.conftest import attendance_payload, consent, form_post, login, submit


def employee_browser(app):
    browser = app.test_client()
    assert login(browser, "rani@nusantara.test").status_code == 302
    consent(browser)
    return browser


def test_haversine_known_distances():
    assert haversine(-6.2, 106.8, -6.2, 106.8) == 0
    assert 110 <= haversine(0, 0, 0.001, 0) <= 112
    assert haversine(0, 0, 0, 180) == pytest.approx(20015086.8, rel=0.00001)


def test_check_in_and_check_out_real_database_and_private_files(app, records, selfie):
    browser = employee_browser(app)
    check_in = submit(browser, attendance_payload(browser, selfie))
    assert check_in.status_code == 200, check_in.get_data(as_text=True)
    attendance_id = check_in.get_json()["attendance_id"]
    check_out = submit(browser, attendance_payload(browser, selfie))
    assert check_out.status_code == 200
    assert check_out.get_json()["attendance_id"] == attendance_id
    with app.app_context():
        record = query("SELECT * FROM attendances WHERE id=%s", (attendance_id,), one=True)
        assert record["client_id"] == records["client"]["id"]
        assert record["employee_id"] == records["employee"]["id"]
        assert record["check_out_at"] >= record["check_in_at"]
        assert record["check_in_distance"] == 0 and record["check_out_distance"] == 0
        assert record["check_in_photo"] != record["check_out_photo"]
        for column in ("check_in_photo", "check_out_photo"):
            path = Path(app.config["PRIVATE_UPLOAD_DIR"]) / record[column]
            assert path.is_file()
            with Image.open(path) as photo:
                assert photo.format == "JPEG" and not photo.getexif()
            assert base64.b64encode(path.read_bytes()).decode() != selfie.split(",")[1]
    assert browser.get("/employee/history").status_code == 200
    assert browser.get("/employee/attendance/challenge").status_code == 409


@pytest.mark.parametrize("overrides,part", [
    ({"latitude": -6.204}, "luar geofence"),
    ({"accuracy": 51}, "belum akurat"),
    ({"accuracy": 0}, "accuracy"),
    ({"accuracy": -1}, "accuracy"),
    ({"accuracy": True}, "accuracy"),
    ({"latitude": float("nan")}, "latitude"),
    ({"latitude": 91}, "latitude"),
    ({"longitude": float("inf")}, "longitude"),
    ({"selfie": ""}, "Selfie"),
    ({"selfie": None}, "Selfie"),
    ({"selfie": "data:image/jpeg;base64,not-base64"}, "Selfie"),
    ({"selfie": "data:image/png;base64,iVBORw0KGgo="}, "Selfie"),
])
def test_invalid_attendance_rejected_without_rows_or_files(app, selfie, overrides, part):
    browser = employee_browser(app)
    before = set(Path(app.config["PRIVATE_UPLOAD_DIR"]).rglob("*.jpg"))
    response = submit(browser, attendance_payload(browser, selfie, **overrides))
    assert response.status_code == 400
    assert part.lower() in response.get_json()["message"].lower()
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendances", one=True)["total"] == 0
    assert set(Path(app.config["PRIVATE_UPLOAD_DIR"]).rglob("*.jpg")) == before


def test_photo_size_and_image_dimensions(app, selfie):
    browser = employee_browser(app)
    too_large = "data:image/jpeg;base64," + "A" * (app.config["MAX_PHOTO_BYTES"] * 2)
    assert submit(browser, attendance_payload(browser, selfie, selfie=too_large)).status_code == 400
    output = BytesIO()
    Image.new("RGB", (80, 80)).save(output, format="JPEG")
    too_small = "data:image/jpeg;base64," + base64.b64encode(output.getvalue()).decode()
    assert submit(browser, attendance_payload(browser, selfie, selfie=too_small)).status_code == 400


@pytest.mark.parametrize("scenario", ["clock", "stale_gps", "future_gps", "forged", "wrong_action", "other_user"])
def test_client_time_and_challenge_validation(app, selfie, scenario):
    browser = employee_browser(app)
    payload = attendance_payload(browser, selfie)
    if scenario == "clock":
        payload["device_time"] += 360000
        payload["location_time"] = payload["device_time"]
    elif scenario == "stale_gps":
        payload["location_time"] -= 61000
    elif scenario == "future_gps":
        payload["location_time"] += 6000
    elif scenario == "forged":
        payload["challenge"] += "forged"
    elif scenario == "wrong_action":
        payload["action"] = "check_out"
    else:
        other = app.test_client()
        login(other, "bima@cakrawala.test")
        consent(other)
        payload["challenge"] = attendance_payload(other, selfie)["challenge"]
    response = submit(browser, payload)
    assert response.status_code == 400


def test_expired_challenge(app, selfie):
    import time
    from itsdangerous import TimestampSigner, URLSafeTimedSerializer

    browser = employee_browser(app)
    payload = attendance_payload(browser, selfie)

    class OldSigner(TimestampSigner):
        def get_timestamp(self):
            return int(time.time()) - 180

    with app.app_context():
        data = serializer().loads(payload["challenge"])
        expired = URLSafeTimedSerializer(app.config["SECRET_KEY"], salt="elrise-attendance", signer=OldSigner)
        payload["challenge"] = expired.dumps(data)
    response = submit(browser, payload)
    assert response.status_code == 400 and "berakhir" in response.get_json()["message"]


def test_simultaneous_check_in_only_one_row(app, selfie):
    first = employee_browser(app)
    payload = attendance_payload(first, selfie)
    second = app.test_client()
    cookie_name = app.config["SESSION_COOKIE_NAME"]
    second.set_cookie(cookie_name, first.get_cookie(cookie_name).value)
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda browser: submit(browser, payload), [first, second]))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with app.app_context():
        assert query("SELECT COUNT(*) AS total FROM attendances", one=True)["total"] == 1


def test_check_out_without_check_in_rejected_by_backend(app, selfie):
    browser = employee_browser(app)
    payload = attendance_payload(browser, selfie)
    with app.app_context():
        signed = serializer().loads(payload["challenge"])
        signed["action"] = "check_out"
        payload["challenge"] = serializer().dumps(signed)
    payload["action"] = "check_out"
    response = submit(browser, payload)
    assert response.status_code == 409 and "memerlukan check-in" in response.get_json()["message"]


@pytest.mark.parametrize("override", [{"latitude": -6.204}, {"accuracy": 51}, {"selfie": ""}])
def test_check_out_also_validates_gps_and_photo(app, selfie, override):
    browser = employee_browser(app)
    assert submit(browser, attendance_payload(browser, selfie)).status_code == 200
    response = submit(browser, attendance_payload(browser, selfie, **override))
    assert response.status_code == 400
    with app.app_context():
        assert query("SELECT check_out_at FROM attendances", one=True)["check_out_at"] is None


def test_check_out_uses_check_in_office_snapshot(app, records, selfie):
    browser = employee_browser(app)
    assert submit(browser, attendance_payload(browser, selfie)).status_code == 200
    with app.app_context():
        execute("UPDATE office_locations SET latitude=0,longitude=0,radius_m=200 WHERE id=%s", (records["employee"]["office_id"],))
    assert submit(browser, attendance_payload(browser, selfie)).status_code == 200


@pytest.mark.parametrize("hour,minute,status,late", [(8, 59, "present", 0), (9, 0, "present", 0), (9, 7, "late", 7)])
def test_lateness_uses_office_schedule_and_server_time(app, selfie, monkeypatch, hour, minute, status, late):
    fixed = now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    monkeypatch.setattr("app.routes.employee.now", lambda: fixed)
    browser = employee_browser(app)
    assert submit(browser, attendance_payload(browser, selfie)).status_code == 200
    with app.app_context():
        record = query("SELECT * FROM attendances", one=True)
        assert record["status"] == status and record["late_minutes"] == late
        assert record["check_in_at"] == fixed


def test_privacy_required_versioned_and_can_be_withdrawn(app, selfie, monkeypatch):
    browser = app.test_client()
    login(browser, "rani@nusantara.test")
    assert browser.get("/employee/attendance").location.endswith("/employee/privacy")
    assert browser.get("/employee/attendance/challenge").status_code == 403
    consent(browser)
    assert browser.get("/employee/attendance/challenge").status_code == 200
    monkeypatch.setitem(app.config, "PRIVACY_VERSION", "next-version")
    assert browser.get("/employee/attendance/challenge").status_code == 403
    consent(browser)
    assert form_post(browser, "/employee/privacy/withdraw").status_code == 302
    assert browser.get("/employee/attendance/challenge").status_code == 403


def test_retention_dry_run_then_deletes_file_and_clears_path(app, selfie):
    browser = employee_browser(app)
    response = submit(browser, attendance_payload(browser, selfie))
    attendance_id = response.get_json()["attendance_id"]
    with app.app_context():
        record = query("SELECT * FROM attendances WHERE id=%s", (attendance_id,), one=True)
        path = Path(app.config["PRIVATE_UPLOAD_DIR"]) / record["check_in_photo"]
        execute("UPDATE attendances SET work_date=%s,check_in_at=%s WHERE id=%s", (now().date() - timedelta(days=40), now() - timedelta(days=40), attendance_id))
    runner = app.test_cli_runner()
    assert runner.invoke(args=["purge-data"]).exit_code == 0 and path.exists()
    result = runner.invoke(args=["purge-data", "--apply"])
    assert result.exit_code == 0, result.output
    assert not path.exists()
    with app.app_context():
        assert query("SELECT check_in_photo FROM attendances WHERE id=%s", (attendance_id,), one=True)["check_in_photo"] is None
    assert browser.get(f"/employee/photos/{attendance_id}/in").status_code == 404


@pytest.mark.parametrize("scenario", ["future_start", "nonworking_day"])
def test_employment_date_and_working_day_rules(app, records, selfie, scenario):
    browser = employee_browser(app)
    payload = attendance_payload(browser, selfie)
    with app.app_context():
        if scenario == "future_start":
            execute("UPDATE employees SET join_date=%s WHERE id=%s", (now().date() + timedelta(days=1), records["employee"]["id"]))
        else:
            different_day = str(now().date().isoweekday() % 7 + 1)
            execute("UPDATE office_locations SET working_days=%s WHERE id=%s", (different_day, records["employee"]["office_id"]))
    assert submit(browser, payload).status_code == (403 if scenario == "future_start" else 400)
