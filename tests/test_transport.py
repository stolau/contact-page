"""The transport gate: `Secure` on the login cookies, and HSTS
(LLM-COP-35 item 1).

WHAT IS UNDER TEST, and it is one switch. `app/security.py`'s
`https_only()` reads the `HTTPS_ONLY` environment variable — the operator's
statement that TLS is terminated in front of this app — and two consumers
read it on every request: the five cookie calls in `app/__init__.py`'s
login flow, and the `after_request` that sends
`Strict-Transport-Security`. Every row below drives a REAL route through a
real test client against a real temp-file database and reads the BYTES of
the response, because the emitted header is the whole product here.

TWO MODES, EVERYWHERE. Almost every row is parametrized over `MODES`:
`off` (the variable unset, the default, and what every other test file in
this suite runs under) and `on` (`HTTPS_ONLY=1`). A row that only measured
the ON mode would not notice a gate welded open, and a row that only
measured OFF would not notice one welded shut — the mutation half of this
change's proof depends on having both.

WHAT THESE ROWS CANNOT PROVE, said rather than implied:

  * **No browser here ever refuses a `Secure` cookie over plain HTTP.** A
    werkzeug test client does not filter on the flag at all
    (`werkzeug.test.Cookie._matches_request` ignores `secure`), and real
    Chrome treats loopback as a trustworthy origin — see
    `tests/browser/test_browser_transport.py`. So what is proved is that
    the app EMITS the flag under the stated condition and not otherwise.
  * **No browser here ever acts on HSTS.** RFC 6797 §8.1.1 excludes
    IP-literal hosts, so a loopback client would ignore the header even if
    it were a browser. Again: emission, under a stated condition.
  * **The forgery rows close no attack.** See their own docstring.

The two-step (TOTP) rows reach the second factor through
`tests/test_auth.py`'s real helpers — `enrol` runs the actual
`admin-totp-enable` command — rather than inventing a second harness, so
nothing here fakes a login in order to look at its cookie.
"""

import io
import os
from http.cookies import SimpleCookie

import pytest

from app import auth, security
from tests import conftest
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    create_admin,
    login,
)
from tests.test_auth import (
    LOGIN_AT,
    code_for,
    enrol,
    freeze_totp,
    post_code,
)
from tests.test_security_headers import HTML_ROUTES, png_bytes, row_id

# --- the two modes ---------------------------------------------------------

HSTS = "Strict-Transport-Security"

# (the value to put in the environment, whether Secure/HSTS is expected).
# `None` means the variable is not in the environment at all, which is the
# state tests/conftest.py's scrub guarantees and the state every other
# file in this suite measures.
MODES = (
    pytest.param(None, False, id="off"),
    pytest.param("1", True, id="on"),
)

# The three headers a proxy — or anybody at all — might send to claim the
# connection is already TLS. See the forgery rows at the bottom.
FORGED_TLS_HEADERS = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-Ssl": "on",
    "Forwarded": "proto=https",
}


def set_mode(monkeypatch, value):
    """Put the process into one of the two modes for one test.

    `monkeypatch` is function-scoped, so this is undone afterwards; and
    `https_only()` reads the environment PER CALL, so setting it here —
    after the app was built by the `app` fixture — is enough. That is the
    same property `tests/browser/test_browser_transport.py` leans on
    against an already-running server.
    """
    if value is None:
        monkeypatch.delenv("HTTPS_ONLY", raising=False)
    else:
        monkeypatch.setenv("HTTPS_ONLY", value)


def morsels(response):
    """Every `Set-Cookie` header on a response, parsed, keyed by name.

    `response.headers.getlist`, never `response.headers["Set-Cookie"]`:
    `POST /yllapito/koodi` emits TWO of them on success (the session it
    mints and the pending half-state it deletes), and reading only the
    first would silently measure whichever one werkzeug happened to put
    there. `tests/test_auth.py`'s `pending_token_of` and
    `session_token_of` do the same multi-header load for the same reason.
    """
    jar = SimpleCookie()
    for header in response.headers.getlist("Set-Cookie"):
        jar.load(header)
    return jar


def assert_cookie_shape(morsel, expect_secure):
    """The one rule all five cookie calls in app/__init__.py read.

    `HttpOnly` and `SameSite=Lax` are asserted in BOTH modes, not only in
    the one under test: they are unconditional, and the likeliest way to
    break this change is to add `secure=` while dropping one of them.
    """
    assert bool(morsel["secure"]) is expect_secure
    assert morsel["httponly"], "HttpOnly is unconditional and went missing"
    assert morsel["samesite"] == "Lax"


