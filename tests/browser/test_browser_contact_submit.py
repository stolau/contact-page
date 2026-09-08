"""LLM-COP-32 — the on-page contact form SENDS, in a real browser.

Nothing here is stubbed. Real Chrome, the real Flask app on a real
loopback port, the app's own POST /api/messages, and the app's own SQLite
file read back through app.db.connect. `page.route` appears below only as
a COUNTER — every handler calls route.continue_(), so the request that is
counted is the request the server actually answered. A stubbed fetch would
have made every assertion in this file a statement about the stub.

WHY THIS FILE EXISTS AT ALL. The unit layer can read the served markup and
say the button is type="submit" and that a consent box is present. It
cannot say whether pressing that button stores a message, whether a dialog
the visitor never asked for opens over the page, whether an unticked box
costs one of five hourly rate-limit slots, or whether the GDPR panel is
reachable when it opens on top of the contact dialog's backdrop. All of
those are browser questions, and all of them are what the artifact was
filed about.

THE RATE BUDGET. app.messages counts arrivals per client key and every
arrival costs a slot, refusals included — five per hour, and this whole
directory is one client (127.0.0.1). tests/browser/conftest.py's autouse
_rate_limiter_isolation resets that window around every test, which is
what lets these tests POST for real more than five times between them. No
test below spends more than five slots on its own.

SCREENSHOTS. Written to tmp_path by default, so this file names no
absolute path and passes on any machine — the convention
tests/browser/test_browser_panel.py:732 states in as many words. Set
COP32_SHOTS=<dir> to collect them somewhere a person can look at them
afterwards.
"""

import os

import pytest

from app import db as database
from tests.browser.conftest import (
    V2_STYLESHEET,
    VIEWPORT,
    set_hero_draft_style,
)
from tests.conftest import edit_published_payload

# What a visitor types. Not asserted as product copy anywhere — it is the
# input, and what matters is that these exact bytes come back out of the
# store and out of the inbox.
VISITOR = {
    "name": "Maria Koskinen",
    "email": "maria@esimerkki.fi",
    "message": "Kuusivuotias poikani ei sano R-äännettä.",
}

# The payload LLM-COP-3 proved inert through the dialog. Proved again here
# for the INLINE path rather than assumed to be inherited: the two paths
# now share one send() function, but they do not share a template, and the
# inbox escapes what it is handed, not what it was handed once.
PAYLOAD = "<script>window.__pwned=1</script>"


@pytest.fixture(params=["v1", "v2"], ids=["v1", "v2"])
def skin(request):
    """Both skins, every test. The artifact asks for both and the two
    templates render the contact card differently enough to matter: V1's
    send button is inside the form, V2's is outside it in the actions
    column and associated by form="…"."""
    return request.param


@pytest.fixture
def shots(tmp_path):
    """Where screenshots land. tmp_path unless COP32_SHOTS says otherwise."""
    target = os.environ.get("COP32_SHOTS")
    if not target:
        return str(tmp_path)
    os.makedirs(target, exist_ok=True)
    return target


@pytest.fixture
def public(browser, live_app, skin):
    """An ANONYMOUS visitor on the public page, in the requested skin.

    A fresh context and no login, deliberately: conftest's `page` fixture
    is a signed-in admin that lands on the wizard, and every claim in this
    file is about what a visitor can do. The pattern is
    tests/browser/test_browser_panel.py:297.

    The style is written to draft AND published (edit_published_payload),
    not draft alone: `/` renders the PUBLISHED style, so a drafted-only v2
    would serve this fixture V1 and every V2 case below would quietly be a
    second V1 run. resolve_style never raises — it falls back — so the
    served stylesheet is asserted rather than trusted.
    """
    if skin == "v2":
        edit_published_payload(live_app, "hero", lambda p: p.update(style="v2"))
    context = browser.new_context(viewport=VIEWPORT)
    visitor = context.new_page()
    visitor.goto(f"{live_app.base_url}/")
    expected = 1 if skin == "v2" else 0
    assert visitor.locator(V2_STYLESHEET).count() == expected, (
        f"/ did not serve the {skin} skin — the style fell back, and this "
        "case would have run against the wrong template"
    )
    yield visitor
    context.close()


