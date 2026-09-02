"""Fixtures for the browser layer (LLM-COP-15): a real Chrome, the real
Flask app on a real HTTP port, and a logged-in page at a fixed viewport.

NOTHING here imports playwright at module level, and neither does any
other file in this directory — test_browser_gate.py asserts that with an
ast scan. The reason is the gate's own shape: a checkout without the
package must still COLLECT, so that test_playwright_is_installed can run
and fail with the pip line. A module-level import turns that honest
failure into a collection error that names an import, not a remedy.

Every fixture is function-scoped except `browser`: one Chrome process for
the session, a fresh context, a fresh app and a fresh database file per
test. Sharing the process is the whole cost saving; sharing anything else
would let one test's state decide another's result.
"""

import json
import struct
import threading
import zlib

import pytest
from werkzeug.serving import make_server

from app import create_app
from app import db as database
from tests.browser.chrome import NO_CHROME, chrome_path
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    create_admin,
    section_rows,
)

# Fixed, so a layout assertion means the same thing on every machine.
# Direct edit mode's two fixed bars and the sticky public header only
# overlap the way they overlap at a stated size.
VIEWPORT = {"width": 1280, "height": 900}

# The auto-retry budget for every expect() in this layer. Generous
# enough for a real page load, short enough that a hung assertion fails
# the gate rather than stalling it.
EXPECT_TIMEOUT_MS = 5000

# The link only page_v2.html emits. The selector, not the class, because a
# stylesheet link is what a browser would actually have to fetch.
V2_STYLESHEET = 'link[href*="style-v2.css"]'


# --- the hero row, shared by every module that asks about the style --------
#
# The style is a value on the HERO payload (LLM-COP-22), so more than one
# module in this directory has to read and plant it. These live here rather
# than in one of them because LLM-COP-24 gave the second module a real need
# for them: it stopped rendering page_v2.html through a route of its own and
# now reaches the product's URL by drafting the style, the same way
# test_browser_panel.py already did.


def hero_row(app):
    return next(row for row in section_rows(app) if row["kind"] == "hero")


def hero_draft(app):
    return json.loads(hero_row(app)["draft"])


def set_hero_draft_style(app, style):
    """Plant a style in the hero's DRAFT column of the live app's own store.

    A direct UPDATE of one column, deliberately: tests/conftest.py's
    edit_published_payload writes draft AND published, which cannot express
    "drafted but not published" — the state the preview-versus-public test is
    entirely about, and the state /muokkaa/sivu reads.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        row = conn.execute(
            "SELECT id, draft FROM sections WHERE kind = 'hero'"
        ).fetchone()
        payload = json.loads(row["draft"])
        payload["style"] = style
        conn.execute(
            "UPDATE sections SET draft = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()


# --- a real picture, for the tests that upload one (LLM-COP-25) ------------
#
# A genuine PNG built byte by byte, not a fixture arranged to pass and not a
# file checked into the tree: /api/kuvat reads the BYTES and refuses anything
# whose header does not say PNG or JPEG, and a browser will only report
# naturalWidth > 0 for something it can actually decode. Both of those are
# claims this builder has to satisfy honestly.
#
# Duplicated from tests/test_images.py's builder rather than shared, which is
# that file's own stated convention for exactly this — it says the duplication
# with tests/test_imagecheck.py is deliberate, so that each module stands
# alone. This directory imports nothing from the Python suite's test modules.


def _png_chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def png_bytes(width=48, height=48, colour=(0x2E, 0x6F, 0x9E)):
    """A real, decodable PNG of the given size."""
    raw = b"".join(b"\x00" + bytes(colour) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        )
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


@pytest.fixture(scope="session")
def browser():
    """One real Google Chrome for the session, launched by absolute path.

    executable_path, never channel=: channel hands resolution back to
    Playwright, and then tests/browser/chrome.py is no longer the only
    thing that decides which browser runs — which is what the
    missing-browser demo depends on. The bundled Chromium is not used at
    all (it is not even downloaded here), so `playwright install` is not
    part of this project's setup.
    """
    from playwright.sync_api import sync_playwright

    path = chrome_path()
    if path is None:
        # fail, never skip: a skip here is the false assurance this whole
        # layer exists to remove, the same rule test_node_is_installed
        # holds to for Node.
        pytest.fail(NO_CHROME)
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(executable_path=path)
        yield instance
        instance.close()


@pytest.fixture
def live_app(tmp_path):
    """The real app, seeded and migrated into its own temp instance
    directory, served on a real loopback port by a real HTTP server.

    Port 0, so parallel worktrees and repeat runs never collide. The
    bound port is read back off the server and hung on the app as
    `base_url`, which is what the tests navigate to.
    """
    app = create_app(instance_path=str(tmp_path / "instance"))
    create_admin(app)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    app.base_url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app
    # shutdown() stops serve_forever's loop; werkzeug's own
    # BaseWSGIServer.serve_forever then closes the listening socket in a
    # finally (werkzeug/serving.py:818-824), so the socket is released
    # even without the next line. That finally runs on the SERVING
    # thread, though, and shutdown() returns as soon as the loop stops —
    # so the explicit close is what releases the port on this thread
    # rather than whenever that one is next scheduled. server_close is
    # idempotent, so the two never fight.
    #
    # Measured either way: two full in-process runs of this directory
    # leak zero sockets and zero threads, with and without the explicit
    # call. The claim that dropping it leaks one bound socket per test
    # does not reproduce against werkzeug, and is not why it is here.
    server.shutdown()
    server.server_close()
    thread.join(timeout=10)


@pytest.fixture
def page(browser, live_app):
    """A page in a fresh context, signed in through the real login form.

    The login is the app's own POST /yllapito/kirjaudu, not a planted
    cookie: a fixture that mints its own session would stop being a test
    of the product the moment auth changed. On a first-run database the
    app redirects a successful login to the wizard (app/wizard.py), so
    this lands on /yllapito/alustus and tests wanting another screen
    navigate there themselves.
    """
    context = browser.new_context(viewport=VIEWPORT)
    open_page = context.new_page()
    open_page.goto(f"{live_app.base_url}/yllapito")
    open_page.fill("input[name=kayttajatunnus]", ADMIN_USERNAME)
    open_page.fill("input[name=salasana]", ADMIN_PASSWORD)
    open_page.click(".login-submit")
    # A state wait, not a time one: the redirect target IS the assertion
    # that the login landed.
    open_page.wait_for_url(f"{live_app.base_url}/yllapito/alustus")
    yield open_page
    context.close()


@pytest.fixture
def expect():
    """playwright's expect, with this layer's timeout already set.

    Handed back as the callable itself rather than wrapped: expect is a
    singleton function, so `expect(locator).to_be_visible()` in a test
    body keeps its auto-retrying semantics untouched. Nothing in
    tests/conftest.py is named expect, so this shadows nothing.
    """
    from playwright.sync_api import expect as playwright_expect

    playwright_expect.set_options(timeout=EXPECT_TIMEOUT_MS)
    return playwright_expect
