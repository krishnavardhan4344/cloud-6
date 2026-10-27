"""Shared helpers: decorators, CSRF protection, security headers, formatting."""
import functools
import os
import re
import secrets

from flask import abort, flash, g, jsonify, redirect, request, session, url_for

from .db import get_db

_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_size(num_bytes) -> str:
    """Human readable file size (1024 based), e.g. ``1.5 MB``."""
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return "0 B"
    if size < 0:
        size = 0.0
    for unit in _UNITS:
        if size < 1024 or unit == _UNITS[-1]:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"  # pragma: no cover


def clean_filename(name: str, max_length: int = 150) -> str:
    """Return a safe *display* name (no path components or control characters).

    The file is never stored under this name on disk - a random UUID is used -
    so this only has to be safe for display and for the download header.
    """
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if len(name) > max_length:
        stem, ext = os.path.splitext(name)
        ext = ext[:20]
        name = stem[: max_length - len(ext)] + ext
    return name or "unnamed"


def wants_json() -> bool:
    return request.path.startswith("/api/")


def login_required(view):
    """Redirect browsers to the login page / return 401 JSON for API calls."""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            if wants_json():
                return jsonify(error="Authentication required. Please sign in."), 401
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def init_security(app) -> None:
    """Register per-request user loading, CSRF checks and security headers."""

    @app.before_request
    def load_user():
        g.user = None
        if request.endpoint == "static":
            return
        user_id = session.get("user_id")
        if user_id is not None:
            row = get_db().execute(
                "SELECT id, username, email, created_at FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
            if row is None:  # account no longer exists
                session.clear()
            g.user = row

    @app.before_request
    def csrf_protect():
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
            expected = session.get("csrf_token", "")
            if not expected or not sent or not secrets.compare_digest(sent, expected):
                abort(400, description="Invalid or missing security token. Refresh the page and try again.")

    @app.context_processor
    def inject_helpers():
        def csrf_token() -> str:
            if "csrf_token" not in session:
                session["csrf_token"] = secrets.token_urlsafe(32)
            return session["csrf_token"]

        return {"csrf_token": csrf_token}

    app.jinja_env.filters["filesize"] = format_size

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response