@pytest.fixture
def edit_page(page, live_app, skin):
    """The signed-in admin on the REAL /muokkaa/sivu, in the requested skin.

    set_hero_draft_style here, not edit_published_payload: direct edit mode
    renders the DRAFT, which is the state an owner is actually in while
    editing.
    """
    set_hero_draft_style(live_app, skin)
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    expected = 1 if skin == "v2" else 0
    assert page.locator(V2_STYLESHEET).count() == expected, (
        f"/muokkaa/sivu did not serve the {skin} skin"
    )
    return page


# --- instruments -------------------------------------------------------------


def count_posts(page):
    """Count arrivals at POST /api/messages and let every one through.

    route.continue_() on every call, so this observes the traffic instead
    of replacing it: the counted request is served by the real endpoint and
    stored in the real database. Returns a one-element list used as a
    counter, so the caller reads it after the fact.
    """
    seen = []

    def handler(route, request):
        if request.method == "POST":
            seen.append(request.url)
        route.continue_()

    page.route("**/api/messages", handler)
    return seen


def settle(page):
    """Wait until any request the last interaction started has been seen.

    NOT a sleep. The send handler issues its fetch synchronously inside the
    submit listener, so if a submission happened its request was created in
    an earlier task than this one; a fetch issued now and awaited to
    completion cannot finish before an earlier request has been reported to
    the route handler. That ordering is what makes a "the counter is still
    zero" assertion mean something rather than being a race the test wins
    by being fast.
    """
    page.evaluate("() => fetch('/').then(function (r) { return r.status; })")


def stored_messages(app):
    """Every stored message, from the app's own database file."""
    conn = database.connect(app.config["DATABASE"])
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM messages ORDER BY id"
        )]
    finally:
        conn.close()


def inline_form(page):
    return page.locator("form.contact-form")


def outcome(page, attribute):
    """The on-page form's success or failure slot, resolved the way the
    product resolves it: read the id out of the form's own data-result /
    data-error and look it up.

    Never `.contact-error` as a bare class selector — the DIALOG's failure
    line carries that class too, and a locator matching both would report
    whichever it liked. Going through the attribute is also the stronger
    claim: it fails if the form names an id nothing answers to, which is a
    send that reports neither outcome and raises nothing.
    """
    slot_id = inline_form(page).get_attribute(attribute)
    assert slot_id, attribute
    return page.locator(f"#{slot_id}")


def send_button(page, skin):
    """The card's Lähetä.

    Two selectors because the two skins really do put it in two places:
    inside the form on V1, in the actions column beside it on V2, where it
    reaches the form through form="…". That attribute is the thing under
    test on the V2 leg, so the locator has to be the button the design
    draws rather than any submit button that happens to be in the form.
    """
    if skin == "v2":
        return page.locator(".v2-contact-primary")
    return page.locator("form.contact-form button[type=submit]")


def fill_inline(page, values=VISITOR, consent=True):
    """Type a visitor's message into the on-page form."""
    form = inline_form(page)
    form.locator("input[name=name]").fill(values["name"])
    form.locator("input[name=email]").fill(values["email"])
    form.locator("textarea[name=message]").fill(values["message"])
    if consent:
        form.locator("input[name=consent]").check()


def fill_dialog(page, values, consent=True):
    """Type the same message into the dialog's own form."""
    form = page.locator("form.contact-dialog-form")
    form.locator("input[name=name]").fill(values["name"])
    form.locator("input[name=email]").fill(values["email"])
    form.locator("textarea[name=message]").fill(values["message"])
    if consent:
        form.locator("input[name=consent]").check()


# --- 1. it sends, and no dialog opens ---------------------------------------


