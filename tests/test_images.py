"""Upload, storage and serving — the first route that takes a file from
outside the process, proved against real routes, a real SQLite file and a real
directory.

Nothing here is mocked. The `app` fixture (tests/conftest.py:44-48) gives every
test its own instance path under `tmp_path`, and `logged_in_admin` (:78-87) is
a genuine posted-and-asserted admin session rather than a patched one, so an
upload in this module really writes bytes to a real directory and really
inserts a row.

The companion module tests/test_imagecheck.py proves the validator refuses what
it must. THIS module proves the three things a correct validator still cannot
give you on its own:

1. **The route consults the validator and obeys it** — a refusal writes nothing
   to disk and inserts no row, so a bomb or an SVG cannot become an orphan.
2. **The serving path is independently safe.** A row is not enough: the content
   type is re-checked against an allowlist at serve time, the filename is
   computed, the disposition is inline, `nosniff` and a sandbox CSP are set.
   That is what makes an accepted polyglot inert — the parser cannot.
3. **The cap refuses without reading the body**, which no status-code assertion
   from the test client can show, because the client hands Werkzeug a body it
   has already buffered. Those cases drive the WSGI callable directly.

On the fixtures: the PNG builders and the two JPEG literals below are
duplicated from tests/test_imagecheck.py on purpose. A shared helper would be
a third file, and each of these two modules is meant to stand alone — so the
duplication is small (one builder and two constants) and deliberate. The JPEGs
are real Pillow 10.2.0 output minted OFFLINE with the *system* Python, because
the gate's interpreter has no PIL; this module never imports it either.
"""

import base64
import hashlib
import io
import json
import os
import struct
import time
import zlib

import pytest
from werkzeug.test import EnvironBuilder

from app import auth
from app import db as database
from app.images import (
    MAX_UPLOAD_BYTES,
    MESSAGES,
    RETENTION_GRACE_SECONDS,
    _digests_from_rows,
    collect_unreferenced,
    image_url,
    referenced_digests,
)
from tests.conftest import delete_section, section_rows

# ---------------------------------------------------------------------------
# Fixtures — built or embedded, never read from disk
# ---------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PHP_PAYLOAD = b'<?php system($_GET[0]); ?>'


def _chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _ihdr(width, height):
    return _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))


def _png(width, height, colour=(0xC8, 0x78, 0x3C)):
    """A real PNG. At 4x4 this is byte-identical to corpus/valid.png."""
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (
        PNG_SIGNATURE
        + _ihdr(width, height)
        + _chunk(b"IDAT", zlib.compress(raw))
        + _chunk(b"IEND", b"")
    )


def _png_claiming(width, height):
    """The bomb shape: a perfect PNG whose IHDR claims a huge size.
    At 30000x30000 this is byte-identical to corpus/bomb.png."""
    return (
        PNG_SIGNATURE
        + _ihdr(width, height)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )


VALID_PNG = _png(4, 4)
OTHER_PNG = _png(64, 64)
BOMB_PNG = _png_claiming(30000, 30000)

XSS_SVG = (
    b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"'
    b' width="100" height="100"><script>alert(document.domain)</script>'
    b'<image href="x" onerror="alert(1)"/></svg>'
)
NOT_AN_IMAGE = b"this is definitely not an image, it is just prose.\n" * 10

# corpus/valid.jpg — a real 633-byte Pillow 10.2.0 JPEG, 8x8.
JPEG_8X8_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQY"
    "GBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYa"
    "KCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAAR"
    "CAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDIooor5E+4P//Z"
)
# corpus/bomb.jpg — the same encoder's output with the SOF patched to claim
# 30000x30000. Pillow 10.2.0 refuses it with DecompressionBombError.
JPEG_BOMB_B64 = (
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwh"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAAR"
    "CHUwdTADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAA"
    "AgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWG"
    "h4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl"
    "5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREA"
    "AgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYk"
    "NOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk"
    "5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDwGiiimI//2Q=="
)
VALID_JPEG = base64.b64decode(JPEG_8X8_B64)
BOMB_JPEG = base64.b64decode(JPEG_BOMB_B64)

