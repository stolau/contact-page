"""Auth layer (LLM-COP-2) — sessions, audit, CLI, dialog and the seam.

The governing spec is cp-admin-login: one test per addressed contains-text
criterion, byte-exact strings taken from the spec JSON. The spec states no
testids, so nothing here invents data-testid selectors; is-visible criteria
are proven as element presence in the served document (a test client cannot
prove CSS visibility), matching tests/test_page.py's convention.

Everything runs against real temp-file databases and the real routes; the
injections are monkeypatch on app.check_password_hash and sqlite3's own
set_trace_callback — both of which observe the real work, never fake a
result.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import pytest
from werkzeug.security import check_password_hash

import app as app_module
from app import LOGIN_ERROR, auth, create_app, messages, totp
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
    # A fresh seeded DB has never been published, so login offers the
    # first-run wizard (LLM-COP-7); the configured-database branch back
    # to "/" is covered in tests/test_wizard.py. What this test exists
    # for — the cookie hardening and the hashed row — is unchanged.
    assert urlparse(response.headers["Location"]).path == "/yllapito/alustus"

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


# --- the login rate limit (LLM-COP-37) ---------------------------------------
#
# The property under proof is per-client REFUSAL: after
# auth.LOGIN_FAILURE_THRESHOLD attempts from one client key inside
# auth.LOGIN_FAILURE_WINDOW seconds, further attempts are answered without the
# username being looked up and without a password hash being computed.
#
# Restart survival is asserted too, but as a REGRESSION GUARD rather than as
# the new property: the throttle this replaces counted rows in audit_log, so
# it already outlived a restart. What could easily have been built wrong is
# the new store, and test_the_refusal_survives_a_process_restart is what
# forbids the process-local shape app/messages.py uses.

THRESHOLD = auth.LOGIN_FAILURE_THRESHOLD

# Two documentation-range addresses, so no test keys on a real host and no two
# clients here collide by accident.
CLIENT = "203.0.113.7"
OTHER_CLIENT = "198.51.100.9"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def login_from(client, address, username=USERNAME, password=PASSWORD,
               remember=False):
    """login(), posted from a named client address.

    conftest's login() sends no environ_base, so every call it makes arrives
    from the test client's default 127.0.0.1 — one shared bucket. Every test
    below that is about per-client accounting has to say which client it is.
    """
    data = {"kayttajatunnus": username, "salasana": password}
    if remember:
        data["pysy"] = "1"
    return client.post(
        "/yllapito/kirjaudu",
        data=data,
        environ_base={"REMOTE_ADDR": address},
    )


def attempt_rows(conn, key):
    return conn.execute(
        "SELECT * FROM login_attempts WHERE client_key = ? ORDER BY id", (key,)
    ).fetchall()


def attempt_count(app, key):
    """Recorded attempts for one client, read through a fresh connection to
    the app's own database file — the store, not a route's opinion of it."""
    c = app_conn(app)
    try:
        return len(attempt_rows(c, key))
    finally:
        c.close()


def hash_calls(monkeypatch):
    """Record every check_password_hash the route makes, and still do it.

    The idiom of test_unknown_username_still_runs_the_hash_check above: the
    real hash is called through, so nothing is faked — the list only observes
    that the expensive credential check happened at all. A refusal that is a
    real refusal never appends to it.
    """
    calls = []
    real = app_module.check_password_hash

    def counting(stored, password):
        calls.append(stored)
        return real(stored, password)

    monkeypatch.setattr(app_module, "check_password_hash", counting)
    return calls


def rewind_login_attempts(conn, seconds):
    """Time travel the suite's way: a direct UPDATE on the stored epoch, as
    rewind_last_seen above does for sessions — the real rows in the real
    store rather than a faked clock reading."""
    conn.execute("UPDATE login_attempts SET at = at - ?", (seconds,))
    conn.commit()


@pytest.fixture
def clean_rate_limiter():
    """This file's one contact-form test resets app.messages' process-global
    window store itself.

    tests/test_messages.py has an autouse fixture for exactly this, but an
    autouse fixture declared in a test module covers that module only, and
    this change deliberately does not touch that file (that it is untouched
    is the proof that the contact limiter is unmodified). Without this, the
    test would pass only by alphabetical collection order and would leave
    _rate_windows at RATE_LIMIT + 1 for whatever ran next. reset_rate_limiter
    is the seam app/messages.py exposes for it.

    Not autouse: only one test in this file needs it, and a second autouse
    copy of a fixture that already exists elsewhere is the kind of thing that
    later gets "cleaned up" by someone who does not know which module owns it.
    """
    messages.reset_rate_limiter()
    yield
    messages.reset_rate_limiter()


# --- obligation 1: N attempts from one client are refused --------------------


def test_the_sixth_attempt_from_one_client_is_refused_without_a_hash(
    admin_app, admin_client, monkeypatch
):
    """A refusal, not a delay and not a filter.

    The (THRESHOLD + 1)th submission carries the CORRECT password. It is
    still answered with the ordinary failure page, and check_password_hash is
    never reached — so the attempt was refused before the credentials were
    looked at, which is the whole difference between this and the one-second
    nap it replaces. A delay implementation, or one that checked the count
    after hashing, appends to `calls` here and goes red.
    """
    calls = hash_calls(monkeypatch)

    for i in range(THRESHOLD):
        response = login_from(admin_client, CLIENT, password="väärä")
        assert response.status_code == 200, i
        assert len(calls) == i + 1, i  # every one of these WAS evaluated

    refused = login_from(admin_client, CLIENT)  # the correct password

    assert refused.status_code == 200
    assert LOGIN_ERROR in refused.get_data(as_text=True)
    assert len(calls) == THRESHOLD  # no hash was computed for it
    assert "Set-Cookie" not in refused.headers
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []  # and no session was minted
        # The refused attempt wrote nothing: an attacker who keeps hammering
        # cannot extend their own lockout, so the owner's wait stays bounded
        # by the window.
        assert len(attempt_rows(c, CLIENT)) == THRESHOLD
    finally:
        c.close()


# --- obligation 2: the refusal survives a process restart --------------------


_RESTART_CHILD = """
import json
import sys

from app import create_app

