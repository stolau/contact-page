"""The Content-Security-Policy, in real Chrome (LLM-COP-35 item 2).

tests/test_security_headers.py proves the BYTES of the header. It cannot
prove a browser accepts the policy, runs the three blessed inline scripts,
or refuses anything — and a CSP that a browser quietly rejects, or that
blocks the product's own code, is invisible to every server-side test in
this repository. This file is that evidence, and it is the first
console / securitypolicyviolation capture this project has ever had.

THE CAPTURE, AND WHICH SIGNAL IS LOAD-BEARING.
Three signals are collected and they are not equal:

  * `securitypolicyviolation` DOM events, pushed into `window.__csp` by an
    init script. **This is the load-bearing one.** It is a DOM event
    defined by the CSP specification, it reaches every frame, and it is
    read back out of the page itself.
  * console messages at `error` level. Chrome's "Refused to..." line
    arrives over the DevTools protocol as `Log.entryAdded`, NOT as
    `Runtime.consoleAPICalled`, so whether Playwright surfaces it through
    `page.on("console")` is a function of the Playwright version. It was
    measured to arrive in this Chrome + Playwright, so it is collected —
    but no product row ASSERTS it is present, and the rows only ever
    assert that no console error MENTIONS the policy. A future Playwright
    bump that stops forwarding those entries makes that check vacuous; it
    cannot turn this suite red for the wrong reason. The one test that
    does pin the console signal is
    test_the_console_also_reports_a_refusal_in_this_chrome, whose
    docstring says plainly that it is a fact about the harness.
  * `pageerror`. The CONSEQUENCE of a blocked bootstrap is an uncaught
    TypeError, not a violation event, so a row that watched only
    `window.__csp` could miss a dead page entirely.

WHY THIS FILE BUILDS ITS OWN CONTEXT instead of using the `page` fixture.
tests/browser/conftest.py's `page` navigates to /yllapito, fills the login
form, clicks and waits for the redirect BEFORE it yields — so a listener
attached in a test body arrives after login_dialog.html's inline script
has already run, and the one screen whose inline script could have been
refused would never be watched. Everything here is built from `browser` +
`live_app` and arms the capture first.

`context.add_init_script`, never `page.add_init_script`: a page-level
script would not reach a second tab opened with `context.new_page()`,
which is a shape this directory already uses
(tests/browser/test_browser_panel.py).

A ZERO-VIOLATION ASSERTION IS WORTHLESS ON ITS OWN, and this file treats
it that way. Three things keep it honest:

  1. `test_the_violation_capture_actually_captures` is the first test in
     the file and the prerequisite for every other. If the listener is
     never installed, `window.__csp` is `undefined`, and `assert not
     undefined` would pass — so every read asserts the value is a LIST,
     per frame, and the positive control proves a real refusal lands in it.
  2. Every row also asserts REAL BEHAVIOUR — the password toggle flips,
     the message is stored, the preview frame rendered, the wizard drew
     its form. A policy that black-holed the product would satisfy "no
     violations" perfectly. Measured, by a second agent in real Chrome:
     with `frame-ancestors 'none'` the editor's preview iframe becomes
     chrome-error://chromewebdata and Chrome fires NO violation event on
     the parent — a violations-only row would have stayed green through a
     completely dead editor.
  3. The public rows assert a COMPUTED COLOUR, not merely that the
     <style> element exists. Also measured: with `'unsafe-inline'` dropped
     from style-src, the <style> block is still present in the served
     bytes and the header simply falls back to white. The element being
     there proves nothing; the colour having arrived does.

BOTH SKINS where the public page is involved. page.html and page_v2.html
are separate documents that each include the same three dialog partials
and each carry their own <style> block. The skin AND the colours are
planted in ONE `edit_published_payload` call — never `set_hero_draft_style`
for a public-page row, which writes the `draft` column alone while `/`
reads `published`, so a v2 row would have silently re-run v1 — and the
served stylesheet is then ASSERTED rather than trusted, because
app/styles.py's resolve_style never raises, it falls back.
"""

import json
import re

import pytest

from tests.browser.conftest import V2_STYLESHEET, VIEWPORT
from tests.conftest import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    edit_published_payload,
    section_rows,
)

