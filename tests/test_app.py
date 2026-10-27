"""Automated tests.  Run from the project root:

    python -m unittest discover -s tests -v
"""
import io
import logging
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import create_app  # noqa: E402
from app.auth import reset_throttle  # noqa: E402

PASSWORD = "Passw0rd123"


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cloudstore-test-")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(Path(self.tmp) / "test.db"),
                "UPLOAD_ROOT": str(Path(self.tmp) / "storage"),
                "USER_QUOTA_BYTES": 1000,
                "MAX_FILE_BYTES": 600,
                "LOGIN_MAX_ATTEMPTS": 3,
            }
        )
        reset_throttle()
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- helpers
    @staticmethod
    def token(client, url="/login"):
        html = client.get(url).get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def register(self, client, username="alice", email=None, password=PASSWORD):
        return client.post(
            "/register",
            data={
                "csrf_token": self.token(client, "/register"),
                "username": username,
                "email": email or f"{username}@example.com",
                "password": password,
                "confirm_password": password,
            },
        )

    def login(self, client, identifier="alice", password=PASSWORD):
        return client.post(
            "/login",
            data={"csrf_token": self.token(client), "identifier": identifier, "password": password},
        )

    def make_user(self, username):
        client = self.app.test_client()
        self.assertEqual(self.register(client, username).status_code, 302)
        self.assertEqual(self.login(client, username).status_code, 302)
        return client

    def upload(self, client, name="hello.txt", data=b"hello world"):
        return client.post(
            "/api/files",
            data={"files": (io.BytesIO(data), name)},
            headers={"X-CSRF-Token": self.token(client, "/dashboard")},
            content_type="multipart/form-data",
        )


