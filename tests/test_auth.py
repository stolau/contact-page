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
from app import LOGIN_ERROR, auth, create_app, messages
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