# Installed at CONTEXT level, before any navigation, so it runs ahead of
# every page script in every frame and every tab. The four fields are what
# a failure needs to be diagnosable: which directive, what was blocked,
# and where from.
CAPTURE = """
window.__csp = [];
document.addEventListener("securitypolicyviolation", function (event) {
  window.__csp.push({
    directive: event.violatedDirective,
    blocked: event.blockedURI,
    source: event.sourceFile,
    line: event.lineNumber
  });
});
"""

# RFC 2606 reserves .invalid, and CSP refuses the request before any DNS
# lookup happens, so the positive control below touches no network.
BLOCKED_IMAGE = "http://example.invalid/x.png"

# Dark enough that "the header is this colour" cannot be true by accident:
# neither skin's default header is anywhere near it (V1 is #ffffff, V2 is
# #d9e8f2, per tests/browser/test_browser_colors.py's frozen literals).
PLANTED_MAIN = "#1a1a2e"
PLANTED_MAIN_RGB = "rgb(26, 26, 46)"
PLANTED_ACCENT = "#b3541e"

# The header element. V2 renders class="site-header v2-header", so one
# selector reaches both skins — the same constant
# tests/browser/test_browser_colors.py uses, for the same reason.
HEADER = ".site-header"

# The heading direct edit binds (hero.title). V1 ONLY: page_v2.html does
# not render it, which is why the direct-edit row below is deliberately
# not parametrized over skins.
HEADING = ".main-heading"

VISITOR = {
    "name": "Maria Koskinen",
    "email": "maria@esimerkki.fi",
    "message": "Kuusivuotias poikani ei sano R-äännettä.",
}

PAYLOAD = "<script>window.__pwned=1</script>"


# --- the capture ------------------------------------------------------------
#
# Module-local, NOT in tests/browser/conftest.py. Two reasons and the
# second is the load-bearing one: this project states the convention that a
# helper only one file needs stays in that file
# (tests/test_sectionlist.py), and conftest is the file most likely to
# collide with work happening beside this. But mainly, the `page` fixture
# there logs in before it yields — see the module docstring.


class Capture:
    """One browser context with the violation capture armed.

    Every page it opens gets the console and pageerror collectors attached
    the moment it is created, so nothing that happens during the very first
    navigation is missed.
    """

    def __init__(self, context, base_url):
        self.context = context
        self.base_url = base_url
        self.console_errors = []
        self.page_errors = []

    def open(self, path="/"):
        """A new tab, watched, navigated, and its response asserted."""
        page = self.context.new_page()
        page.on("console", self._console)
        page.on("pageerror", self._pageerror)
        response = page.goto(f"{self.base_url}{path}")
        assert response is not None and response.status == 200, (
            f"GET {path} answered {response and response.status}"
        )
        return page

    def _console(self, message):
        if message.type == "error":
            self.console_errors.append(message.text)

    def _pageerror(self, error):
        self.page_errors.append(str(error))

    # -- reading the capture back --------------------------------------------

    def per_frame(self, page):
        """[(frame url, window.__csp)] for every frame of `page`.

        The value is read out of the page, so a frame the init script never
        reached answers `None` rather than `[]` — which is precisely the
        difference between "ran and saw nothing" and "never ran", and the
        reason no caller here may use a truthiness test.
        """
        seen = []
        for frame in page.frames:
            try:
                seen.append((frame.url, frame.evaluate("window.__csp")))
            except Exception as error:  # noqa: BLE001 - reported, not hidden
                seen.append((frame.url, f"unreachable frame: {error}"))
        return seen

    def violations(self, page):
        """Every violation from every frame, after proving each frame ran.

        `== []` per frame, never `assert not ...`: `undefined` comes back
        as None and None is falsy.
        """
        total = []
        for url, seen in self.per_frame(page):
            assert isinstance(seen, list), (
                f"the capture never ran in {url} (window.__csp is {seen!r}), "
                "so a zero-violation verdict for this page would be a "
                "statement about nothing"
            )
            total.extend(seen)
        return total

    def assert_silent(self, page):
        """No violation in any frame, no uncaught error, and no console
        line about the policy.

        The violation list is the load-bearing half. The console check is
        narrowed to messages that NAME the policy on purpose: Chrome's
        refusal line reaches Playwright as a Log entry rather than a
        console API call, so a version that stops forwarding it should make
        this vacuous, never red. See the module docstring.
        """
        assert self.violations(page) == []
        assert self.page_errors == []
        policy_lines = [
            line
            for line in self.console_errors
            if "Content Security Policy" in line
        ]
        assert policy_lines == []


