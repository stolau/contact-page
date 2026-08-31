"""Auth layer (LLM-COP-2) — sessions, audit, CLI, dialog and the seam.

The governing spec is cp-admin-login: one test per addressed contains-text
criterion, byte-exact strings taken from the spec JSON. The spec states no
testids, so nothing here invents data-testid selectors; is-visible criteria
are proven as element presence in the served document (a test client cannot
prove CSS visibility), matching tests/test_page.py's convention.

Everything runs against real temp-file databases and the real routes; the
only injection is auth._sleep, the module's own observation point for the
rate-limit delay — replaced to observe the call, never to fake a result.
"""

import hashlib
import time
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import pytest
from werkzeug.security import check_password_hash

from app import LOGIN_ERROR, auth, create_app
from app import db as database
from tests.conftest import (
    ADMIN_PASSWORD as PASSWORD,
)
from tests.conftest import (
    ADMIN_USERNAME as USERNAME,
)
from tests.conftest import (
    create_admin,
    element_text,
    login,
)

# --- helpers -----------------------------------------------------------------


def app_conn(app):
    return database.connect(app.config["DATABASE"])


def session_lookup(app, conn, token):
    """current_admin_session for a request carrying the session cookie."""
    with app.test_request_context(
        "/", headers={"Cookie": f"{auth.SESSION_COOKIE}={token}"}
    ):
        return auth.current_admin_session(conn)


def rewind_last_seen(conn, seconds):
    conn.execute(
        "UPDATE sessions SET last_seen_at = last_seen_at - ?", (seconds,)
    )
    conn.commit()


def session_rows(conn):
    return conn.execute("SELECT * FROM sessions").fetchall()


def audit_events(app):
    c = app_conn(app)
    try:
        return [
            row["event"]
            for row in c.execute("SELECT event FROM audit_log ORDER BY id")
        ]
    finally:
        c.close()


class _Inputs(HTMLParser):
    """Collects (tag, attrs) for the input elements in a document."""

    def __init__(self):
        super().__init__()
        self.inputs = []

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))


def input_names(html):
    parser = _Inputs()
    parser.feed(html)
    return {attrs.get("name") for attrs in parser.inputs}


@pytest.fixture
def admin_app(app):
    create_admin(app)
    return app


@pytest.fixture
def admin_client(admin_app):
    return admin_app.test_client()


@pytest.fixture
def gated_app(admin_app):
    """The app with one extra route behind the real require_admin decorator,
    so the seam's pass-through side effects (the last_seen_at slide) stay
    observable — the only shipped gated route, logout, deletes the session
    it just validated."""

    @admin_app.route("/_suojattu")
    @auth.require_admin
    def _suojattu():
        return "ok"

    return admin_app


# --- session rules (auth.current_admin_session) ------------------------------


def test_db_never_holds_the_raw_token(conn):
    token = auth.mint_session(conn, remember=False)
    rows = session_rows(conn)
    assert len(rows) == 1
    for value in tuple(rows[0]):
        assert token not in str(value)
    assert (
        rows[0]["token_hash"]
        == hashlib.sha256(token.encode("utf-8")).hexdigest()
    )


def test_idle_31_min_without_remember_refuses_and_deletes_the_row(conn, app):
    token = auth.mint_session(conn, remember=False)
    rewind_last_seen(conn, 31 * 60)
    assert session_lookup(app, conn, token) is None
    assert session_rows(conn) == []
    # The refusal is permanent, not cosmetic: the token never validates again.
    assert session_lookup(app, conn, token) is None


def test_idle_31_min_with_remember_still_passes(conn, app):
    token = auth.mint_session(conn, remember=True)
    rewind_last_seen(conn, 31 * 60)
    row = session_lookup(app, conn, token)
    assert row is not None
    assert row["remember"] == 1