def two_step_client(app, monkeypatch):
    """An admin with the second factor really enrolled, and a client.

    `enrol` invokes the real `admin-totp-enable` command; the clock is
    then frozen one period on, at `LOGIN_AT`, because the enrolling code
    is spent at enrolment (see `tests/test_auth.py`'s constants).
    """
    create_admin(app)
    enrol(app, monkeypatch)
    freeze_totp(monkeypatch, LOGIN_AT)
    return app.test_client()


def uploaded_image_ref(admin):
    """A real PNG through the real POST /api/kuvat, returning its digest."""
    return admin.post(
        "/api/kuvat",
        data={"kuva": (io.BytesIO(png_bytes()), "kuva.png")},
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    ).get_json()["ref"]


# === step 1 — the two functions, and the values they answer ================


@pytest.mark.parametrize(
    "value,expected",
    (
        pytest.param(None, False, id="unset"),
        pytest.param("", False, id="empty"),
        pytest.param("1", True, id="one"),
    ),
)
def test_https_only_answers_the_environment(monkeypatch, value, expected):
    """Unset is off, EMPTY is off, and a value is on.

    The empty row is the one with teeth. An `EnvironmentFile` line left as
    `HTTPS_ONLY=` means the operator has not set it — the same rule
    `_data_path` states in app/__init__.py — and the obvious
    `"HTTPS_ONLY" in os.environ` would read it as on, putting a
    plain-HTTP deployment into a mode where the login cookie never comes
    back. This row is what forbids that spelling.
    """
    set_mode(monkeypatch, value)

    assert security.https_only() is expected


def test_the_hsts_value_is_one_day_and_nothing_else():
    """`max-age=86400`, byte-exact, with no includeSubDomains, no preload.

    Pinned byte-exact so raising the max-age is a deliberate act with a
    test to edit, not a drive-by — HSTS is remembered CLIENT-side and a
    year-long pin over a certificate nobody can renew is a year-long
    outage. The two absent directives are asserted by name rather than by
    comparing the whole string twice: they are whole-domain claims this
    app is not entitled to make, and this is what notices if someone adds
    one without touching the value.
    """
    value = security.strict_transport_security()

    assert value == "max-age=86400"
    assert value == f"max-age={security.HSTS_MAX_AGE}"
    assert "includeSubDomains" not in value
    assert "preload" not in value


# === step 5 — the guard on the suite's own environment =====================


def test_the_suite_is_not_running_in_the_https_mode():
    """No ambient `HTTPS_ONLY`, or every OFF row here is a lie.

    `app/security.py` reads the variable per request, so a developer or CI
    runner with it exported would put the WHOLE suite into the ON mode:
    every cookie `Secure`, every response carrying HSTS, and every
    assertion about the default behaviour red for a reason that is about
    the shell rather than about the code. `tests/conftest.py`'s
    session-scoped `_no_ambient_environment` deletes it; this is that
    scrub, observed.

    WHAT IT DOES NOT CATCH, plainly: on a machine where nobody exported
    the variable, deleting the scrub leaves this row green. That is
    exactly why the next row exists.
    """
    assert os.environ.get("HTTPS_ONLY") is None


def test_the_ambient_scrub_still_names_https_only():
    """The scrub's membership, which is machine-independent.

    The row above is a coincidence on most machines; this one is red
    wherever the name is dropped from the guard, exported or not. That is
    what turns "remember to scrub it" from a protocol somebody has to
    remember into something CI says out loud.
    """
    assert "HTTPS_ONLY" in conftest._AMBIENT_NAMES


# === step 2 — the three cookies the login flow WRITES ======================


@pytest.mark.parametrize("value,expect_secure", MODES)
def test_the_one_step_login_cookie(app, monkeypatch, value, expect_secure):
    """`admin_session` from POST /yllapito/kirjaudu, no second factor."""
    create_admin(app)
    set_mode(monkeypatch, value)

    response = login(app.test_client())

    assert response.status_code == 302, response.get_data(as_text=True)
    assert_cookie_shape(morsels(response)[auth.SESSION_COOKIE], expect_secure)


@pytest.mark.parametrize("value,expect_secure", MODES)
def test_the_pending_cookie_of_the_totp_half_state(
    app, monkeypatch, value, expect_secure
):
    """`admin_pending` — the half-authenticated state between the two steps.

    It is the shortest-lived of the three and the easiest to forget, which
    is precisely why it is measured separately: it carries a token that
    completes a login, so an operator who set `HTTPS_ONLY` and got two
    `Secure` cookies out of three has a hole exactly where the flow is
    already halfway open.
    """
    client = two_step_client(app, monkeypatch)
    set_mode(monkeypatch, value)

    response = login(client)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert_cookie_shape(morsels(response)[auth.PENDING_COOKIE], expect_secure)


