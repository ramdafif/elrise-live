import json
import logging
import secrets
from datetime import timedelta
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from app import create_app
from app.cli import initialize_database
from app.config import ROOT
from app.db import connect, query
from app.utils.validation import now


def main():
    database_name = "elrise_test_browser_" + secrets.token_hex(6)
    initial_password = "Browser-QA!" + secrets.token_hex(8)
    output = ROOT / "test-results"
    output.mkdir(exist_ok=True)
    app = create_app({"APP_ENV": "development", "TESTING": True, "SECRET_KEY": secrets.token_hex(32),
        "MYSQL_DATABASE": database_name, "DEMO_PASSWORD": initial_password, "SESSION_COOKIE_SECURE": False,
        "PRIVATE_UPLOAD_DIR": str(output / database_name / "photos")})
    with app.app_context():
        initialize_database()
    seed = app.test_cli_runner().invoke(args=["seed-demo"])
    assert seed.exit_code == 0, seed.output
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    checks = []

    def register(page):
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        page.on("dialog", lambda dialog: dialog.accept())

    def login(page, address):
        page.goto(base + "/login")
        branding_loaded(page)
        no_overflow(page)
        page.locator('input[name="email"]').fill(address)
        page.locator('input[name="password"]').fill(initial_password)
        page.get_by_role("button", name="Masuk ke workspace").click()
        page.wait_for_url("**/" + ("superadmin/" if address == "owner@elrise.test" else "admin/" if address.startswith("admin@") else "employee/"))

    def no_overflow(page):
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), page.url

    def branding_loaded(page):
        expect(page.locator("img[data-brand-logo]").first).to_have_js_property("naturalWidth", 256)
        assert page.locator("img[data-brand-logo]").evaluate_all(
            "images => images.length >= 2 && images.every(image => image.complete && image.naturalWidth > 0)"
        ), page.url

    def desktop_login_fit(page):
        geometry = page.evaluate("""() => {
            const bounds = selector => {
                const rectangle = document.querySelector(selector).getBoundingClientRect();
                return {center: rectangle.x + rectangle.width / 2, width: rectangle.width,
                    top: rectangle.top, bottom: rectangle.bottom};
            };
            return {width: innerWidth, height: innerHeight,
                documentWidth: document.documentElement.scrollWidth,
                documentHeight: document.documentElement.scrollHeight,
                panel: bounds('.login-story'), content: bounds('.story-content'),
                copy: bounds('.story-copy'), art: bounds('.story-art'),
                form: bounds('.login-form-wrap'), copyright: bounds('.login-copyright'),
                controlsVisible: [...document.querySelectorAll('.login-form-wrap input:not([type="hidden"]), .login-form-wrap button')]
                    .every(control => {
                        const rectangle = control.getBoundingClientRect();
                        return rectangle.top >= 0 && rectangle.bottom <= innerHeight &&
                            rectangle.left >= 0 && rectangle.right <= innerWidth;
                    })};
        }""")
        assert geometry["documentWidth"] <= geometry["width"], geometry
        assert geometry["documentHeight"] <= geometry["height"], geometry
        assert abs(geometry["panel"]["width"] - geometry["width"] / 2) <= 1, geometry
        for element in ["content", "copy", "art"]:
            assert abs(geometry[element]["center"] - geometry["panel"]["center"]) <= 1, geometry
        assert geometry["form"]["top"] >= 0 and geometry["controlsVisible"], geometry
        assert geometry["form"]["bottom"] + 8 <= geometry["copyright"]["top"], geometry

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True,
                args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
            desktop = browser.new_context(viewport={"width": 1440, "height": 1000})
            layout_page = desktop.new_page()
            layout_page.on("pageerror", lambda error: errors.append(str(error)))
            for width, height in [(1366, 768), (1280, 600), (1280, 560), (1024, 600),
                    (800, 600), (1440, 900), (1536, 864), (1920, 1080)]:
                layout_page.set_viewport_size({"width": width, "height": height})
                layout_page.goto(base + "/login")
                branding_loaded(layout_page)
                desktop_login_fit(layout_page)
                if (width, height) == (1366, 768):
                    layout_page.screenshot(path=str(output / "desktop-login-1366x768.png"))
            layout_page.locator('input[name="email"]').fill("layout-check@elrise.test")
            layout_page.locator('input[name="password"]').fill("not-a-valid-layout-password")
            with layout_page.expect_response(lambda response: response.url.endswith("/login") and response.request.method == "POST") as rejected:
                layout_page.get_by_role("button", name="Masuk ke workspace").click()
            assert rejected.value.status == 401
            expect(layout_page.locator(".notice-danger")).to_be_visible()
            for width, height in [(1280, 560), (1366, 768)]:
                layout_page.set_viewport_size({"width": width, "height": height})
                desktop_login_fit(layout_page)
            layout_page.close()
            checks.append("desktop login has no page scroll at eight viewport sizes; left copy and art are centered; form and error notice remain visible")
            admin_page = desktop.new_page()
            register(admin_page)
            admin_page.goto(base + "/login")
            branding_loaded(admin_page)
            favicon = admin_page.request.get(base + "/static/img/favicon.png")
            assert favicon.status == 200 and favicon.headers["content-type"].startswith("image/png")
            admin_page.screenshot(path=str(output / "desktop-login.png"), full_page=True)
            login(admin_page, "admin@nusantara.test")
            branding_loaded(admin_page)
            no_overflow(admin_page)
            admin_page.wait_for_timeout(700)
            admin_page.screenshot(path=str(output / "desktop-admin.png"), full_page=True)
            checks.append("desktop admin login, dashboard, assets, no overflow")

            mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                permissions=["geolocation", "camera"], geolocation={"latitude": -6.2, "longitude": 106.816666, "accuracy": 10})
            employee_page = mobile.new_page()
            register(employee_page)
            login(employee_page, "rani@nusantara.test")
            branding_loaded(employee_page)
            expect(employee_page.locator(".mobile-brand")).to_be_visible()
            no_overflow(employee_page)
            expect(employee_page.locator(".bottom-nav")).to_be_visible()
            employee_page.screenshot(path=str(output / "mobile-employee.png"), full_page=True)
            employee_page.goto(base + "/employee/attendance")
            employee_page.wait_for_url("**/employee/privacy")
            employee_page.locator('input[name="consent"]').check()
            employee_page.get_by_role("button", name="Setuju & lanjut ke absensi").click()
            employee_page.wait_for_url("**/employee/attendance")
            no_overflow(employee_page)

            for action in ["check_in", "check_out"]:
                employee_page.bring_to_front()
                expect(employee_page.locator("#attendance-app")).to_have_attribute("data-action", action)
                employee_page.locator("#start-attendance").click()
                expect(employee_page.locator("#capture-selfie")).to_be_enabled(timeout=20000)
                expect(employee_page.locator("#gps-distance")).to_have_text("0 m")
                employee_page.locator("#capture-selfie").click()
                expect(employee_page.locator("#selfie-preview")).to_be_visible(timeout=15000)
                expect(employee_page.locator("#submit-attendance")).to_be_enabled()
                if action == "check_in":
                    employee_page.screenshot(path=str(output / "mobile-attendance-ready.png"), full_page=True)
                with employee_page.expect_response(lambda response: response.url.endswith("/employee/attendance/submit")) as submitted:
                    employee_page.locator("#submit-attendance").click()
                assert submitted.value.status == 200, submitted.value.text()
                if action == "check_in":
                    expect(employee_page.locator("#attendance-app")).to_have_attribute("data-action", "check_out", timeout=15000)
                else:
                    expect(employee_page.locator("#attendance-app")).to_have_attribute("data-complete", "true", timeout=15000)
            checks.append("mobile GPS, MediaDevices fake-camera capture, compression, check-in and check-out saved to database")
            employee_page.locator('.bottom-nav a[href="/employee/history"]').click()
            expect(employee_page.locator(".history-entry")).to_have_count(1)
            photo_url = employee_page.get_by_role("link", name="Selfie masuk").get_attribute("href")
            assert mobile.request.get(base + photo_url).status == 200
            checks.append("mobile bottom navigation, history and authenticated selfie")

            employee_page.goto(base + "/employee/leaves")
            employee_page.get_by_role("button", name="Buat pengajuan").click()
            expect(employee_page.locator("#new-leave")).to_be_visible()
            tomorrow = str(now().date() + timedelta(days=1))
            employee_page.locator('input[name="start_date"]').fill(tomorrow)
            employee_page.locator('input[name="end_date"]').fill(tomorrow)
            employee_page.locator('textarea[name="reason"]').fill("Browser QA leave request")
            employee_page.get_by_role("button", name="Kirim ke HR").click()
            expect(employee_page.locator(".leave-entry")).to_have_count(1)
            admin_page.bring_to_front()
            admin_page.goto(base + "/admin/leaves")
            admin_page.get_by_role("button", name="Tinjau", exact=True).click()
            admin_page.locator('textarea[name="admin_note"]').fill("Approved in browser QA")
            admin_page.get_by_role("button", name="Setujui", exact=True).click()
            admin_page.wait_for_url("**/admin/leaves")
            with app.app_context():
                assert query("SELECT status FROM leave_requests", one=True)["status"] == "approved"
            checks.append("employee leave dialog, admin review dialog and submitter status preserved")
            admin_page.goto(base + "/admin/attendance")
            with admin_page.expect_download() as exported:
                admin_page.get_by_role("link", name="Export Excel").click()
            exported.value.save_as(str(output / "browser-attendance.xlsx"))
            checks.append("authenticated Excel download")

            owner_context = browser.new_context(viewport={"width": 1440, "height": 1000})
            owner_page = owner_context.new_page()
            register(owner_page)
            login(owner_page, "owner@elrise.test")
            branding_loaded(owner_page)
            owner_page.get_by_role("link", name="Tambah perusahaan").click()
            owner_page.locator('input[name="name"]').fill("PT Browser QA")
            owner_page.locator('input[name="code"]').fill("BROWSER-QA")
            owner_page.locator('input[name="email"]').fill("qa@browser.test")
            owner_page.get_by_role("button", name="Simpan perusahaan").click()
            owner_page.get_by_role("button", name="Admin", exact=True).click()
            owner_page.locator('#new-admin input[name="name"]').fill("QA Admin")
            owner_page.locator('#new-admin input[name="email"]').fill("qa@browser.test")
            owner_page.locator('#new-admin input[name="password"]').fill(initial_password)
            owner_page.get_by_role("button", name="Buat akun admin").click()
            owner_page.get_by_role("button", name="Aktifkan PT", exact=True).click()
            owner_page.wait_for_load_state("networkidle")
            no_overflow(owner_page)
            owner_page.screenshot(path=str(output / "desktop-superadmin.png"), full_page=True)
            with app.app_context():
                assert query("SELECT is_active FROM clients WHERE code='BROWSER-QA'", one=True)["is_active"]
            checks.append("superadmin create company, admin account dialog, activation confirmation")

            compact = browser.new_context(viewport={"width": 360, "height": 800}, is_mobile=True, has_touch=True)
            compact_page = compact.new_page()
            register(compact_page)
            login(compact_page, "admin@nusantara.test")
            compact_page.locator("#sidebar-toggle").click()
            expect(compact_page.locator("#sidebar")).to_have_class("sidebar is-open")
            compact_page.locator('.side-nav a[href="/admin/employees"]').click()
            no_overflow(compact_page)
            for path in ["/admin/offices", "/admin/offices/new", "/admin/attendance", "/admin/company"]:
                compact_page.goto(base + path)
                no_overflow(compact_page)
            checks.append("360px admin sidebar, forms, offices and report table no page overflow")
            checks.append("supplied Elrise symbol and wordmark load on login, all three roles and mobile header; PNG favicon serves correctly")
            assert not errors, "\n".join(errors)
            browser.close()
        report = {"checks": checks, "browser": "Microsoft Edge headless", "database": database_name,
            "gps_camera": "SIMULATED browser sensors, not real hardware", "javascript_csp_errors": errors}
        (output / "browser-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        thread.join(timeout=5)
        with app.app_context():
            assert app.config["MYSQL_DATABASE"] == database_name and database_name.startswith("elrise_test_browser_")
            connection = connect(database=False)
            cursor = connection.cursor()
            cursor.execute(f"DROP DATABASE {database_name}")
            cursor.close()
            connection.close()


if __name__ == "__main__":
    main()
