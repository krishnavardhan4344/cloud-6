"""User registration, login and logout."""
import re
import sqlite3
import time
from pathlib import Path

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db
from .utils import login_required

bp = Blueprint("auth", __name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Used to keep response time similar for unknown users (limits user enumeration).
_DUMMY_HASH = generate_password_hash("not-a-real-password")

# In-memory login throttle: {(ip, identifier): (failed_count, locked_until)}
_failures: dict = {}


def reset_throttle() -> None:
    _failures.clear()


def _throttle_key(identifier: str):
    return (request.remote_addr or "?", identifier.lower())


def _seconds_locked(key) -> int:
    entry = _failures.get(key)
    if not entry:
        return 0
    remaining = int(entry[1] - time.time())
    if remaining <= 0 and entry[0] >= current_app.config["LOGIN_MAX_ATTEMPTS"]:
        _failures.pop(key, None)
        return 0
    return max(remaining, 0)


def _register_failure(key) -> None:
    count, _ = _failures.get(key, (0, 0))
    count += 1
    locked_until = 0
    if count >= current_app.config["LOGIN_MAX_ATTEMPTS"]:
        locked_until = time.time() + current_app.config["LOGIN_LOCK_SECONDS"]
    _failures[key] = (count, locked_until)


def validate_registration(username: str, email: str, password: str, confirm: str) -> list:
    errors = []
    if not USERNAME_RE.match(username):
        errors.append("Username must be 3-30 characters: letters, numbers and underscores only.")
    if len(email) > 254 or not EMAIL_RE.match(email):
        errors.append("Please enter a valid email address.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    elif len(password) > 128:
        errors.append("Password must be at most 128 characters long.")
    elif not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        errors.append("Password must contain at least one letter and one number.")
    if password != confirm:
        errors.append("Passwords do not match.")
    return errors


@bp.route("/")
def index():
    if g.user:
        return redirect(url_for("files.dashboard"))
    return render_template("index.html")


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("files.dashboard"))
    form = {"username": "", "email": ""}
    errors = []
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        form = {"username": username, "email": email}
        errors = validate_registration(username, email, password, confirm)
        if not errors:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                errors.append("That username or email is already registered.")
            else:
                try:
                    (Path(current_app.config["UPLOAD_ROOT"]) / str(cur.lastrowid)).mkdir(
                        parents=True, exist_ok=True
                    )
                except OSError:
                    current_app.logger.exception("Could not create storage folder")
                flash("Account created successfully. Please sign in.", "success")
                return redirect(url_for("auth.login"))
    return render_template("register.html", errors=errors, form=form), (400 if errors else 200)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("files.dashboard"))
    errors = []
    identifier = ""
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        key = _throttle_key(identifier)
        locked = _seconds_locked(key)
        if locked:
            minutes = max(1, (locked + 59) // 60)
            errors.append(f"Too many failed attempts. Try again in about {minutes} minute(s).")
        else:
            user = get_db().execute(
                "SELECT id, password_hash FROM users WHERE username = ? OR email = ?",
                (identifier, identifier.lower()),
            ).fetchone()
            valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
            if user and valid:
                _failures.pop(key, None)
                session.clear()  # prevents session fixation
                session["user_id"] = user["id"]
                session.permanent = True
                flash("Welcome back!", "success")
                return redirect(url_for("files.dashboard"))
            _register_failure(key)
            errors.append("Invalid username/email or password.")
    return render_template("login.html", errors=errors, identifier=identifier), (401 if errors else 200)


@bp.route("/logout", methods=("POST",))
@login_required
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