def test_remember_session_past_expires_at_is_refused(conn, app):
    token = auth.mint_session(conn, remember=True)
    conn.execute("UPDATE sessions SET expires_at = ?", (int(time.time()) - 1,))
    conn.commit()
    assert session_lookup(app, conn, token) is None
    assert session_rows(conn) == []


def test_last_seen_at_slides_on_a_valid_request(conn, app):
    token = auth.mint_session(conn, remember=False)
    rewind_last_seen(conn, 20 * 60)
    (before,) = conn.execute("SELECT last_seen_at FROM sessions").fetchone()
    assert session_lookup(app, conn, token) is not None
    (after,) = conn.execute("SELECT last_seen_at FROM sessions").fetchone()
    assert after >= before + 20 * 60 - 2  # slid back to ~now


# --- audit log (auth.audit) --------------------------------------------------


def test_audit_keeps_only_the_newest_1000_rows(conn):
    for i in range(1005):
        auth.audit(conn, f"event {i}")
    rows = conn.execute("SELECT event FROM audit_log ORDER BY id").fetchall()
    assert len(rows) == 1000
    assert rows[0]["event"] == "event 5"  # the 5 oldest were trimmed
    assert rows[-1]["event"] == "event 1004"  # the newest survived


# --- CLI (admin-create, admin-reset-password) --------------------------------


def admin_row(app):
    c = app_conn(app)
    try:
        return c.execute("SELECT * FROM admin_user").fetchall()
    finally:
        c.close()


def cli_create(app, username=USERNAME, password=PASSWORD):
    return app.test_cli_runner().invoke(
        args=["admin-create", username], input=f"{password}\n{password}\n"
    )


def test_admin_create_stores_a_salted_werkzeug_hash(app):
    result = cli_create(app)
    assert result.exit_code == 0, result.output
    rows = admin_row(app)
    assert len(rows) == 1
    assert rows[0]["username"] == USERNAME
    stored = rows[0]["password_hash"]
    # A werkzeug hash: method prefix, then $salt$hash — never the plaintext.
    assert stored.startswith(("scrypt:", "pbkdf2:"))
    _method, salt, digest = stored.split("$")
    assert salt and digest
    assert PASSWORD not in stored
    assert check_password_hash(stored, PASSWORD)
    assert not check_password_hash(stored, "jokin muu")


def test_admin_create_refuses_a_second_account(app):
    assert cli_create(app).exit_code == 0
    before = admin_row(app)

    result = cli_create(app, username="toinen.tunnus", password="toinen pw")

    assert result.exit_code != 0
    assert "admin-reset-password" in result.output
    after = admin_row(app)
    assert len(after) == 1
    assert tuple(after[0]) == tuple(before[0])  # the row is untouched


def test_admin_reset_password_replaces_the_hash(app):
    assert cli_create(app).exit_code == 0
    old_hash = admin_row(app)[0]["password_hash"]
    new_password = "uusi salasana 456"

    result = app.test_cli_runner().invoke(
        args=["admin-reset-password"],
        input=f"{new_password}\n{new_password}\n",
    )

    assert result.exit_code == 0, result.output
    new_hash = admin_row(app)[0]["password_hash"]
    assert new_hash != old_hash
    assert check_password_hash(new_hash, new_password)
    assert not check_password_hash(new_hash, PASSWORD)  # the old one is dead


# --- the dialog (GET /yllapito), spec cp-admin-login -------------------------


@pytest.fixture
def dialog_html(client):
    response = client.get("/yllapito")
    assert response.status_code == 200
    return response.get_data(as_text=True)


@pytest.fixture
def dialog_text(dialog_html):
    """cp-admin-login.login-dialog is-visible — the dialog element itself
    exists in the served document; its text scopes the criteria below."""
    text = element_text(dialog_html, "div", cls="login-dialog")
    assert text is not None
    return text