app = create_app(instance_path=sys.argv[1])
response = app.test_client().post(
    "/yllapito/kirjaudu",
    data={"kayttajatunnus": sys.argv[2], "salasana": sys.argv[3]},
    environ_base={"REMOTE_ADDR": sys.argv[4]},
)
print(json.dumps({
    "status": response.status_code,
    "cookie": "Set-Cookie" in response.headers,
}))
"""


def test_the_refusal_survives_a_process_restart(tmp_path):
    """A genuinely new interpreter, because nothing weaker proves this.

    Calling create_app a second time in THIS process would not clear a single
    module global, so a process-local dict limiter — the shape
    app/messages.py uses, and the shape the artifact warns against copying —
    would sail through such a test. Only a new interpreter, whose module
    globals start empty, can tell a database-backed counter from a
    process-local one. So the "restart" is subprocess.run([sys.executable,
    ...]) against the SAME instance directory.

    Honest framing: restart survival is a regression guard here, not the new
    property. The throttle this replaces counted rows in audit_log and
    already had it. What is new is per-client refusal (obligation 1); this
    test is what stops the new store being built the process-local way.

    Shaped after tests/test_js_suite.py, the suite's only other subprocess
    test: capture_output, an explicit timeout so a hang fails the gate rather
    than freezing it, and the return code asserted FIRST with the child's
    whole stdout+stderr in the message — a child that dies must produce a red
    test that says why, not a confusing parse error.
    """
    instance = str(tmp_path / "instance")
    app = create_app(instance_path=instance)
    create_admin(app)
    client = app.test_client()
    for _ in range(THRESHOLD):
        assert login_from(client, CLIENT, password="väärä").status_code == 200
    assert attempt_count(app, CLIENT) == THRESHOLD

    env = {k: v for k, v in os.environ.items() if k != "TRUSTED_PROXY"}
    env["PYTHONPATH"] = REPO_ROOT
    proc = subprocess.run(
        [sys.executable, "-c", _RESTART_CHILD, instance, USERNAME, PASSWORD,
         CLIENT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    report = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"the restarted interpreter exited {proc.returncode}\n{report}"
    )
    answer = json.loads(proc.stdout.strip().splitlines()[-1])
    # The new process, holding the CORRECT password, is still refused.
    assert answer == {"status": 200, "cookie": False}, report
    # And the count it refused on came off the disk, not out of this process.
    assert attempt_count(app, CLIENT) == THRESHOLD
    c = app_conn(app)
    try:
        assert session_rows(c) == []
    finally:
        c.close()


# --- obligation 3: one client's failures do not throttle another -------------


def test_one_clients_failures_do_not_throttle_another(admin_app, admin_client):
    """The hazard the replaced throttle actually had.

    auth.throttle_failures counted every login failure site-wide, so an
    attacker anywhere on the internet slowed the owner down. A limiter keyed
    on a constant — or on nothing — passes every other test in this section
    and fails this one.
    """
    for _ in range(THRESHOLD):
        assert (
            login_from(admin_client, CLIENT, password="väärä").status_code
            == 200
        )
    assert login_from(admin_client, CLIENT).status_code == 200  # locked out

    response = login_from(admin_client, OTHER_CLIENT)

    assert response.status_code == 302
    assert "Set-Cookie" in response.headers
    c = app_conn(admin_app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()


# --- obligation 4: a throttled attempt is not an existence oracle ------------


def test_a_throttled_attempt_answers_the_same_whether_the_user_exists(
    tmp_path,
):
    """A sibling of
    test_wrong_password_and_unknown_username_answer_byte_identically, asked
    of the throttled path.

    Two apps on two instance paths: on one the submitted username exists (so
    every submission is a wrong password), on the other it does not (unknown
    username). Both are driven past the threshold, then handed one more
    identical submission. The two throttled answers must be equal to the
    byte, and equal to an ordinary un-throttled failure from a different
    client key on the same app.

    THE EXACT STRENGTH OF THE CLAIM, so nobody later reads it as more: this
    is a CONTENT claim, NOT a timing one. The throttled path skips the
    password hash and therefore answers measurably sooner than an evaluated
    failure — an attacker can tell by the clock that they are being refused,
    which is information they already hold, because they know their own
    attempt count. What matters, and what is proved here, is that neither the
    content nor the timing of a throttled answer depends on whether the
    username exists: the refusal is decided before admin_user is read at all.
    """
    app_known = create_app(instance_path=str(tmp_path / "known"))
    create_admin(app_known, username=USERNAME)
    app_unknown = create_app(instance_path=str(tmp_path / "unknown"))
    create_admin(app_unknown, username="toinen.tunnus")
    known_client = app_known.test_client()
    unknown_client = app_unknown.test_client()

    for _ in range(THRESHOLD):
        login_from(known_client, CLIENT, password="väärä")
        login_from(unknown_client, CLIENT, password="väärä")

    known = login_from(known_client, CLIENT, password="väärä")
    unknown = login_from(unknown_client, CLIENT, password="väärä")

    assert known.status_code == unknown.status_code == 200
    assert known.get_data() == unknown.get_data()
    assert LOGIN_ERROR in known.get_data(as_text=True)
    assert "Set-Cookie" not in known.headers
    assert "Set-Cookie" not in unknown.headers
    # Both really were refused rather than merely failing: neither wrote a
    # (THRESHOLD + 1)th row.
    assert attempt_count(app_known, CLIENT) == THRESHOLD
    assert attempt_count(app_unknown, CLIENT) == THRESHOLD

    # ... and a throttled answer is indistinguishable from an ordinary,
    # un-throttled failure too, so the refusal is not its own signal either.
    ordinary = login_from(known_client, OTHER_CLIENT, password="väärä")
    assert ordinary.status_code == 200
    assert ordinary.get_data() == known.get_data()
    assert attempt_count(app_known, OTHER_CLIENT) == 1  # it WAS evaluated


# --- obligation 5: the contact form's limiter is untouched -------------------


CONTACT_MESSAGE = {
    "name": "Maria Koskinen",
    "message": "Onko teillä vapaita aikoja ensi viikolla?",
    "email": "maria@esimerkki.fi",
    "consent": True,
}


def test_the_two_limiters_are_independent(
    admin_app, admin_client, clean_rate_limiter
):
    """The login lockout consumes no contact slot, and vice versa.

    tests/test_messages.py is deliberately NOT modified by this change — that
    file being untouched, with its seven rate-limit cases still green against
    the client key moved into app/auth.py, is the proof that the contact
    limiter still behaves exactly as it did. This test adds the one thing
    that file cannot say: that the two limiters do not share a counter.

    The final reset_rate_limiter() assertion is what pins the contact form to
    its PROCESS-LOCAL dict: emptying that dict alone restores the form, so
    its window state is not in the database — the login limiter was added
    beside it, not underneath it.
    """
    assert messages.RATE_LIMIT == 5
    assert messages.RATE_WINDOW == 3600

    for _ in range(THRESHOLD):
        login_from(admin_client, CLIENT, password="väärä")
    assert login_from(admin_client, CLIENT).status_code == 200  # locked out

    # A locked-out client still gets its full five contact messages.
    for i in range(messages.RATE_LIMIT):
        response = admin_client.post(
            "/api/messages",
            json=CONTACT_MESSAGE,
            environ_base={"REMOTE_ADDR": CLIENT},
        )
        assert response.status_code == 201, i
    over = admin_client.post(
        "/api/messages",
        json=CONTACT_MESSAGE,
        environ_base={"REMOTE_ADDR": CLIENT},
    )
    assert over.status_code == 429

    # Five contact messages consumed no login attempt in the other direction.
    assert attempt_count(admin_app, CLIENT) == THRESHOLD

    messages.reset_rate_limiter()
    restored = admin_client.post(
        "/api/messages",
        json=CONTACT_MESSAGE,
        environ_base={"REMOTE_ADDR": CLIENT},
    )
    assert restored.status_code == 201
    # ... while the login is still locked: clearing the in-process store did
    # nothing to the database-backed counter.
    assert login_from(admin_client, CLIENT).status_code == 200


# --- obligation 6: the attempt is recorded, and committed, before the hash ---


def test_the_attempt_is_recorded_before_the_password_is_hashed(
    admin_app, admin_client, monkeypatch
):
    """The ordering the whole guarantee rests on, observed from inside the
    hash through a SECOND connection to the same database file.

    A second connection can only see COMMITTED rows, so a green run proves
    both halves at once: the attempt row is inserted before
    check_password_hash begins, and it is committed rather than sitting in an
    open transaction where a concurrent gate's count would not see it.

    Why it matters: if the insert happened after the hash instead, the gate's
    read and its write would be separated by a full scrypt, and the
    documented server is thread-per-connection with no ceiling — so the
    number of guesses admitted per window would be the attacker's socket
    count rather than THRESHOLD. Every other test in this section passes
    against that ordering, because the Flask test client is serial. This one
    does not: it records 0 instead of 1.
    """
    seen = []
    real = app_module.check_password_hash

    def observing(stored, password):
        other = database.connect(admin_app.config["DATABASE"])
        try:
            seen.append(len(attempt_rows(other, CLIENT)))
        finally:
            other.close()
        return real(stored, password)

    monkeypatch.setattr(app_module, "check_password_hash", observing)

    response = login_from(admin_client, CLIENT, password="väärä")

    assert response.status_code == 200
    assert seen == [1]


def test_the_gate_takes_the_write_lock_before_it_counts(conn):
    """A MECHANISM assertion, and named as one.

    What it pins: the count the admission decision is made on, and the INSERT
    that consumes it, happen inside one BEGIN IMMEDIATE transaction.
    Underneath that is SQLite's guarantee — once RESERVED is held, no other
    connection can commit between the count and the insert — and that
    guarantee is not observable through a serial test client. A threaded
    burst would pass by luck whenever the requests happened not to interleave,
    and a barrier inside the transaction would need a seam in production code
    that exists only for a test. So the mechanism is asserted instead, and the
    cost of that is stated rather than hidden: the atomicity of the gate is
    pinned here, not demonstrated behaviourally.

    The first, UNLOCKED count is skipped deliberately: a client already over
    the threshold is refused there and never touches the write lock, so that
    statement is correct code and comes before BEGIN IMMEDIATE. The test
    below is what proves the refused path really does stay lock-free.
    """
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        admitted, crossed = auth.admit_login_attempt(conn, "k")
    finally:
        conn.set_trace_callback(None)
    assert (admitted, crossed) == (True, False)

    assert "BEGIN IMMEDIATE" in statements, statements
    in_lock = statements[statements.index("BEGIN IMMEDIATE"):]
    counted = next(
        i for i, s in enumerate(in_lock)
        if s.startswith("SELECT COUNT(*) FROM login_attempts")
    )
    inserted = next(
        i for i, s in enumerate(in_lock)
        if s.startswith("INSERT INTO login_attempts")
    )
    committed = in_lock.index("COMMIT")
    assert 0 < counted < inserted < committed, in_lock


def test_a_refused_attempt_never_takes_the_write_lock(conn):
    """The other half of the mechanism, and the reason the refused path is
    cheap: a flood of refusals costs one indexed read each and no write
    transaction at all. An implementation that opened BEGIN IMMEDIATE before
    deciding would rebuild, on the refusal path, exactly the amplification
    this control exists to remove."""
    for _ in range(THRESHOLD):
        assert auth.admit_login_attempt(conn, "k")[0] is True

    statements = []
    conn.set_trace_callback(statements.append)
    try:
        assert auth.admit_login_attempt(conn, "k") == (False, False)
    finally:
        conn.set_trace_callback(None)

    assert not any(s.startswith("BEGIN") for s in statements), statements
    assert not any("INSERT" in s for s in statements), statements
    assert not any("DELETE" in s for s in statements), statements


# --- the audit log distinguishes throttled from failed -----------------------


def test_the_audit_log_distinguishes_throttled_from_failed(
    admin_app, admin_client
):
    """One row per lockout, not one per refused packet.

    The crossing is audited exactly once — on the attempt that brings the
    client to the threshold and then fails. Refusals after it write nothing,
    on purpose: an unbounded flood of throttled rows would be a write per
    request (the amplification the refusal exists to remove) and would trim
    the newest AUDIT_KEEP window past the evidence of the attack it was
    recording.
    """
    for _ in range(THRESHOLD):
        login_from(admin_client, CLIENT, password="väärä")

    events = audit_events(admin_app)
    failed = [e for e in events if e.startswith("login failed")]
    throttled = [e for e in events if e.startswith("login throttled")]
    assert len(failed) == THRESHOLD
    assert throttled == [f"login throttled client_key={CLIENT}"]

    for _ in range(10):
        login_from(admin_client, CLIENT, password="väärä")

    events = audit_events(admin_app)
    assert len([e for e in events if e.startswith("login failed")]) == THRESHOLD
    assert len([e for e in events if e.startswith("login throttled")]) == 1


# --- the owner's escapes, each in its true scope -----------------------------


def test_a_successful_login_clears_the_counter(
    admin_app, admin_client, monkeypatch
):
    """BELOW the threshold only — which is the only place the clearing exists.

    Four typos and then the right password must not leave the owner one typo
    from a lockout, so the success wipes the key's rows, including the one
    the successful attempt itself inserted. Four more failures afterwards are
    therefore all still EVALUATED, which is what the hash counter shows.

    It deliberately does NOT claim that a success ends a lockout. Once the
    threshold is crossed the refusal is decided before the password is looked
    at, so this clearing is unreachable and a correct password does not get
    the owner in — obligation 1 proves exactly that, and the window or
    login-unlock is the way out.
    """
    calls = hash_calls(monkeypatch)

    for _ in range(THRESHOLD - 1):
        assert (
            login_from(admin_client, CLIENT, password="väärä").status_code
            == 200
        )
    assert len(calls) == THRESHOLD - 1

    success = login_from(admin_client, CLIENT)

    assert success.status_code == 302
    assert "Set-Cookie" in success.headers
    assert attempt_count(admin_app, CLIENT) == 0  # a genuinely clean slate

    for i in range(THRESHOLD - 1):
        assert (
            login_from(admin_client, CLIENT, password="väärä").status_code
            == 200
        )
        assert len(calls) == THRESHOLD + 1 + i  # still evaluated, not refused


def test_the_window_slides(admin_app, admin_client, monkeypatch):
    """The owner's only in-band relief, and the bound the fifteen-minute
    window rests on."""
    calls = hash_calls(monkeypatch)
    for _ in range(THRESHOLD):
        login_from(admin_client, CLIENT, password="väärä")
    assert login_from(admin_client, CLIENT).status_code == 200
    assert len(calls) == THRESHOLD  # the last one was refused

    c = app_conn(admin_app)
    try:
        rewind_login_attempts(c, auth.LOGIN_FAILURE_WINDOW + 1)
    finally:
        c.close()

    response = login_from(admin_client, CLIENT)

    assert response.status_code == 302
    assert "Set-Cookie" in response.headers
    assert len(calls) == THRESHOLD + 1  # evaluated again


def test_login_unlock_clears_a_lockout(admin_app, admin_client):
    """The out-of-band escape, without which "wait fifteen minutes" is the
    only answer a locked-out owner gets. Driven through the real route and
    the real CLI runner, the idiom the admin-create and admin-reset-password
    tests use."""
    for _ in range(THRESHOLD):
        login_from(admin_client, CLIENT, password="väärä")
    refused = login_from(admin_client, CLIENT)
    assert refused.status_code == 200
    assert "Set-Cookie" not in refused.headers

    result = admin_app.test_cli_runner().invoke(args=["login-unlock"])

    assert result.exit_code == 0, result.output
    assert str(THRESHOLD) in result.output
    assert attempt_count(admin_app, CLIENT) == 0

    response = login_from(admin_client, CLIENT)

    assert response.status_code == 302
    assert "Set-Cookie" in response.headers


def test_login_unlock_on_an_untouched_install_clears_nothing(app):
    """The command is honest when there is nothing to clear, so an owner who
    runs it speculatively is not told a lockout was lifted."""
    result = app.test_cli_runner().invoke(args=["login-unlock"])
    assert result.exit_code == 0, result.output
    assert "cleared 0 " in result.output


# --- the limiter itself, against a real temp-file connection -----------------


def test_admit_login_attempt_records_one_row_per_admitted_attempt(conn):
    assert auth.admit_login_attempt(conn, "k") == (True, False)
    assert len(attempt_rows(conn, "k")) == 1
    for _ in range(THRESHOLD - 2):
        assert auth.admit_login_attempt(conn, "k") == (True, False)
    assert len(attempt_rows(conn, "k")) == THRESHOLD - 1


def test_the_threshold_attempt_reports_the_crossing_once(conn):
    crossings = [
        auth.admit_login_attempt(conn, "k")[1] for _ in range(THRESHOLD)
    ]
    assert crossings == [False] * (THRESHOLD - 1) + [True]
    # And a refusal is not a second crossing, so the audit row cannot repeat.
    assert auth.admit_login_attempt(conn, "k") == (False, False)


def test_a_refused_attempt_writes_no_row(conn):
    for _ in range(THRESHOLD):
        auth.admit_login_attempt(conn, "k")
    before = [tuple(row) for row in attempt_rows(conn, "k")]

    for _ in range(10):
        assert auth.admit_login_attempt(conn, "k") == (False, False)

    assert [tuple(row) for row in attempt_rows(conn, "k")] == before


def test_one_keys_attempts_do_not_count_against_another(conn):
    for _ in range(THRESHOLD):
        auth.admit_login_attempt(conn, "k")
    assert auth.admit_login_attempt(conn, "k") == (False, False)

    assert auth.admit_login_attempt(conn, "toinen") == (True, False)


def test_attempts_older_than_the_window_stop_counting(conn):
    for _ in range(THRESHOLD):
        auth.admit_login_attempt(conn, "k")
    assert auth.admit_login_attempt(conn, "k") == (False, False)

    rewind_login_attempts(conn, auth.LOGIN_FAILURE_WINDOW + 1)

    assert auth.admit_login_attempt(conn, "k") == (True, False)
    # The stale rows are pruned by the admitted attempt, so the table does not
    # grow without bound.
    assert len(attempt_rows(conn, "k")) == 1


def test_clear_login_attempts_frees_only_that_key(conn):
    for _ in range(THRESHOLD - 1):
        auth.admit_login_attempt(conn, "k")
        auth.admit_login_attempt(conn, "toinen")

    auth.clear_login_attempts(conn, "k")

    assert attempt_rows(conn, "k") == []
    assert len(attempt_rows(conn, "toinen")) == THRESHOLD - 1
    assert auth.admit_login_attempt(conn, "k") == (True, False)


def test_clear_all_login_attempts_empties_the_table_and_counts(conn):
    for _ in range(THRESHOLD):
        auth.admit_login_attempt(conn, "k")
    auth.admit_login_attempt(conn, "toinen")

    removed = auth.clear_all_login_attempts(conn)

    assert removed == THRESHOLD + 1
    (total,) = conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()
    assert total == 0


def test_a_keyless_client_gets_a_bucket_rather_than_no_limit(conn):
    """bucket_key's fail-CLOSED rule, exercised through the limiter.

    client_key() returns request.remote_addr unchanged, which can be None. A
    None key would violate login_attempts.client_key NOT NULL; falling back
    to "no limit at all" would be worse. It buckets instead.
    """
    assert auth.bucket_key(None) == ""
    assert auth.bucket_key("203.0.113.7") == "203.0.113.7"
    for _ in range(THRESHOLD):
        assert auth.admit_login_attempt(conn, None)[0] is True

    assert auth.admit_login_attempt(conn, None) == (False, False)
    assert len(attempt_rows(conn, "")) == THRESHOLD


# --- the shared client key ---------------------------------------------------


def test_client_key_ignores_forwarded_for_when_no_proxy_is_trusted(
    app, monkeypatch
):
    """The same rule the contact form has always had, now in app/auth.py so
    both limiters read one implementation. Without TRUSTED_PROXY the header
    is worthless, so a spoofed value cannot mint a fresh window on either
    route."""
    monkeypatch.delenv("TRUSTED_PROXY", raising=False)
    with app.test_request_context(
        "/",
        headers={"X-Forwarded-For": "203.0.113.1"},
        environ_base={"REMOTE_ADDR": OTHER_CLIENT},
    ):
        assert auth.client_key() == OTHER_CLIENT


def test_client_key_takes_the_rightmost_forwarded_entry_when_trusted(
    app, monkeypatch
):
    """With TRUSTED_PROXY set the rightmost entry is the one our own proxy
    appended; everything left of it is client-supplied and forgeable."""
    monkeypatch.setenv("TRUSTED_PROXY", "1")
    with app.test_request_context(
        "/",
        headers={"X-Forwarded-For": f"203.0.113.1, {OTHER_CLIENT}"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    ):
        assert auth.client_key() == OTHER_CLIENT


def test_client_key_falls_back_when_the_trusted_header_is_empty(
    app, monkeypatch
):
    """An empty X-Forwarded-For is not a client key: client_key() drops empty
    entries and falls back to remote_addr, so bucket_key never has to rescue
    a stray "" that arrived in a header."""
    monkeypatch.setenv("TRUSTED_PROXY", "1")
    with app.test_request_context(
        "/",
        headers={"X-Forwarded-For": " , "},
        environ_base={"REMOTE_ADDR": OTHER_CLIENT},
    ):
        assert auth.client_key() == OTHER_CLIENT


def test_the_login_limiter_keys_on_the_trusted_forwarded_entry(
    admin_app, admin_client, monkeypatch
):
    """The login route really does go through that shared key: behind a
    trusted proxy, two requests from the same remote_addr but different
    rightmost entries are two different clients."""
    monkeypatch.setenv("TRUSTED_PROXY", "1")
    for _ in range(THRESHOLD):
        admin_client.post(
            "/yllapito/kirjaudu",
            data={"kayttajatunnus": USERNAME, "salasana": "väärä"},
            headers={"X-Forwarded-For": f"198.51.100.1, {CLIENT}"},
        )
    assert attempt_count(admin_app, CLIENT) == THRESHOLD

    response = admin_client.post(
        "/yllapito/kirjaudu",
        data={"kayttajatunnus": USERNAME, "salasana": PASSWORD},
        headers={"X-Forwarded-For": f"198.51.100.1, {OTHER_CLIENT}"},
    )

    assert response.status_code == 302  # a different client, not locked out
    assert "Set-Cookie" in response.headers


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


# --- the second factor (LLM-COP-39): the flow proofs -------------------------
#
# tests/test_totp.py carries the whole correctness burden for the ARITHMETIC,
# against RFC 4226 and RFC 6238's published vectors. Nothing below re-proves
# it: every test here computes its expected code with app/totp.py itself, so
# these can only prove the FLOW — that the route, the store and the limiter
# behave as the second factor's six hazards demand. Saying which test is
# load-bearing for what is the difference between a proof and a rigged
# fixture.
#
# Everything runs against real temp-file databases and the real routes. Two
# injections, both of which observe real work rather than replacing it:
# app.totp._now (the module's own documented seam, so a step boundary is a
# decision rather than a race) and, in enrol() only, app.totp.random_secret —
# see that helper for why a CliRunner leaves no other honest option.

# A step whose epoch is safely in the PAST. It has to be: the restart proof
# runs a child interpreter on the real clock, and a FROZEN in the future
# would leave that child's code below the step enrolment already spent, so it
# would be refused by the REPLAY rule while the test claimed to be about the
# rate limiter.
ENROL_AT = (1_700_000_000 // totp.TOTP_PERIOD) * totp.TOTP_PERIOD + 15

# One period on. The enrolling code is spent at enrolment (admin-totp-enable
# stores its step in totp_last_step, deliberately), so a flow test that logs
# in at the enrolment step is refused by the replay rule and proves nothing
# about the thing it names.
LOGIN_AT = ENROL_AT + totp.TOTP_PERIOD

# Drawn once, by the real random_secret, at import.
ENROL_SECRET = totp.random_secret()

# The seventeen rules require_admin marks today. The sweep below reads the
# live url_map, so a route added later is covered without anyone remembering
# — but the set is pinned as well as swept, because a route that silently
# LOSES its gate would otherwise just shrink the sweep and stay green.
GATED_PATHS = {
    "/api/kuvat",
    "/api/kuvat/<digest>",
    "/api/publish",
    "/api/sections",
    "/api/sections/<int:section_id>/draft",
    "/api/sections/<int:section_id>/restore",
    "/api/sections/<int:section_id>/state",
    "/api/sections/order",
    "/muokkaa",
    "/muokkaa/esikatselu",
    "/muokkaa/osiot",
    "/muokkaa/osiot/rivi/<int:section_id>",
    "/muokkaa/sivu",
    "/yllapito/alustus",
    "/yllapito/kirjaudu-ulos",
    "/yllapito/viestit",
    "/yllapito/viestit/<int:message_id>/poista",
}


def freeze_totp(monkeypatch, at):
    """Pin app/totp.py's clock seam, so a step boundary cannot be a race."""
    monkeypatch.setattr(totp, "_now", lambda: at)


