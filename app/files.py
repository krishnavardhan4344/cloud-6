"""File upload, listing, download and delete.

ACCESS CONTROL: every query below filters on ``user_id = g.user['id']`` and every
file lives in a folder named after its owner, so a user can never read, list or
delete another user's files.  Asking for somebody else's file returns the same
404 as a file that does not exist, so ids cannot be probed.
"""
import mimetypes
import uuid
from pathlib import Path

from flask import (Blueprint, abort, current_app, g, jsonify, render_template,
                   request, send_file)

from .db import get_db
from .utils import clean_filename, format_size, login_required

bp = Blueprint("files", __name__)


# ----------------------------------------------------------------- helpers
def user_dir(user_id: int) -> Path:
    path = Path(current_app.config["UPLOAD_ROOT"]) / str(user_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def serialize(row) -> dict:
    return {
        "id": row["id"],
        "name": row["original_name"],
        "size": row["size"],
        "size_human": format_size(row["size"]),
        "mime_type": row["mime_type"],
        "uploaded_at": row["uploaded_at"],
        "download_url": f"/api/files/{row['id']}/download",
    }


def usage_for(user_id: int) -> dict:
    used = get_db().execute(
        "SELECT COALESCE(SUM(size), 0) AS total, COUNT(*) AS n FROM files WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    quota = current_app.config["USER_QUOTA_BYTES"]
    return {
        "used": used["total"],
        "count": used["n"],
        "quota": quota,
        "used_human": format_size(used["total"]),
        "quota_human": format_size(quota),
        "percent": min(100, round(used["total"] * 100 / quota, 1)) if quota else 0,
    }


def list_for(user_id: int) -> list:
    rows = get_db().execute(
        "SELECT id, original_name, size, mime_type, uploaded_at FROM files "
        "WHERE user_id = ? ORDER BY uploaded_at DESC, id DESC",
        (user_id,),
    ).fetchall()
    return [serialize(r) for r in rows]


def _error(message: str, status: int):
    return jsonify(error=message), status


def _get_owned_file(file_id: int):
    """Fetch a file only if it belongs to the signed-in user, else 404."""
    row = get_db().execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?", (file_id, g.user["id"])
    ).fetchone()
    if row is None:
        abort(404, description="File not found.")
    return row


# ------------------------------------------------------------------ routes
@bp.route("/dashboard")
@login_required
def dashboard():
    cfg = current_app.config
    initial = {"files": list_for(g.user["id"]), "usage": usage_for(g.user["id"])}
    return render_template(
        "dashboard.html",
        initial=initial,
        max_file_bytes=cfg["MAX_FILE_BYTES"],
        max_file_human=format_size(cfg["MAX_FILE_BYTES"]),
        max_files=cfg["MAX_FILES_PER_UPLOAD"],
    )


@bp.route("/api/files", methods=("GET",))
@login_required
def api_list():
    return jsonify(files=list_for(g.user["id"]), usage=usage_for(g.user["id"]))


@bp.route("/api/files", methods=("POST",))
@login_required
def api_upload():
    cfg = current_app.config
    incoming = [f for f in request.files.getlist("files") if f and f.filename]
    if not incoming:
        return _error("No file selected. Choose at least one file to upload.", 400)
    if len(incoming) > cfg["MAX_FILES_PER_UPLOAD"]:
        return _error(f"You can upload at most {cfg['MAX_FILES_PER_UPLOAD']} files at a time.", 400)

    db = get_db()
    destination = user_dir(g.user["id"])
    used = usage_for(g.user["id"])["used"]
    uploaded, errors = [], []

    for incoming_file in incoming:
        display = clean_filename(incoming_file.filename)
        ext = display.rsplit(".", 1)[-1].lower() if "." in display else ""
        if ext in cfg["BLOCKED_EXTENSIONS"]:
            errors.append(f"'{display}': .{ext} files are not allowed.")
            continue

        # Size is checked on the stream first so oversized files are never written.
        stream = incoming_file.stream
        try:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(0)
        except (OSError, ValueError):
            size = None
        if size == 0:
            errors.append(f"'{display}': the file is empty.")
            continue
        if size is not None and size > cfg["MAX_FILE_BYTES"]:
            errors.append(f"'{display}': larger than the {format_size(cfg['MAX_FILE_BYTES'])} limit.")
            continue
        if size is not None and used + size > cfg["USER_QUOTA_BYTES"]:
            errors.append(f"'{display}': not enough free space in your storage quota.")
            continue

        stored_name = uuid.uuid4().hex
        path = destination / stored_name
        try:
            incoming_file.save(path)
            size = path.stat().st_size
            if used + size > cfg["USER_QUOTA_BYTES"] or size > cfg["MAX_FILE_BYTES"]:
                path.unlink(missing_ok=True)
                errors.append(f"'{display}': exceeds your storage limits.")
                continue
            mime = mimetypes.guess_type(display)[0] or "application/octet-stream"
            cur = db.execute(
                "INSERT INTO files (user_id, original_name, stored_name, size, mime_type) "
                "VALUES (?, ?, ?, ?, ?)",
                (g.user["id"], display, stored_name, size, mime),
            )
            db.commit()
        except Exception:  # noqa: BLE001 - never leave orphaned bytes behind
            db.rollback()
            path.unlink(missing_ok=True)
            current_app.logger.exception("Upload failed for %s", display)
            errors.append(f"'{display}': could not be saved. Please try again.")
            continue

        used += size
        row = db.execute("SELECT * FROM files WHERE id = ?", (cur.lastrowid,)).fetchone()
        uploaded.append(serialize(row))

    status = 201 if uploaded else 400
    return jsonify(uploaded=uploaded, errors=errors, usage=usage_for(g.user["id"])), status


@bp.route("/api/files/<int:file_id>/download", methods=("GET",))
@login_required
def api_download(file_id: int):
    row = _get_owned_file(file_id)
    path = user_dir(g.user["id"]) / row["stored_name"]
    if not path.is_file():
        abort(404, description="The file data could not be found on the server.")
    return send_file(
        path,
        as_attachment=True,
        download_name=row["original_name"],
        mimetype=row["mime_type"] or "application/octet-stream",
        conditional=True,
    )


@bp.route("/api/files/<int:file_id>", methods=("DELETE",))
@login_required
def api_delete(file_id: int):
    row = _get_owned_file(file_id)
    db = get_db()
    db.execute("DELETE FROM files WHERE id = ? AND user_id = ?", (file_id, g.user["id"]))
    db.commit()
    try:
        (user_dir(g.user["id"]) / row["stored_name"]).unlink(missing_ok=True)
    except OSError:
        current_app.logger.exception("Could not remove file data for id %s", file_id)
    return jsonify(message=f"'{row['original_name']}' was deleted.", usage=usage_for(g.user["id"]))