JSON_ACCEPT = {"Accept": "application/json"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def upload(client, data, filename="kuva.png", field="kuva", headers=None):
    """POST one part to the real route, the way the browser's FormData does."""
    return client.post(
        "/api/kuvat",
        data={field: (io.BytesIO(data), filename)},
        content_type="multipart/form-data",
        headers=JSON_ACCEPT if headers is None else headers,
    )


def upload_dir(app):
    return app.config["UPLOAD_DIR"]


def stored_files(app):
    directory = upload_dir(app)
    if not os.path.isdir(directory):
        return []
    return sorted(os.listdir(directory))


def upload_rows(app):
    conn = database.connect(app.config["DATABASE"])
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM uploads").fetchall()]
    finally:
        conn.close()


def hero_row(app):
    return next(r for r in section_rows(app) if r["kind"] == "hero")


def section_row(app, kind):
    return next(r for r in section_rows(app) if r["kind"] == kind)


def digests_in_store(app):
    return {row["digest"] for row in upload_rows(app)}


def stored_path(app, digest, extension="png"):
    """Where the store keeps one digest's blob — recomputed from the digest
    and an allowlisted extension, exactly as the serving route recomputes it,
    never read out of the row."""
    return os.path.join(upload_dir(app), f"{digest}.{extension}")


def fetch(app, digest):
    """GET /kuvat/<digest> through the real, public serving route."""
    return app.test_client().get(f"/kuvat/{digest}")


def referenced_now(app):
    """referenced_digests over the app's own database file."""
    conn = database.connect(app.config["DATABASE"])
    try:
        return referenced_digests(conn)
    finally:
        conn.close()


def payload_rows(app):
    """The three payload columns of every section, as the collector reads
    them."""
    conn = database.connect(app.config["DATABASE"])
    try:
        return conn.execute(
            "SELECT draft, published, previous_published FROM sections"
        ).fetchall()
    finally:
        conn.close()


def collect(app):
    """Drive collect_unreferenced directly, on a real connection to the app's
    own database, inside an app context — the collector recomputes its paths
    from UPLOAD_DIR, so it needs one."""
    with app.app_context():
        conn = database.connect(app.config["DATABASE"])
        try:
            return collect_unreferenced(conn)
        finally:
            conn.close()


def age(app, digest, seconds=RETENTION_GRACE_SECONDS + 60):
    """Move one upload's created_at back — what the passage of time does, done
    to the one datum the retention floor reads and to nothing else.

    This is not a rigged fixture. The route, the store, the bytes, the
    payloads and every assertion around it stay real; arranging the clock is
    the only way to test a time-based rule without sleeping for a quarter of
    an hour in the gate.

    ONE THING A FUTURE TEST AUTHOR MUST KNOW: re-uploading the same bytes
    UN-AGES the digest. POST /api/kuvat refreshes uploads.created_at on
    conflict, so the row records the last time the digest was handed out, not
    the first — that is the whole of LLM-COP-27's dedup fix. A test that ages
    a digest, re-uploads it, and then expects it to stay collectable is
    re-asserting the bug, not a behaviour.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        cursor = conn.execute(
            "UPDATE uploads SET created_at = created_at - ? WHERE digest = ?",
            (seconds, digest),
        )
        assert cursor.rowcount == 1, f"no upload row to age for {digest}"
        conn.commit()
    finally:
        conn.close()


def upload_aged(app, admin, picture):
    """Upload one picture through the real route and age it at once — the
    convention of the collection section below."""
    response = upload(admin, picture)
    assert response.status_code == 200, response.get_data(as_text=True)
    ref = response.get_json()["ref"]
    age(app, ref)
    return ref


def put_payload(admin, app, kind, payload):
    """PUT one whole payload to a section's draft, the way the panel does."""
    row = section_row(app, kind)
    response = admin.put(
        f"/api/sections/{row['id']}/draft", json=payload, headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    return response


def save_draft(admin, app, kind, **changes):
    """Read the stored draft, change the named fields, PUT the whole payload
    back — a real collecting write (app/edit.py:put_draft)."""
    payload = json.loads(section_row(app, kind)["draft"])
    payload.update(changes)
    return put_payload(admin, app, kind, payload)


def publish_all(admin):
    """POST /api/publish, and answer the ids it really published."""
    response = admin.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["published"]


# Four distinct, genuine PNGs — different sizes, so different bytes and
# different digests. Nothing here is a fixture arranged to pass.
PICTURE_X = _png(70, 70)
PICTURE_Y = _png(71, 71)
PICTURE_Z = _png(72, 72)
PICTURE_W = _png(73, 73)


def portrait_pushed_into_previous_published(app, admin):
    """Upload X and Y, age both, publish each in turn, and return (x, y).

    Leaves the hero at draft = published = PY, previous_published = PX, which
    is the state cases 1, 2 and 4 each need and none of them may inherit from
    another: they are separate test functions and pytest guarantees no
    ordering, least of all under -k.

    Both digests are aged, per the convention below, so every verdict a caller
    later reaches about either of them is the count's doing and never the
    retention floor's.
    """
    x = upload_aged(app, admin, PICTURE_X)
    save_draft(admin, app, "hero", portrait=x)
    publish_all(admin)

    y = upload_aged(app, admin, PICTURE_Y)
    save_draft(admin, app, "hero", portrait=y)
    publish_all(admin)
    return x, y


def tree(root):
    """Every file under root, relative, excluding SQLite's own scratch files
    (-journal / -wal / -shm), which come and go for reasons of their own."""
    found = set()
    for base, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(("-journal", "-wal", "-shm")):
                continue
            found.add(os.path.relpath(os.path.join(base, name), root))
    return found


# ---------------------------------------------------------------------------
# The route is behind the admin session — and answers 401, not a redirect
# ---------------------------------------------------------------------------


def test_upload_without_a_session_answers_401_and_not_a_redirect(client):
    """The correction that is a real bug, not a nit.

    `auth._prefers_json` (app/auth.py:128-130) compares the quality of
    application/json against text/html, so a request that does NOT say it
    wants JSON is REDIRECTED to /yllapito instead of refused. `fetch` follows
    a redirect transparently and then `response.json()` throws on an HTML
    body — the panel would show a JSON parse error instead of "your session
    expired". The upload fetch therefore sends `Accept: application/json`, and
    this is the test that says the server keeps its half of that bargain.
    """
    response = upload(client, VALID_PNG)
    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


def test_a_bare_fetch_accept_would_have_been_redirected(client):
    """Why the header is mandatory rather than tidy.

    `Accept: */*` is exactly what a bare fetch() sends, and it scores
    application/json and text/html equally, so `_prefers_json` is False. This
    test pins the trap so that anyone who later drops the header from
    edit.js can see, here, what they have done.
    """
    response = upload(client, VALID_PNG, headers={"Accept": "*/*"})
    assert response.status_code == 302
    assert "/yllapito" in response.headers["Location"]


def test_serving_is_public_because_the_portrait_is(app, logged_in_admin):
    """GET /kuvat/<digest> takes no session: the picture is destined for the
    public page, so an admin-only serving route could never render it."""
    ref = upload(logged_in_admin, VALID_PNG).get_json()["ref"]
    anonymous = app.test_client()
    assert anonymous.get(f"/kuvat/{ref}").status_code == 200


# ---------------------------------------------------------------------------
# image_url — the filter that keeps untrusted payload text out of a URL
# ---------------------------------------------------------------------------


def test_image_url_resolves_a_digest():
    ref = "a" * 64
    assert image_url(ref) == f"/kuvat/{ref}"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="empty"),
        pytest.param("a" * 63, id="63-hex"),
        pytest.param("a" * 65, id="65-hex"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param("g" * 64, id="non-hex"),
        pytest.param("../../../etc/passwd", id="traversal"),
        pytest.param("a" * 63 + "/", id="slash"),
        pytest.param("a" * 64 + "?x=1", id="query"),
        pytest.param("javascript:alert(1)", id="javascript-url"),
    ],
)
def test_image_url_refuses_anything_that_is_not_a_digest(value):
    """The field is an ordinary plain string an owner can type anything into.
    Only 64 lowercase hex characters ever become a URL."""
    assert image_url(value) is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="none"),
        pytest.param(123, id="int"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="bool"),
        pytest.param([], id="list"),
        pytest.param({}, id="dict"),
    ],
)
def test_image_url_type_guards_before_the_pattern(value):
    """`re.fullmatch(pattern, <not a str>)` raises TypeError.

    The filter runs over payloads loaded from stored JSON, so the value is
    whatever is in the database — and app/templates/_section_row.html renders
    the same macro for every section. Without an isinstance check ahead of the
    pattern this is a 500 on a page, not a None.
    """
    assert image_url(value) is None


def test_image_url_type_guards_a_jinja_undefined():
    """The likeliest non-string of all: a key that is simply not there.

    `p.portrait` on a payload without the key is an Undefined, and Undefined
    is not a str — so this is the exact value that would have raised.
    """
    from jinja2 import Undefined

    assert image_url(Undefined(name="portrait")) is None


def test_a_non_string_portrait_does_not_500_any_page(app, client, logged_in_admin):
    """The type guard where it actually bites, through real routes.

    A payload is stored JSON; nothing stops a number being in it. Both the
    public page and the editor's section list render the hero macro, so both
    would have taken the 500.
    """
    from tests.conftest import edit_published_payload

    edit_published_payload(app, "hero", lambda p: p.__setitem__("portrait", 12345))
    assert client.get("/").status_code == 200
    assert logged_in_admin.get("/muokkaa").status_code == 200


# ---------------------------------------------------------------------------
# Refusals: nothing gets in, and nothing is left behind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,data,filename,reason",
    [
        # "Validate the content, not the filename."
        ("php with a png name", PNG_SIGNATURE + PHP_PAYLOAD, "photo.png", "format"),
        ("prose with a png name", NOT_AN_IMAGE, "photo.png", "format"),
        ("prose with a jpg name", NOT_AN_IMAGE, "photo.jpg", "format"),
        # An SVG is a script vector, and renaming it changes nothing because
        # the route never reads the name.
        ("an svg", XSS_SVG, "drawing.svg", "format"),
        ("an svg named .png", XSS_SVG, "drawing.png", "format"),
        ("an svg named .jpg", XSS_SVG, "drawing.jpg", "format"),
        ("a truncated png", VALID_PNG[:36], "photo.png", "format"),
        # The bombs: structurally perfect, refused on their declared size, and
        # with a DIFFERENT message so the owner is told something true.
        ("bomb.png", BOMB_PNG, "photo.png", "dimensions"),
        ("bomb.jpg", BOMB_JPEG, "photo.jpg", "dimensions"),
    ],
)
def test_a_refused_upload_stores_nothing_at_all(
    app, logged_in_admin, name, data, filename, reason
):
    """415 with the right message, no file on disk, no row in the table.

    The last two clauses are the ones that matter: a route that refused but
    had already written the bytes would leave a permanently public, permanently
    undeletable orphan at a stable URL — which is exactly the durability
    property the README has to disclose for the files we DO accept.
    """
    response = upload(logged_in_admin, data, filename=filename)
    assert response.status_code == 415, response.get_data(as_text=True)
    assert response.get_json()["error"] == MESSAGES[reason]
    assert stored_files(app) == []
    assert upload_rows(app) == []


def test_the_dimension_message_is_not_the_format_message():
    """Two refusals that mean different things must read differently, or the
    owner cannot act on either. 'not a valid image' for a perfectly valid
    photograph that is merely too large is a lie."""
    assert MESSAGES["dimensions"] != MESSAGES["format"]
    assert MESSAGES["too_large"] not in (MESSAGES["format"], MESSAGES["dimensions"])
    assert MESSAGES["empty"] != MESSAGES["format"]


def test_the_messages_are_finnish_and_say_what_to_do():
    """Product copy, pinned. The panel puts these in front of the owner
    verbatim (they cannot go through showErrors — hero.portrait has no
    FIELD_LABELS entry, so it would render as the raw key)."""
    assert MESSAGES["too_large"] == "Kuva on liian suuri: enintään 5 Mt."
    assert MESSAGES["empty"] == (
        "Kuvaa ei vastaanotettu — lähetä tiedosto uudelleen."
    )
    assert MESSAGES["format"] == (
        "Vain PNG- ja JPEG-kuvat kelpaavat, eikä tiedosto ole ehjä PNG tai JPEG."
    )
    assert MESSAGES["dimensions"] == (
        "Kuva on liian suuri: enintään 10 000 × 10 000 pikseliä"
        " ja 25 megapikseliä."
    )