def code_for(at, offset=0, secret=ENROL_SECRET):
    """The account's own code for the step containing `at`, plus `offset`."""
    return totp.hotp(totp.decode_secret(secret), totp.step_for(at) + offset)


def wrong_code(at=None, secret=ENROL_SECRET):
    """A code that is genuinely this account's, five steps away.

    Deliberately not "000000": a literal is only PROBABLY wrong (one in a
    million per candidate step), and a test whose meaning depends on luck is
    a test that will one day go red for the wrong reason. Five steps is
    outside TOTP_SKEW by four, so this is deterministically refused.
    """
    return code_for(time.time() if at is None else at, 5, secret)


def recovery_codes_in(output):
    """The recovery codes admin-totp-enable printed, by their pinned shape."""
    return [
        line.strip()
        for line in output.splitlines()
        if auth.RECOVERY_PATTERN.match(line.strip())
    ]


def enrol(app, monkeypatch, at=ENROL_AT, secret=ENROL_SECRET):
    """Turn the factor on through the REAL admin-totp-enable command.

    Returns the ten recovery codes it printed.

    The one injection: totp.random_secret answers a secret this module drew
    itself, with the real function, at import. A CliRunner has to know the
    command's whole input before the command runs, and the operator's code is
    computed from a secret the command has not generated yet — so a test that
    faked nothing could not answer the prompt at all. Everything else is the
    real command: it verifies with the real accepted_step (a wrong code still
    fails it — see the enrolment test below), writes the real rows and issues
    real recovery codes. The randomness of random_secret is proved in
    tests/test_totp.py, where it is the subject.
    """
    monkeypatch.setattr(totp, "random_secret", lambda: secret)
    freeze_totp(monkeypatch, at)
    result = app.test_cli_runner().invoke(
        args=["admin-totp-enable"], input=f"{code_for(at)}\n"
    )
    assert result.exit_code == 0, result.output
    assert secret in result.output  # the operator really was shown it
    codes = recovery_codes_in(result.output)
    assert len(codes) == auth.RECOVERY_CODE_COUNT, result.output
    return codes