DIALOG_TEXT_CRITERIA = [
    ("cp-admin-login.login-dialog.login-title", "Ylläpitäjän kirjautuminen"),
    ("cp-admin-login.login-dialog.login-subtitle", "Sivun sisällön muokkaus"),
    ("cp-admin-login.login-dialog.username-label", "Käyttäjätunnus"),
    ("cp-admin-login.login-dialog.password-label", "Salasana"),
    ("cp-admin-login.login-dialog.password-input.password-show", "Näytä"),
    ("cp-admin-login.login-dialog.remember-row", "Pysy kirjautuneena"),
    ("cp-admin-login.login-dialog.forgot-link", "Unohtuiko salasana?"),
    ("cp-admin-login.login-dialog.login-submit", "Kirjaudu sisään"),
    (
        "cp-admin-login.login-dialog.login-footnote-0",
        "Kirjautuminen kirjataan lokiin.",
    ),
    (
        "cp-admin-login.login-dialog.login-footnote-1",
        "Istunto päättyy 30 min käyttämättömyyden jälkeen.",
    ),
]


@pytest.mark.parametrize(
    "address,expected",
    [pytest.param(a, e, id=a) for a, e in DIALOG_TEXT_CRITERIA],
)
def test_dialog_contains_text(dialog_text, address, expected):
    assert expected in dialog_text, f"{address}: {expected!r} not in dialog"


def test_dialog_close_button_present(dialog_html):
    # cp-admin-login.login-dialog.login-close is-visible
    assert element_text(dialog_html, "a", cls="login-close") is not None


def test_dialog_inputs_present(dialog_html):
    # cp-admin-login.login-dialog.username-input / password-input is-visible
    names = input_names(dialog_html)
    assert "kayttajatunnus" in names
    assert "salasana" in names
    assert "pysy" in names  # the remember-row checkbox


def test_dialog_absent_from_the_public_page(client):
    html = client.get("/").get_data(as_text=True)
    assert "Ylläpitäjän kirjautuminen" not in html


def test_unohtui_shows_the_cli_reset_note(client):
    plain = client.get("/yllapito").get_data(as_text=True)
    assert "admin-reset-password" not in plain
    forgot = client.get("/yllapito", query_string={"unohtui": "1"})
    assert "admin-reset-password" in forgot.get_data(as_text=True)


# --- login POST /yllapito/kirjaudu -------------------------------------------


def test_login_success_sets_hardened_cookie_with_hashed_row(
    admin_app, admin_client
):
    response = login(admin_client)
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/"

    jar = SimpleCookie()
    jar.load(response.headers["Set-Cookie"])
    morsel = jar[auth.SESSION_COOKIE]
    assert morsel["httponly"]
    assert morsel["samesite"] == "Lax"
    token = morsel.value
    assert token

    c = app_conn(admin_app)
    try:
        rows = session_rows(c)
        assert len(rows) == 1
        assert (
            rows[0]["token_hash"]
            == hashlib.sha256(token.encode("utf-8")).hexdigest()
        )
        for value in tuple(rows[0]):
            assert token not in str(value)
    finally:
        c.close()


def test_wrong_password_and_unknown_username_answer_byte_identically(tmp_path):
    # Two identical submissions; on one app the username exists (wrong
    # password), on the other it does not (unknown username). The two
    # responses must be indistinguishable to the byte.
    app_known = create_app(instance_path=str(tmp_path / "known"))
    create_admin(app_known, username=USERNAME)
    app_unknown = create_app(instance_path=str(tmp_path / "unknown"))
    create_admin(app_unknown, username="toinen.tunnus")

    known = login(app_known.test_client(), password="väärä")
    unknown = login(app_unknown.test_client(), password="väärä")

    assert known.status_code == unknown.status_code == 200
    assert known.get_data() == unknown.get_data()
    assert LOGIN_ERROR in known.get_data(as_text=True)
    assert "Set-Cookie" not in known.headers
    assert "Set-Cookie" not in unknown.headers

    # ... while the audit rows differ.
    assert any(
        e.startswith("login failed (wrong password)")
        for e in audit_events(app_known)
    )
    assert any(
        e.startswith("login failed (unknown username)")
        for e in audit_events(app_unknown)
    )