# ---------------------------------------------------------------------------
# The cap — proven, not asserted
# ---------------------------------------------------------------------------


def test_the_cap_is_five_megabytes_and_is_not_applied_app_wide(app):
    """Per-request, so no other route's behaviour changes. An app-wide
    MAX_CONTENT_LENGTH would silently cap the JSON draft save too."""
    assert MAX_UPLOAD_BYTES == 5 * 1024 * 1024
    assert app.config.get("MAX_CONTENT_LENGTH") is None


def test_a_body_over_the_cap_is_refused(app, logged_in_admin):
    """corpus/oversize.png is 12.5 MB. In production the cap reaches it first
    and the parser's own refusal is the second line, not the first."""
    oversize = VALID_PNG + b"\x00" * (12 * 1024 * 1024)
    response = upload(logged_in_admin, oversize)
    assert response.status_code == 413
    assert response.get_json()["error"] == MESSAGES["too_large"]
    assert stored_files(app) == []
    assert upload_rows(app) == []


class _ExplodingStream(io.RawIOBase):
    """A request body that records any attempt to read it, then refuses.

    HOW THIS FAILS, precisely — because getting it wrong would make the test
    look like it proves more than it does. Flask CATCHES this AssertionError
    and turns it into a 500 (PROPAGATE_EXCEPTIONS is None and the app is
    neither testing nor debug), so it never reaches the test as an error. A
    regression that moved the cap after the read shows up as the `reads == 0`
    assertion failing, with the AssertionError below it as chained context.
    Measured with a negative control that deleted the preemptive cap and put a
    post-hoc `len(data)` check in its place: with the cap, 413 and zero reads;
    without it, `reads == 1` and a 500. So this test discriminates between the
    two mechanisms, which is the whole point — both of them answer 413 to an
    ordinary oversized upload, and only one of them refuses to buffer it.
    """

    def __init__(self):
        self.reads = 0

    def readable(self):
        return True

    def read(self, size=-1):
        self.reads += 1
        raise AssertionError("the body was read — the cap did not refuse first")

    readinto = read


def _drive_wsgi(app, environ):
    """Call the WSGI application directly.

    The test client rebuilds CONTENT_LENGTH from the stream it is given, so it
    physically cannot present the environ these cases need. This is the only
    way to hand the app a body it has not already buffered.
    """
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = int(status.split(" ", 1)[0])
        captured["headers"] = headers

    body = b"".join(app(environ, start_response))
    return captured["status"], body


def _upload_environ(payload, cookie):
    builder = EnvironBuilder(
        method="POST",
        path="/api/kuvat",
        data={"kuva": (io.BytesIO(payload), "kuva.png")},
        content_type="multipart/form-data",
        headers={"Accept": "application/json", "Cookie": cookie},
    )
    return builder.get_environ()


@pytest.fixture
def admin_cookie(logged_in_admin):
    cookie = logged_in_admin.get_cookie(auth.SESSION_COOKIE)
    assert cookie is not None, "the session fixture did not set a cookie"
    return f"{auth.SESSION_COOKIE}={cookie.value}"


def test_an_oversized_body_is_refused_without_being_read(app, admin_cookie):
    """The claim the whole cap rests on, with a proof that can fail.

    A status-code assertion from the test client proves a status code and
    nothing more. Here CONTENT_LENGTH declares 5 GB and `wsgi.input` raises on
    any read, so a 413 can only have come from the declared length —
    werkzeug/wsgi.py:183-187 compares get_content_length(environ) against the
    limit and raises RequestEntityTooLarge before the stream is touched.
    """
    environ = _upload_environ(b"", admin_cookie)
    environ["CONTENT_LENGTH"] = str(5 * 1024 * 1024 * 1024)
    stream = _ExplodingStream()
    environ["wsgi.input"] = stream

    status, body = _drive_wsgi(app, environ)

    assert stream.reads == 0, (
        "the request body was read before the cap refused it — the cap is no"
        " longer preemptive and an arbitrary upload can be buffered"
    )
    assert status == 413, body
    assert json.loads(body)["error"] == MESSAGES["too_large"]
    assert stored_files(app) == []


def test_a_chunked_body_the_server_did_not_terminate_answers_the_empty_message(
    app, admin_cookie
):
    """The documented 415, so it cannot regress into silence.

    With no Content-Length and no `wsgi.input_terminated`,
    werkzeug/wsgi.py:205-206 hands back an empty BytesIO — the view sees zero
    bytes and must NOT say "not a valid image", which would cost somebody an
    afternoon. Browsers send Content-Length for FormData, so this is a
    documented edge rather than a defect.
    """
    environ = _upload_environ(VALID_PNG, admin_cookie)
    environ.pop("CONTENT_LENGTH", None)
    environ.pop("wsgi.input_terminated", None)

    status, body = _drive_wsgi(app, environ)

    assert status == 415, body
    assert json.loads(body)["error"] == MESSAGES["empty"]
    assert stored_files(app) == []


def test_a_chunked_body_the_server_did_terminate_is_still_capped(app, admin_cookie):
    """The other half: a server that sets wsgi.input_terminated gets the cap
    enforced WHILE reading, through LimitedStream(is_max=True)
    (werkzeug/wsgi.py:191-198). So there is no way in through chunking."""
    oversize = VALID_PNG + b"\x00" * (12 * 1024 * 1024)
    environ = _upload_environ(oversize, admin_cookie)
    environ.pop("CONTENT_LENGTH", None)
    environ["wsgi.input_terminated"] = True

    status, body = _drive_wsgi(app, environ)

    assert status == 413, body
    assert stored_files(app) == []


def test_an_empty_part_answers_the_empty_message(app, logged_in_admin):
    response = upload(logged_in_admin, b"")
    assert response.status_code == 415
    assert response.get_json()["error"] == MESSAGES["empty"]
    assert stored_files(app) == []


def test_a_request_with_no_file_part_at_all_answers_the_empty_message(
    app, logged_in_admin
):
    response = logged_in_admin.post(
        "/api/kuvat", data={}, content_type="multipart/form-data",
        headers=JSON_ACCEPT,
    )
    assert response.status_code == 415
    assert response.get_json()["error"] == MESSAGES["empty"]
    assert stored_files(app) == []


# ---------------------------------------------------------------------------
# The client's filename reaches nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        pytest.param("../../../etc/cron.d/x.png", id="posix-traversal"),
        pytest.param("....//....//evil.png", id="doubled-traversal"),
        pytest.param("..\\..\\..\\windows\\evil.png", id="windows-traversal"),
        pytest.param("/etc/passwd", id="absolute"),
        pytest.param("kuva.png\x00.php", id="null-byte"),
        pytest.param("kuva.php", id="wrong-extension"),
        pytest.param("", id="empty-name"),
    ],
)
def test_a_hostile_filename_cannot_escape_or_even_be_used(
    app, tmp_path, logged_in_admin, filename
):
    """Structurally impossible, not filtered.

    The stored name is `sha256(canonical bytes).<extension we determined>`, so
    the client's filename is not sanitised — it is never consulted. The proof
    is a whole-tree diff of the instance directory: the ONLY thing that
    appeared is the digest-named file inside UPLOAD_DIR.
    """
    before = tree(str(tmp_path))
    response = upload(logged_in_admin, VALID_PNG, filename=filename)
    assert response.status_code == 200, response.get_data(as_text=True)
    ref = response.get_json()["ref"]

    assert ref == hashlib.sha256(VALID_PNG).hexdigest()
    assert stored_files(app) == [f"{ref}.png"]

    expected = os.path.join(upload_dir(app), f"{ref}.png")
    assert os.path.isfile(expected)
    with open(expected, "rb") as handle:
        assert handle.read() == VALID_PNG

    added = tree(str(tmp_path)) - before
    assert added == {os.path.relpath(expected, str(tmp_path))}, (
        f"filename {filename!r} caused something to be written outside"
        f" UPLOAD_DIR: {sorted(added)}"
    )


def test_the_upload_directory_is_under_the_instance_path(app):
    """The app fixture gives each test its own instance path, so this also
    proves an upload cannot reach a shared location."""
    assert upload_dir(app) == os.path.join(app.instance_path, "uploads")
    assert os.path.isdir(upload_dir(app))