def totp_row(app):
    c = app_conn(app)
    try:
        return c.execute("SELECT * FROM admin_user").fetchone()
    finally:
        c.close()


def table_rows(app, table):
    c = app_conn(app)
    try:
        return c.execute(f"SELECT * FROM {table}").fetchall()
    finally:
        c.close()


def reset_last_step(app):
    """Put totp_last_step back to NULL, straight in the store.

    The skew sub-cases need this between them: without it, accepting a code
    at one step makes the NEXT sub-case fail by the REPLAY rule, and the
    assertion would prove nothing about the window it names.
    """
    c = app_conn(app)
    try:
        c.execute("UPDATE admin_user SET totp_last_step = NULL")
        c.commit()
    finally:
        c.close()


def clear_attempts(app):
    """Empty login_attempts, the way login-unlock does.

    Same reason as reset_last_step: a sub-case about the skew window must not
    be decided by the rate limiter instead.
    """
    c = app_conn(app)
    try:
        auth.clear_all_login_attempts(c)
    finally:
        c.close()


def pending_token_of(response):
    """The admin_pending cookie the password step set, or None."""
    jar = SimpleCookie()
    for header in response.headers.getlist("Set-Cookie"):
        jar.load(header)
    if auth.PENDING_COOKIE not in jar:
        return None
    return jar[auth.PENDING_COOKIE].value


