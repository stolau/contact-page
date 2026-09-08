"""USR-COP-1 — the contact dialog is the ONE send path, in a real browser.

Nothing here is stubbed. Real Chrome, the real Flask app on a real
loopback port, the app's own POST /api/messages, and the app's own SQLite
file read back through app.db.connect. `page.route` appears below only as
a COUNTER — every handler calls route.continue_(), so the request that is
counted is the request the server actually answered. A stubbed fetch would
have made every assertion in this file a statement about the stub.

WHY THIS FILE EXISTS AT ALL. The unit layer can read the served markup and
say the card's button carries .cta-contact and that the dialog's form has a
consent box. It cannot say whether pressing that button opens the dialog,
whether the dialog then stores a message, whether an unticked box costs one
of five hourly rate-limit slots, or whether the GDPR panel is reachable when
it opens on top of the contact dialog's backdrop. All of those are browser
questions.

WHAT CHANGED UNDER THIS FILE. LLM-COP-32 wired a SECOND send path — a form
drawn into the page beside the dialog's — and most of this file was written
to prove that second path carried the same consent, the same validation and
the same reporting as the first. USR-COP-1 deletes the second path instead:
one form, in the dialog, so nothing can drift. The tests that compared the
two are gone; the tests that are about the product's one real send path are
re-aimed at it and are stronger for covering the only path there is.

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
    """Both skins, every test. The two templates render the contact card
    differently enough to matter: V1's button sits directly in the section,
    V2's in the card's actions column beside the phone and email rows. Both
    must open the same one dialog."""
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


def card_button(page):
    """The contact card's button, scoped to its own section.

    ONE locator for both skins, because data-kind="yhteydenotto" is on the
    section in both. Never a bare `.cta-contact`: the hero carries that class
    too, page.click() is non-strict, and a bare selector would resolve to the
    hero by document order — passing happily against a build where the card's
    button was never given the class at all.
    """
    return page.locator('section[data-kind="yhteydenotto"] .cta-contact')


def fill_dialog(page, values, consent=True):
    """Type the same message into the dialog's own form."""
    form = page.locator("form.contact-dialog-form")
    form.locator("input[name=name]").fill(values["name"])
    form.locator("input[name=email]").fill(values["email"])
    form.locator("textarea[name=message]").fill(values["message"])
    if consent:
        form.locator("input[name=consent]").check()


# --- 1. the card's button opens the dialog, and that path sends -------------


def test_the_card_button_opens_the_dialog_and_that_path_sends(
    public, expect, live_app, skin, shots
):
    """The artifact's first sentence, executable.

    The card's button used to submit a form of its own (LLM-COP-32) and,
    before that, to open a dialog over the answers the visitor had already
    typed into that form (LLM-COP-6's collision). There is one form now and
    the button opens it; the proof that the path works end to end is the ROW
    — read out of the app's own SQLite file, not out of a response body the
    page happened to show.

    The locator is SCOPED to the yhteydenotto section and the located element
    is asserted to be the one carrying data-field="send_label". A bare
    `.cta-contact` resolves to the hero and would pass against a build where
    the card's button never got the class, which is exactly the regression
    this test is here to catch.
    """
    posts = count_posts(public)

    button = card_button(public)
    expect(button).to_have_count(1)
    assert button.get_attribute("data-field") == "send_label", (
        "the located element is not the card's own button"
    )

    button.click()
    expect(public.locator(".contact-panel")).to_be_visible()

    fill_dialog(public, VISITOR)
    public.screenshot(
        path=os.path.join(shots, f"usr-cop1-{skin}-kortista-avattu.png"),
        full_page=True,
    )
    with public.expect_response("**/api/messages") as answer:
        public.click(".cd-submit")
    assert answer.value.status == 201, answer.value.text()

    rows = stored_messages(live_app)
    assert len(rows) == 1, rows
    assert rows[0]["name"] == VISITOR["name"]
    assert rows[0]["body"] == VISITOR["message"]
    assert rows[0]["email"] == VISITOR["email"]
    # Consent is recorded, not merely demanded: the row carries the stamp.
    assert rows[0]["consented_at"], rows[0]
    assert len(posts) == 1, posts


# --- 2. the top bar opens the dialog too, and that path sends ---------------