def test_the_stored_extension_comes_from_the_bytes_not_the_name(
    app, logged_in_admin
):
    """A JPEG uploaded as `.png` is stored as `.jpg` and served as
    image/jpeg — the determined type wins everywhere."""
    ref = upload(logged_in_admin, VALID_JPEG, filename="lies.png").get_json()["ref"]
    assert stored_files(app) == [f"{ref}.jpg"]
    response = app.test_client().get(f"/kuvat/{ref}")
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/jpeg"


# ---------------------------------------------------------------------------
# Identical bytes cost one file
# ---------------------------------------------------------------------------


def test_uploading_the_same_bytes_twice_costs_one_file_and_one_row(
    app, logged_in_admin
):
    first = upload(logged_in_admin, VALID_PNG, filename="a.png")
    second = upload(logged_in_admin, VALID_PNG, filename="completely-other.png")
    assert first.status_code == second.status_code == 200

    ref = first.get_json()["ref"]
    assert second.get_json()["ref"] == ref
    assert stored_files(app) == [f"{ref}.png"]

    rows = upload_rows(app)
    assert len(rows) == 1
    assert rows[0]["digest"] == ref


def test_a_jpeg_and_the_same_jpeg_with_a_payload_glued_on_are_one_file(
    app, logged_in_admin
):
    """Canonicalisation, at the layer where it pays.

    The digest is over the span the validator tiled, not over the request
    body, so an appended payload cannot fork storage and cannot reach disk.
    Hashing the body instead would give two digests, two files, and one of
    them carrying the payload.
    """
    clean = upload(logged_in_admin, VALID_JPEG, filename="a.jpg")
    dirty = upload(logged_in_admin, VALID_JPEG + PHP_PAYLOAD, filename="b.jpg")
    assert clean.status_code == dirty.status_code == 200
    ref = clean.get_json()["ref"]
    assert dirty.get_json()["ref"] == ref

    assert stored_files(app) == [f"{ref}.jpg"]
    assert len(upload_rows(app)) == 1
    with open(os.path.join(upload_dir(app), f"{ref}.jpg"), "rb") as handle:
        stored = handle.read()
    assert stored == VALID_JPEG
    assert PHP_PAYLOAD not in stored


def test_two_different_pictures_cost_two_files(app, logged_in_admin):
    """The other side of dedup: a content-addressed store that collapsed
    distinct pictures would be worse than one that never deduped."""
    first = upload(logged_in_admin, VALID_PNG).get_json()["ref"]
    second = upload(logged_in_admin, OTHER_PNG).get_json()["ref"]
    assert first != second
    assert stored_files(app) == sorted([f"{first}.png", f"{second}.png"])
    assert len(upload_rows(app)) == 2


def test_the_row_records_what_we_determined(app, logged_in_admin):
    """Content type, byte size and dimensions come from the parser; byte_size
    is the length of the STORED bytes, not of the request body."""
    body = VALID_JPEG + PHP_PAYLOAD
    ref = upload(logged_in_admin, body, filename="x.png").get_json()["ref"]
    (row,) = upload_rows(app)
    assert row["digest"] == ref
    assert row["stored_name"] == f"{ref}.jpg"
    assert row["content_type"] == "image/jpeg"
    assert row["width"] == 8
    assert row["height"] == 8
    assert row["byte_size"] == len(VALID_JPEG)
    assert row["byte_size"] != len(body)
    assert isinstance(row["created_at"], int)


# ---------------------------------------------------------------------------
# Serving is independently safe
# ---------------------------------------------------------------------------


def test_serving_headers_neuter_the_response(app, logged_in_admin):
    """The polyglot limit is answered HERE, not in the parser.

    A structurally perfect PNG carrying a payload inside a well-formed chunk
    is accepted by any validator short of a re-encoder. What makes it inert is
    this: a Flask view (not a web server mapping extensions onto
    interpreters), a content type we determined, nosniff so the browser cannot
    reconsider it, a sandbox CSP, and a computed inline disposition.
    """
    payload_png = (
        PNG_SIGNATURE
        + _ihdr(4, 4)
        + _chunk(b"tEXt", b"comment\x00" + PHP_PAYLOAD)
        + _chunk(b"IDAT", zlib.compress(b"\x00" * 100))
        + _chunk(b"IEND", b"")
    )
    ref = upload(logged_in_admin, payload_png, filename="x.png").get_json()["ref"]
    response = app.test_client().get(f"/kuvat/{ref}")

    assert response.status_code == 200
    assert response.headers["Content-Type"] == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "sandbox" in csp
    disposition = response.headers["Content-Disposition"]
    assert disposition.startswith("inline")
    assert f"{ref}.png" in disposition
    # The URL is the content hash, so immutable caching is safe.
    cache = response.headers["Cache-Control"]
    assert "public" in cache and "immutable" in cache and "max-age=31536000" in cache
    assert response.get_data() == payload_png


def test_a_row_claiming_svg_still_cannot_be_served(app, logged_in_admin, tmp_path):
    """The serving allowlist as a SECOND, INDEPENDENT control.

    Upload refuses SVG — but a control that only exists at admission is one
    bug away from nothing. So this plants the row and the file directly in the
    store, bypassing the route entirely, and the serving path must still
    refuse. The file really is on disk; the 404 is the allowlist, not a
    missing file.
    """
    digest = hashlib.sha256(XSS_SVG).hexdigest()
    directory = upload_dir(app)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{digest}.svg")
    with open(path, "wb") as handle:
        handle.write(XSS_SVG)
    conn = database.connect(app.config["DATABASE"])
    try:
        conn.execute(
            "INSERT INTO uploads (digest, stored_name, content_type, byte_size,"
            " width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (digest, f"{digest}.svg", "image/svg+xml", len(XSS_SVG), 100, 100, 0),
        )
        conn.commit()
    finally:
        conn.close()

    assert os.path.isfile(path)  # the file is really there
    response = app.test_client().get(f"/kuvat/{digest}")
    assert response.status_code == 404
    assert b"<script>" not in response.get_data()


def test_the_serving_digest_pattern_refuses_even_a_row_that_matches(
    app, logged_in_admin, tmp_path
):
    """The serving route's DIGEST_PATTERN check, on its own.

    Every other non-digest case is caught by the row lookup finding nothing,
    so deleting the pattern check leaves them all green — it is
    defence-in-depth that nothing defends. Here the row EXISTS and its digest
    column is not hex, so the lookup would succeed and the only thing left
    standing between a URL segment and the Content-Disposition header it is
    interpolated into is the pattern.
    """
    bogus = "x" * 64
    directory = upload_dir(app)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{bogus}.png")
    with open(path, "wb") as handle:
        handle.write(VALID_PNG)
    conn = database.connect(app.config["DATABASE"])
    try:
        conn.execute(
            "INSERT INTO uploads (digest, stored_name, content_type, byte_size,"
            " width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bogus, f"{bogus}.png", "image/png", len(VALID_PNG), 4, 4, 0),
        )
        conn.commit()
    finally:
        conn.close()

    assert os.path.isfile(path)  # the file and the row both really exist
    response = app.test_client().get(f"/kuvat/{bogus}")
    assert response.status_code == 404
    assert response.get_data() != VALID_PNG


@pytest.mark.parametrize(
    "ref",
    [
        pytest.param("b" * 64, id="unknown-digest"),
        pytest.param("a" * 63, id="too-short"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param("g" * 64, id="non-hex"),
        pytest.param("..%2f..%2fetc%2fpasswd", id="encoded-traversal"),
        pytest.param("....//....//etc/passwd", id="traversal"),
    ],
)
def test_serving_refuses_anything_that_is_not_a_stored_digest(app, ref):
    response = app.test_client().get(f"/kuvat/{ref}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# A section without an image is untouched
# ---------------------------------------------------------------------------


def test_an_upload_does_not_perturb_any_section_payload(app, logged_in_admin):
    """`badge()` compares raw stored JSON, so a byte of drift in a payload
    would mark an untouched section dirty forever.

    Snapshot every row's stored text, run a real upload, read the rows back
    and require byte-equality — the store, not a route's opinion of it.
    """
    before = section_rows(app)
    response = upload(logged_in_admin, VALID_PNG)
    assert response.status_code == 200
    after = section_rows(app)

    assert len(before) == len(after)
    for old, new in zip(before, after):
        assert old == new, f"section {old['kind']} changed under an upload"


def test_the_seeded_hero_payload_has_no_new_keys(app):
    """The reference-in-payload shape adds no field: hero.portrait was already
    a declared plain field. An upload route that needed a new key would have
    collided with the key-order assertions in test_seed.py and test_edit.py.
    """
    payload = json.loads(hero_row(app)["draft"])
    assert payload["portrait"] == ""


# ---------------------------------------------------------------------------
# Migration 5
# ---------------------------------------------------------------------------


def test_the_uploads_table_exists_at_the_stamped_version(conn):
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS)
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'uploads'"
    ).fetchone()
    assert row is not None