@pytest.fixture
def capture(browser, live_app):
    """A fresh context with the capture installed BEFORE any navigation."""
    context = browser.new_context(viewport=VIEWPORT)
    context.add_init_script(CAPTURE)
    watcher = Capture(context, live_app.base_url)
    yield watcher
    context.close()


# --- planting ---------------------------------------------------------------


def plant(live_app, skin):
    """The skin AND both colours, in ONE edit_published_payload call.

    edit_published_payload writes the `draft` and `published` columns in a
    single UPDATE, so `/` (published), /muokkaa/esikatselu and
    /muokkaa/sivu (draft) all see the same thing. `set_hero_draft_style`
    must NOT be used for a public-page row: it writes `draft` alone, `/`
    reads `published`, and a v2 case would then have been a second, silent
    v1 run against page.html. Mixing the two is worse still — the second
    write would leave `/` on one skin and /muokkaa/sivu on the other.

    The COLOURS are not decoration. app/palette.py returns "" when neither
    is set and both templates guard the <style> block with
    {% if site_colors_css %}, so on a fresh seed there is no inline style
    at all — measured — and a public-page row on the default seed would
    never exercise style-src and would pass for the wrong reason.
    """
    edit_published_payload(
        live_app,
        "hero",
        lambda p: p.update(
            style=skin, color_main=PLANTED_MAIN, color_accent=PLANTED_ACCENT
        ),
    )


def assert_skin_and_colour(page, skin):
    """The plant LANDED: the right template, a real <style> block, and the
    colour the browser actually resolved.

    All three, in order, because each catches something the others do not.
    resolve_style falls back rather than raising, so the stylesheet count
    is what says the template is the one intended. The <style> element is
    what says palette_css produced anything. And the COMPUTED colour is
    what says style-src let it apply: measured, with 'unsafe-inline'
    dropped from style-src the element is still in the served bytes and
    the header simply falls back to white, so the element's presence alone
    would have been green through a broken policy.
    """
    assert page.locator(V2_STYLESHEET).count() == (1 if skin == "v2" else 0), (
        f"the page did not serve the {skin} skin"
    )
    assert page.locator("head > style").count() == 1, (
        "no inline <style> block in the document, so nothing here exercises "
        "style-src and a zero-violation verdict would mean nothing"
    )
    resolved = page.evaluate(
        f"() => getComputedStyle(document.querySelector('{HEADER}'))"
        ".backgroundColor"
    )
    assert resolved == PLANTED_MAIN_RGB, (
        f"the header resolved to {resolved}, not the planted "
        f"{PLANTED_MAIN_RGB} — the inline <style> block did not apply"
    )


def sign_in(capture, live_app):
    """Through the app's own login form, with the capture already armed.

    Deliberately NOT the conftest `page` fixture: that one signs in before
    it yields, so login_dialog.html's inline script would have run before
    any listener existed — and that script is one of the three this policy
    blesses.
    """
    page = capture.open("/yllapito")
    page.fill("input[name=kayttajatunnus]", ADMIN_USERNAME)
    page.fill("input[name=salasana]", ADMIN_PASSWORD)
    page.click(".login-submit")
    page.wait_for_url(f"{live_app.base_url}/yllapito/alustus")
    return page


def hero_id(live_app):
    return next(
        row["id"] for row in section_rows(live_app) if row["kind"] == "hero"
    )


# === 0 — the positive controls =============================================
#
# Nothing below this point means anything without these two.