def test_the_top_bar_still_opens_the_dialog_and_that_path_still_sends(
    public, expect, live_app, skin, shots
):
    """The half of the ask that was already true and had to stay true.

    The header's Ota yhteyttä is the opener that predates every contact
    button on the page, and deleting the on-page form must not have disturbed
    it. Narrowed to that one path since USR-COP-1: the inline lead-in this
    test used to open with sent through a form that no longer exists, so the
    store now holds one row rather than two.
    """
    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()

    fill_dialog(public, VISITOR)
    public.screenshot(
        path=os.path.join(shots, f"usr-cop1-{skin}-dialogi-taytetty.png"),
        full_page=True,
    )
    with public.expect_response("**/api/messages") as answer:
        public.click(".cd-submit")
    assert answer.value.status == 201, answer.value.text()

    # The dialog's success slot is #contact-thanks (class cd-thanks) — the
    # owner's thanks copy, addressed by data-result.
    expect(public.locator("#contact-thanks")).to_be_visible()
    # And the form GOES AWAY. send() sets form.hidden on 201, and that has to
    # be true on the SCREEN and not merely in the attribute: a form that stays
    # visible with every field still filled tells the visitor nothing landed,
    # and the obvious response to that is to press Lähetä again and send the
    # same message twice. It was red when it was first written —
    # .contact-dialog-form { display: flex } outranked the UA's [hidden] rule
    # — and it is now one of only two surviving proofs of that fix.
    expect(public.locator("form.contact-dialog-form")).to_be_hidden()

    rows = stored_messages(live_app)
    assert len(rows) == 1, rows
    assert rows[0]["name"] == VISITOR["name"]


# --- 3. consent, refused on both paths --------------------------------------


def test_the_dialog_refuses_an_unticked_box_in_place(
    public, expect, live_app, skin
):
    """The rate-limit hazard the product has to respect, on the one form.

    app/messages.py charges a slot BEFORE it parses anything, so a submission
    that reaches the server without consent burns one of the visitor's five.
    The browser therefore refuses it first — and the assertion that matters is
    not that an error appeared, it is that the request counter is at ZERO.
    Nothing was sent, so nothing was spent.

    The refusal reports into #contact-error. Before LLM-COP-32 the dialog had
    no failure reporting at all and a refused send left the form sitting there
    with no explanation.

    AND THE FORM SURVIVES THE REFUSAL: still on screen, still holding every
    character the visitor typed. A page that swallowed the attempt and cleared
    the fields would be a worse bug than the one being refused — the visitor
    would have to retype the whole message to tick one box. That claim used to
    be made of the deleted on-page form and of nothing else; USR-COP-1 leaves
    this the only collection path there is, so it is made here rather than lost
    with the path it was written against.
    """
    posts = count_posts(public)
    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()
    fill_dialog(public, VISITOR, consent=False)
    public.click(".cd-submit")

    expect(public.locator("#contact-error")).to_be_visible()
    assert (
        public.locator("#contact-error").text_content() or ""
    ).strip(), "the refusal says nothing"
    expect(public.locator("#contact-thanks")).to_be_hidden()

    form = public.locator("form.contact-dialog-form")
    expect(form).to_be_visible()
    assert form.locator("input[name=name]").input_value() == VISITOR["name"]
    assert form.locator("input[name=email]").input_value() == VISITOR["email"]
    assert (
        form.locator("textarea[name=message]").input_value()
        == VISITOR["message"]
    )

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
    """The GDPR dialog, opened from the page rather than from inside another
    dialog — the case where it is the only thing on the screen.

    The opener is the FOOTER's link since USR-COP-1. It used to be the on-page
    form's, and that form is gone; the footer link is what keeps the privacy
    statement reachable for a visitor who never opens the contact dialog at
    all, so it is also the address this test now guards.

    page.click("#gdpr-close") rather than a visibility assertion for the
    close: to_be_visible() does not hit-test, so it would pass over a panel
    buried under a backdrop. click() runs Playwright's actionability
    checks, which do hit-test — if the stacking were wrong this line fails
    and nothing else has to know why.
    """
    opener = public.locator("footer .gdpr-open")
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
        " === document.querySelector('footer .gdpr-open')"
    ), "focus was not returned to the link that opened the dialog"

    # Escape is the second close path, asserted separately so a broken
    # keyboard route cannot hide behind a working button.
    opener.click()
    expect(public.locator(".gdpr-panel")).to_be_visible()
    public.keyboard.press("Escape")
    expect(public.locator(".gdpr-dialog")).to_have_attribute("hidden", "")
    # No other dialog was ever underneath: this is the one-dialog case, and
    # the contact dialog is still shut after all of it.
    expect(public.locator(".contact-dialog")).to_have_attribute("hidden", "")


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