@pytest.mark.parametrize("value,expect_secure", MODES)
def test_the_session_cookie_minted_on_totp_success(
    app, monkeypatch, value, expect_secure
):
    """`admin_session` from POST /yllapito/koodi — the OTHER mint site.

    A second `set_cookie` call for the same cookie, in a different branch;
    a change applied to the one-step site alone leaves this one bare, and
    nothing else in the suite would say so.
    """
    client = two_step_client(app, monkeypatch)
    login(client)
    set_mode(monkeypatch, value)

    response = post_code(client, code_for(LOGIN_AT))

    assert response.status_code == 302, response.get_data(as_text=True)
    assert_cookie_shape(morsels(response)[auth.SESSION_COOKIE], expect_secure)


# === step 4 — the two cookies the flow DELETES =============================
#
# The EMITTED deletion header, server-side, not the browser's jar. Both of
# these deletions were bare before this change — `admin_session=;
# Expires=Thu, 01 Jan 1970 00:00:00 GMT; Max-Age=0; Path=/`, no HttpOnly,
# no SameSite, no Secure — and nothing in the suite pinned those bytes
# (tests/test_auth.py's logout rows check the 302, the Location and that
# the session row is gone, never the morsel). So these four rows are
# genuinely red before this change and green after.
#
# Stated honestly: matching the attributes on a deletion is HYGIENE, not a
# fix. RFC 6265bis's "Leave Secure Cookies Alone" only bites when a
# non-secure origin tries to overwrite a Secure cookie, and a bare
# deletion does clear one on an HTTPS deployment. The value is that all
# five cookie calls now read ONE rule instead of three reading it and two
# not — which is the kind of thing only a test keeps true.


@pytest.mark.parametrize("value,expect_secure", MODES)
def test_the_logout_deletion_header(app, monkeypatch, value, expect_secure):
    """POST /yllapito/kirjaudu-ulos, after a real login.

    Server-side deliberately, and not by preference: there is no logout
    CONTROL anywhere in the product — `kirjaudu-ulos` appears in
    `app/templates/`, `app/static/` and `app/*.py` only at the route
    definition — so there is nothing for a browser test to click, and
    `page.request.post` does not carry the session. The emitted header is
    the whole of what can be observed, so it is what is asserted.
    """
    create_admin(app)
    set_mode(monkeypatch, value)
    client = app.test_client()
    assert login(client).status_code == 302

    response = client.post("/yllapito/kirjaudu-ulos")

    assert response.status_code == 302, response.get_data(as_text=True)
    morsel = morsels(response)[auth.SESSION_COOKIE]
    assert morsel.value == ""  # it really is a deletion
    assert_cookie_shape(morsel, expect_secure)


@pytest.mark.parametrize("value,expect_secure", MODES)
def test_the_pending_deletion_header_on_totp_success(
    app, monkeypatch, value, expect_secure
):
    """POST /yllapito/koodi emits TWO Set-Cookie headers; this is the other.

    The same response that mints the session deletes the pending
    half-state, so this row and
    test_the_session_cookie_minted_on_totp_success read two different
    morsels off one response — which is exactly why `morsels()` loads
    every header rather than one.
    """
    client = two_step_client(app, monkeypatch)
    login(client)
    set_mode(monkeypatch, value)

    response = post_code(client, code_for(LOGIN_AT))

    assert response.status_code == 302, response.get_data(as_text=True)
    assert len(response.headers.getlist("Set-Cookie")) == 2
    morsel = morsels(response)[auth.PENDING_COOKIE]
    assert morsel.value == ""
    assert_cookie_shape(morsel, expect_secure)


# === step 3 — HSTS, across every kind of response ==========================


@pytest.mark.parametrize("value,expect_hsts", MODES)
@pytest.mark.parametrize("route", HTML_ROUTES)
def test_hsts_on_every_html_route(
    app, logged_in_admin, monkeypatch, route, value, expect_hsts
):
    """The nine HTML routes, both modes.

    The status assertion is load-bearing for the same reason
    tests/test_security_headers.py gives: seven of these nine are
    `@auth.require_admin` and a redirect is also `text/html`, so a session
    that quietly stopped working would leave every row green while
    measuring a login page instead.
    """
    set_mode(monkeypatch, value)
    path = route.format(row=row_id(app))

    response = logged_in_admin.get(path)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == "text/html"
    if expect_hsts:
        assert response.headers[HSTS] == "max-age=86400"
    else:
        assert HSTS not in response.headers