class AuthTests(BaseCase):
    def test_pages_load(self):
        for url in ("/", "/login", "/register"):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_register_success_creates_storage_folder(self):
        r = self.register(self.client)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/login"))
        self.assertTrue((Path(self.tmp) / "storage" / "1").is_dir())

    def test_register_validation_errors(self):
        r = self.register(self.client, username="a!", password="short")
        self.assertEqual(r.status_code, 400)
        text = r.get_data(as_text=True)
        self.assertIn("Username must be", text)
        self.assertIn("at least 8 characters", text)

    def test_password_needs_letter_and_digit(self):
        r = self.register(self.client, password="onlyletters")
        self.assertEqual(r.status_code, 400)
        self.assertIn("letter and one number", r.get_data(as_text=True))

    def test_password_mismatch(self):
        r = self.client.post(
            "/register",
            data={
                "csrf_token": self.token(self.client, "/register"),
                "username": "bob",
                "email": "bob@example.com",
                "password": PASSWORD,
                "confirm_password": PASSWORD + "x",
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("do not match", r.get_data(as_text=True))

    def test_duplicate_username_and_email(self):
        self.register(self.client, "alice")
        r = self.register(self.client, "ALICE", email="other@example.com")  # username is case-insensitive
        self.assertEqual(r.status_code, 400)
        self.assertIn("already registered", r.get_data(as_text=True))
        r = self.register(self.client, "alice2", email="alice@example.com")
        self.assertEqual(r.status_code, 400)

    def test_password_is_hashed(self):
        self.register(self.client)
        with self.app.app_context():
            from app.db import get_db

            h = get_db().execute("SELECT password_hash FROM users").fetchone()[0]
        self.assertNotIn(PASSWORD, h)
        self.assertTrue(h.startswith(("scrypt:", "pbkdf2:")))

    def test_login_by_username_and_email(self):
        self.register(self.client)
        self.assertEqual(self.login(self.client, "alice").status_code, 302)
        self.client.post("/logout", data={"csrf_token": self.token(self.client, "/dashboard")})
        self.assertEqual(self.login(self.client, "ALICE@example.com").status_code, 302)

    def test_login_wrong_password(self):
        self.register(self.client)
        r = self.login(self.client, "alice", "WrongPass1")
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid username/email or password", r.get_data(as_text=True))

    def test_login_unknown_user_same_message(self):
        r = self.login(self.client, "ghost", PASSWORD)
        self.assertEqual(r.status_code, 401)
        self.assertIn("Invalid username/email or password", r.get_data(as_text=True))

    def test_login_lockout_after_repeated_failures(self):
        self.register(self.client)
        for _ in range(3):
            self.login(self.client, "alice", "WrongPass1")
        r = self.login(self.client, "alice", PASSWORD)  # correct password, but locked
        self.assertEqual(r.status_code, 401)
        self.assertIn("Too many failed attempts", r.get_data(as_text=True))

    def test_logout_ends_session(self):
        self.register(self.client)
        self.login(self.client)
        self.assertEqual(self.client.get("/dashboard").status_code, 200)
        self.client.post("/logout", data={"csrf_token": self.token(self.client, "/dashboard")})
        self.assertEqual(self.client.get("/dashboard").status_code, 302)

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_csrf_blocks_forms_without_token(self):
        r = self.client.post("/register", data={"username": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("security token", r.get_data(as_text=True))

    def test_logged_in_user_redirected_from_login(self):
        self.register(self.client)
        self.login(self.client)
        self.assertEqual(self.client.get("/login").status_code, 302)


class FileTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.alice = self.make_user("alice")
        self.bob = self.make_user("bob")

    def test_dashboard_requires_login(self):
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])

    def test_api_requires_login(self):
        for method, url in (("get", "/api/files"), ("get", "/api/files/1/download")):
            r = getattr(self.client, method)(url)
            self.assertEqual(r.status_code, 401, url)
            self.assertIn("error", r.get_json())

    def test_upload_list_download_roundtrip(self):
        r = self.upload(self.alice, "notes.txt", b"my notes")
        self.assertEqual(r.status_code, 201)
        item = r.get_json()["uploaded"][0]
        self.assertEqual(item["name"], "notes.txt")
        self.assertEqual(item["size"], 8)
        self.assertEqual(item["size_human"], "8 B")

        listing = self.alice.get("/api/files").get_json()
        self.assertEqual(len(listing["files"]), 1)
        self.assertEqual(listing["usage"]["used"], 8)

        d = self.alice.get(item["download_url"])
        self.assertEqual(d.status_code, 200)
        self.assertEqual(d.data, b"my notes")
        self.assertIn("attachment", d.headers["Content-Disposition"])
        self.assertIn("notes.txt", d.headers["Content-Disposition"])
        self.assertEqual(d.headers["X-Content-Type-Options"], "nosniff")

    def test_multiple_files_in_one_request(self):
        r = self.alice.post(
            "/api/files",
            data={"files": [(io.BytesIO(b"a"), "a.txt"), (io.BytesIO(b"bb"), "b.txt")]},
            headers={"X-CSRF-Token": self.token(self.alice, "/dashboard")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.get_json()["uploaded"]), 2)

    def test_file_size_formatting(self):
        from app.utils import format_size

        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(1023), "1023 B")
        self.assertEqual(format_size(1024), "1.0 KB")
        self.assertEqual(format_size(1536), "1.5 KB")
        self.assertEqual(format_size(5 * 1024 * 1024), "5.0 MB")
        self.assertEqual(format_size(3 * 1024 ** 3), "3.0 GB")

    def test_user_cannot_list_others_files(self):
        self.upload(self.alice, "secret.txt", b"alice only")
        self.assertEqual(self.bob.get("/api/files").get_json()["files"], [])
        self.assertNotIn("secret.txt", self.bob.get("/dashboard").get_data(as_text=True))

    def test_user_cannot_download_others_files(self):
        fid = self.upload(self.alice, "secret.txt", b"alice only").get_json()["uploaded"][0]["id"]
        r = self.bob.get(f"/api/files/{fid}/download")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"alice only", r.data)

    def test_user_cannot_delete_others_files(self):
        fid = self.upload(self.alice, "secret.txt", b"alice only").get_json()["uploaded"][0]["id"]
        r = self.bob.delete(f"/api/files/{fid}", headers={"X-CSRF-Token": self.token(self.bob, "/dashboard")})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(self.alice.get("/api/files").get_json()["files"]), 1)  # still there

    def test_delete_removes_record_and_bytes(self):
        fid = self.upload(self.alice, "x.txt", b"data").get_json()["uploaded"][0]["id"]
        stored = list((Path(self.tmp) / "storage" / "1").iterdir())
        self.assertEqual(len(stored), 1)
        r = self.alice.delete(f"/api/files/{fid}", headers={"X-CSRF-Token": self.token(self.alice, "/dashboard")})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["usage"]["used"], 0)
        self.assertEqual(list((Path(self.tmp) / "storage" / "1").iterdir()), [])
        self.assertEqual(self.alice.get(f"/api/files/{fid}/download").status_code, 404)

    def test_delete_requires_csrf_token(self):
        fid = self.upload(self.alice).get_json()["uploaded"][0]["id"]
        self.assertEqual(self.alice.delete(f"/api/files/{fid}").status_code, 400)

    def test_upload_requires_csrf_token(self):
        r = self.alice.post("/api/files", data={"files": (io.BytesIO(b"x"), "x.txt")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)

    def test_upload_without_file(self):
        r = self.alice.post("/api/files", data={}, headers={"X-CSRF-Token": self.token(self.alice, "/dashboard")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("No file selected", r.get_json()["error"])

    def test_blocked_extension(self):
        r = self.upload(self.alice, "virus.exe", b"MZ")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not allowed", r.get_json()["errors"][0])

    def test_empty_file_rejected(self):
        r = self.upload(self.alice, "empty.txt", b"")
        self.assertEqual(r.status_code, 400)

    def test_per_file_size_limit(self):
        r = self.upload(self.alice, "big.bin", b"x" * 601)
        self.assertEqual(r.status_code, 400)
        self.assertIn("larger than", r.get_json()["errors"][0])

    def test_storage_quota_enforced(self):
        self.assertEqual(self.upload(self.alice, "a.bin", b"x" * 600).status_code, 201)
        self.assertEqual(self.upload(self.alice, "b.bin", b"x" * 300).status_code, 201)
        r = self.upload(self.alice, "c.bin", b"x" * 200)  # 600+300+200 > 1000
        self.assertEqual(r.status_code, 400)
        self.assertIn("storage quota", r.get_json()["errors"][0])
        # Bob has his own, separate quota
        self.assertEqual(self.upload(self.bob, "a.bin", b"x" * 600).status_code, 201)

    def test_request_too_large_returns_json_413(self):
        self.app.config["MAX_CONTENT_LENGTH"] = 200
        r = self.upload(self.alice, "a.bin", b"x" * 500)
        self.assertEqual(r.status_code, 413)
        self.assertIn("error", r.get_json())

    def test_path_traversal_in_filename_is_neutralised(self):
        r = self.upload(self.alice, "../../etc/passwd", b"nope")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["uploaded"][0]["name"], "passwd")
        # nothing escaped the user's folder
        self.assertEqual(len(list((Path(self.tmp) / "storage").rglob("*"))), 3)  # 2 user dirs + 1 file

    def test_html_filename_is_returned_as_data_not_markup(self):
        r = self.upload(self.alice, "<script>alert(1)</script>.txt", b"x")
        self.assertEqual(r.status_code, 201)
        page = self.alice.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)  # escaped inside the JSON block

    def test_download_missing_data_returns_404(self):
        item = self.upload(self.alice).get_json()["uploaded"][0]
        for p in (Path(self.tmp) / "storage" / "1").iterdir():
            p.unlink()
        self.assertEqual(self.alice.get(item["download_url"]).status_code, 404)


class ErrorAndHeaderTests(BaseCase):
    def test_404_page(self):
        r = self.client.get("/nope")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Not Found", r.get_data(as_text=True))

    def test_api_404_is_json(self):
        r = self.client.get("/api/unknown")
        self.assertEqual(r.status_code, 404)
        self.assertIn("error", r.get_json())

    def test_security_headers(self):
        r = self.client.get("/")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_unhandled_exception_returns_500_page(self):
        @self.app.route("/boom")
        def boom():
            raise RuntimeError("kaboom")

        self.app.config["PROPAGATE_EXCEPTIONS"] = False
        logging.disable(logging.CRITICAL)  # keep the expected traceback out of the test output
        try:
            r = self.client.get("/boom")
        finally:
            logging.disable(logging.NOTSET)
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("kaboom", r.get_data(as_text=True))  # internals are not leaked


if __name__ == "__main__":
    unittest.main(verbosity=2)