def test_the_on_page_form_stores_a_message_and_opens_no_dialog(
    public, expect, live_app, skin, shots
):
    """The artifact's first sentence, executable.

    Before LLM-COP-32 this press threw the answers away and reopened the
    same three questions in a dialog (V2), or did nothing whatsoever (V1).
    Now it stores a row, and the proof is the row — read out of the app's
    own SQLite file, not out of a response body the page happened to show.

    BOTH dialog assertions, not one. expect(.contact-panel).to_be_hidden()
    auto-retries until it succeeds, so on its own it would pass against a
    dialog that opened and was closed a frame later; the hidden ATTRIBUTE
    on .contact-dialog is the state that says it was never opened at all.
    That pair is the shape tests/browser/test_browser_v2_direct_edit.py:496
    already uses.
    """
    posts = count_posts(public)
    fill_inline(public)

    with public.expect_response("**/api/messages") as answer:
        send_button(public, skin).click()
    assert answer.value.status == 201, answer.value.text()

    rows = stored_messages(live_app)
    assert len(rows) == 1, rows
    assert rows[0]["name"] == VISITOR["name"]
    assert rows[0]["body"] == VISITOR["message"]
    assert rows[0]["email"] == VISITOR["email"]
    # Consent is recorded, not merely demanded: the row carries the stamp.
    assert rows[0]["consented_at"], rows[0]

    expect(outcome(public, "data-result")).to_be_visible()
    # And the form GOES AWAY. send() sets form.hidden on 201, and that has
    # to be true on the screen and not merely in the attribute: a form that
    # stays visible with every field still filled tells the visitor nothing
    # landed, and the obvious response to that is to press Lähetä again and
    # send the same message twice. This assertion was RED when it was first
    # written — see the PR notes on `.contact-form { display: flex }`.
    expect(inline_form(public)).to_be_hidden()
    expect(public.locator(".contact-panel")).to_be_hidden()
    expect(public.locator(".contact-dialog")).to_have_attribute("hidden", "")

    assert len(posts) == 1, posts
    public.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-lomake-lahetetty.png"),
        full_page=True,
    )


# --- 2. the top bar still opens the dialog, and that path still sends -------


def test_the_top_bar_still_opens_the_dialog_and_that_path_still_sends(
    public, expect, live_app, skin, shots
):
    """The half of the ask that was already true and had to stay true.

    Both paths in one session and one store: the inline form sends first,
    then the header's Ota yhteyttä opens the dialog and sends again, and
    the database holds TWO distinct rows. One shared send() serving two
    forms is the change this proves did not collapse into one form serving
    itself twice.
    """
    fill_inline(public)
    with public.expect_response("**/api/messages"):
        send_button(public, skin).click()
    assert len(stored_messages(live_app)) == 1

    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()

    second = {
        "name": "Petri Salo",
        "email": "petri@esimerkki.fi",
        "message": "Voisiko ajan varata iltapäivälle?",
    }
    fill_dialog(public, second)
    public.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-dialogi-taytetty.png"),
        full_page=True,
    )
    with public.expect_response("**/api/messages") as answer:
        public.click(".cd-submit")
    assert answer.value.status == 201, answer.value.text()

    # The dialog's success slot is #contact-thanks (class cd-thanks) — the
    # seeded copy LLM-COP-3 shipped, addressed by data-result rather than
    # replaced by the page forms' .contact-result.
    expect(public.locator("#contact-thanks")).to_be_visible()
    # The same disappearance, on the dialog's own form. It never actually
    # happened before this artifact either — send() has always set
    # form.hidden here and .contact-dialog-form { display: flex } has always
    # outranked the UA's [hidden] rule — so the thank-you used to appear
    # UNDER a dialog still showing the message that had just been sent.
    expect(public.locator("form.contact-dialog-form")).to_be_hidden()

    rows = stored_messages(live_app)
    assert len(rows) == 2, rows
    assert [row["name"] for row in rows] == [VISITOR["name"], second["name"]]


# --- 3. consent, refused on both paths --------------------------------------