def post_code(client, code, address=None):
    kwargs = {}
    if address is not None:
        kwargs["environ_base"] = {"REMOTE_ADDR": address}
    return client.post("/yllapito/koodi", data={"koodi": code}, **kwargs)


def pending_lookup(app, conn, token):
    """current_pending_login for a request carrying the pending cookie."""
    with app.test_request_context(
        "/", headers={"Cookie": f"{auth.PENDING_COOKIE}={token}"}
    ):
        return auth.current_pending_login(conn)


# --- hazard 1: the partial state is not a session ----------------------------


def gated_rules(app):
    """Every rule whose view carries require_admin's marker.

    __admin_gated__ and not hasattr(view, "__wrapped__"): the latter matches
    any functools.wraps decorator and would quietly include or exclude routes
    for reasons that have nothing to do with the gate.
    """
    return [
        rule
        for rule in app.url_map.iter_rules()
        if getattr(
            app.view_functions[rule.endpoint], "__admin_gated__", False
        )
    ]


def rule_requests(rule):
    """(method, path) for every method a rule really serves."""
    _host, path = rule.build({name: 1 for name in rule.arguments})
    return [
        (method, path)
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"})
    ]


def test_the_password_step_mints_nothing_a_session_cookie_could_carry(
    admin_app, monkeypatch
):
    """Hazard 1, the store side: a correct password writes no session.

    If the password step minted anything the sessions table holds, the second
    factor would be decorative whatever the sweep below said.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    client = admin_app.test_client()

    response = login(client)

    assert response.status_code == 200
    cookies = response.headers.getlist("Set-Cookie")
    assert not any(
        header.startswith(f"{auth.SESSION_COOKIE}=") for header in cookies
    ), cookies
    assert pending_token_of(response) is not None  # it did mint the half-state
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []
        assert len(c.execute("SELECT * FROM pending_logins").fetchall()) == 1
    finally:
        c.close()
    assert audit_events(admin_app)[-1] == (
        f"login password ok, code required username={USERNAME}"
    )


def test_the_pending_token_reaches_no_admin_route(admin_app, monkeypatch):
    """Hazard 1, swept and not sampled.

    Every gated rule in the live url_map, by every method it serves, twice:
    once with the pending token under its own cookie name, once with the SAME
    token presented as admin_session — because the token being useless is one
    claim and the cookie NAME being the only thing that saves us is another,
    and only the second probe can tell them apart. Never 200.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    token = pending_token_of(login(admin_app.test_client()))
    assert token is not None

    rules = gated_rules(admin_app)
    assert {rule.rule for rule in rules} == GATED_PATHS
    probed = 0
    for rule in rules:
        for method, path in rule_requests(rule):
            for name in (auth.PENDING_COOKIE, auth.SESSION_COOKIE):
                probe = admin_app.test_client()
                probe.set_cookie(name, token)
                response = probe.open(path, method=method)
                where = (method, path, name)
                assert response.status_code in (302, 401), where
                if response.status_code == 302:
                    location = urlparse(response.headers["Location"]).path
                    assert location == "/yllapito", where
                probed += 1

    assert probed == 2 * len(GATED_PATHS)  # every rule, both cookie names
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []  # and not one probe minted anything
    finally:
        c.close()


