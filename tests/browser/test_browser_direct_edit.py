"""Direct in-place edit mode, driven in a real browser (LLM-COP-15) —
app/static/direct-edit.js over /muokkaa/sivu.

Four of this project's shipped defects lived in this file and none of
them is reachable without real layout, real event dispatch and a real
network: a contact dialog that stole focus and killed editing with its
backdrop; a sticky header clipped until "Ota yhteyttä" hit-tested to the
exit-edit button; and two dropped-connection paths that produced an
unhandled rejection and a silently no-op publish.

tests/test_direct_edit_css.py fences two of those by asserting CSS
literals, which is a real fence but a narrow one: it fails when the rule
is deleted and passes for every other way of breaking the same layout.
Test 2 below is the one that reads the rendered box.
"""

import json

from tests.conftest import section_rows

# The one heading the direct-edit tests type into: hero.title, cap 60
# (app/fields.py), seeded "Nimi tähän" — ten characters, so one keystroke
# reads 11 / 60.
HEADING = ".main-heading"


def hero_draft(app):
    """The hero row's draft payload, straight from the app's own DB file
    — the store, not a route's opinion of the store."""
    row = next(row for row in section_rows(app) if row["kind"] == "hero")
    return json.loads(row["draft"])


def open_direct_edit(page, live_app):
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    return page


def test_clicking_a_bound_button_edits_it_and_leaves_the_dialog_shut(
    page, expect, live_app
):
    """hero.contact_label is rendered as the page's own .cta-contact
    button, which on the public page opens the contact dialog. In edit
    mode that click must mean "edit me" and nothing else.

    The rule is one CAPTURE-phase listener on the document
    (direct-edit.js:346-355): contact_dialog.html registers its own
    listener on the element first, and listeners on one node run in
    registration order whatever their capture flag, so only an ancestor
    capturing can beat it. Flip that `true` to `false` and the dialog
    opens.

    .contact-panel, not .contact-dialog, carries the assertion:
    .contact-dialog has no layout rule of its own and its only child is
    position: fixed, so it is a zero-box wrapper that reports itself
    hidden with the dialog wide open. The hidden attribute is asserted
    separately, on the wrapper that actually carries it.

    The tag is asserted VISIBLE as well as worded. It ships `hidden` in
    direct_edit_chrome.html and activate() unhides it, so to_have_text
    alone reads the textContent of a box nobody can see: with
    `tag.hidden = false` deleted this assertion still passed. Measured.
    """
    open_direct_edit(page, live_app)
    page.click(".cta-contact")

    expect(page.locator(".direct-field-tag")).to_be_visible()
    expect(page.locator(".direct-field-tag")).to_have_text("PAINIKE 1")
    expect(page.locator(".contact-panel")).to_be_hidden()
    expect(page.locator(".contact-dialog")).to_have_attribute("hidden", "")


def test_header_contact_hit_tests_to_itself_when_scrolled(page, expect, live_app):
    """The sticky public header versus the fixed edit top bar, read off
    the rendered document rather than off the stylesheet.

    .site-header is `position: sticky; top: 0` with no z-index anywhere in
    style.css, so it loses to .direct-topbar's z-index: 30 and, once
    scrolled, is clipped until the centre of "Ota yhteyttä" resolves to
    BUTTON.direct-poistu — an owner aiming at the contact button is
    thrown out of edit mode instead. direct-edit.css:71 pins the header
    below the bar; direct-edit.css:54-70 is the app's own account of the
    defect.

    This asks the browser the question the owner's mouse asks. It fails
    for ANY way of breaking that layout — a taller top bar, a changed
    offset, a lost z-index — where the CSS test's `== "65px"` fails only
    when that one literal changes.
    """
    open_direct_edit(page, live_app)
    reading = page.evaluate(
        """() => {
            window.scrollTo(0, 600);
            const button = document.querySelector('.header-contact');
            const box = button.getBoundingClientRect();
            const hit = document.elementFromPoint(
                box.left + box.width / 2, box.top + box.height / 2
            );
            return {
                scrolled: window.scrollY,
                hit: hit ? (hit.className || '') + '|' + hit.tagName : 'null'
            };
        }"""
    )
    # A page that did not scroll would pass the hit test for the wrong
    # reason: unscrolled, the header is not yet under the bar.
    assert reading["scrolled"] > 0, reading
    assert "header-contact" in reading["hit"], reading["hit"]