def test_unknown_username_still_runs_the_hash_check(
    admin_client, monkeypatch
):
    # The unknown-username path must pay the same hashing cost as a wrong
    # password (against app._DUMMY_HASH) — skipping check_password_hash
    # would answer measurably faster and leak user existence through
    # response timing. The assertion is on the mechanism, not wall-clock.
    import app as app_module

    calls = []
    real = app_module.check_password_hash

    def counting(stored, password):
        calls.append(stored)
        return real(stored, password)

    monkeypatch.setattr(app_module, "check_password_hash", counting)

    response = login(admin_client, username="ei.ketaan", password="väärä")

    assert response.status_code == 200
    assert calls == [app_module._DUMMY_HASH]


def test_one_failure_of_each_kind_leaves_both_audit_rows(
    admin_app, admin_client
):
    login(admin_client, password="väärä")
    login(admin_client, username="ei.ketaan", password="väärä")
    failures = [
        e for e in audit_events(admin_app) if e.startswith("login failed")
    ]
    assert len(failures) == 2
    assert any("(wrong password)" in e for e in failures)
    assert any("(unknown username)" in e for e in failures)


def test_throttle_sleeps_after_three_recent_failures(
    admin_app, admin_client, monkeypatch
):
    naps = []
    monkeypatch.setattr(auth, "_sleep", naps.append)

    for _ in range(3):
        login(admin_client, password="väärä")
    assert naps == []  # the threshold counts prior failures

    login(admin_client, password="väärä")
    assert naps == [auth.FAILURE_DELAY]


# --- the seam (auth.require_admin over the real routes) ----------------------


def test_anonymous_gated_request_redirects_to_yllapito(client):
    response = client.post("/yllapito/kirjaudu-ulos")
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"


def test_anonymous_gated_request_preferring_json_gets_401(client):
    response = client.post(
        "/yllapito/kirjaudu-ulos", headers={"Accept": "application/json"}
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_logged_in_request_passes_and_slides_last_seen_at(gated_app):
    client = gated_app.test_client()
    assert login(client).status_code == 302

    c = app_conn(gated_app)
    try:
        rewind_last_seen(c, 10 * 60)
        (before,) = c.execute("SELECT last_seen_at FROM sessions").fetchone()

        response = client.get("/_suojattu")
        assert response.status_code == 200
        assert response.get_data() == b"ok"

        (after,) = c.execute("SELECT last_seen_at FROM sessions").fetchone()
        assert after >= before + 10 * 60 - 2  # slid back to ~now
    finally:
        c.close()


def test_idle_session_is_refused_at_the_seam(gated_app):
    client = gated_app.test_client()
    assert login(client).status_code == 302
    assert client.get("/_suojattu").status_code == 200  # valid until idle

    c = app_conn(gated_app)
    try:
        rewind_last_seen(c, 31 * 60)
        response = client.get("/_suojattu")
        assert response.status_code == 302
        assert urlparse(response.headers["Location"]).path == "/yllapito"
        assert session_rows(c) == []  # the expired row was deleted
    finally:
        c.close()


def test_logout_invalidates_the_old_cookie_server_side(gated_app):
    client = gated_app.test_client()
    jar = SimpleCookie()
    jar.load(login(client).headers["Set-Cookie"])
    token = jar[auth.SESSION_COOKIE].value

    # The logged-in logout passes the gate and lands back on the page.
    response = client.post("/yllapito/kirjaudu-ulos")
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/"

    c = app_conn(gated_app)
    try:
        assert session_rows(c) == []  # deleted server-side, not just the cookie
    finally:
        c.close()

    # Re-present the old cookie explicitly: it must no longer validate.
    client.set_cookie(auth.SESSION_COOKIE, token)
    response = client.get("/_suojattu")
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"