def test_an_unticked_consent_box_is_refused_in_place_and_costs_no_slot(
    public, expect, live_app, skin, shots
):
    """The rate-limit hazard the artifact named, proved rather than described.

    app/messages.py charges a slot BEFORE it parses anything, so a
    submission that reaches the server without consent burns one of the
    visitor's five. The browser therefore refuses it first — and the
    assertion that matters is not that an error appeared, it is that the
    request counter is at ZERO. Nothing was sent, so nothing was spent.

    The form must also survive the refusal: still visible, still holding
    every character the visitor typed. A page that swallowed the attempt
    and cleared the fields would be a worse bug than the one being fixed.
    """
    posts = count_posts(public)
    fill_inline(public, consent=False)
    send_button(public, skin).click()

    error = outcome(public, "data-error")
    expect(error).to_be_visible()
    assert (error.text_content() or "").strip(), "the refusal says nothing"

    form = inline_form(public)
    expect(form).to_be_visible()
    assert form.locator("input[name=name]").input_value() == VISITOR["name"]
    assert form.locator("input[name=email]").input_value() == VISITOR["email"]
    assert (
        form.locator("textarea[name=message]").input_value()
        == VISITOR["message"]
    )
    expect(outcome(public, "data-result")).to_be_hidden()

    settle(public)
    assert posts == [], posts
    assert stored_messages(live_app) == []

    public.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-suostumus-puuttuu.png"),
        full_page=True,
    )


def test_the_dialog_refuses_an_unticked_box_in_place_too(
    public, expect, live_app, skin
):
    """The same guard on the other form, because it is the same function.

    The dialog had no failure reporting at all before this change: a
    refused send left the form sitting there with no explanation. It now
    reports into #contact-error and, like the inline form, sends nothing.
    """
    posts = count_posts(public)
    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()
    fill_dialog(public, VISITOR, consent=False)
    public.click(".cd-submit")

    expect(public.locator("#contact-error")).to_be_visible()
    expect(public.locator("#contact-thanks")).to_be_hidden()
    settle(public)
    assert posts == [], posts
    assert stored_messages(live_app) == []


@pytest.mark.parametrize(
    "case, body",
    [
        ("absent", {k: v for k, v in VISITOR.items()}),
        ("false", dict(VISITOR, consent=False)),
        # The STRING "true", not the boolean. A client that serialized its
        # checkbox as text would look like consent to anything doing a
        # truthiness test, and the server's rule is identity with True.
        ("the string true", dict(VISITOR, consent="true")),
    ],
)
def test_the_server_refuses_a_consentless_post_from_any_client(
    public, live_app, case, body
):
    """The browser's guard is a courtesy; THIS is the rule.

    A real HTTP POST from the browser's own context, straight at the
    endpoint, past every line of JavaScript in the product — which is
    exactly what an attacker or a broken client does. app/messages.py is
    unchanged by this artifact and must refuse all three.
    """
    response = public.request.post(
        f"{live_app.base_url}/api/messages", data=body
    )
    assert response.status == 400, (case, response.text())
    assert response.json()["error"] == "consent is required", case
    assert stored_messages(live_app) == [], case


# --- 4. the GDPR dialog ------------------------------------------------------