def test_the_violation_capture_actually_captures(capture):
    """THE PREREQUISITE. A real refusal lands in window.__csp.

    Under img-src 'self', an image pointed at another origin must be
    refused and must produce exactly one captured entry naming that
    directive and that URI. example.invalid is reserved by RFC 2606 and
    CSP blocks the request before DNS, so this touches no network.

    Without this test every "the violation list is empty" assertion in
    this file is unfalsifiable: a listener that was never installed, an
    init script that never ran, a typo in the event name — all of them
    produce an empty list and a green suite.
    """
    page = capture.open("/")
    assert capture.violations(page) == []

    page.evaluate(
        f"() => {{ var i = new Image(); i.src = '{BLOCKED_IMAGE}'; }}"
    )
    page.wait_for_function("window.__csp.length > 0")

    seen = capture.violations(page)
    assert len(seen) == 1, seen
    assert seen[0]["directive"].startswith("img-src"), seen[0]
    assert seen[0]["blocked"] == BLOCKED_IMAGE, seen[0]


def test_an_injected_inline_script_is_actually_refused(capture):
    """THE SECOND POSITIVE CONTROL, and the security claim itself.

    This is what the whole policy is for: a <script> element that gets into
    a page the owner is looking at does not run. The element is created and
    appended the way an XSS payload would end up executing — a real element
    in the real document, not innerHTML, which no browser executes anyway
    and which would therefore have proved nothing.

    It is a control as well as a claim: it shows the capture reacts to
    script-src and not only to img-src, so one working directive cannot
    stand in for the rest.
    """
    page = capture.open("/")

    page.evaluate(
        """() => {
            var s = document.createElement('script');
            s.textContent = 'window.__pwned = 1;';
            document.body.appendChild(s);
        }"""
    )

    assert page.evaluate("() => window.__pwned") is None
    seen = capture.violations(page)
    assert len(seen) == 1, seen
    assert seen[0]["directive"].startswith("script-src"), seen[0]


def test_the_console_also_reports_a_refusal_in_this_chrome(capture):
    """A FACT ABOUT THE HARNESS, not about the product.

    Chrome's "Refused to load..." line reaches the DevTools protocol as
    Log.entryAdded rather than Runtime.consoleAPICalled, so whether
    page.on("console") surfaces it depends on the Playwright version. It
    does in this one, and that is worth having written down — but it is
    pinned HERE, alone, and nowhere else in this file, so a Playwright
    bump that stops forwarding those entries turns exactly one test red
    and that test says in its own name that it is about the console. The
    product rows rest on the securitypolicyviolation event instead.
    """
    page = capture.open("/")

    page.evaluate(
        f"() => {{ var i = new Image(); i.src = '{BLOCKED_IMAGE}'; }}"
    )
    page.wait_for_function("window.__csp.length > 0")

    assert any(
        "Content Security Policy" in line for line in capture.console_errors
    ), capture.console_errors


# === 1 — the login screen's inline script ===================================


def test_the_login_screen_runs_its_inline_script_under_the_policy(capture):
    """login_dialog.html's hash is right, proved by the toggle working.

    The Näytä button's only job is to flip the password field between
    `password` and `text`, and the code that does it is one of the three
    inline scripts the policy blesses by hash. If that hash were wrong the
    script would be refused, the listener would never be attached, and the
    field's type would not move — which is what is asserted, rather than
    "the script tag is in the document".
    """
    page = capture.open("/yllapito")
    field = page.locator("#login-password")
    assert field.get_attribute("type") == "password"

    page.click("#password-show")
    assert field.get_attribute("type") == "text"
    page.click("#password-show")
    assert field.get_attribute("type") == "password"

    capture.assert_silent(page)


# === 2 and 3 — the two public dialogs, both skins ===========================


