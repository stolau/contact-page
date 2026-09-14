"""The transport gate in real Chrome (LLM-COP-35 item 1).

`tests/test_transport.py` proves the BYTES: with `HTTPS_ONLY` set the app
emits `Secure` on every login cookie and `Strict-Transport-Security` on
every response. It cannot prove the one thing the whole conditional exists
to avoid — that a `Secure` cookie a browser refuses to send back turns a
successful login into a login that silently does nothing, with the
database insisting it worked. That failure is invisible to a werkzeug test
client, which ignores the flag entirely
(`werkzeug.test.Cookie._matches_request` does not look at `secure`). This
file is that evidence, and there is exactly one row of it: a real Chrome,
the app's own login form, the session cookie handed out and handed BACK.

THE MEASUREMENT THIS RESTS ON — read it before "fixing" this test.
**Chrome treats `127.0.0.1` as a potentially-trustworthy origin** (the
secure-contexts specification's exemption for loopback), and therefore
both STORES and RETURNS a `Secure` cookie over plain HTTP there. That is
why a row about `Secure` cookies can run against `live_app`'s plain-HTTP
loopback server with no TLS harness at all. Without that fact this test
looks impossible, and a reader who does not know it will conclude the
assertion is wrong and weaken it. It is not wrong; it is loopback.

The corollary, stated so nobody claims more than is here: **this file does
NOT prove a browser refuses a `Secure` cookie over ordinary plain HTTP.**
That is Chrome's documented behaviour on non-loopback origins and this
suite does not re-derive it — proving it would need a real certificate and
a non-loopback name. What is proved is the direction that can actually
break the product: the flag goes on and the session still works.

**Nor does any browser here act on HSTS.** RFC 6797 §8.1.1 excludes
IP-literal hosts, and Chrome was measured ignoring even a one-year
`max-age` on loopback. The header is therefore asserted as RECEIVED — read
off the real navigation response by the real browser — and not as obeyed.

NO POISONING, measured: a `browser.new_context()` is a fresh cookie jar
and a fresh HSTS store, so the `Secure` cookie and the
`Strict-Transport-Security` this row provokes do not reach any sibling
test sharing the session-scoped `browser` process. A sibling context gets
status 200 and an empty jar.

WHY THIS BUILDS ITS OWN CONTEXT instead of taking the `page` fixture.
`tests/browser/conftest.py`'s `page` performs the login during SETUP —
before a test body could run at all — so a `monkeypatch.setenv` in the
body would arrive after the cookie had already been issued in the OFF
mode. The order here is the point: set the variable FIRST, then open the
context, then log in. `https_only()` reads the environment per request, so
a function-scoped `setenv` is enough against the already-running
in-process `live_app` server.

NO LOGOUT LEG. There is no logout CONTROL in this product —
`kirjaudu-ulos` exists as a route and appears in no template and no
script — so there is nothing to click, and `page.request.post` does not
carry the session. The deletion headers are proved server-side, in
`tests/test_transport.py`.
"""

from tests.browser.conftest import VIEWPORT
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME


def test_a_real_login_survives_the_secure_flag_and_carries_hsts(
    browser, live_app, monkeypatch
):
    """HTTPS_ONLY on: Chrome logs in, keeps the `Secure` cookie, is pinned.

    Three assertions, and the first is the one that would actually cost
    somebody a deployment:

      1. **The redirect landed.** `wait_for_url` on /yllapito/alustus is
         only reachable if Chrome STORED the session cookie and SENT IT
         BACK on the following request — `@auth.require_admin` would
         bounce it otherwise. This is the row that goes red if `Secure` is
         ever set on a connection a browser will not carry it over, which
         is the failure the gate is conditional to avoid.
      2. **The flag is really on the cookie in the jar**, read out of
         Chrome's own store rather than off a response header, so a cookie
         the browser accepted while dropping the attribute would not pass.
      3. **The navigation response carries the header**, byte-exact, as
         the browser received it.
    """
    monkeypatch.setenv("HTTPS_ONLY", "1")

    context = browser.new_context(viewport=VIEWPORT)
    try:
        open_page = context.new_page()
        open_page.goto(f"{live_app.base_url}/yllapito")
        open_page.fill("input[name=kayttajatunnus]", ADMIN_USERNAME)
        open_page.fill("input[name=salasana]", ADMIN_PASSWORD)
        open_page.click(".login-submit")
        # 1. A state wait, not a time one: arriving here IS the proof that
        # the cookie came back.
        open_page.wait_for_url(f"{live_app.base_url}/yllapito/alustus")

        # 2. Chrome's own jar.
        session = [
            cookie
            for cookie in context.cookies()
            if cookie["name"] == "admin_session"
        ]
        assert len(session) == 1, context.cookies()
        assert session[0]["secure"] is True
        assert session[0]["httpOnly"] is True

        # 3. A real, admin-authenticated navigation — 200 rather than a
        # bounce to the login screen, so the session is still being
        # carried when the header is read.
        response = open_page.goto(f"{live_app.base_url}/yllapito/alustus")
        assert response.status == 200
        assert open_page.url == f"{live_app.base_url}/yllapito/alustus"
        assert (
            response.headers["strict-transport-security"] == "max-age=86400"
        )
    finally:
        context.close()