def test_the_privacy_link_on_the_page_opens_closes_and_returns_focus(
    public, expect, skin, shots
):
    """The new dialog, opened from the link beside the consent box.

    page.click("#gdpr-close") rather than a visibility assertion for the
    close: to_be_visible() does not hit-test, so it would pass over a panel
    buried under a backdrop. click() runs Playwright's actionability
    checks, which do hit-test — if the stacking were wrong this line fails
    and nothing else has to know why.
    """
    opener = inline_form(public).locator(".gdpr-open")
    opener.click()
    expect(public.locator(".gdpr-panel")).to_be_visible()
    # The text is a placeholder and says so on the page — the artifact
    # asked for exactly that and for no invented legal wording.
    expect(public.locator(".gdpr-placeholder")).to_be_visible()
    public.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-tietosuoja-auki.png"),
        full_page=True,
    )

    public.click("#gdpr-close")
    expect(public.locator(".gdpr-dialog")).to_have_attribute("hidden", "")
    assert public.evaluate(
        "() => document.activeElement"
        " === document.querySelector('form.contact-form .gdpr-open')"
    ), "focus was not returned to the link that opened the dialog"

    # Escape is the second close path, asserted separately so a broken
    # keyboard route cannot hide behind a working button.
    opener.click()
    expect(public.locator(".gdpr-panel")).to_be_visible()
    public.keyboard.press("Escape")
    expect(public.locator(".gdpr-dialog")).to_have_attribute("hidden", "")
    # The page's own form is untouched by any of it.
    expect(inline_form(public)).to_be_visible()


def test_the_privacy_link_inside_the_dialog_stacks_without_disturbing_it(
    public, expect, skin, shots
):
    """The second-order problem the link inside the consent row creates.

    Three things can go wrong here and each has its own assertion. The
    GDPR panel can open UNDER the contact dialog's backdrop — the
    page.click("#gdpr-close") is what catches that, because a covered
    panel is not clickable however visible it looks. Escape can close the
    wrong dialog, or both. And the link lives inside a <label> whose
    control is the consent checkbox, so opening the privacy statement
    could silently tick the box it explains.
    """
    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()
    consent = public.locator("form.contact-dialog-form input[name=consent]")
    assert consent.is_checked() is False

    link = public.locator(".cd-consent .gdpr-open")
    link.click()
    expect(public.locator(".gdpr-panel")).to_be_visible()
    # Both dialogs open at once — the contact one is still there, behind.
    expect(public.locator(".contact-panel")).to_be_visible()
    # Reading about consent did not give consent.
    assert consent.is_checked() is False
    public.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-tietosuoja-dialogin-yli.png"),
        full_page=True,
    )

    # Hit-tested, so this line is the non-occlusion proof.
    public.click("#gdpr-close")
    expect(public.locator(".gdpr-dialog")).to_have_attribute("hidden", "")
    expect(public.locator(".contact-panel")).to_be_visible()
    assert public.evaluate(
        "() => document.activeElement"
        " === document.querySelector('.cd-consent .gdpr-open')"
    ), "focus was not returned to the link inside the consent row"

    # Escape closes the TOPMOST dialog only: the contact dialog stays open.
    link.click()
    expect(public.locator(".gdpr-panel")).to_be_visible()
    public.keyboard.press("Escape")
    expect(public.locator(".gdpr-dialog")).to_have_attribute("hidden", "")
    expect(public.locator(".contact-panel")).to_be_visible()
    assert consent.is_checked() is False


# --- 5. a script payload through the INLINE path ----------------------------


def test_a_script_payload_sent_inline_renders_inert_in_the_inbox(
    public, page, expect, live_app, skin, shots
):
    """LLM-COP-3 proved this for the dialog. It is proved again HERE for the
    inline path rather than assumed to be inherited.

    The two paths share a send() function but not a template, and the
    escaping that matters happens in a third file entirely
    (app/templates/inbox.html). Nothing about "the dialog's payload was
    safe" tells an admin that the inline form's is.

    Both halves are asserted. window.__pwned being undefined says the
    script never executed; the text content being the literal payload says
    the admin can actually READ what was sent, which a blunt strip would
    have destroyed while passing the first half.
    """
    marked = {
        "name": PAYLOAD,
        "email": f"{PAYLOAD}@esimerkki.fi",
        "message": f"Terveisin {PAYLOAD}",
    }
    fill_inline(public, marked)
    with public.expect_response("**/api/messages") as answer:
        send_button(public, skin).click()
    assert answer.value.status == 201, answer.value.text()
    assert len(stored_messages(live_app)) == 1

    page.goto(f"{live_app.base_url}/yllapito/viestit")
    expect(page.locator(".inbox-message")).to_have_count(1)
    assert page.evaluate("() => window.__pwned") is None
    assert page.locator(".inbox-name").text_content() == marked["name"]
    assert page.locator(".inbox-body").text_content() == marked["message"]
    assert page.locator(".inbox-email").text_content() == marked["email"]
    page.screenshot(
        path=os.path.join(shots, f"cop32-{skin}-postilaatikko.png"),
        full_page=True,
    )