@pytest.mark.parametrize("skin", ["v1", "v2"])
def test_the_contact_dialog_opens_and_sends_under_the_policy(
    capture, live_app, expect, skin
):
    """contact_dialog.html's hash is right, end to end and for real.

    The dialog opens, the real form is filled, and the real POST
    /api/messages is awaited and asserted 201 — so the inline script's
    fetch() survived connect-src 'self' as well as script-src. The message
    is then read back out of the app's own database, because a 201 nobody
    reads is a claim about a response.

    Both skins. page.html and page_v2.html render the contact card
    differently and each carries its own <style> block; a policy proved on
    one is not proved on the other.
    """
    plant(live_app, skin)
    page = capture.open("/")
    assert_skin_and_colour(page, skin)

    page.click('section[data-kind="yhteydenotto"] .cta-contact')
    form = page.locator("form.contact-dialog-form")
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(VISITOR["name"])
    form.locator("input[name=email]").fill(VISITOR["email"])
    form.locator("textarea[name=message]").fill(VISITOR["message"])
    form.locator("input[name=consent]").check()
    with page.expect_response("**/api/messages") as sent:
        form.locator("button[type=submit]").click()

    assert sent.value.status == 201, sent.value.text()
    expect(page.locator("#contact-thanks")).to_be_visible()
    assert stored_bodies(live_app) == [VISITOR["message"]]

    capture.assert_silent(page)


@pytest.mark.parametrize("skin", ["v1", "v2"])
def test_the_gdpr_dialog_opens_and_closes_under_the_policy(
    capture, live_app, expect, skin
):
    """gdpr_dialog.html's hash is right, proved by the behaviour only that
    script has: it opens, it moves focus to the close button, and it
    RESTORES focus to whatever opened it.

    Focus restoration is the assertion worth making. The dialog's `hidden`
    attribute could be moved by anything; `restore = document.activeElement`
    and `restore.focus()` exist only inside the blessed script, so focus
    coming back to the footer link is that script having run.
    """
    plant(live_app, skin)
    page = capture.open("/")
    assert_skin_and_colour(page, skin)

    dialog = page.locator(".gdpr-dialog")
    panel = page.locator(".gdpr-panel")
    expect(dialog).to_have_attribute("hidden", "")
    page.locator("footer .gdpr-open").click()

    # .gdpr-panel, not .gdpr-dialog: the wrapper has no layout rule of its
    # own and its only child is position: fixed, so it reports itself hidden
    # with the dialog wide open — the trap
    # tests/browser/test_browser_direct_edit.py already hit on
    # .contact-dialog. The wrapper's `hidden` attribute is asserted
    # separately, on the element that actually carries it.
    expect(panel).to_be_visible()
    expect(dialog).not_to_have_attribute("hidden", "")
    assert page.evaluate("() => document.activeElement.id") == "gdpr-close"
    page.click("#gdpr-close")
    expect(dialog).to_have_attribute("hidden", "")
    assert page.evaluate(
        "() => document.activeElement.className"
    ) == "gdpr-open"

    capture.assert_silent(page)


# === 4 — the editor shell and its same-origin preview frame =================


def test_the_edit_shell_and_its_preview_iframe_survive_the_policy(
    capture, live_app, expect
):
    """Two claims that no server-side test can make.

    (a) The type="application/json" bootstrap is not checked against
    script-src — edit.js JSON.parses #bootstrap and section-form.js draws
    the open section's form from it, so a form with real fields in it is
    the bootstrap having been read.

    (b) frame-ancestors 'self' really permits the editor's own preview.
    THE FRAME'S CONTENT IS ASSERTED, not just its existence and not just
    an empty violation list. Measured by a second agent in real Chrome:
    with frame-ancestors 'none' the frame becomes
    chrome-error://chromewebdata, the preview is dead, and Chrome fires NO
    securitypolicyviolation on the parent — so a violations-only row would
    have been green through a completely broken editor. Reading real
    sections out of the frame is what closes that hole.
    """
    page = sign_in(capture, live_app)
    page.goto(f"{live_app.base_url}/muokkaa")

    page.locator(".muut-osiot-list li").first.click()
    expect(page.locator(".section-form .field").first).to_be_visible()
    assert page.locator(".section-form .field-label").count() > 0

    preview = next(
        (f for f in page.frames if f.url.endswith("/muokkaa/esikatselu")),
        None,
    )
    assert preview is not None, [f.url for f in page.frames]
    sections = preview.evaluate(
        "() => document.querySelectorAll('section').length"
    )
    assert sections > 0, (
        "the preview frame rendered no sections — frame-ancestors black-holed "
        "the editor's own pane, which fires no violation on the parent"
    )
    expect(page.frame_locator(".preview").locator("body")).to_be_visible()

    # Per frame, and `== []` rather than a truthiness test: a frame the
    # init script never reached answers None, and `assert not None` passes.
    for url, seen in capture.per_frame(page):
        assert seen == [], (url, seen)
    capture.assert_silent(page)