def test_typing_updates_the_change_count_and_the_field_counter(page, expect, live_app):
    """The floating chrome is computed in the browser and nowhere else:
    the counter's "11 / 60" and the publish bar's change count are the
    two strings tests/test_direct_edit.py names as browser-only and
    asserts only the bootstrap they are derived from.

    .direct-counter is asserted VISIBLE, not merely worded. Both the
    counter and the change badge ship `hidden` in
    direct_edit_chrome.html and are unhidden by updateCounter /
    updateChanges; to_have_text reads textContent, which a `hidden`
    element still has. With `counter.hidden = false` deleted the
    "11 / 60" assertion still passed. Measured. The badge already had its
    to_be_visible; the counter did not.
    """
    open_direct_edit(page, live_app)
    page.click(HEADING)
    page.keyboard.type("!")

    expect(page.locator(".direct-counter")).to_be_visible()
    expect(page.locator(".direct-counter-value")).to_have_text("11 / 60")
    expect(page.locator(".direct-changes")).to_be_visible()
    expect(page.locator(".direct-changes-count")).to_have_text("1")


def test_tallenna_luonnos_stores_exactly_what_the_page_shows(page, expect, live_app):
    """Round trip through the real PUT to the real database.

    The assertion compares the store against the element's own text
    rather than against an assumed literal, on purpose: click() drops the
    caret wherever it lands, so the typed character's position is a
    browser decision and any literal here would be asserting the caret's
    behaviour by accident. What must hold is that the store and the page
    agree.

    The wait is state: a successful save rebaselines lastSaved, so the
    change badge going hidden IS the save landing (direct-edit.js:114-119).
    """
    open_direct_edit(page, live_app)
    page.click(HEADING)
    page.keyboard.type("X")
    expect(page.locator(".direct-changes-count")).to_have_text("1")

    page.click(".direct-tallenna")
    expect(page.locator(".direct-changes")).to_be_hidden()

    assert hero_draft(live_app)["title"] == page.locator(HEADING).text_content()


def test_a_dropped_save_connection_says_yhteysvirhe(page, expect, live_app):
    """A dropped connection, produced for real by aborting the route.

    The label matters more than the note appearing. direct-edit.js hangs
    this handler on the fetch ALONE (:467-476), so "yhteysvirhe" is
    honest by construction — only a request that never completed can
    reach it. Gut that handler and the outer safety net at :477 still
    paints a note, but an unattributed one, so asserting the bare
    "tallennus epäonnistui" would pass on the broken version too.
    """
    open_direct_edit(page, live_app)
    page.click(HEADING)
    page.keyboard.type("X")
    expect(page.locator(".direct-changes-count")).to_have_text("1")

    page.route("**/api/sections/*/draft", lambda route: route.abort())
    page.click(".direct-tallenna")

    expect(page.locator(".direct-errors")).to_be_visible()
    expect(page.locator(".direct-errors")).to_contain_text(
        "tallennus epäonnistui (yhteysvirhe)"
    )


def test_a_dropped_publish_connection_says_yhteysvirhe_and_stays_put(
    page, expect, live_app
):
    """The publish fetch needs its own rejection handler
    (direct-edit.js:544-551): with nothing dirty, saveDrafts resolves
    ok === true without issuing a request at all, so the save-side
    handlers are never involved and this is the only thing between a
    dropped connection and a click that visibly does nothing.

    The page must also stay where it is — a successful publish reloads,
    and reloading on a failure would hand the owner a clean page and an
    empty badge while the public site still shows the old copy. A marker
    on window is what proves that: a reload would take it with it.
    """
    open_direct_edit(page, live_app)
    page.evaluate("window.__cop15_not_reloaded = true")

    page.route("**/api/publish", lambda route: route.abort())
    page.click(".direct-julkaise")

    expect(page.locator(".direct-errors")).to_be_visible()
    expect(page.locator(".direct-errors")).to_contain_text(
        "julkaisu epäonnistui (yhteysvirhe)"
    )
    assert page.evaluate("window.__cop15_not_reloaded") is True
