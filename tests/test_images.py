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
import zlib

import pytest
from werkzeug.test import EnvironBuilder

from app import auth
from app import db as database
from app.images import MAX_UPLOAD_BYTES, MESSAGES, image_url
from tests.conftest import section_rows

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

    # 9. THE ORPHAN, asserted rather than merely written down in the README.
    #    Poista removes the picture from the page, not from disk: there is no
    #    delete route and no garbage collection, so the bytes stay world-
    #    readable at a stable URL forever. A reviewer should see this fail the
    #    day someone implements deletion, and update the README in the same
    #    commit.
    assert client.get(f"/kuvat/{ref}").status_code == 200
    assert os.path.isfile(path)
