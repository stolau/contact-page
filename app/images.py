"""Uploaded images (LLM-COP-21): the upload route, the serving route, and
the template filter that turns a stored reference into a URL.

The first route in the product that takes a file from outside the process,
so the shape is deliberate:

  * The bytes are validated structurally (app/imagecheck.py). The client's
    filename and its asserted content type are read NOWHERE — not for the
    format, not for the stored name, not for the served content type.
  * What is hashed, stored and served is facts.data, the canonical span the
    validator tiled — never the request body. A JPEG's trailing appendix
    therefore cannot reach disk, and the same photograph with and without
    one is a single file.
  * The stored name is the SHA-256 hex digest plus an extension we compute,
    so a traversal in a filename is not filtered, it is structurally
    impossible: no part of the client's input reaches the path.
  * The file is written before the row is inserted, so a row always implies
    a file.

**The cap is per-request, not app-wide.** request.max_content_length is set
on this view only, so no other route's behaviour changes. What that buys,
precisely (Werkzeug 3.1.8): werkzeug/wsgi.py:183-187 compares the
Content-Length header against the limit and raises RequestEntityTooLarge
before the stream is touched at all, so an oversized body is refused without
being read into memory. With no Content-Length but wsgi.input_terminated set
(a chunked-capable server), werkzeug/wsgi.py:191-198 wraps the stream in a
LimitedStream and the cap is enforced while reading. With neither — the case
a plain WSGI environ presents — werkzeug/wsgi.py:205-206 hands back an empty
BytesIO, so the view sees zero bytes and would otherwise answer a confusing
"not a valid image". It answers MESSAGES["empty"] instead. Browsers always
send Content-Length for FormData, so this is documentation rather than a
defect, but an undocumented 415 on a chunked upload costs somebody an
afternoon.

**Serving.** GET /kuvat/<digest> is public, and must be: the portrait is on
the public page. The reference is a 256-bit content hash and the picture is
destined for publication, so the URL is unguessable and the content is not
secret. It is served with a content type we recorded, checked a second time
against SERVE_ALLOWLIST at serve time — an independent control, so a row
somehow claiming image/svg+xml cannot be served even if one got into the
table — plus nosniff, a sandbox CSP, an inline disposition whose filename we
compute, and a year of immutable caching, which is safe precisely because
the URL is the hash of the content.

**What is not here, and is disclosed rather than hidden.** There is no
delete route and no garbage collection: an upload is permanent and
world-readable from the moment it lands, before any publish. See README.md.
"""

import hashlib
import os
import re
import time

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    send_from_directory,
)
from werkzeug.exceptions import RequestEntityTooLarge

from . import auth
from . import db as database
from .imagecheck import sniff_image

bp = Blueprint("images", __name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# A stored reference is exactly a SHA-256 hex digest. Nothing else ever
# reaches a URL or a path.
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")

# The serving allowlist: the second, independent check on what may leave
# this process as an image. Extensions are computed from the content type,
# never taken from the client.
SERVE_ALLOWLIST = {"image/png": "png", "image/jpeg": "jpg"}

# Finnish, and actionable: each one tells the owner what to do next. They
# are shown verbatim in the panel's .muotokuva-error element rather than
# through showErrors, because hero.portrait has no FIELD_LABELS entry and
# would surface there as a raw key (app/fields.py).
MESSAGES = {
    "too_large": "Kuva on liian suuri: enintään 5 Mt.",
    "empty": "Kuvaa ei vastaanotettu — lähetä tiedosto uudelleen.",
    "format": (
        "Vain PNG- ja JPEG-kuvat kelpaavat, eikä tiedosto ole ehjä PNG"
        " tai JPEG."
    ),
    "dimensions": (
        "Kuva on liian suuri: enintään 10 000 × 10 000 pikseliä ja"
        " 25 megapikseliä."
    ),
}


def _connect():
    return database.connect(current_app.config["DATABASE"])


def image_url(ref):
    """A stored reference to a URL, or None when there is no picture.

    Pure and database-free: it is the guard that keeps untrusted payload
    text out of a URL. The isinstance check comes first on purpose — this
    filter runs over stored JSON in app/templates/_section_row.html, where
    the value can be a Jinja Undefined or a non-string, and handing that to
    re.fullmatch raises rather than answering False.
    """
    if not isinstance(ref, str):
        return None
    if not DIGEST_PATTERN.fullmatch(ref):
        return None
    return f"/kuvat/{ref}"


def _upload_dir():
    return current_app.config["UPLOAD_DIR"]


@bp.route("/api/kuvat", methods=["POST"])
@auth.require_admin
def upload():
    """Take one image, validate it structurally, store it by its digest.

    require_admin reads no body, so the gate runs before the cap is even
    set and the decorator order is safe either way.
    """
    # Set before request.files is touched: that attribute is what triggers
    # the parse, and the limit has to be in place first.
    request.max_content_length = MAX_UPLOAD_BYTES
    try:
        # The first file part, whatever it is named — the route takes one
        # image and knows nothing about which field it is destined for.
        parts = list(request.files.values())
    except RequestEntityTooLarge:
        return jsonify(error=MESSAGES["too_large"]), 413
    data = parts[0].read() if parts else b""
    if not data:
        return jsonify(error=MESSAGES["empty"]), 415
    facts, reason = sniff_image(data)
    if facts is None:
        return jsonify(error=MESSAGES[reason]), 415

    digest = hashlib.sha256(facts.data).hexdigest()
    stored_name = f"{digest}.{facts.extension}"
    directory = _upload_dir()
    path = os.path.join(directory, stored_name)
    if not os.path.exists(path):
        # Write to a temp name in the same directory and rename: os.replace
        # is atomic within a filesystem, so a reader never sees a half file.
        temp = f"{path}.{os.getpid()}.part"
        with open(temp, "wb") as handle:
            handle.write(facts.data)
        os.replace(temp, path)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO uploads"
            " (digest, stored_name, content_type, byte_size, width, height,"
            "  created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(digest) DO NOTHING",
            (
                digest,
                stored_name,
                facts.content_type,
                len(facts.data),
                facts.width,
                facts.height,
                int(time.time()),
            ),
        )
        conn.commit()
        auth.audit(conn, f"image uploaded digest={digest}")
    finally:
        conn.close()
    return jsonify(ref=digest, url=f"/kuvat/{digest}")


@bp.route("/kuvat/<digest>")
def kuva(digest):
    """Serve one stored image. Public, because the portrait is."""
    if not DIGEST_PATTERN.fullmatch(digest):
        return jsonify(error="not found"), 404
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT stored_name, content_type FROM uploads WHERE digest = ?",
            (digest,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return jsonify(error="not found"), 404
    extension = SERVE_ALLOWLIST.get(row["content_type"])
    if extension is None:
        # The second control: a row claiming a type we do not serve is a
        # 404, not a download.
        return jsonify(error="not found"), 404
    response = send_from_directory(
        _upload_dir(), row["stored_name"], mimetype=row["content_type"]
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = (
        f'inline; filename="{digest}.{extension}"'
    )
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    # Safe because the URL *is* the digest of the content it serves.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
