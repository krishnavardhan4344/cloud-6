"""Capture the screenshots used in the project report.

It starts a *temporary* copy of the app (own database + storage in a temp
folder, so your real data is never touched), drives it with a headless
Chromium browser through the real user interface, and saves PNG files to
docs/screenshots/.

Setup (one time):
    pip install -r requirements-dev.txt
    playwright install chromium

Run from the project root:
    python scripts/capture_screenshots.py
"""
import shutil
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("Playwright is not installed. Run:  pip install -r requirements-dev.txt && playwright install chromium")

from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
PASSWORD = "Demo12345"

SAMPLE_FILES = {
    "Project_Report.pdf": 482_000,
    "Lecture_Notes_Unit3.docx": 96_500,
    "Database_Schema.png": 1_250_000,
    "Marks_Sheet.xlsx": 38_200,
    "Source_Code.zip": 3_480_000,
}


def make_samples(folder: Path) -> list:
    paths = []
    for name, size in SAMPLE_FILES.items():
        p = folder / name
        p.write_bytes(b"CloudStore demo content\n" * (size // 24 + 1))
        paths.append(str(p))
    return paths


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="cloudstore-shots-"))
    OUT.mkdir(parents=True, exist_ok=True)
    app = create_app(
        {
            "SECRET_KEY": "screenshot-only",
            "DATABASE": str(tmp / "demo.db"),
            "UPLOAD_ROOT": str(tmp / "storage"),
            "TESTING": False,
        }
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    samples = make_samples(tmp)

    def shot(page, name, full=True):
        page.screenshot(path=str(OUT / name), full_page=full)
        print("saved", OUT / name)

    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:  # fall back to a pre-installed Chromium if one is configured
                browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            ctx = browser.new_context(viewport={"width": 1280, "height": 800}, color_scheme="light")
            page = ctx.new_page()

            page.goto(base + "/")
            shot(page, "01_home.png")

            page.goto(base + "/register")
            page.fill("input[name=username]", "demo_student")
            page.fill("input[name=email]", "student@example.com")
            page.fill("input[name=password]", PASSWORD)
            page.fill("input[name=confirm_password]", PASSWORD)
            shot(page, "02_register.png")
            page.click("button[type=submit]")

            page.wait_for_url("**/login")
            page.fill("input[name=identifier]", "demo_student")
            page.fill("input[name=password]", "wrong-password1")
            page.click("button[type=submit]")
            shot(page, "03_login_error.png")
            page.fill("input[name=identifier]", "demo_student")
            page.fill("input[name=password]", PASSWORD)
            shot(page, "04_login.png")
            page.click("button[type=submit]")

            page.wait_for_url("**/dashboard")
            shot(page, "05_dashboard_empty.png")

            page.set_input_files("#file-input", samples)
            page.wait_for_selector("#file-body tr:nth-child(5)")
            page.wait_for_selector("#upload-progress", state="hidden")
            page.wait_for_selector(".toast")
            shot(page, "06_upload_success.png")
            page.wait_for_timeout(6000)  # let the toasts disappear

            shot(page, "07_file_list.png")

            page.click("#file-body tr:first-child .btn-danger")
            page.wait_for_selector("#confirm-dialog[open]")
            shot(page, "08_delete_confirm.png", full=False)
            page.click("#confirm-yes")
            page.wait_for_selector("#file-body tr:nth-child(5)", state="detached")
            page.wait_for_timeout(500)
            shot(page, "09_after_delete.png")

            # Access control demo: a second user cannot reach the first user's files
            first_id = page.evaluate("fetch('/api/files').then(r => r.json()).then(d => d.files[0].id)")
            ctx2 = browser.new_context(viewport={"width": 1280, "height": 800})
            other = ctx2.new_page()
            other.goto(base + "/register")
            other.fill("input[name=username]", "other_user")
            other.fill("input[name=email]", "other@example.com")
            other.fill("input[name=password]", PASSWORD)
            other.fill("input[name=confirm_password]", PASSWORD)
            other.click("button[type=submit]")
            other.wait_for_url("**/login")
            other.fill("input[name=identifier]", "other_user")
            other.fill("input[name=password]", PASSWORD)
            other.click("button[type=submit]")
            other.wait_for_url("**/dashboard")
            other.goto(f"{base}/api/files/{first_id}/download")
            shot(other, "10_access_denied.png", full=False)
            ctx2.close()

            # Mobile layout
            mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True)
            m = mobile.new_page()
            m.goto(base + "/login")
            m.fill("input[name=identifier]", "demo_student")
            m.fill("input[name=password]", PASSWORD)
            m.click("button[type=submit]")
            m.wait_for_url("**/dashboard")
            m.wait_for_selector("#file-body tr")
            shot(m, "11_mobile_dashboard.png")
            mobile.close()

            browser.close()
    finally:
        server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nAll screenshots saved to", OUT)


if __name__ == "__main__":
    main()