@pytest.mark.parametrize("value,expect_hsts", MODES)
def test_hsts_on_the_image_route(
    app, logged_in_admin, monkeypatch, value, expect_hsts
):
    """GET /kuvat/<digest> — and its own policy, untouched, in BOTH modes.

    HSTS is a claim about the CONNECTION, not about a document, so it has
    to sit OUTSIDE the `text/html` gate in `_security_headers`: a visitor
    whose first contact with this host is an image would otherwise never
    be pinned at all. That placement is also the hazard — the image route
    sets its own, far stricter `default-src 'none'; sandbox`
    (app/images.py), and a change that moved too much out of the gate
    would overwrite it and turn every stored image into a same-origin
    document that may load scripts. So the CSP is asserted byte-exact
    here, in both modes, beside the header this change actually adds.
    """
    ref = uploaded_image_ref(logged_in_admin)
    set_mode(monkeypatch, value)

    response = app.test_client().get(f"/kuvat/{ref}")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; sandbox"
    )
    if expect_hsts:
        assert response.headers[HSTS] == "max-age=86400"
    else:
        assert HSTS not in response.headers


@pytest.mark.parametrize("value,expect_hsts", MODES)
def test_hsts_on_the_json_api(client, monkeypatch, value, expect_hsts):
    """POST /api/messages — a JSON response, pinned too.

    The public contact form is the one request a first-time visitor is
    most likely to make before any HTML of ours is cached, and it gets no
    CSP (a policy about a document that does not exist). HSTS is the
    header it DOES want, which is the whole argument for keeping the two
    on opposite sides of that gate.
    """
    set_mode(monkeypatch, value)

    response = client.post(
        "/api/messages",
        json={
            "name": "Maria Koskinen",
            "email": "maria@esimerkki.fi",
            "message": "Hei.",
            "consent": True,
        },
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 201
    assert response.mimetype == "application/json"
    assert "Content-Security-Policy" not in response.headers
    if expect_hsts:
        assert response.headers[HSTS] == "max-age=86400"
    else:
        assert HSTS not in response.headers


# === step 7 — the trust boundary ==========================================


@pytest.mark.parametrize(
    "trusted_proxy",
    (
        pytest.param(None, id="no-trusted-proxy"),
        pytest.param("1", id="trusted-proxy-set"),
    ),
)
def test_forged_tls_headers_do_not_move_the_gate(
    app, monkeypatch, trusted_proxy
):
    """THE EXACT CLAIM: the app reads no such header, so the gate cannot be
    moved from outside the process.

    With `HTTPS_ONLY` unset, a request arrives carrying every header a
    TLS-terminating proxy conventionally sends — `X-Forwarded-Proto:
    https`, `X-Forwarded-Ssl: on`, `Forwarded: proto=https` — and the
    login cookie still has no `Secure` and the response still carries no
    HSTS. The gate's only input is the process environment.

    WHAT THIS DOES NOT DO, and it must not be read as doing it: **it
    closes no attack.** A forged header rides on the attacker's OWN
    request and changes only the attacker's OWN response; nobody's session
    is at stake in the scenario these rows describe. What they pin is a
    DESIGN decision — that `https_only()` is told, never derived — in the
    only place a decision like that can be pinned, which is behaviour.

    NOR do they go red the instant somebody adds `ProxyFix`. `ProxyFix`
    alone rewrites `wsgi.url_scheme` while the gate still reads
    `os.environ`, so these rows would stay GREEN. They redden when the
    GATE itself is changed — to consult the request scheme, or to OR in
    `TRUSTED_PROXY`. The second parametrization is there for exactly that
    second temptation: `TRUSTED_PROXY` already governs how this app reads
    the `X-Forwarded-*` family for its two rate limiters, and overloading
    it to also mean "and therefore TLS" is the shortcut this row forbids.
    The two variables are independent, and that is what is being said.
    """
    create_admin(app)
    set_mode(monkeypatch, None)
    if trusted_proxy is None:
        monkeypatch.delenv("TRUSTED_PROXY", raising=False)
    else:
        monkeypatch.setenv("TRUSTED_PROXY", trusted_proxy)

    response = app.test_client().post(
        "/yllapito/kirjaudu",
        data={"kayttajatunnus": ADMIN_USERNAME, "salasana": ADMIN_PASSWORD},
        headers=FORGED_TLS_HEADERS,
    )

    assert response.status_code == 302, response.get_data(as_text=True)
    assert_cookie_shape(
        morsels(response)[auth.SESSION_COOKIE], expect_secure=False
    )
    assert HSTS not in response.headers