# --- 5. a script payload through the product's one send path ----------------


def test_a_script_payload_sent_through_the_dialog_renders_inert_in_the_inbox(
    public, page, expect, live_app, skin, shots
):
    """A <script> typed into the product's real send path renders inert in the
    real inbox.

    This is the only BROWSER-level proof that window.__pwned is undefined:
    tests/test_messages.py's inbox check is a unit-level statement about the
    template's escaping, which is a different claim from "no script executed
    in a real Chrome rendering the real page". It used to be aimed at the
    inline form; USR-COP-1 deleted that path, so it is re-aimed at the one
    that remains rather than dropped.

    Both halves are asserted. window.__pwned being undefined says the script
    never executed; the text content being the literal payload says the admin
    can actually READ what was sent, which a blunt strip would have destroyed
    while passing the first half.
    """
    marked = {
        "name": PAYLOAD,
        "email": f"{PAYLOAD}@esimerkki.fi",
        "message": f"Terveisin {PAYLOAD}",
    }
    public.click(".header-contact")
    expect(public.locator(".contact-panel")).to_be_visible()
    fill_dialog(public, marked)
    with public.expect_response("**/api/messages") as answer:
        public.click(".cd-submit")
    assert answer.value.status == 201, answer.value.text()
    assert len(stored_messages(live_app)) == 1

    page.goto(f"{live_app.base_url}/yllapito/viestit")
    expect(page.locator(".inbox-message")).to_have_count(1)
    assert page.evaluate("() => window.__pwned") is None
    assert page.locator(".inbox-name").text_content() == marked["name"]
    assert page.locator(".inbox-body").text_content() == marked["message"]
    assert page.locator(".inbox-email").text_content() == marked["email"]
    page.screenshot(
        path=os.path.join(shots, f"usr-cop1-{skin}-postilaatikko.png"),
        full_page=True,
    )


# --- 6. direct edit mode: the card's button edits, and opens no dialog -------


def test_the_send_button_edits_its_label_and_opens_no_dialog_in_direct_edit_mode(
    edit_page, expect, live_app, skin, shots
):
    """The riskiest thing this artifact creates, and its guard.

    The card's button is now BOTH a .cta-contact dialog opener and a
    data-field="send_label" editable — the exact collision LLM-COP-6 shipped
    once on the hero. While an owner is renaming it, a press must mean "edit
    me" and must not also open the dialog: the dialog's backdrop swallows
    pointer events and editing stops dead with no error anywhere.

    direct-edit.js:346-355 is the guard — one capture-phase click listener on
    the document that preventDefault()s and stopPropagation()s any click
    landing inside a [data-field]. Capture on an ancestor is what makes it beat
    contact_dialog.html's own listener, which is registered first because the
    dialog is included before this script.

    THE LOAD-BEARING ASSERTIONS are the last two. .contact-dialog has no
    layout rule of its own and can report itself hidden with the dialog wide
    open, so .contact-panel carries the visibility assertion and
    .contact-dialog's hidden ATTRIBUTE is the state that says it was never
    opened at all. tests/browser/test_browser_v2_direct_edit.py states the
    same pairing, and the two must not drift apart.

    ONE TRIGGER, not two. The keyboard leg this test used to carry was
    implicit submission — Enter in a text field reaching the form's default
    button — and there is no form on the card any more, so it would assert
    nothing.

    NOTHING HERE COUNTS POSTS, deliberately. Until USR-COP-1 this test filled
    the card's form first and asserted zero posts, because the button was a
    SUBMITTER and a failed guard would have sent what was typed. The button is
    an OPENER now and the card has no form, so "nothing was posted" is true of
    every build including a broken one — it would be a vacuous assertion, and
    the dialog-stays-shut assertions above are what carry the guard instead.
    """
    button = card_button(edit_page)
    expect(button).to_have_count(1)
    assert button.get_attribute("data-field") == "send_label"
    button.scroll_into_view_if_needed()
    button.click()

    # The click still means "edit me": the field tag names the label.
    expect(edit_page.locator(".direct-field-tag")).to_be_visible()
    edit_page.screenshot(
        path=os.path.join(shots, f"usr-cop1-{skin}-muokkaustila.png"),
        full_page=True,
    )

    expect(edit_page.locator(".contact-panel")).to_be_hidden()
    expect(edit_page.locator(".contact-dialog")).to_have_attribute("hidden", "")