def test_the_uploads_digest_is_unique(conn):
    """The dedup guarantee has to be in the schema, not only in the route:
    two concurrent uploads of the same picture must not make two rows."""
    values = ("d" * 64, "d.png", "image/png", 10, 4, 4, 0)
    columns = (
        "INSERT INTO uploads (digest, stored_name, content_type, byte_size,"
        " width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    conn.execute(columns, values)
    conn.commit()
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(columns, values)


# ---------------------------------------------------------------------------
# The round trip: upload, publish, render, remove
# ---------------------------------------------------------------------------


def test_the_portrait_survives_upload_publish_render_and_removal(
    app, client, logged_in_admin
):
    """Every step through a real route against a real store — and then back
    out again, because a picture you cannot remove is a defect, not a feature.

    This is the reviewer's last check ("the portrait actually renders on the
    public page after an upload and a publish") plus the one the plan added
    when it noticed `hero.portrait` is in no form, so `Vaihda` could only ever
    SET a digest and `Peruuta` restores only the last save.
    """
    # 1. a genuine PNG, not a fixture arranged to pass
    picture = _png(64, 64)

    # 2. upload
    response = upload(logged_in_admin, picture, filename="muotokuva.png")
    assert response.status_code == 200, response.get_data(as_text=True)
    ref = response.get_json()["ref"]
    assert response.get_json()["url"] == f"/kuvat/{ref}"

    # 3. the bytes really are on disk, addressed by their own digest
    path = os.path.join(upload_dir(app), f"{ref}.png")
    with open(path, "rb") as handle:
        on_disk = handle.read()
    assert on_disk == picture
    assert hashlib.sha256(on_disk).hexdigest() == ref

    # 3a. Age it (LLM-COP-27). A freshly uploaded digest is retained for
    #     RETENTION_GRACE_SECONDS whatever the count says, so an unaged
    #     picture would survive steps 9a and 9b for a reason that has nothing
    #     to do with references. Everything this test later concludes about
    #     retention has to be the COUNT's doing, not the floor's.
    age(app, ref)

    # 4. put the reference in the hero draft
    hero = hero_row(app)
    payload = json.loads(hero["draft"])
    payload["portrait"] = ref
    response = logged_in_admin.put(
        f"/api/sections/{hero['id']}/draft", json=payload, headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["badge"] == "Luonnos"

    # 5. publish
    response = logged_in_admin.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 200
    assert hero["id"] in response.get_json()["published"]

    # 6. the public page renders the picture and drops the placeholder
    page = client.get("/").get_data(as_text=True)
    assert f'src="/kuvat/{ref}"' in page
    assert "portrait-image" in page
    assert "has-image" in page
    assert "portrait-icon" not in page
    assert "or browse files" not in page

    # 7. and it serves, byte-identically, with the type we determined
    response = client.get(f"/kuvat/{ref}")
    assert response.status_code == 200
    assert response.get_data() == picture
    assert response.headers["Content-Type"] == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert f"{ref}.png" in response.headers["Content-Disposition"]

    # 8. take it away again — the same field, the same save, no new route
    payload["portrait"] = ""
    response = logged_in_admin.put(
        f"/api/sections/{hero['id']}/draft", json=payload, headers=JSON_ACCEPT
    )
    assert response.status_code == 200
    assert logged_in_admin.post("/api/publish", headers=JSON_ACCEPT).status_code == 200

    page = client.get("/").get_data(as_text=True)
    assert "portrait-image" not in page
    assert f"/kuvat/{ref}" not in page
    assert "portrait-icon" in page
    assert "or browse files" in page

    # 9. THE REMOVAL REACHES DISK — but one publish later, not now
    #    (LLM-COP-27). Taking the picture off the page is not yet taking it
    #    off disk, because after step 8 the hero holds draft = published = the
    #    portrait-less payload while previous_published still holds the one
    #    naming this digest — and Palauta edellinen versio would bring it
    #    back. The bytes go at the publish PAST that, the moment
    #    previous_published is overwritten and no column of any section names
    #    the digest any more. `ref` was aged at step 3a, so each verdict below
    #    is about the reference count and nothing else.

    # 9a. still served, because previous_published still names it
    assert client.get(f"/kuvat/{ref}").status_code == 200
    assert os.path.isfile(path)

    # 9b. make the hero genuinely dirty again — app/sections.py:116 publishes
    #     only sections whose draft differs from their published payload, so
    #     without a real change the next publish moves no column at all. This
    #     PUT runs a collection; previous_published has not moved, so the
    #     picture must survive it. That is what makes "collected only when the
    #     LAST column stops naming it" observable rather than merely claimed.
    payload["title"] = "Uusi otsikko"
    response = logged_in_admin.put(
        f"/api/sections/{hero['id']}/draft", json=payload, headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert client.get(f"/kuvat/{ref}").status_code == 200
    assert os.path.isfile(path)

    # 9c. publish past it: the hero is dirty, so previous_published takes the
    #     portrait-less published payload and the last reference is gone.
    response = logged_in_admin.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 200
    assert hero["id"] in response.get_json()["published"]

    # 9d. collected: no route, no file, no row.
    assert client.get(f"/kuvat/{ref}").status_code == 404
    assert not os.path.isfile(path)
    assert ref not in digests_in_store(app)


# ---------------------------------------------------------------------------
# Collection (LLM-COP-27): an upload leaves when nothing names it any more
#
# THE CONVENTION OF THIS SECTION, and it is load-bearing: EVERY UPLOAD IS
# AGED THE MOMENT IT IS MADE, UNLESS ITS FRESHNESS IS THE POINT OF THE TEST.
#
# Two independent things retain a picture — the count (some section payload
# still names it) and the retention floor (POST /api/kuvat answered that
# digest less than RETENTION_GRACE_SECONDS ago). So a "the picture survives"
# assertion over a FRESH upload passes whatever the count says, and proves
# nothing about the count. Aging first is what makes every survival verdict
# below the count's doing. `upload_aged` exists so that is the easy path.
#
# Exactly three tests keep an upload fresh on purpose — case 5's explicit
# delete, and case 6's two arms — and each says in its docstring why.
#
# Nothing here is mocked, per this module's opening paragraph: real routes, a
# real SQLite file, real bytes in the real UPLOAD_DIR. The ONE thing ever
# arranged is a single upload's created_at, through `age`.
# ---------------------------------------------------------------------------


# --- the extractor: referenced_digests / _digests_from_rows ----------------


def test_a_digest_in_the_hero_portrait_is_referenced(app, logged_in_admin):
    ref = upload_aged(app, logged_in_admin, PICTURE_X)
    assert ref not in referenced_now(app)
    save_draft(logged_in_admin, app, "hero", portrait=ref)
    assert ref in referenced_now(app)


def test_a_digest_typed_into_a_plain_text_field_is_referenced(
    app, logged_in_admin
):
    """The generic extractor, asserted rather than assumed.

    referenced_digests scans the RAW stored text of the three payload columns:
    it knows nothing about FIELDS, nothing about `portrait`, and does not
    parse JSON. sijainti.address is a plain field with no cap
    (app/fields.py:78) stored verbatim (app/sanitize.py:179), so a digest put
    there through the real draft route is counted exactly like one in
    hero.portrait. That is the decision, not a workaround: a field-specific
    extractor would under-count silently the day a second image field exists,
    and under-counting deletes a live picture.
    """
    ref = upload_aged(app, logged_in_admin, PICTURE_X)
    save_draft(logged_in_admin, app, "sijainti", address=ref)
    assert ref in referenced_now(app)


def test_a_digest_only_in_previous_published_is_referenced(
    app, logged_in_admin
):
    """previous_published is a first-class counted column, because Palauta
    edellinen versio restores from it: a picture named only there is still
    reachable and must be counted."""
    x, _ = portrait_pushed_into_previous_published(app, logged_in_admin)
    hero = section_row(app, "hero")
    assert x not in hero["draft"]
    assert x not in hero["published"]
    assert x in hero["previous_published"]
    assert x in referenced_now(app)


def test_null_payload_columns_do_not_raise(app):
    """A freshly seeded store has previous_published NULL on all six rows —
    the ordinary state, and the one a naive extractor blows up on."""
    rows = payload_rows(app)
    assert len(rows) == 6
    assert all(row["previous_published"] is None for row in rows)
    assert _digests_from_rows(rows) == set()
    assert referenced_now(app) == set()


def test_a_stored_upload_names_itself_nowhere(app, logged_in_admin):
    """The count reads `sections` and only `sections`. Scanning
    uploads.stored_name would pin the entire store by construction, and the
    collector would then never collect anything — a bug that looks exactly
    like the feature working."""
    ref = upload_aged(app, logged_in_admin, PICTURE_X)
    assert ref in digests_in_store(app)
    assert referenced_now(app) == set()


def test_the_extractor_unites_all_three_columns_under_one_rule(
    app, logged_in_admin
):
    """One extraction rule, not two: referenced_digests is _digests_from_rows
    over its own SELECT, and the collector is the same helper over the rows it
    already fetched. A drift where the DESTROYING function found fewer digests
    than the checking one would be a hole, so the two are asserted equal over
    a store where the three columns hold different digests."""
    x, y = portrait_pushed_into_previous_published(app, logged_in_admin)
    assert _digests_from_rows(payload_rows(app)) == referenced_now(app)
    assert {x, y} <= referenced_now(app)


# --- the collector, driven directly ----------------------------------------


def plant_upload(app, digest, stored_name, content_type, data):
    """Plant a row and its file straight into the store, bypassing the route
    — the shape tests/test_images.py:716-745 and :748-780 already use.

    created_at is 0: as far past the retention floor as a row can be, so
    nothing but the collector's own refusal can save it.
    """
    directory = upload_dir(app)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, stored_name)
    with open(path, "wb") as handle:
        handle.write(data)
    conn = database.connect(app.config["DATABASE"])
    try:
        conn.execute(
            "INSERT INTO uploads (digest, stored_name, content_type, byte_size,"
            " width, height, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (digest, stored_name, content_type, len(data), 100, 100, 0),
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_the_collector_takes_the_unreferenced_and_leaves_the_referenced(
    app, logged_in_admin
):
    """One aged referenced digest and one aged unreferenced one, collected in
    a single call: exactly one row and one file go, and the other pair is
    untouched. Both are aged, so the difference between them is the count."""
    kept = upload(logged_in_admin, PICTURE_X).get_json()["ref"]
    save_draft(logged_in_admin, app, "hero", portrait=kept)
    # Uploaded AFTER that write, so no route's collection has swept it yet.
    orphan = upload(logged_in_admin, PICTURE_Y).get_json()["ref"]
    age(app, kept)
    age(app, orphan)
    assert kept in referenced_now(app)
    assert orphan not in referenced_now(app)

    assert collect(app) == [orphan]

    assert orphan not in digests_in_store(app)
    assert not os.path.isfile(stored_path(app, orphan))
    assert fetch(app, orphan).status_code == 404

    assert kept in digests_in_store(app)
    assert os.path.isfile(stored_path(app, kept))
    assert fetch(app, kept).status_code == 200


def test_a_row_claiming_svg_is_not_collected(app):
    """A row the collector cannot name is skipped ENTIRELY — row and file
    both left alone.

    image/svg+xml is not in SERVE_ALLOWLIST, so no extension can be computed
    and no path exists to unlink. A defensive branch that DESTROYS is exactly
    the one a reviewer suspicious of over-collection should distrust, so this
    one refuses instead. Nothing is reachable either way: the serving route
    already 404s such a row (:716-745). Being wrong here leaves a file, not a
    hole.
    """
    digest = hashlib.sha256(XSS_SVG).hexdigest()
    path = plant_upload(app, digest, f"{digest}.svg", "image/svg+xml", XSS_SVG)
    assert digest not in referenced_now(app)

    assert collect(app) == []

    assert digest in digests_in_store(app)
    assert os.path.isfile(path)


def test_a_row_whose_digest_is_not_a_digest_is_not_collected(app):
    """The same refusal on the other unnameable row: the collector checks
    DIGEST_PATTERN.fullmatch — not match — before it computes a path, so a
    64-character non-digest, or a 64-hex PREFIX of some longer stored value,
    can never become a path something is unlinked from."""
    bogus = "x" * 64
    path = plant_upload(app, bogus, f"{bogus}.png", "image/png", VALID_PNG)
    assert bogus not in referenced_now(app)

    assert collect(app) == []

    assert bogus in digests_in_store(app)
    assert os.path.isfile(path)


def test_an_empty_sections_table_authorises_nothing(app, logged_in_admin):
    """The guard, in the one place the destruction is.

    An empty `sections` gives an empty referenced set, which without this
    guard reads as "nothing is named, delete the whole store". Unreachable
    today — seed_if_empty always inserts six — but one `if` buys it back in
    the retaining direction.
    """
    ref = upload_aged(app, logged_in_admin, PICTURE_X)
    for kind in (
        "hero",
        "tietoa",
        "palvelut",
        "vastaanottoajat",
        "yhteydenotto",
        "sijainti",
    ):
        delete_section(app, kind)
    assert section_rows(app) == []

    assert collect(app) == []

    assert ref in digests_in_store(app)
    assert os.path.isfile(stored_path(app, ref))


# --- the retention floor ---------------------------------------------------


def test_the_retention_grace_is_fifteen_minutes():
    """Pinned, so a change to the value is deliberate — the shape
    test_the_cap_is_five_megabytes_and_is_not_applied_app_wide already uses.

    The floor has to outlast the longest plausible gap between an upload
    landing and the write that names it: a 2 s autosave debounce
    (app/static/autosave.js:56) on top of a body that may be 5 MB, which is
    roughly thirteen minutes at a poor-but-real mobile uplink, plus the one
    further PUT setPortrait issues. The two errors are not symmetrical — too
    short destroys a picture the owner is actively placing (a hole), too long
    leaves an abandoned one on disk for a quarter of an hour (a file) — so the
    value is rounded generously toward retaining.
    """
    assert RETENTION_GRACE_SECONDS == 15 * 60


def test_a_fresh_orphan_is_retained_until_the_grace_expires(
    app, logged_in_admin
):
    """Both directions in one test, and the second half is the point.

    The first half alone could pass for any number of reasons; what proves the
    retention was the FLOOR is that the only thing changed between the two
    halves is created_at. Same picture, same unreferenced state, same
    collecting write, opposite verdicts.
    """
    ref = upload(logged_in_admin, PICTURE_X).get_json()["ref"]  # fresh: the subject
    path = stored_path(app, ref)
    assert ref not in referenced_now(app)  # only the floor can save it

    # a real collecting write, on a section that does not name it
    save_draft(logged_in_admin, app, "sijainti", address="Katutie 1")
    assert ref in digests_in_store(app)
    assert os.path.isfile(path)
    assert fetch(app, ref).status_code == 200

    age(app, ref)
    save_draft(logged_in_admin, app, "sijainti", address="Katutie 2")
    assert ref not in digests_in_store(app)
    assert not os.path.isfile(path)
    assert fetch(app, ref).status_code == 404


def test_re_uploading_the_same_bytes_refreshes_the_retention_clock(
    app, logged_in_admin
):
    """The dedup path's timestamp, which is what makes the floor's promise
    true as written.

    The floor protects "a digest POST /api/kuvat has just answered", not "a
    first upload of some bytes". Those differ by exactly the dedup path: the
    route short-circuits the file write and takes ON CONFLICT, so without the
    refresh a re-uploaded orphan is already past the floor at the instant the
    route hands it to the owner. Aging between the two uploads is what makes
    the comparison deterministic rather than a one-second race.
    """
    first = upload(logged_in_admin, PICTURE_X, filename="a.png")
    ref = first.get_json()["ref"]
    age(app, ref)
    before = upload_rows(app)[0]["created_at"]

    second = upload(logged_in_admin, PICTURE_X, filename="completely-other.png")
    assert second.status_code == 200
    assert second.get_json()["ref"] == ref

    rows = upload_rows(app)
    assert len(rows) == 1  # an upsert, not a second row
    assert stored_files(app) == [f"{ref}.png"]
    after = rows[0]["created_at"]
    assert after > before
    assert abs(after - int(time.time())) <= 5


# --- the gate cases, each through real routes ------------------------------


def test_an_image_named_only_by_previous_published_survives(
    app, logged_in_admin
):
    """Gate case 1. The rollback window is exactly as deep as
    previous_published, and everything at that depth must still be there."""
    x, _ = portrait_pushed_into_previous_published(app, logged_in_admin)

    # the precondition, stated by the test rather than assumed
    for row in section_rows(app):
        for column in ("draft", "published", "previous_published"):
            here = x in (row[column] or "")
            expected = row["kind"] == "hero" and column == "previous_published"
            assert here is expected, f"{row['kind']}.{column} names X: {here}"

    assert x in digests_in_store(app)
    assert os.path.isfile(stored_path(app, x))
    assert fetch(app, x).status_code == 200


def test_publishing_past_a_previous_version_collects_only_what_nothing_names(
    app, logged_in_admin
):
    """Gate case 2, both halves in one test so "collects" and "only what
    nothing names" fail separately. All three digests are aged, so every
    verdict here is the count's and none of it is the floor's."""
    x, y = portrait_pushed_into_previous_published(app, logged_in_admin)
    z = upload_aged(app, logged_in_admin, PICTURE_Z)
    save_draft(logged_in_admin, app, "hero", portrait=z)
    publish_all(logged_in_admin)
    # hero: draft = published = PZ, previous_published = PY. Nothing names X.

    assert x not in digests_in_store(app)
    assert not os.path.isfile(stored_path(app, x))
    assert fetch(app, x).status_code == 404

    for surviving in (y, z):
        assert surviving in digests_in_store(app)
        assert os.path.isfile(stored_path(app, surviving))
        assert fetch(app, surviving).status_code == 200


def test_two_sections_sharing_a_digest_survive_one_removing_it(
    app, logged_in_admin
):
    """Gate case 3 — the invisible sharing hazard.

    Identical bytes are ONE file and ONE row (app/images.py:164-186), so two
    sections naming the same digest name the same blob. The count is over
    digests and never over sections, exactly so the collector is never asked
    "who owned this file" — a question it could answer wrongly. Here the hero
    lets go of X entirely and sijainti still names it, so X must stay.
    """
    x = upload_aged(app, logged_in_admin, PICTURE_X)
    save_draft(logged_in_admin, app, "hero", portrait=x)
    save_draft(logged_in_admin, app, "sijainti", address=x)
    publish_all(logged_in_admin)

    save_draft(logged_in_admin, app, "hero", portrait="")
    publish_all(logged_in_admin)  # hero: previous_published = PX, published = P0

    save_draft(logged_in_admin, app, "hero", title="Uusi otsikko")
    publish_all(logged_in_admin)  # hero: previous_published = P0. X is gone from it.

    # The precondition, per column, so a future change that makes the hero pin
    # X again fails HERE rather than quietly making the next block vacuous.
    hero = section_row(app, "hero")
    assert x not in hero["draft"], "hero.draft still names X"
    assert x not in hero["published"], "hero.published still names X"
    assert x not in (
        hero["previous_published"] or ""
    ), "hero.previous_published still names X"
    sijainti = section_row(app, "sijainti")
    assert x in sijainti["draft"], "the surviving reference should be sijainti's"
    assert x in sijainti["published"]

    # X survives — and by the assertions above, only sijainti's contribution
    # to the union can be keeping it. An extractor that scanned the hero row
    # alone fails right here.
    assert x in digests_in_store(app)
    assert os.path.isfile(stored_path(app, x))
    assert fetch(app, x).status_code == 200

    # The negative control, in one observation: the collector demonstrably
    # ran, demonstrably deletes, and demonstrably left X alone. W is aged, or
    # the floor would retain it and the control would fail for a reason that
    # has nothing to do with the collector.
    w = upload_aged(app, logged_in_admin, PICTURE_W)
    save_draft(logged_in_admin, app, "hero", title="Vielä uudempi otsikko")
    assert w not in digests_in_store(app)
    assert not os.path.isfile(stored_path(app, w))
    assert fetch(app, w).status_code == 404
    assert fetch(app, x).status_code == 200


def test_a_rollback_finds_its_picture_and_the_public_page_shows_it_again(
    app, client, logged_in_admin
):
    """Gate case 4. The rollback is proved by the public page rendering the
    picture, not by a row count."""
    x, _ = portrait_pushed_into_previous_published(app, logged_in_admin)
    hero = section_row(app, "hero")

    response = logged_in_admin.post(
        f"/api/sections/{hero['id']}/restore", headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["payload"]["portrait"] == x
    publish_all(logged_in_admin)

    assert f'src="/kuvat/{x}"' in client.get("/").get_data(as_text=True)
    served = fetch(app, x)
    assert served.status_code == 200
    assert served.get_data() == PICTURE_X


def test_a_stale_autosave_landing_during_an_upload_does_not_destroy_the_picture(
    app, client, logged_in_admin
):
    """Gate case 6, arm A — the window the floor exists for.

    X is deliberately FRESH: its freshness is the whole subject, and aging it
    here would age away the hazard. The three requests are in the exact order
    shipped client code produces them, and no threads are needed, because the
    hazard is about ORDER and not concurrency — app/static/edit.js writes
    draft.portrait only inside the upload's .then (:306) and the Vaihda change
    handler never cancels the armed autosave (:277-309), so a 2 s debounce
    really can fire in the middle of a 5 MB upload.

    Against a collector with no floor this fails at step 3, and the picture
    the owner is placing is gone with no error anywhere.
    """
    # what the keystroke that armed the timer left in the draft
    stale = json.loads(section_row(app, "hero")["draft"])
    stale["title"] = "Kesken jäänyt otsikko"

    # 1. the upload lands; setPortrait has not run, so nothing names X yet
    ref = upload(logged_in_admin, PICTURE_X).get_json()["ref"]
    assert ref not in referenced_now(app)

    # 2. the stale timer fires: a real collecting write, with a pre-upload
    #    payload that does not mention X
    put_payload(logged_in_admin, app, "hero", stale)

    # 3. the picture the owner is placing is still there
    assert ref in digests_in_store(app)
    assert os.path.isfile(stored_path(app, ref))
    assert fetch(app, ref).status_code == 200

    # 4. the upload's .then lands late, 5. and the owner publishes
    save_draft(logged_in_admin, app, "hero", portrait=ref)
    publish_all(logged_in_admin)
    assert f'src="/kuvat/{ref}"' in client.get("/").get_data(as_text=True)
    assert fetch(app, ref).get_data() == PICTURE_X


def test_a_stale_autosave_does_not_destroy_a_picture_the_owner_just_re_uploaded(
    app, client, logged_in_admin
):
    """Gate case 6, arm B — the same window after a DEDUPED re-upload.

    The owner uploaded A an hour ago and the .then never landed (an expired
    session, a closed tab), so A is an ancient orphan: a row and a file older
    than the grace, named by nothing. Nothing collected it, because collection
    runs only inside the three writes that can drop a reference. Then they
    come back and pick the same file again.

    A is aged BEFORE the second upload, and that ordering is what gives this
    arm its power: the subject is that the re-upload RESTORES freshness to an
    aged digest. Aging afterwards would undo the very refresh being asserted,
    and would fail against the fixed design too. Against ON CONFLICT DO
    NOTHING, A's created_at stays ancient, step 3's write finds it
    unreferenced and past the floor, and step 4 fails on all three counts.
    """
    stale = json.loads(section_row(app, "hero")["draft"])
    stale["title"] = "Kesken jäänyt otsikko"

    # 1. the abandoned upload, and the hour the owner spent away
    a = upload(logged_in_admin, PICTURE_X).get_json()["ref"]
    age(app, a)
    assert a not in referenced_now(app)

    # 2. the same bytes again — and the test STATES it took the dedup path
    second = upload(logged_in_admin, PICTURE_X, filename="sama-kuva.png")
    assert second.status_code == 200
    assert second.get_json()["ref"] == a
    assert len(upload_rows(app)) == 1
    assert stored_files(app) == [f"{a}.png"]

    # 3. the stale autosave timer, exactly as in arm A
    put_payload(logged_in_admin, app, "hero", stale)

    # 4. A survives, because the response the owner is acting on is seconds old
    assert a in digests_in_store(app)
    assert os.path.isfile(stored_path(app, a))
    assert fetch(app, a).status_code == 200

    # 5. the .then lands, the owner publishes, the picture is on the page
    save_draft(logged_in_admin, app, "hero", portrait=a)
    publish_all(logged_in_admin)
    assert f'src="/kuvat/{a}"' in client.get("/").get_data(as_text=True)
    assert fetch(app, a).get_data() == PICTURE_X


# --- the explicit delete ---------------------------------------------------


def test_an_explicit_delete_removes_the_row_and_the_file_together(
    app, logged_in_admin
):
    """Gate case 5 — and, because the picture is deliberately FRESH, the proof
    that the owner's explicit intent bypasses the retention floor.

    That bypass is load-bearing rather than a convenience: with a fifteen
    minute floor, this route is the only way in the design to take back a
    wrong photograph immediately, which is the whole point of an artifact
    filed as security. The floor protects a digest whose reference has not
    landed yet — a machine race the owner cannot see. This is the opposite:
    the owner naming one digest and saying remove it.
    """
    ref = upload(logged_in_admin, PICTURE_X).get_json()["ref"]
    assert os.path.isfile(stored_path(app, ref))

    response = logged_in_admin.delete(f"/api/kuvat/{ref}", headers=JSON_ACCEPT)
    assert response.status_code == 200, response.get_data(as_text=True)

    assert upload_rows(app) == []
    assert stored_files(app) == []
    assert fetch(app, ref).status_code == 404


def test_an_explicit_delete_refuses_a_picture_the_page_still_names(
    app, logged_in_admin
):
    """409, not a force: the route takes a digest and knows nothing about
    sections, so a force would leave a payload naming a missing file — a 404
    where a picture was. Refusing makes that structurally impossible."""
    ref = upload(logged_in_admin, PICTURE_X).get_json()["ref"]
    save_draft(logged_in_admin, app, "hero", portrait=ref)

    response = logged_in_admin.delete(f"/api/kuvat/{ref}", headers=JSON_ACCEPT)
    assert response.status_code == 409
    assert response.get_json()["error"] == MESSAGES["in_use"]

    assert ref in digests_in_store(app)
    assert os.path.isfile(stored_path(app, ref))
    assert fetch(app, ref).status_code == 200


def test_delete_without_a_session_answers_401_and_not_a_redirect(client):
    """The same trap the upload route pins at :191-217: a request that does
    not say it wants JSON is REDIRECTED rather than refused, and fetch follows
    a redirect transparently and then throws on an HTML body."""
    response = client.delete(f"/api/kuvat/{'a' * 64}", headers=JSON_ACCEPT)
    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorized"


@pytest.mark.parametrize(
    "ref",
    [
        pytest.param("b" * 64, id="unknown-digest"),
        pytest.param("A" * 64, id="uppercase"),
        pytest.param("g" * 64, id="non-hex"),
    ],
)
def test_deleting_something_that_is_not_a_stored_digest_is_a_404(
    logged_in_admin, ref
):
    response = logged_in_admin.delete(f"/api/kuvat/{ref}", headers=JSON_ACCEPT)
    assert response.status_code == 404


# --- the guards ------------------------------------------------------------


def test_an_upload_collects_nothing_not_even_an_old_orphan(
    app, logged_in_admin
):
    """POST /api/kuvat must not collect, and this is the criterion that can
    fail if somebody adds a call to it.

    A is an aged, unreferenced orphan, so the floor is not what saves it: an
    upload route that collected would sweep A inside B's request. Asserting
    instead that a FRESH upload survives its own request would prove nothing,
    because the floor retains it either way.
    """
    a = upload_aged(app, logged_in_admin, PICTURE_X)
    b = upload(logged_in_admin, PICTURE_Y).get_json()["ref"]

    assert {a, b} <= digests_in_store(app)
    assert os.path.isfile(stored_path(app, a))
    assert os.path.isfile(stored_path(app, b))
    assert fetch(app, a).status_code == 200
    assert fetch(app, b).status_code == 200


def test_a_collecting_draft_save_moves_no_other_payload(app, logged_in_admin):
    """badge() compares raw stored JSON, so a byte of drift in a payload would
    mark an untouched section dirty forever. The collector's only SQL against
    a section is a SELECT; this asserts that byte-for-byte anyway, over a
    write that really did collect."""
    ref = upload_aged(app, logged_in_admin, PICTURE_X)
    before = section_rows(app)

    save_draft(logged_in_admin, app, "hero", title="Uusi otsikko")

    # the write really collected — otherwise this test proves nothing
    assert ref not in digests_in_store(app)
    assert not os.path.isfile(stored_path(app, ref))

    after = section_rows(app)
    assert len(before) == len(after)
    for old, new in zip(before, after):
        if old["kind"] == "hero":
            assert new["draft"] != old["draft"]  # the one row the PUT changed
            assert {k: v for k, v in old.items() if k != "draft"} == {
                k: v for k, v in new.items() if k != "draft"
            }
        else:
            assert old == new, f"section {old['kind']} moved under a collection"


def test_hiding_a_section_does_not_collect_its_picture(app, logged_in_admin):
    """POST /api/sections/<id>/state writes `state` and nothing else, so a
    hidden section still pins its picture — and unhiding must find it. The
    picture is aged, so this is the count keeping it and not the floor."""
    x = upload_aged(app, logged_in_admin, PICTURE_X)
    save_draft(logged_in_admin, app, "hero", portrait=x)
    publish_all(logged_in_admin)

    hero = section_row(app, "hero")
    response = logged_in_admin.post(
        f"/api/sections/{hero['id']}/state",
        json={"state": "hidden"},
        headers=JSON_ACCEPT,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert section_row(app, "hero")["state"] == "hidden"

    # a real collecting write elsewhere, while the hero is hidden
    save_draft(logged_in_admin, app, "sijainti", address="Katutie 3")

    assert x in digests_in_store(app)
    assert os.path.isfile(stored_path(app, x))
    assert fetch(app, x).status_code == 200


def test_a_restore_collects_the_draft_it_discarded(app, logged_in_admin):
    """The third collecting write path, driven on its own.

    Palauta edellinen versio replaces the draft wholesale, so the digest the
    discarded draft named can be this store's last reference to a picture. Z
    is aged and lives in NO column but that draft, so the collection has to
    happen inside the restore request itself — case 4 reaches the collector
    through the publish that follows its restore, and so proves nothing about
    this call site.

    The second half is the other direction, and it is why this test is not
    only about under-collection: X and Y are still named after the restore and
    must survive it. A destroying call site that over-collected would have
    nothing else in the suite to catch it.
    """
    x, y = portrait_pushed_into_previous_published(app, logged_in_admin)
    # hero: draft = published = PY, previous_published = PX
    z = upload_aged(app, logged_in_admin, PICTURE_Z)
    save_draft(logged_in_admin, app, "hero", portrait=z)

    # the precondition, per column: only the draft names Z
    for row in section_rows(app):
        for column in ("draft", "published", "previous_published"):
            here = z in (row[column] or "")
            expected = row["kind"] == "hero" and column == "draft"
            assert here is expected, f"{row['kind']}.{column} names Z: {here}"
    assert z in digests_in_store(app)

    hero = section_row(app, "hero")
    response = logged_in_admin.post(
        f"/api/sections/{hero['id']}/restore", headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["payload"]["portrait"] == x  # PX is back in the draft

    # the discarded draft's picture goes, in this request
    assert z not in referenced_now(app)
    assert z not in digests_in_store(app)
    assert not os.path.isfile(stored_path(app, z))
    assert fetch(app, z).status_code == 404

    # and nothing else does: X is now in draft and previous_published, Y in
    # published, so both are still named and both must still be served.
    for surviving in (x, y):
        assert surviving in digests_in_store(app)
        assert os.path.isfile(stored_path(app, surviving))
        assert fetch(app, surviving).status_code == 200