# === 5 — the wizard's bootstrap =============================================


def test_the_wizard_bootstrap_draws_its_form_under_the_policy(
    capture, live_app, expect
):
    """wizard.html's application/json bootstrap was parsed and wizard.js
    drew the step machine — asserted through the machine, not the tag.

    wizard.js JSON.parses #bootstrap on line one; if that block were ever
    refused, every control below it would be undrawn. So the assertion is
    that a control resolves UNDER a named field of step 0 and holds the
    value the store actually has for it ("Yläotsikko" is app/fields.py's
    label for hero.kicker, and the expectation is read from the store
    rather than written down), plus the three facts only the running machine produces:
    panel 0 shown, panel 1 hidden, and .wizard-back DISABLED — it is
    rendered with no disabled attribute and wizard.js disables it.

    The locator is by LABEL, the shape tests/browser/test_browser_wizard.py
    uses, so a reordered step roster moves nothing silently.
    """
    page = sign_in(capture, live_app)
    assert page.url == f"{live_app.base_url}/yllapito/alustus"

    kicker = (
        page.locator(".wizard-panel[data-step='0'] .field")
        .filter(has=page.locator(".field-label", has_text="Yläotsikko"))
        .locator("input, textarea")
        .first
    )
    expect(kicker).to_be_visible()
    assert kicker.input_value() == seeded_hero_field(live_app, "kicker")
    expect(page.locator(".wizard-panel[data-step='0']")).to_be_visible()
    expect(page.locator(".wizard-panel[data-step='1']")).to_be_hidden()
    expect(page.locator(".wizard-back")).to_be_disabled()

    capture.assert_silent(page)


# === 6 — direct edit, and the CSSOM writes style-src-attr could have hit ====


def test_direct_edit_survives_the_policy(capture, live_app, expect):
    """style-src-attr 'none' does NOT block direct edit's CSSOM writes.

    That directive narrows style-src to <style> ELEMENTS, so an injected
    style="..." attribute is refused — and the open question was whether
    it also refuses the property writes app/static/direct-edit.js makes in
    placeChrome: tag.style.top and tag.style.left, the two lines that put
    the floating field tag where the clicked field is.

    THE ASSERTION IS THE INLINE style.top, NOT THE COMPUTED ONE, and the
    difference is the whole test. Measured: with those two writes removed,
    computed top on .direct-field-tag is a large pixel value inherited from
    the stylesheet (~2702px) — a "computed top is not auto" assertion would
    have passed with placeChrome gutted. The inline value is '' when the
    writes are stripped and a px string when they land, so only the inline
    one is evidence. No absolute pixel literal is expected here either: the
    number depends on layout, and what is being proved is that a number
    arrived.

    NOT parametrized over skins, deliberately: .main-heading is rendered by
    page.html and not by page_v2.html, so a v2 case would fail for a reason
    that has nothing to do with this policy.

    FALSIFIED, not assumed: with the two tag.style lines in
    app/static/direct-edit.js commented out this test failed on the inline
    style.top assertion, and passed again once the file was restored.
    """
    page = sign_in(capture, live_app)
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    assert page.locator(V2_STYLESHEET).count() == 0

    page.click(HEADING)
    page.keyboard.type("!")

    tag = page.locator(".direct-field-tag")
    expect(tag).to_be_visible()
    inline = page.evaluate(
        "() => document.querySelector('.direct-field-tag').style.top"
    )
    assert re.fullmatch(r"-?\d+(\.\d+)?px", inline or ""), (
        f"the field tag's INLINE top is {inline!r} — placeChrome's CSSOM "
        "write did not land, which is what style-src-attr 'none' would look "
        "like if it bit"
    )
    left = page.evaluate(
        "() => document.querySelector('.direct-field-tag').style.left"
    )
    assert re.fullmatch(r"-?\d+(\.\d+)?px", left or ""), left
    expect(page.locator(".direct-counter")).to_be_visible()

    capture.assert_silent(page)


