"""Application configuration.

All settings can be overridden with environment variables (or a local ``.env``
file, see ``.env.example``).  No external service or API key is required.
"""
import os
import secrets
from pathlib import Path

try:  # python-dotenv is optional at runtime
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable, falling back to *default*."""
    try:
        value = int(os.environ.get(name, default))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def load_secret_key() -> str:
    """Return the Flask secret key.

    Priority: ``SECRET_KEY`` env var -> ``instance/secret_key`` file.  If neither
    exists a random key is generated once and stored in ``instance/`` so that
    sessions survive restarts without the developer having to configure anything.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(exist_ok=True)
    key_file = instance_dir / "secret_key"
    if key_file.exists():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or None  # resolved in create_app()

    # Storage locations
    DATABASE = os.environ.get("DATABASE_PATH") or str(BASE_DIR / "instance" / "cloudstore.db")
    UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT") or str(BASE_DIR / "storage")

    # Limits
    MAX_FILE_MB = _int_env("MAX_FILE_MB", 25)  # per file
    MAX_REQUEST_MB = _int_env("MAX_REQUEST_MB", 100)  # per upload request
    USER_QUOTA_MB = _int_env("USER_QUOTA_MB", 100)  # per user
    MAX_FILES_PER_UPLOAD = _int_env("MAX_FILES_PER_UPLOAD", 20)

    MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
    MAX_CONTENT_LENGTH = MAX_REQUEST_MB * 1024 * 1024
    USER_QUOTA_BYTES = USER_QUOTA_MB * 1024 * 1024

    # Blocked file types (executables / scripts commonly used to spread malware)
    BLOCKED_EXTENSIONS = frozenset(
        {"exe", "bat", "cmd", "com", "msi", "scr", "vbs", "ps1", "dll"}
    )

    # Brute-force protection
    LOGIN_MAX_ATTEMPTS = _int_env("LOGIN_MAX_ATTEMPTS", 5)
    LOGIN_LOCK_SECONDS = _int_env("LOGIN_LOCK_SECONDS", 300)

    # Sessions / cookies
    SESSION_HOURS = _int_env("SESSION_HOURS", 2)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Set COOKIE_SECURE=1 when serving over HTTPS in production.
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "0") == "1"
