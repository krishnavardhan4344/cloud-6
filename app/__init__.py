"""CloudStore - a small cloud-style file storage service built with Flask."""
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from config import Config, load_secret_key

from . import auth, db, files, utils


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key()

    from datetime import timedelta

    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=app.config["SESSION_HOURS"])

    Path(app.config["UPLOAD_ROOT"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    with app.app_context():
        db.init_db()

    utils.init_security(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(files.bp)
    register_error_handlers(app)
    return app


def register_error_handlers(app: Flask) -> None:
    def respond(status: int, title: str, message: str):
        if request.path.startswith("/api/"):
            return jsonify(error=message), status
        return render_template("error.html", status=status, title=title, message=message), status

    @app.errorhandler(RequestEntityTooLarge)
    def too_large(_e):
        limit_mb = app.config["MAX_REQUEST_MB"]
        return respond(413, "Upload too large", f"The upload is larger than the {limit_mb} MB request limit.")

    @app.errorhandler(HTTPException)
    def http_error(e: HTTPException):
        return respond(e.code or 500, e.name, e.description or "Something went wrong.")

    @app.errorhandler(Exception)
    def unexpected_error(e: Exception):
        app.logger.exception("Unhandled error: %s", e)
        return respond(500, "Server error", "Something went wrong on our side. Please try again later.")
