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

**Collection (LLM-COP-27).** An upload leaves when nothing names it any
more. referenced_digests scans the raw text of every section's draft,
published and previous_published — the same rows the renderer reads — and
collect_unreferenced deletes the row and then the blob of every stored
digest outside that set. It runs inside the three writes that can drop a
reference (the draft PUT, the publish, the restore) and nowhere else: no
timer, no startup sweep. A digest POST /api/kuvat has just answered is held
for RETENTION_GRACE_SECONDS whatever the count says, because the write that
names it lands after the upload responds. DELETE /api/kuvat/<digest> is the
owner's explicit removal: it honours the count (a referenced digest is
refused) and bypasses the floor. Every part of it is built to fail in the
retaining direction — being wrong leaves a file, not a hole, because
instance/ is not backed up. See README.md.
"""

import hashlib
import os
import re
import tempfile
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


def _umask():
    """This process's umask.

    There is no way to read it without setting it, so it is read once here at
    import — single-threaded, before any request — and restored immediately.
    Doing this per upload would race: another thread creating a file in the
    window would take the temporarily-set mask.
    """
    value = os.umask(0o022)
    os.umask(value)
    return value


_UMASK = _umask()

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# A digest POST /api/kuvat has just answered is never eligible for
# collection for this long, whatever the count says. The write that names an
# upload lands AFTER the upload has responded — the panel writes
# draft.portrait in the response's .then — so without this floor an autosave
# that fires in that window collects the picture the owner is placing. The
# upload route refreshes uploads.created_at on conflict so this holds for a
# deduped re-upload too: the row records the last time the digest was handed
# out, not the first. Fifteen minutes clears a 5 MB upload on a poor mobile
# uplink with room to spare; too short destroys a picture (a hole), too long
# leaves an abandoned one on disk for a quarter of an hour (a file).
RETENTION_GRACE_SECONDS = 15 * 60

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
    "in_use": "Kuva on käytössä sivulla. Poista se ensin osiosta.",
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


def _digests_from_rows(rows):
    """The one place a stored payload becomes a set of digests.

    Both entry points go through this, so the counting rule exists once: a
    drift where the destroying function found fewer digests than the
    checking one would be a hole.

    It scans the RAW stored text and knows nothing about FIELDS, nothing
    about `portrait`, and does not parse JSON. json.dumps(ensure_ascii=False)
    — the one serializer every payload writer uses — escapes only ", \\ and
    control characters, so a real reference is always present verbatim in
    the text and a raw scan cannot miss one. DIGEST_PATTERN is deliberately
    unanchored here: findall finds a digest wherever it sits inside a JSON
    string, and its only error is to over-count, which retains a file. A
    field-specific extractor would under-count silently the day a second
    image field exists, and that deletes a live picture.
    """
    found = set()
    for row in rows:
        for text in (row["draft"], row["published"], row["previous_published"]):
            if text:
                found.update(DIGEST_PATTERN.findall(text))
    return found


def referenced_digests(conn):
    """Every digest any section's draft, published or previous_published
    names — the count, over digests and never over sections.

    Three columns, because previous_published is what Palauta edellinen
    versio restores from: an image named only there is still reachable and
    must survive. A set, because two sections naming one digest contribute
    one entry — so one of them clearing its field leaves the union standing
    and the collector is never asked who owned a file.

    It reads `sections` only. It must never scan uploads.stored_name, which
    contains every digest by construction and would pin the whole store.

    Deliberately UNGUARDED against an empty `sections` table, unlike
    collect_unreferenced: this is the thin wrapper the DELETE route's in-use
    check calls, where an empty store honestly means nothing names this
    digest. The guard belongs where the destruction is.
    """
    rows = conn.execute(
        "SELECT draft, published, previous_published FROM sections"
    ).fetchall()
    return _digests_from_rows(rows)


def _stored_name(digest, content_type):
    """The stored file's name, or None when we cannot name it.

    fullmatch, not match: DIGEST_PATTERN is unanchored, so an unanchored
    check would accept a 64-hex PREFIX of some longer stored value and then
    compute a path from something that is not the digest. The destroying
    code takes the strict test — the same one image_url uses — and the
    counting code takes the generous one; each fails in the retaining
    direction.
    """
    if not DIGEST_PATTERN.fullmatch(digest):
        return None
    extension = SERVE_ALLOWLIST.get(content_type)
    if extension is None:
        return None
    return f"{digest}.{extension}"


def _remove_upload(conn, digest, content_type):
    """Remove one stored image: the ROW first, then the blob. False when the
    row is one we cannot name, in which case nothing at all is touched.

    The order mirrors the upload's, which writes the file before the row so
    that a row always implies a file (see the module docstring). A crash
    between the two here leaves a file with no row, which is unreachable —
    kuva() answers 404 when the row is missing — and self-heals, because a
    later upload of the same bytes takes the os.path.exists short-circuit
    and re-inserts the row. The other order would leave a row promising a
    picture that is not there.

    The path is RECOMPUTED from the digest and the allowlisted extension,
    exactly as kuva() recomputes it: stored_name is read for nothing. A row
    whose digest or content type we cannot name is skipped entirely, row and
    file both — a defensive branch that DESTROYS is the one a reviewer
    suspicious of over-collection should distrust, so this one refuses.

    The unlink is best-effort. The row is already committed when it runs, so
    an OSError propagating out would 500 a save that actually succeeded; it
    leaves a file, not a hole. An in-flight download is undisturbed —
    send_from_directory holds an open descriptor and a POSIX unlink does not
    close it.
    """
    stored = _stored_name(digest, content_type)
    if stored is None:
        return False
    conn.execute("DELETE FROM uploads WHERE digest = ?", (digest,))
    conn.commit()
    try:
        os.unlink(os.path.join(_upload_dir(), stored))
    except OSError:
        pass
    return True


def collect_unreferenced(conn):
    """Delete every stored image no section payload names any more, and
    return the digests collected.

    Called from the three writes that can drop a reference and from nowhere
    else, on the CALLER'S connection: opening a second one while the route's
    is mid-transaction invites `database is locked`.

    It never touches `sections` — its only SQL against a section is a
    SELECT — so no stored payload text can move and no badge() comparison
    can flip.
    """
    rows = conn.execute(
        "SELECT draft, published, previous_published FROM sections"
    ).fetchall()
    if not rows:
        # A store with no sections authorises nothing. An empty referenced
        # set would otherwise mean "delete everything". Unreachable today —
        # seed_if_empty always inserts six — but the destruction is here, so
        # the guard is here.
        return []
    referenced = _digests_from_rows(rows)
    # The floor, as arithmetic on a stored integer rather than on a
    # scheduler's clock. A created_at in the future (clock skew, a restored
    # backup) simply fails this test and the row is retained.
    cutoff = int(time.time()) - RETENTION_GRACE_SECONDS
    candidates = conn.execute(
        "SELECT digest, content_type FROM uploads WHERE created_at <= ?",
        (cutoff,),
    ).fetchall()
    collected = []
    for row in candidates:
        digest = row["digest"]
        if digest in referenced:
            continue
        if not _remove_upload(conn, digest, row["content_type"]):
            continue
        auth.audit(conn, f"image collected digest={digest}")
        collected.append(digest)
    return collected


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
        # mkstemp rather than a pid-derived name: two threads of ONE process
        # uploading the same new digest would otherwise pick the same temp
        # path, and the one that loses the race finds its file already
        # renamed away and raises FileNotFoundError out of os.replace.
        handle_fd, temp = tempfile.mkstemp(dir=directory, suffix=".part")
        try:
            with os.fdopen(handle_fd, "wb") as handle:
                handle.write(facts.data)
            # mkstemp creates at 0600; a plain open() would have taken the
            # umask. Put the umask's mode back rather than letting the
            # tempfile detail decide the permissions of a published file —
            # these are pictures meant to be served, and a deployment that
            # ever let a web server read the directory would find 0600 files
            # it could not open, for no reason anybody wrote down.
            os.chmod(temp, 0o666 & ~_UMASK)
            os.replace(temp, path)
        except BaseException:
            # Never leave a .part behind on a failed write.
            if os.path.exists(temp):
                os.unlink(temp)
            raise
    conn = _connect()
    try:
        # The conflict clause refreshes created_at and nothing else: the
        # retention floor's promise is about the digest THIS response just
        # handed the owner, not about the first upload of these bytes, and
        # on the dedup path above those are different moments. Without it a
        # re-uploaded orphan is already past the floor at the instant the
        # route answers it. excluded.created_at is the int(time.time())
        # bound below, which every request evaluates.
        conn.execute(
            "INSERT INTO uploads"
            " (digest, stored_name, content_type, byte_size, width, height,"
            "  created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(digest) DO UPDATE SET created_at ="
            " excluded.created_at",
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


@bp.route("/api/kuvat/<digest>", methods=["DELETE"])
@auth.require_admin
def delete_kuva(digest):
    """The owner's explicit removal of one stored image.

    It honours the count and is refused with 409 when a payload still names
    the digest: the route knows nothing about sections, so a force would
    leave a payload naming a missing file — a 404 where a picture was.
    Refusing makes that structurally impossible.

    It does NOT consult the retention floor. The floor protects a digest
    whose reference has not landed yet — a machine race the owner cannot see
    and did not cause. This is the opposite: the owner naming one digest and
    saying remove it, and it is the only way in the design to take back a
    wrong photograph immediately. Making them wait a quarter of an hour
    would answer "come back later" to exactly the person this is for.
    """
    if not DIGEST_PATTERN.fullmatch(digest):
        return jsonify(error="not found"), 404
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT content_type FROM uploads WHERE digest = ?", (digest,)
        ).fetchone()
        if row is None:
            return jsonify(error="not found"), 404
        if digest in referenced_digests(conn):
            return jsonify(error=MESSAGES["in_use"]), 409
        if not _remove_upload(conn, digest, row["content_type"]):
            # A row we cannot name is not servable either (kuva() 404s on
            # the same condition), so it is not found rather than deleted.
            return jsonify(error="not found"), 404
        auth.audit(conn, f"image deleted digest={digest}")
    finally:
        conn.close()
    return jsonify(deleted=digest)


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
    # The filename is RECOMPUTED from the digest (already matched against
    # DIGEST_PATTERN above) and the allowlisted extension — never taken from
    # the stored row. Werkzeug's safe_join would catch a planted traversal in
    # stored_name anyway, but recomputing makes this module's own claim — that
    # nothing client-derived reaches a path — true of the serving path by
    # construction rather than by a dependency's grace.
    response = send_from_directory(
        _upload_dir(), f"{digest}.{extension}", mimetype=row["content_type"]
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Disposition"] = (
        f'inline; filename="{digest}.{extension}"'
    )
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    # Safe because the URL *is* the digest of the content it serves.
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