def test_the_password_step_answers_the_code_step(admin_app, monkeypatch):
    """The second state of the dialog: the code form, and nothing else.

    The password-show assertion is objection 6's companion. A test client
    never runs the toggle script, so it cannot observe the TypeError a code
    step with no #password-show would throw in a browser; what it CAN say is
    that the button and its script are not on this page at all.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)

    html = login(admin_app.test_client()).get_data(as_text=True)

    assert 'name="koodi"' in html
    assert 'name="salasana"' not in html
    assert 'name="pysy"' not in html
    assert "password-show" not in html
    # The shared chrome survives — same dialog, second step.
    assert "Ylläpitäjän kirjautuminen" in html
    assert element_text(html, "div", "login-dialog") is not None


# --- hazard 2: replay --------------------------------------------------------


def test_a_code_cannot_be_replayed_inside_its_own_step(
    admin_app, monkeypatch
):
    """Hazard 2, at the route, with the clock pinned.

    Both logins happen at the same frozen instant, so they are provably
    inside one 30-second window with no sleep and no wall-clock race. The
    six digits that just worked must not work again.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    code = code_for(LOGIN_AT)

    client = admin_app.test_client()
    assert login(client).status_code == 200
    first = post_code(client, code)
    assert first.status_code == 302
    c = app_conn(admin_app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()

    assert client.post("/yllapito/kirjaudu-ulos").status_code == 302

    replay = admin_app.test_client()
    assert login(replay).status_code == 200
    second = post_code(replay, code)

    assert second.status_code == 200
    assert LOGIN_ERROR in second.get_data(as_text=True)
    assert "Set-Cookie" not in second.headers
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []  # the logout emptied it and it stayed so
    finally:
        c.close()
    assert audit_events(admin_app)[-1] == (
        f"login failed (wrong code) username={USERNAME}"
    )


# --- hazard 3: the code step is rate-limited ---------------------------------


_CODE_RESTART_CHILD = """
import json
import sys
import time

from app import create_app, totp

app = create_app(instance_path=sys.argv[1])
secret, pending, address = sys.argv[2], sys.argv[3], sys.argv[4]
client = app.test_client()
client.set_cookie("admin_pending", pending)
code = totp.hotp(totp.decode_secret(secret), totp.step_for(time.time()))
response = client.post(
    "/yllapito/koodi",
    data={"koodi": code},
    environ_base={"REMOTE_ADDR": address},
)
print(json.dumps({
    "status": response.status_code,
    "cookie": "Set-Cookie" in response.headers,
}))
"""


def test_the_code_steps_refusal_survives_a_process_restart(
    tmp_path, monkeypatch
):
    """Hazard 3, in a genuinely new interpreter.

    The child holds everything a successful login needs — a VALID pending
    cookie minted by the real password step, the account's real secret, and
    a code it computes for its own real clock — so the only thing between it
    and a session is the limiter. That matters: "refused and set no cookie"
    is also what a request with no pending cookie gets, so a child without a
    cookie would pass this test with the limiter deleted.

    The discriminator is the LAST assertion pair, copied from
    test_the_refusal_survives_a_process_restart above: the attempt count is
    unmoved (the child was refused AT the gate and wrote no row), and then
    the very same cookie and a freshly computed code DO mint a session once
    login-unlock clears the counter. Without that positive control this test
    could not tell a durable limiter from a broken pending row.
    """
    instance = str(tmp_path / "instance")
    app = create_app(instance_path=instance)
    create_admin(app)
    enrol(app, monkeypatch)
    # Give the seam back: the child runs on the real clock, and so must the
    # parent's own probes from here on.
    monkeypatch.setattr(totp, "_now", time.time)

    client = app.test_client()
    first = client.post(
        "/yllapito/kirjaudu",
        data={"kayttajatunnus": USERNAME, "salasana": PASSWORD},
        environ_base={"REMOTE_ADDR": CLIENT},
    )
    assert first.status_code == 200
    token = pending_token_of(first)
    assert token is not None
    assert attempt_count(app, CLIENT) == 1

    for i in range(THRESHOLD - 1):
        response = post_code(client, wrong_code(), address=CLIENT)
        assert response.status_code == 200, i
    assert attempt_count(app, CLIENT) == THRESHOLD

    env = {k: v for k, v in os.environ.items() if k != "TRUSTED_PROXY"}
    env["PYTHONPATH"] = REPO_ROOT
    proc = subprocess.run(
        [sys.executable, "-c", _CODE_RESTART_CHILD, instance, ENROL_SECRET,
         token, CLIENT],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    report = proc.stdout + proc.stderr
    assert proc.returncode == 0, (
        f"the restarted interpreter exited {proc.returncode}\n{report}"
    )
    answer = json.loads(proc.stdout.strip().splitlines()[-1])
    assert answer == {"status": 200, "cookie": False}, report
    # The count it was refused on came off the disk, not out of this process,
    # and the refusal happened at the gate: no row was added for it.
    assert attempt_count(app, CLIENT) == THRESHOLD
    c = app_conn(app)
    try:
        assert session_rows(c) == []
    finally:
        c.close()

    # The positive control. Same cookie, same account, correct code — the
    # only thing that changed is the counter.
    assert (
        app.test_cli_runner().invoke(args=["login-unlock"]).exit_code == 0
    )
    unlocked = app.test_client()
    unlocked.set_cookie(auth.PENDING_COOKIE, token)
    response = post_code(unlocked, code_for(time.time()), address=CLIENT)
    assert response.status_code == 302, response.get_data(as_text=True)
    c = app_conn(app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()


def test_a_fresh_password_post_does_not_re_arm_the_code_step(
    admin_app, monkeypatch
):
    """Hazard 3's real hole: the guessing budget must not be refillable.

    An attacker who holds the password can post it again whenever they like.
    If the password step cleared login_attempts on the second-factor branch —
    as the one-step success path does, and as app/__init__.py did before this
    change — they would get unlimited guesses at six digits.

    Asserted on the ROW COUNT in login_attempts, through attempt_count's own
    connection, and not on the response: a response-only assertion stays
    green while the counter is reset, because a wrong code is answered the
    same way either way. That is why this test looks at the store.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    client = admin_app.test_client()

    def password_step():
        """The CORRECT password: a wrong one never reached
        clear_login_attempts even before this change, so it would prove
        nothing."""
        return client.post(
            "/yllapito/kirjaudu",
            data={"kayttajatunnus": USERNAME, "salasana": PASSWORD},
            environ_base={"REMOTE_ADDR": CLIENT},
        )

    def guess():
        return post_code(client, wrong_code(LOGIN_AT), address=CLIENT)

    assert password_step().status_code == 200
    assert attempt_count(admin_app, CLIENT) == 1
    assert guess().status_code == 200
    assert attempt_count(admin_app, CLIENT) == 2

    assert password_step().status_code == 200
    # THE assertion: the counter ROSE. It did not reset, and it did not stand
    # still. This is the line that goes red if clear_login_attempts is left
    # on the second-factor branch.
    assert attempt_count(admin_app, CLIENT) == 3

    assert guess().status_code == 200
    assert attempt_count(admin_app, CLIENT) == 4
    assert password_step().status_code == 200
    assert attempt_count(admin_app, CLIENT) == THRESHOLD

    # The budget is spent, so the next code is refused whatever it says —
    # and this one is CORRECT.
    refused = post_code(client, code_for(LOGIN_AT), address=CLIENT)
    assert refused.status_code == 200
    assert LOGIN_ERROR in refused.get_data(as_text=True)
    assert "Set-Cookie" not in refused.headers
    assert attempt_count(admin_app, CLIENT) == THRESHOLD  # refused at the gate
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []
    finally:
        c.close()


# --- hazard 4: clock skew ----------------------------------------------------


def test_the_code_step_accepts_one_step_either_side_and_no_wider(
    admin_app, monkeypatch
):
    """Hazard 4, with the order stated and the other two rules held off.

    Between every sub-case, totp_last_step goes back to NULL and
    login_attempts is emptied. Without the first, accepting +1 makes a later
    -1 fail by REPLAY and the test would go red with a perfectly correct
    window; without the second, the fifth request would be refused by the
    RATE LIMITER. Either way the assertion would be about something other
    than the window it names.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    sessions = 0

    for offset, accepted in ((-1, True), (1, True), (-2, False), (2, False)):
        reset_last_step(admin_app)
        clear_attempts(admin_app)
        client = admin_app.test_client()
        assert login(client).status_code == 200, offset

        response = post_code(client, code_for(LOGIN_AT, offset))

        if accepted:
            assert response.status_code == 302, offset
            sessions += 1
            assert totp_row(admin_app)["totp_last_step"] == (
                totp.step_for(LOGIN_AT) + offset
            ), offset
        else:
            assert response.status_code == 200, offset
            assert LOGIN_ERROR in response.get_data(as_text=True), offset
            assert "Set-Cookie" not in response.headers, offset
            assert totp_row(admin_app)["totp_last_step"] is None, offset
        c = app_conn(admin_app)
        try:
            assert len(session_rows(c)) == sessions, offset
        finally:
            c.close()

    # The fifth sub-case, deliberately WITHOUT the reset: the replay rule
    # seen from the skew test's side, at the edge of the window. This is the
    # one place the two rules are allowed to interact, and it is named.
    reset_last_step(admin_app)
    clear_attempts(admin_app)
    edge = admin_app.test_client()
    assert login(edge).status_code == 200
    assert post_code(edge, code_for(LOGIN_AT, -1)).status_code == 302
    again = admin_app.test_client()
    assert login(again).status_code == 200
    assert post_code(again, code_for(LOGIN_AT, -1)).status_code == 200


# --- hazard 5: recovery ------------------------------------------------------


def test_a_recovery_code_signs_in_once_and_never_again(
    admin_app, monkeypatch
):
    """Hazard 5: single use, proved against a second code that still works.

    The control matters. "The second attempt is refused" is also what a
    broken recovery path answers, so an unused sibling code is spent
    immediately afterwards: the refusal was single-use, not the feature
    falling over.
    """
    codes = enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    spent_step = totp_row(admin_app)["totp_last_step"]
    assert spent_step is not None  # enrolment spent its own code

    client = admin_app.test_client()
    assert login(client).status_code == 200
    first = post_code(client, codes[0])

    assert first.status_code == 302
    c = app_conn(admin_app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()
    # A recovery code says nothing about a time step, so the TOTP replay
    # guard must be exactly where enrolment left it.
    assert totp_row(admin_app)["totp_last_step"] == spent_step
    used = [
        row
        for row in table_rows(admin_app, "recovery_codes")
        if row["used_at"] is not None
    ]
    assert len(used) == 1
    assert audit_events(admin_app)[-1] == (
        f"login ok (recovery code) username={USERNAME}"
    )

    assert client.post("/yllapito/kirjaudu-ulos").status_code == 302
    second = admin_app.test_client()
    assert login(second).status_code == 200

    refused = post_code(second, codes[0])
    assert refused.status_code == 200
    assert LOGIN_ERROR in refused.get_data(as_text=True)
    c = app_conn(admin_app)
    try:
        assert session_rows(c) == []
    finally:
        c.close()

    # The control: a different, unused code — in upper case, because they
    # are typed back by hand — still signs in on the same pending row.
    ok = post_code(second, codes[1].upper())
    assert ok.status_code == 302
    c = app_conn(admin_app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()


def test_admin_totp_disable_returns_the_account_to_one_step_login(
    admin_app, monkeypatch
):
    """Hazard 5's backstop: the way back in, and no half-state left behind."""
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    stale = admin_app.test_client()
    assert login(stale).status_code == 200  # a half-authenticated token
    assert len(table_rows(admin_app, "pending_logins")) == 1

    result = admin_app.test_cli_runner().invoke(args=["admin-totp-disable"])

    assert result.exit_code == 0, result.output
    row = totp_row(admin_app)
    assert row["totp_enabled"] == 0
    assert row["totp_secret"] is None
    assert row["totp_last_step"] is None
    assert table_rows(admin_app, "recovery_codes") == []
    assert table_rows(admin_app, "pending_logins") == []

    # The token minted a moment before is dead, not merely pointless.
    assert post_code(stale, code_for(LOGIN_AT)).status_code == 200

    # And conftest's stock login() — the one the whole non-2FA suite uses —
    # is a WHOLE login again, in one step.
    client = admin_app.test_client()
    response = login(client)
    assert response.status_code == 302
    assert f"{auth.SESSION_COOKIE}=" in response.headers["Set-Cookie"]
    c = app_conn(admin_app)
    try:
        assert len(session_rows(c)) == 1
    finally:
        c.close()


# --- enrolment ---------------------------------------------------------------


def test_admin_totp_enable_refuses_a_code_that_does_not_verify(
    admin_app, monkeypatch
):
    """One verified code or nothing: an account left holding a secret it
    cannot prove is a lockout dressed up as an enrolment."""
    monkeypatch.setattr(totp, "random_secret", lambda: ENROL_SECRET)
    freeze_totp(monkeypatch, ENROL_AT)

    result = admin_app.test_cli_runner().invoke(
        args=["admin-totp-enable"], input=f"{wrong_code(ENROL_AT)}\n"
    )

    assert result.exit_code != 0
    row = totp_row(admin_app)
    assert row["totp_enabled"] == 0
    assert row["totp_secret"] is None
    assert row["totp_last_step"] is None
    assert table_rows(admin_app, "recovery_codes") == []
    # Nothing was half-written: the account still signs in the way it did
    # before the operator typed the command.
    assert login(admin_app.test_client()).status_code == 302


def test_admin_totp_enable_writes_the_secret_and_no_plaintext_code(
    admin_app, monkeypatch
):
    """The success path, and the at-rest caveat asserted rather than promised.

    The recovery codes are NOT in the database file — only werkzeug hashes.
    The secret IS, in plaintext, because verifying a code needs it: that is
    the caveat README.md states, and pinning it here means the README cannot
    quietly become a lie in either direction.
    """
    codes = enrol(admin_app, monkeypatch)

    row = totp_row(admin_app)
    assert row["totp_enabled"] == 1
    assert row["totp_secret"] == ENROL_SECRET
    assert row["totp_last_step"] == totp.step_for(ENROL_AT)
    with open(admin_app.config["DATABASE"], "rb") as handle:
        blob = handle.read()
    for code in codes:
        assert code.encode() not in blob, code
    assert ENROL_SECRET.encode() in blob  # the documented at-rest caveat

    # And it refuses to re-enrol over a live enrolment, which would throw
    # away ten recovery codes the owner may be relying on.
    again = admin_app.test_cli_runner().invoke(
        args=["admin-totp-enable"], input="123456\n"
    )
    assert again.exit_code != 0
    assert "admin-totp-disable" in again.output
    assert totp_row(admin_app)["totp_secret"] == ENROL_SECRET


# --- the seams the two steps stand on ----------------------------------------


def test_a_recovery_code_can_never_look_like_a_totp_code(conn):
    """The format closes its own loop.

    koodi() only tries the recovery path when the input is NOT six ASCII
    digits. Without this test the two halves of that decision are coupled by
    intention alone, and a future change to the code format would silently
    kill the lockout backstop while the comment about CPU amplification still
    read fine.
    """
    drawn = [auth._recovery_code() for _ in range(200)]
    for code in drawn:
        assert auth.RECOVERY_PATTERN.match(code), code
        assert not app_module._looks_like_a_totp_code(code), code
    assert len(set(drawn)) == 200  # a constant would pass everything else

    issued = auth.issue_recovery_codes(conn, 1)
    assert len(issued) == auth.RECOVERY_CODE_COUNT
    stored = conn.execute("SELECT * FROM recovery_codes").fetchall()
    for code in issued:
        assert auth.RECOVERY_PATTERN.match(code), code
        assert not app_module._looks_like_a_totp_code(code), code
        assert not any(code in str(tuple(row)) for row in stored), code


def test_a_non_ascii_code_is_refused_the_way_a_wrong_one_is(
    admin_app, monkeypatch
):
    """A typo is answered in the same bytes as a wrong code, not a 500.

    hmac.compare_digest raises TypeError on a non-ASCII str, and the field
    is labelled Kertakäyttökoodi for a Finnish audience — ä is one key away
    from a digit, so this is an ordinary typo rather than a crafted attack.
    accepted_step refuses it instead, which is what keeps the route's own
    invariant true: a wrong code, a missing pending cookie and a throttled
    request answer identically. A 500 is not 200.

    The fullwidth and Arabic-Indic rows are the subtle half. str.isdigit()
    is True for both, so they are exactly the inputs a shape check written
    with isdigit() alone would wave through — and they reach compare_digest
    before _looks_like_a_totp_code ever sees them.
    """
    enrol(admin_app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)

    for code in ("12345ä", "１２３４５６", "١٢٣٤٥٦"):
        reset_last_step(admin_app)
        clear_attempts(admin_app)
        client = admin_app.test_client()
        assert login(client).status_code == 200, code

        response = post_code(client, code)

        assert response.status_code == 200, code
        assert LOGIN_ERROR in response.get_data(as_text=True), code
        assert "Set-Cookie" not in response.headers, code
        c = app_conn(admin_app)
        try:
            assert session_rows(c) == [], code
        finally:
            c.close()


def test_mint_pending_leaves_one_live_row_per_account(app):
    """One live pending row is an invariant, not a hope.

    GET /yllapito renders the password step even mid-flow, so an owner who
    reloads and re-posts would otherwise mint a second redeemable token, and
    current_pending_login only ever deletes the one it read.
    """
    c = app_conn(app)
    try:
        first = auth.mint_pending(c, 1, False)
        second = auth.mint_pending(c, 1, True)

        rows = c.execute(
            "SELECT * FROM pending_logins WHERE user_id = 1"
        ).fetchall()
        assert len(rows) == 1
        # Only sha256(token) is stored — mint_session's discipline.
        assert first not in str(tuple(rows[0]))
        assert second not in str(tuple(rows[0]))
        assert rows[0]["token_hash"] == hashlib.sha256(
            second.encode()
        ).hexdigest()

        assert pending_lookup(app, c, first) is None  # the older token is dead
        live = pending_lookup(app, c, second)
        assert live is not None
        assert live["remember"] == 1  # remember rides on the row, not the form
    finally:
        c.close()


def test_an_expired_pending_row_is_deleted_not_merely_refused(app):
    """current_admin_session's discipline, kept on the half-state too: the
    token can never validate again, not merely fail on this request."""
    c = app_conn(app)
    try:
        token = auth.mint_pending(c, 1, False)
        c.execute(
            "UPDATE pending_logins SET expires_at = expires_at - ?",
            (auth.PENDING_LIFETIME + 60,),
        )
        c.commit()

        assert pending_lookup(app, c, token) is None
        assert c.execute("SELECT * FROM pending_logins").fetchall() == []
    finally:
        c.close()