# === 7 — the section list's re-injected HTML fragment =======================


def test_the_section_list_survives_the_policy(capture, live_app, expect):
    """The fragment route's headers break nothing.

    Toggling a row's state makes sectionlist.js fetch
    /muokkaa/osiot/rivi/<id> and innerHTML the answer back into the list —
    a text/html response that is NOT a document, now carrying the same CSP
    and X-Frame-Options as one. The re-injected row rendering, with its
    badge moved to Piilotettu, is what says the round trip worked.
    """
    page = sign_in(capture, live_app)
    page.goto(f"{live_app.base_url}/muokkaa/osiot")

    row = page.locator(f".section-row[data-section-id='{hero_id(live_app)}']")
    expect(row.locator(".row-status-badge")).to_have_text("Julkaistu")
    row.locator(".row-menu-toggle").click()
    with page.expect_response("**/muokkaa/osiot/rivi/*") as fragment:
        row.locator('.row-menu-item[data-action="hide"]').click()

    assert fragment.value.status == 200
    assert fragment.value.headers["content-security-policy"]
    expect(row.locator(".row-status-badge")).to_have_text("Piilotettu")

    capture.assert_silent(page)


# === 8 — the inbox, where visitor text meets the admin's browser ============


def test_the_inbox_renders_a_script_payload_inert(capture, live_app, expect):
    """The screen this whole policy exists for, with BOTH controls named.

    A visitor's message body is "<script>window.__pwned=1</script>", stored
    through the real POST /api/messages.

    (1) AUTOESCAPING is the primary control, and it is what makes
    window.__pwned undefined here. That half would pass with the
    after_request deleted, and it is not header proof.

    (2) THE HEADER is proved separately, on this same document, by doing
    what a successful injection would have done: creating a <script>
    element and appending it. That is refused, window.__pwned2 stays
    undefined, and a script-src violation is captured — so had the escaping
    failed, the payload still could not have run in the owner's
    authenticated browser. This is the assertion that goes red if the
    policy is removed.

    The violation list is therefore deliberately NON-empty by the end, and
    exactly one entry is expected.
    """
    page = capture.open("/")
    sent = page.request.post(
        f"{live_app.base_url}/api/messages",
        data={**VISITOR, "message": PAYLOAD, "consent": True},
    )
    assert sent.status == 201, sent.text()
    assert stored_bodies(live_app) == [PAYLOAD]

    page = sign_in(capture, live_app)
    page.goto(f"{live_app.base_url}/yllapito/viestit")

    # (1) escaping: the payload is on the screen as TEXT and never ran.
    expect(page.locator(".inbox-body")).to_have_text(PAYLOAD)
    assert page.evaluate("() => window.__pwned") is None
    assert capture.violations(page) == []

    # (2) the header: the same payload, injected the way it would actually
    # have executed, is refused by the policy this response carries.
    page.evaluate(
        """() => {
            var s = document.createElement('script');
            s.textContent = 'window.__pwned2 = 1;';
            document.querySelector('.inbox-body').appendChild(s);
        }"""
    )
    assert page.evaluate("() => window.__pwned2") is None
    refusals = capture.violations(page)
    assert len(refusals) == 1, refusals
    assert refusals[0]["directive"].startswith("script-src"), refusals[0]
    assert capture.page_errors == []


# --- small readers ----------------------------------------------------------


def stored_bodies(app):
    """Every stored message body, from the app's own database file."""
    from app import db as database

    conn = database.connect(app.config["DATABASE"])
    try:
        return [
            row["body"]
            for row in conn.execute("SELECT body FROM messages ORDER BY id")
        ]
    finally:
        conn.close()


def seeded_hero_field(app, name):
    """What the store actually holds for one hero field — never a literal,
    so a reseeded value moves the expectation with it rather than turning
    this file red for a copy change.

    "Yläotsikko" is app/fields.py's label for hero.kicker, not for
    hero.title; looking it up by field NAME is what keeps the wizard row
    honest about which control it found.
    """
    row = next(r for r in section_rows(app) if r["kind"] == "hero")
    return json.loads(row["draft"])[name]