# --- 6. direct edit mode: the send button edits, and posts nothing -----------


@pytest.mark.parametrize("trigger", ["pointer", "enter"])
def test_the_send_button_edits_its_label_and_posts_nothing_in_direct_edit_mode(
    edit_page, expect, live_app, skin, trigger, shots
):
    """The riskiest thing this artifact creates, and its guard.

    The card's Lähetä is now BOTH a type="submit" control and a
    data-field="send_label" editable — so while an owner is renaming it, a
    press must mean "edit me" and must not also send whatever happens to
    be typed into the form underneath. direct-edit.js:346-355 is one
    capture-phase click listener on the document that preventDefault()s any
    click landing inside a [data-field], and preventDefault on a submit
    button's click IS the cancelled submission.

    THE FORM IS FILLED FIRST, and that is what stops this test being
    vacuous. Against an empty form the browser's own pre-validation would
    refuse before fetching and the counter would read zero for entirely the
    wrong reason. With every field filled and consent ticked, this is a
    submission that WOULD post — test 1 above sends exactly this payload
    for real through the same button on the public page — so zero here is a
    fact about the guard.

    TWO TRIGGERS. The pointer leg is the obvious one. The keyboard leg is
    implicit submission: Enter in a text field dispatches a synthetic click
    at the form's DEFAULT button, which on V2 is this button only because
    form="…" makes it the form's first submit control in tree order. That
    relationship is exactly what a later refactor could break in silence,
    so it is pinned rather than inherited.

    The keyboard leg does NOT assert .direct-field-tag. The tag is unhidden
    by activate() (direct-edit.js:152-160), which is bound to the FOCUS
    event (:315-317); implicit submission dispatches its click without
    focusing anything, and the form's text inputs carry no data-field, so
    the tag legitimately stays hidden. Asserting it here would be an
    assertion about the harness, and making it true would mean changing the
    product to satisfy a test.
    """
    posts = count_posts(edit_page)
    before = len(stored_messages(live_app))

    # focus() + keyboard, not fill(): direct edit mode's two fixed bars and
    # the floating toolbar intercept synthetic clicks at whatever scrolls
    # under them, which is a fact about the chrome rather than about the
    # product (tests/browser/test_browser_v2_direct_edit.py's `activate`
    # says the same thing for the same reason).
    form = inline_form(edit_page)
    for selector, value in (
        ("input[name=name]", VISITOR["name"]),
        ("input[name=email]", VISITOR["email"]),
        ("textarea[name=message]", VISITOR["message"]),
    ):
        field = form.locator(selector)
        field.focus()
        edit_page.keyboard.type(value)
    consent = form.locator("input[name=consent]")
    consent.focus()
    edit_page.keyboard.press("Space")
    assert consent.is_checked(), "the form under test is not actually sendable"

    button = send_button(edit_page, skin)
    button.scroll_into_view_if_needed()
    if trigger == "pointer":
        button.click()
        # The click still means "edit me": the field tag names the label.
        expect(edit_page.locator(".direct-field-tag")).to_be_visible()
        edit_page.screenshot(
            path=os.path.join(shots, f"cop32-{skin}-muokkaustila.png"),
            full_page=True,
        )
    else:
        form.locator("input[name=name]").focus()
        edit_page.keyboard.press("Enter")

    settle(edit_page)
    assert posts == [], posts
    assert len(stored_messages(live_app)) == before
    expect(edit_page.locator(".contact-dialog")).to_have_attribute("hidden", "")
    expect(outcome(edit_page, "data-result")).to_be_hidden()
