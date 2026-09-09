"""The side edit panel's state machine, driven in a real browser
(LLM-COP-15) — app/static/edit.js over /muokkaa.

The panel's three interesting behaviours are all timing: a debounce that
must fire, a Peruuta that must restore the last SAVED payload rather than
the last rendered one, and a section switch that must flush a pending
write against the section it was typed into. The last is a shipped
defect — a save race that lost a keystroke while the badge said saved.

No test here sleeps. Time is page.clock's throughout: frozen, so nothing
fires by accident, and advanced explicitly where a timer is the subject.
"""

import json
import re

from tests.browser.conftest import (
    V2_STYLESHEET,
    hero_draft,
    hero_row,
    png_bytes,
    set_hero_draft_style,
)
from tests.conftest import assert_absent_from_app, section_rows

# Any instant; only its stillness matters.
FROZEN = "2026-01-01T09:00:00"


def freeze_clock(page):
    """Stop the page's clock dead, so no timer fires on its own.

    install() ALONE does not do this, which is easy to assume and wrong:
    the fake timers it installs still advance with real time, so a
    two-second debounce still fires two seconds later. Measured, in this
    worktree, before this helper existed. pause_at() is what actually
    stops the clock; fast_forward() still works against a stopped one,
    which is what makes "nothing yet" and "now" both assertable below.
    """
    page.clock.install(time=FROZEN)
    page.clock.pause_at(time=FROZEN)


def panel_input(page, label):
    """The control under one labelled field of the open section's form."""
    return (
        page.locator(".section-form .field")
        .filter(has=page.locator(".field-label", has_text=label))
        .locator("input, textarea")
        .first
    )


def test_autosave_saves_the_draft_after_the_shared_debounce(page, expect, live_app):
    """createAutosave.DELAY is 2000 ms (autosave.js:56) and nothing else
    in the panel writes on a timer, so this is the debounce itself.

    Ordering: goto, THEN freeze, then edit, then fast_forward. Freezing
    after arrival is safe because the timer is armed at EDIT time, not
    load time, so no timer this test cares about exists yet; freezing
    before navigation would additionally stop the page's own load-time
    timers for no benefit. "00:03" is MM:SS — three seconds, past the
    two-second debounce, and fast_forward fires due timers at most once,
    which is exactly right for a single debounce.

    The freeze is what makes the first assertion mean anything: on a live
    clock "not saved yet" is a claim about how fast this test ran.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    panel_input(page, "Yläotsikko").fill("AUTOSAVE")
    # Nothing has fired yet: the edit alone must not save.
    expect(page.locator(".draft-saved-note")).to_be_hidden()

    page.clock.fast_forward("00:03")
    expect(page.locator(".draft-saved-note")).to_be_visible()
    assert hero_draft(live_app)["kicker"] == "AUTOSAVE"


def test_peruuta_restores_the_last_saved_draft(page, expect, live_app):
    """Peruuta is `draft = deepCopy(lastSaved)` (edit.js:244) — the last
    payload the SERVER accepted, not the last one rendered. Drop that one
    line and the form rebuilds from the edited draft, so the note appears
    and nothing is actually restored.

    The clock is frozen, so the pending autosave cannot fire and quietly
    redefine "last saved" mid-test. That is a removed race, not a wait.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    original = panel_input(page, "Yläotsikko").input_value()
    panel_input(page, "Yläotsikko").fill("EI SAA JÄÄDÄ")

    page.click(".peruuta-button")
    expect(page.locator(".peruuta-note")).to_be_visible()
    expect(page.locator(".draft-saved-note")).to_be_hidden()
    # buildForm() replaces the control, so this re-resolves deliberately.
    expect(panel_input(page, "Yläotsikko")).to_have_value(original)


def test_switching_sections_flushes_the_pending_save_to_the_right_section(
    page, expect, live_app
):
    """openSection's first statement is autosave.flush() (edit.js:200),
    and it is first for a reason: `current`, `draft` and `lastSaved` are
    all rebound on the next three lines, so a timer that survived the
    switch resolves its section at fire time and writes the NEW section's
    untouched payload — the hero keystroke is lost while the badge says
    saved.

    Two assertions, and both are needed. The response URL names the
    symptom ("wrote the wrong section") and the database proves the
    keystroke survived. The URL alone would not catch a dropped flush if
    it only asked whether a PUT happened, because one still does — just
    against the wrong id. The database alone catches it but reports it as
    a missing keystroke, which is one inference away from the cause.

    The clock choreography is what makes this a test of flush() rather
    than a race against the debounce. Frozen, the 2 s timer cannot fire
    on its own before the click, so on a correct build the ONLY thing
    that can produce a PUT is flush(). Advancing it inside the response
    wait then gives a broken build its own rope: with flush() gone the
    surviving timer fires after `current` and `draft` have been rebound
    and writes to the new section, and the failure says so by id instead
    of merely timing out.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    panel_input(page, "Yläotsikko").fill("LENNOSSA")
    with page.expect_response("**/api/sections/*/draft") as flushed:
        page.locator(".muut-osiot-list li").first.click()
        page.clock.fast_forward("00:03")

    hero_id = hero_row(live_app)["id"]
    assert flushed.value.url.endswith(f"/api/sections/{hero_id}/draft"), (
        flushed.value.url
    )
    expect(page.locator(".section-name")).to_have_text("Tietoa minusta")
    assert hero_draft(live_app)["kicker"] == "LENNOSSA"


def test_switching_sections_shows_the_new_name_and_position(page, expect, live_app):
    """The panel is one document that repaints, so which section is open
    is only visible in the browser. Six sections, because /muokkaa loads
    them with include_hidden=True (app/edit.py:36).

    The first pair restates edit.html, which server-renders "Aloitusosio"
    and "Osio 1 / 6"; it is here as the before, not as the claim. The
    claim is the pair AFTER the click, which nothing but edit.js:205-207
    can paint — and the click itself needs a .muut-osiot-list the server
    ships empty, so an unbooted panel cannot even reach it. Measured:
    with edit.js neutered the test fails.
    """
    page.goto(f"{live_app.base_url}/muokkaa")

    expect(page.locator(".section-name")).to_have_text("Aloitusosio")
    expect(page.locator(".section-position")).to_have_text("Osio 1 / 6")

    page.locator(".muut-osiot-list li").first.click()

    expect(page.locator(".section-name")).to_have_text("Tietoa minusta")
    expect(page.locator(".section-position")).to_have_text("Osio 2 / 6")


# --- the Ulkoasu tab and the site-wide style (LLM-COP-22) -------------------
#
# The style is a field on the HERO payload whose control sits outside the
# section form, so it can be written while some OTHER section is open — a
# write path no other panel control has. These four tests are the only place
# it is exercised end to end: the tab actually showing its body, the write
# actually landing in the store, the mark actually following what is stored
# rather than what was clicked, and the drafted skin actually reaching the
# preview iframe and then the public page.
#
# NOTHING HERE ASSERTS V2'S APPEARANCE. The claim is always the stylesheet
# link or the stored value; tests/test_page_v2.py owns V2's markup and
# tests/browser/test_browser_v2_direct_edit.py owns its behaviour.


def open_a_section_that_is_not_the_hero(page, expect):
    """Open the first row of Muut osiot, so the hero is NOT the open section.

    That is the branch worth testing: with the hero open the style is just
    another field of the in-memory draft, but from here setStyle has to find
    the hero, copy ITS payload and write it — the path that can silently write
    the wrong section, or write nothing.
    """
    page.locator(".muut-osiot-list li").first.click()
    expect(page.locator(".section-name")).to_have_text("Tietoa minusta")


def test_the_ulkoasu_tab_opens_and_its_choice_saves_the_hero_draft_from_another_section(
    page, expect, live_app
):
    """The tab, the body swap and the write, from a non-hero section.

    Four things are asserted and each can fail alone: the Sisältö body hides
    and the Ulkoasu body shows (the tab wiring), no option is marked before a
    choice (the seeded "" reaching the page raw), the option gains .active
    after the write (the mark following hero.payload, which advances only on a
    successful PUT), and the DATABASE holds "v1" (the write landed on the hero
    row while a different section was open).

    The store read is the one that cannot be faked by the UI: a build that
    marked the option and wrote nothing passes the first three.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)
    open_a_section_that_is_not_the_hero(page, expect)

    page.click('.panel-tab[data-tab="ulkoasu"]')
    expect(page.locator('.panel-body[data-panel="sisalto"]')).to_be_hidden()
    expect(page.locator('.panel-body[data-panel="ulkoasu"]')).to_be_visible()

    # Nothing chosen yet: the seeded style is "", which is not one of the
    # offered values, so no option wears the mark.
    expect(page.locator(".tyyli-option.active")).to_have_count(0)
    assert hero_draft(live_app)["style"] == ""

    with page.expect_response("**/api/sections/*/draft") as written:
        page.click('.tyyli-option[data-style="v1"]')

    hero_id = hero_row(live_app)["id"]
    assert written.value.url.endswith(f"/api/sections/{hero_id}/draft"), (
        written.value.url
    )
    expect(page.locator('.tyyli-option[data-style="v1"].active')).to_have_count(1)
    assert hero_draft(live_app)["style"] == "v1"
    # The section that was open was not written over.
    assert hero_draft(live_app)["title"], "the hero payload was not truncated"


def test_a_dropped_style_write_leaves_the_choice_unmarked(
    page, expect, live_app
):
    """The mark follows the STORE, never the click — the hero-not-open rule.

    With the hero not open, the mark is read from hero.payload, and edit.js
    refreshes that only on a successful PUT. So a write that never completes
    must leave the option exactly as it was: unmarked, with "" still stored.
    A build that marked optimistically here — the obvious way to write this
    control, and the wrong one — tells the owner their site changed skin when
    it did not, and keeps telling them until they reload.

    An abort, not a timing window: route.abort() (the shipped idiom at
    tests/browser/test_browser_direct_edit.py) makes the failure deterministic
    rather than a race this test would sometimes lose.

    The second half is what makes the first half mean something. Without it,
    "nothing was marked and nothing was stored" is also true of a page where
    the button does nothing at all — so the route is removed and the same
    click is made again, and both flip.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)
    open_a_section_that_is_not_the_hero(page, expect)
    page.click('.panel-tab[data-tab="ulkoasu"]')

    page.route("**/api/sections/*/draft", lambda route: route.abort())
    with page.expect_event("requestfailed"):
        page.click('.tyyli-option[data-style="v1"]')

    expect(page.locator(".tyyli-option.active")).to_have_count(0)
    assert hero_draft(live_app)["style"] == ""

    page.unroute("**/api/sections/*/draft")
    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v1"]')

    expect(page.locator('.tyyli-option[data-style="v1"].active')).to_have_count(1)
    assert hero_draft(live_app)["style"] == "v1"


def test_the_preview_pane_shows_the_drafted_skin_and_julkaise_takes_it_public(
    page, expect, live_app
):
    """Draft -> preview -> publish, in a real browser, end to end.

    The preview pane is an iframe of /muokkaa/esikatselu (edit.html), so this
    is the only place the drafted skin is seen the way the owner sees it:
    inside the pane, while the public page still serves the published one.
    Julkaise is then the real button and the real POST /api/publish.

    WHY THE STYLE IS PLANTED BEFORE THE PAGE LOADS, stated because an earlier
    draft of this test claimed otherwise: with the draft already written there
    is no putDraft in flight when Julkaise is clicked, so this does NOT
    demonstrate julkaise waiting on a style write. It demonstrates the cycle —
    a drafted style previews, does not leak to the public page, and publishes.
    That is what it is for, and the claim is kept to it.

    The public page is a SECOND tab rather than a navigation away and back,
    so the panel is never reloaded and the publish is the only thing that can
    move it.
    """
    set_hero_draft_style(live_app, "v2")
    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    expect(public.locator(V2_STYLESHEET)).to_have_count(0)

    page.goto(f"{live_app.base_url}/muokkaa")
    # The pane follows the DRAFT: a preview that ignored the drafted skin
    # would show the owner a page they are not about to publish.
    expect(
        page.frame_locator(".preview").locator(V2_STYLESHEET)
    ).to_have_count(1)
    # ...and the public page has not moved.
    public.reload()
    expect(public.locator(V2_STYLESHEET)).to_have_count(0)

    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public.reload()
    expect(public.locator(V2_STYLESHEET)).to_have_count(1)
    public.close()


def test_the_real_direct_edit_route_serves_the_v2_skin_when_the_draft_says_so(
    page, expect, live_app
):
    """/muokkaa/sivu, asked whether direct-edit.js BOOTS on the served skin.

    tests/test_style_selection.py already asserts server-side that this route
    selects page_v2.html and links style-v2.css. This test earns its seconds
    for the one thing that check cannot show: .direct-tallenna actually
    coming up over V2.

    tests/browser/test_browser_v2_direct_edit.py's eight tests now reach this
    same URL (LLM-COP-24 deleted the test-local harness route they used). What
    the harness gave them was that it named page_v2.html literally and could
    not fall back; an unknown style resolves to V1 by design, so a subtly
    wrong selection would serve them V1 and they would type into V1's
    bindings and pass. Their fixture asserts the served document is V2 before
    yielding, which is that property restored on the real URL.
    """
    set_hero_draft_style(live_app, "v2")

    page.goto(f"{live_app.base_url}/muokkaa/sivu")

    expect(page.locator(V2_STYLESHEET)).to_have_count(1)
    expect(page.locator(".direct-tallenna")).to_be_visible()


# --- the owner's whole cycle, on the real control (LLM-COP-24) -------------


def style_bytes(app):
    """Every row's (draft, published), keyed by kind.

    previous_published is deliberately NOT in here, and leaving it out is a
    measured decision rather than a convenience: publish_dirty sets
    previous_published = published on every publish (app/sections.py), so
    after v1 -> v2 -> v1 the hero's previous_published legitimately holds the
    v2 payload. A whole-row comparison goes red on CORRECT code — measured,
    on the hero, on this tree. The two columns that must not move are these.
    """
    return {
        row["kind"]: (row["draft"], row["published"])
        for row in section_rows(app)
    }


def row_badges(page, base_url):
    """The badges as the OWNER sees them, off /muokkaa/osiot's own document.

    A second tab, so the panel under test is never reloaded and the publish
    stays the only thing that can move anything.
    """
    rows = page.context.new_page()
    rows.goto(f"{base_url}/muokkaa/osiot")
    badges = rows.locator(".row-status-badge").all_text_contents()
    rows.close()
    return badges


def test_choosing_kuvallinen_publishing_and_going_back_moves_nothing(
    page, expect, live_app
):
    """The artifact's reviewer checklist, driven end to end on the real
    control: a site with all six kinds published renders all six under V2,
    and switching V1 -> V2 -> V1 leaves every payload and every badge where
    it found them.

    WHAT IS NEW HERE versus the draft/preview/publish test above, which
    already runs a v2 cycle: that one PLANTS the style in the store, because
    when it was written no control existed to click. This one clicks
    .tyyli-option[data-style="v2"] — a button that exists only because
    LLM-COP-24 appended a tuple to STYLE_CHOICES — and then reads the public
    page the owner would send a client to.

    WHY THE BASELINE IS CUT AFTER THE FIRST Perus + Julkaise, not at the
    seed. app/seed.py stores style "" rather than "v1", so the first v1 write
    is a real content change: it dirties the hero, flips its badge to
    Luonnos, and moves its bytes. All of that is correct. Comparing the end
    of the round trip against the SEED would therefore fail on a correct
    build. The round trip this test is about starts once a style has actually
    been chosen and published.

    THE PREMISE IS ASSERTED, NOT ASSUMED. The claim is "a site with ALL SIX
    kinds published renders all six", and the comparison further down is
    drawn == published — both sides read from the same store. So on a site
    with five kinds published the comparison is still true and this test
    still passes, while the claim it is quoted for has quietly stopped being
    proven. Measured: hide sijainti before this line and every assertion
    below stays green. Naming the six here is what makes the quantity part
    of the claim rather than a property of whatever the seed happens to do.
    """
    premise = sorted(
        row["kind"] for row in section_rows(live_app) if row["state"] == "published"
    )
    assert premise == [
        "hero",
        "palvelut",
        "sijainti",
        "tietoa",
        "vastaanottoajat",
        "yhteydenotto",
    ], f"this test is quoted for ALL SIX kinds; this site publishes {premise}"

    page.goto(f"{live_app.base_url}/muokkaa")
    page.click('.panel-tab[data-tab="ulkoasu"]')

    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v1"]')
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    baseline = style_bytes(live_app)
    baseline_badges = row_badges(page, live_app.base_url)
    assert baseline_badges, "no rows on /muokkaa/osiot to compare"

    # The real control, which only exists now that V2 is offered.
    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v2"]')
    expect(
        page.locator('.tyyli-option[data-style="v2"].active')
    ).to_have_count(1)
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    # ...and the public page really is V2, with nothing published missing
    # from it. A second tab, so the panel is never reloaded.
    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    expect(public.locator(V2_STYLESHEET)).to_have_count(1)

    published_kinds = sorted(
        row["kind"] for row in section_rows(live_app) if row["state"] == "published"
    )
    drawn = public.eval_on_selector_all(
        "main section[data-kind]",
        "els => els.map(el => el.getAttribute('data-kind'))",
    )
    assert sorted(drawn) == published_kinds, (sorted(drawn), published_kinds)
    # Present in the markup is not the promise; the promise is that nothing
    # published disappears from the PAGE.
    collapsed = public.eval_on_selector_all(
        "main section[data-kind]",
        """els => els.filter(el => {
            const box = el.getBoundingClientRect();
            return box.width === 0 || box.height === 0;
        }).map(el => el.getAttribute('data-kind'))""",
    )
    assert collapsed == [], collapsed
    public.close()

    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v1"]')
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    assert style_bytes(live_app) == baseline
    assert row_badges(page, live_app.base_url) == baseline_badges


# --- the portrait and its alt text, on the owner's own path (LLM-COP-25) ---

# Words no template could have produced: asserted absent from app/ inside the
# test, so an alt attribute that matched would have to have come from what was
# typed. Deliberately ordinary Finnish prose, which is what an owner writes.
PORTRAIT_ALT = "Vaaleahiuksinen henkilö sinisessä paidassa, rajattu olkapäistä"
RENAMED_KICKER = "TÄLLAISTA TYÖ ON KANSSANI"


def portrait_is_loaded(page, selector):
    """True once the browser has DECODED the picture at `selector`.

    naturalWidth, not the attribute: `src` and `alt` in the markup are what
    the server sent, and a broken reference — a digest with no bytes behind
    it, a serving route that 404s, a Content-Type the browser refuses —
    leaves both attributes exactly as they are while the page shows nothing.
    An alt attribute with no image behind it is not accessible alternative
    text; it is a description of a picture that is not there.
    """
    page.wait_for_function(
        """selector => {
            const el = document.querySelector(selector);
            return !!el && el.complete && el.naturalWidth > 0;
        }""",
        arg=selector,
    )
    return True


def test_the_owner_uploads_a_portrait_types_its_alt_text_and_both_go_public(
    page, expect, live_app, tmp_path
):
    """The whole of LLM-COP-25's group-1 claim, on the path the OWNER walks.

    This is the answer to "can the owner actually set it", and nothing here
    is short-cut. The picture goes in through the real .vaihda-input, whose
    change handler (app/static/edit.js) performs the real POST /api/kuvat and
    then the real draft save. The alt text is TYPED into the panel row
    labelled Muotokuvan tekstivastine — the row exists only because the key
    carries a FIELD_LABELS entry, and it is the only editor the value has,
    since an alt attribute is not a text node the in-place editor can reach.
    Julkaise is the real button and the real POST /api/publish. The public
    page is then read in a second tab, so the panel is never reloaded and the
    publish is the only thing that can have moved it.

    Nothing in tests/browser/ uploaded a file before this test, so the
    control had never been driven in a browser at all: every earlier proof
    that /api/kuvat works goes through the Python test client, which builds
    the multipart body itself rather than letting Chrome build it.

    THE TWO ASSERTIONS AT THE END ARE ONE CLAIM. The alt attribute says the
    words reached the markup; naturalWidth says the picture reached the
    screen. Either alone is satisfied by a broken build — an alt on an image
    that never loads, or an image with no description — and the feature is
    the pair.

    The clock is frozen so the 2 s autosave debounce is a thing this test
    advances deliberately rather than a race it runs against.
    """
    assert_absent_from_app(PORTRAIT_ALT)
    picture = tmp_path / "muotokuva.png"
    picture.write_bytes(png_bytes())

    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    # The upload row is hero-only and hidden for every other section
    # (edit.js), so its visibility here is part of the claim that this is
    # the owner's real path rather than a control reached by selector alone.
    expect(page.locator(".muotokuva-row")).to_be_visible()

    # setPortrait saves immediately rather than on the debounce, so the draft
    # PUT is what says the upload came back and was written — one wait for
    # both, and a failure to upload times out here rather than three
    # assertions later.
    # BOTH selectors are scoped to .muotokuva-row since LLM-COP-30 put a
    # second picture row in this panel. .vaihda-input now matches twice, and
    # page-level selector methods are NOT strict in Playwright — set_input_files
    # would silently take whichever row came first in the DOM and upload into
    # the wrong field, failing as what reads like a product bug. The error
    # element does not collide (the other row's is .taustakuva-error) but is
    # scoped anyway, so this resolves to one element by the selector rather
    # than by a naming convention stated nowhere in this file.
    with page.expect_response("**/api/sections/*/draft"):
        page.set_input_files(".muotokuva-row .vaihda-input", str(picture))
    expect(page.locator(".muotokuva-row .muotokuva-error")).to_be_hidden()

    stored = hero_draft(live_app)["portrait"]
    assert len(stored) == 64, f"portrait is not a digest: {stored!r}"

    # The alt text, typed into the panel's own row.
    panel_input(page, "Muotokuvan tekstivastine").fill(PORTRAIT_ALT)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")
    assert hero_draft(live_app)["portrait_alt"] == PORTRAIT_ALT

    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    image = public.locator("img.portrait-image")
    expect(image).to_have_attribute("alt", PORTRAIT_ALT)
    assert portrait_is_loaded(public, "img.portrait-image")
    assert image.get_attribute("src") == f"/kuvat/{stored}"
    public.close()


# --- the hero's two pictures, on the owner's own path (LLM-COP-30) ---------

# The second alt text. Ordinary Finnish prose describing a LANDSCAPE, so the
# two strings could not be swapped without the swap reading as nonsense —
# and asserted absent from app/ inside the test, so an attribute that matched
# had to have come from what was typed.
BACKGROUND_ALT = "Vastaanottohuone aamuvalossa, leveä näkymä ikkunasta"

# The third (LLM-COP-28), belonging to the Tietoa band's OWN picture rather
# than to either hero field. A third distinct subject for the same reason the
# second is a landscape: three strings that could be swapped without reading
# as nonsense would let a build pair the right alt with the wrong src and
# still pass.
SECTION_ALT = "Työpöytä ja avoin muistikirja, kuvattu ylhäältä"


def section_draft(app, kind):
    """One section's DRAFT payload from the live app's own store.

    hero_draft's sibling for the kinds that are not the hero. LLM-COP-28 put
    a picture on four of them, so "which payload did the row write into" is a
    question this layer now has to be able to ask of a section other than the
    hero — and asking it of the store rather than of the panel is what makes
    the answer independent of the code that wrote it.
    """
    row = next(r for r in section_rows(app) if r["kind"] == kind)
    return json.loads(row["draft"])


def test_the_owner_sets_two_different_hero_pictures_and_both_go_public(
    page, expect, live_app, tmp_path
):
    """THE ARTIFACT'S OWN COMPLAINT, executable: the owner supplies TWO
    pictures and the published V2 page shows two.

    Before LLM-COP-30 the panel had one picture control and page_v2.html
    painted that one reference twice — the full-bleed hero photograph and the
    tietoa band's circle were the same image, and no owner could make them
    differ. Every other test of this change asks part of that question of a
    template, a payload or a column. This one asks the whole of it of a real
    Chrome, on the path the owner actually walks, and the sentence it makes
    executable is the last assertion: the two rendered srcs are not equal.

    NOTHING IS SHORT-CUT. Both files go in through the real .vaihda-input,
    whose change handler performs the real POST /api/kuvat and the real draft
    save. Both alt texts are TYPED into the panel's own generated rows. The
    skin is chosen with the real .tyyli-option, Julkaise is the real button
    and the real POST /api/publish, and the public page is read in a SECOND
    TAB so the panel is never reloaded and the publish is the only thing that
    can have moved it.

    THE TWO PICTURES ARE VISIBLY DIFFERENT — different sizes AND different
    colours, so they are different bytes and therefore different digests.
    /api/kuvat dedupes by content, so two identical PNGs would answer one ref
    and this test could not tell the two bands apart at all; the colours are
    what make the screenshots below legible as a fix rather than as a
    coincidence.

    EACH IMAGE IS ASSERTED AS A TRIPLE — src, alt and naturalWidth. src and
    alt together are what make the two references distinguishable: a build
    that fed the hero from portrait again puts the right alt beside the wrong
    picture and fails a named line rather than an arithmetic one.
    naturalWidth is the third, because an alt attribute on an image that
    never loaded describes nothing (portrait_is_loaded, above).

    The clock is frozen so the 2 s autosave debounce is a thing this test
    advances deliberately rather than a race it runs against.
    """
    assert_absent_from_app(PORTRAIT_ALT)
    assert_absent_from_app(BACKGROUND_ALT)
    assert_absent_from_app(SECTION_ALT)
    portrait_file = tmp_path / "muotokuva.png"
    portrait_file.write_bytes(png_bytes(64, 64, (0x2E, 0x6F, 0x9E)))
    background_file = tmp_path / "taustakuva.png"
    background_file.write_bytes(png_bytes(96, 48, (0xC8, 0x78, 0x3C)))
    # A third, for the Tietoa band's own picture (LLM-COP-28). A third size
    # AND a third colour, because /api/kuvat dedupes by content: two
    # identical PNGs answer one ref, and this test's whole arithmetic is that
    # three uploads give three digests.
    section_file = tmp_path / "osiokuva.png"
    section_file.write_bytes(png_bytes(72, 56, (0x4C, 0x8B, 0x5A)))
    assert (
        len(
            {
                portrait_file.read_bytes(),
                background_file.read_bytes(),
                section_file.read_bytes(),
            }
        )
        == 3
    )

    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    # V2 first, through the real control: the hero band this whole artifact
    # is about exists only on that skin, so nothing below would be about it
    # otherwise. Choosing the style is a write, not a preference.
    page.click('.panel-tab[data-tab="ulkoasu"]')
    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v2"]')
    page.click('.panel-tab[data-tab="sisalto"]')

    # Two picture rows, both visible on the hero. The background row's Poista
    # is hidden while the field is empty — the same hidden-attribute rule the
    # portrait row has always followed, asked of the new row so "it renders"
    # is not mistaken for "it is wired".
    portrait_row = page.locator('.kuva-row[data-field="portrait"]')
    background_row = page.locator('.kuva-row[data-field="background"]')
    # KEPT, AND LOAD-BEARING FOR A DECISION SINCE LLM-COP-28. V2 is the open
    # skin here, chosen through the real control above, and page_v2.html no
    # longer draws hero.portrait at all — the tietoa band reads its own
    # tietoa.image now. The Muotokuva row stays visible on that skin anyway,
    # deliberately: DEFAULT_STYLE is "v1", so an owner who switches back
    # tomorrow must find their photograph already there, and a hidden row
    # would leave a stored digest REFERENCED (app/images.py counts it) with
    # no control anywhere in the product able to clear it. This line is where
    # that decision is falsifiable.
    expect(portrait_row).to_be_visible()
    expect(background_row).to_be_visible()
    expect(background_row.locator(".poista-button")).to_be_hidden()

    # The rows belong to the hero and must leave with it. Asserted here
    # because edit.js has always SET .hidden on the picture row while
    # .muotokuva-row's author-origin `display: flex` beat the UA sheet's
    # [hidden] { display: none } by origin, so the row was drawn on every
    # section until LLM-COP-30 added .kuva-row[hidden]. Both rows are
    # asserted still ATTACHED as well as not visible: to_be_hidden passes
    # for an element that is not in the document at all, so the count is
    # what makes "hidden" mean hidden rather than "never rendered".
    #
    # THREE rows since LLM-COP-28, not two, and this number is a deliberate
    # load-bearing edit rather than a re-baseline: the generic section
    # picture row (.osiokuva-row) is the third, and it is exactly the row
    # that must be VISIBLE on Tietoa while these two are hidden. Bumping the
    # count without asserting that would have turned this line from a guard
    # into a tally.
    open_a_section_that_is_not_the_hero(page, expect)
    expect(page.locator(".kuva-row")).to_have_count(3)
    expect(portrait_row).to_be_hidden()
    expect(background_row).to_be_hidden()
    expect(page.locator(".osiokuva-row")).to_be_visible()

    # Muut osiot lists every section except the open one, in order, so with
    # Tietoa open the hero is its FIRST row.
    page.locator(".muut-osiot-list li").first.click()
    expect(page.locator(".section-name")).to_have_text("Aloitusosio")
    expect(portrait_row).to_be_visible()
    expect(background_row).to_be_visible()

    # --- the portrait: the person -----------------------------------------
    #
    # Scoped to its row. .vaihda-input matches TWICE in this document now,
    # and page-level selector methods are not strict in Playwright, so an
    # unscoped call would silently take whichever row came first in the DOM.
    with page.expect_response("**/api/sections/*/draft"):
        page.set_input_files(".muotokuva-row .vaihda-input", str(portrait_file))
    expect(page.locator(".muotokuva-row .muotokuva-error")).to_be_hidden()

    panel_input(page, "Muotokuvan tekstivastine").fill(PORTRAIT_ALT)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")

    # --- the background: the photograph behind the hero card --------------
    #
    # Reached by data-field rather than by position, so a reordering of the
    # two rows in edit.html cannot make this test upload into the other one.
    with page.expect_response("**/api/sections/*/draft"):
        page.set_input_files(
            '.kuva-row[data-field="background"] .vaihda-input',
            str(background_file),
        )
    expect(page.locator(".taustakuva-row .taustakuva-error")).to_be_hidden()
    expect(background_row.locator(".poista-button")).to_be_visible()

    panel_input(page, "Taustakuvan tekstivastine").fill(BACKGROUND_ALT)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")

    # TWO REFERENCES, AND THEY DIFFER. This is the claim the panel had no way
    # of making before this change: one control could only ever store one.
    stored = hero_draft(live_app)
    portrait_ref = stored["portrait"]
    background_ref = stored["background"]
    for name, ref in (("portrait", portrait_ref), ("background", background_ref)):
        assert len(ref) == 64, f"{name} is not a digest: {ref!r}"
        assert set(ref) <= set("0123456789abcdef"), f"{name}: {ref!r}"
    assert portrait_ref != background_ref, (
        "both rows stored the same digest, so the panel still has one picture"
    )
    assert stored["portrait_alt"] == PORTRAIT_ALT
    assert stored["background_alt"] == BACKGROUND_ALT

    # The panel with both rows populated, for a person who would rather look
    # than read. tmp_path and nothing else: this test names no absolute path
    # and nothing outside the repository, so it passes on any machine.
    #
    # Scrolled back to the picture rows first: fill() left the panel at its
    # last text row, and a screenshot named "kaksi riviä" that does not show
    # the two rows is a picture of nothing.
    portrait_row.scroll_into_view_if_needed()
    page.screenshot(
        path=str(tmp_path / "cop30-paneeli-kaksi-riviä.png"), full_page=True
    )

    # --- the band's own picture (LLM-COP-28) ------------------------------
    #
    # A THIRD picture, and it is what the V2 circle draws now. Until this
    # artifact that circle was fed hero.portrait, hoisted across the section
    # boundary by the template; the band that draws a picture is the section
    # that STORES it now, so the picture goes in through the generic
    # .osiokuva-row with TIETOA open — a different section's panel, a
    # different row, a different payload.
    #
    # Scoped to the row for the reason the two above are, and one step
    # sharper: .vaihda-input matches THREE times in this document now.
    open_a_section_that_is_not_the_hero(page, expect)
    expect(page.locator(".osiokuva-row")).to_be_visible()
    with page.expect_response("**/api/sections/*/draft"):
        page.set_input_files(".osiokuva-row .vaihda-input", str(section_file))
    expect(page.locator(".osiokuva-row .osiokuva-error")).to_be_hidden()

    panel_input(page, "Kuvan tekstivastine").fill(SECTION_ALT)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")

    tietoa = section_draft(live_app, "tietoa")
    section_ref = tietoa["image"]
    assert len(section_ref) == 64, f"image is not a digest: {section_ref!r}"
    assert set(section_ref) <= set("0123456789abcdef"), section_ref
    assert tietoa["image_alt"] == SECTION_ALT
    # THREE references, all different, across TWO sections. The hero row
    # still wrote the hero's own field — that is Decision 3's evidence that
    # the control still works on the skin that no longer draws it.
    assert len({portrait_ref, background_ref, section_ref}) == 3

    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    # The skin first, or nothing below is about V2.
    expect(public.locator(V2_STYLESHEET)).to_have_count(1)

    # The circle is fed by tietoa.image since LLM-COP-28, NOT by
    # hero.portrait. The locator stays strict — expect() fails on two
    # matches rather than taking the first — and it resolves to one element
    # because exactly one band carries a picture in this scenario: tietoa.
    # Any future scenario here that wants two media bands has to scope by
    # section[data-kind="…"] first.
    expected = {
        "img.v2-hero-image": (background_ref, BACKGROUND_ALT),
        ".v2-band-media img.portrait-image": (section_ref, SECTION_ALT),
    }
    rendered = {}
    for selector, (expected_ref, expected_alt) in expected.items():
        image = public.locator(selector)
        expect(image).to_have_attribute("alt", expected_alt)
        assert portrait_is_loaded(public, selector), selector
        rendered[selector] = image.get_attribute("src")
        assert rendered[selector] == f"/kuvat/{expected_ref}", selector

    # The author's sentence, executable: two pictures, not one drawn twice.
    assert len(set(rendered.values())) == 2, rendered

    # And the hero portrait — stored, still edited from a row that is
    # visible on this skin — reaches this document nowhere. Decision 3 as an
    # assertion in a real browser rather than as prose.
    served = public.content()
    assert portrait_ref not in served
    assert PORTRAIT_ALT not in served

    public.screenshot(
        path=str(tmp_path / "cop30-julkinen-v2.png"), full_page=True
    )
    public.close()


def test_a_renamed_section_label_reaches_the_public_page(
    page, expect, live_app
):
    """Group 3's claim in a real browser: the owner renames a kicker in the
    panel and the new words are what a visitor reads.

    tests/test_page.py proves the same thing server-side against strings
    absent from app/. This adds the part a rendered document cannot show —
    that the row is reachable and typeable in the panel of a section that is
    NOT the hero (openSection rebuilds the form per kind), and that the value
    survives the debounce, the publish and the round trip to the public page.

    Palvelut, deliberately: its kicker is drawn by the shared prose_band
    macro under V2 and by its own line under V1, and it is one of the three
    criteria this change demoted on the spec.
    """
    assert_absent_from_app(RENAMED_KICKER)

    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    # The other-sections list is how an owner reaches a non-hero panel. The
    # rows carry no kind attribute, so they are found the way the owner finds
    # them: by the name printed on them (SECTION_NAMES in app/fields.py).
    page.locator(".muut-osiot-list li").filter(
        has=page.locator(".muut-osiot-name", has_text="Palvelut")
    ).first.click()
    expect(page.locator(".section-name")).to_have_text("Palvelut")

    panel_input(page, "Osion otsikko").fill(RENAMED_KICKER)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    expect(
        public.locator('section[data-kind="palvelut"] .section-kicker')
    ).to_have_text(RENAMED_KICKER)
    # The nav link that points at this section is NOT renameable: it comes
    # from NAV_LABELS, which stays product chrome. Asserted so the known
    # divergence is recorded by a test rather than discovered in a
    # screenshot — and so a later unit that wires the nav to section_label
    # trips this line instead of four spec criteria.
    expect(public.locator("nav")).to_contain_text("Palvelut")
    public.close()


# --- USR-COP-4: the availability notice, in a real browser ------------------

NOTICE_SENTENCE = "Ajanvaraus on tauolla kesäkuun ajan"


def yhteydenotto_draft(app):
    """The contact section's drafted payload, out of the app's own store."""
    row = next(r for r in section_rows(app) if r["kind"] == "yhteydenotto")
    return json.loads(row["draft"])


def test_the_owner_writes_a_notice_switches_it_on_and_off_and_keeps_the_text(
    page, expect, live_app
):
    """The whole feature in one owner's hands, and the half no server-side
    test can show.

    tests/test_page.py and tests/test_page_v2.py prove that the resolver
    decides and that "off" means absent from the served bytes. What they
    cannot show is that an owner can reach any of it: that the toggle is a
    real control in the panel, that ticking it writes without touching the
    text, and — the assertion this feature exists for — that after switching
    the notice OFF the sentence is still sitting in the Ilmoitusteksti box,
    ready to switch back on. One field where empty means off would pass every
    server-side test in this repo and fail that last line.

    The hidden-with-the-hero assertion at the top is not decoration. edit.js
    sets .hidden on this row for every non-yhteydenotto section, but
    .ilmoitus-row declares `display: flex`, and an author-origin display
    beats the UA sheet's [hidden] { display: none } by origin — which is
    exactly how the portrait row leaked into every section until LLM-COP-30
    added .kuva-row[hidden]. This row's companion rule is asserted here so
    that defect cannot ship a second time. ATTACHED as well as not visible,
    for the reason the picture-row test states: to_be_hidden passes for an
    element that is not in the document at all.
    """
    assert_absent_from_app(NOTICE_SENTENCE)

    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    # The hero is the section the panel opens on, so this is the [hidden]
    # check in the state cp-main-edit's own screenshots were captured in.
    expect(page.locator(".section-name")).to_have_text("Aloitusosio")
    expect(page.locator(".ilmoitus-row")).to_have_count(1)
    expect(page.locator(".ilmoitus-row")).to_be_hidden()

    page.locator(".muut-osiot-list li").filter(
        has=page.locator(".muut-osiot-name", has_text="Yhteydenottolomake")
    ).first.click()
    expect(page.locator(".section-name")).to_have_text("Yhteydenottolomake")
    expect(page.locator(".ilmoitus-row")).to_be_visible()
    # Nothing is ticked before the owner ticks it: the seed stores "" for
    # notice_on, and what the box shows is what is STORED — the same rule the
    # style mark and the colour swatches follow.
    expect(page.locator(".ilmoitus-toggle")).not_to_be_checked()

    # The text first, through the generated form's own row. It is drawn LAST
    # because notice_text is declared last in its kind, which is what puts it
    # directly above the toggle rather than far from it.
    panel_input(page, "Ilmoitusteksti").fill(NOTICE_SENTENCE)
    with page.expect_response("**/api/sections/*/draft"):
        page.clock.fast_forward("00:03")

    # Typing the text alone must not publish a notice: the flag is still "".
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")
    public = page.context.new_page()
    public.goto(f"{live_app.base_url}/")
    expect(public.locator(".contact-notice")).to_have_count(0)

    # Now the toggle. A click IS the write here — no debounce — so the
    # response is awaited on the click itself.
    with page.expect_response("**/api/sections/*/draft"):
        page.click(".ilmoitus-toggle")
    expect(page.locator(".ilmoitus-toggle")).to_be_checked()
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public.reload()
    expect(public.locator(".contact-notice")).to_have_text(NOTICE_SENTENCE)

    # And off again, WITHOUT touching Ilmoitusteksti.
    with page.expect_response("**/api/sections/*/draft"):
        page.click(".ilmoitus-toggle")
    expect(page.locator(".ilmoitus-toggle")).not_to_be_checked()
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")

    public.reload()
    # Gone from the page, and gone from the BYTES — not merely invisible.
    # This is the assertion an always-emitted `hidden` paragraph would fail,
    # and the reason the render is conditional at all.
    expect(public.locator(".contact-notice")).to_have_count(0)
    assert NOTICE_SENTENCE not in public.content()
    public.close()

    # THE LINE THE FEATURE IS FOR: the owner's sentence is still in the box.
    expect(panel_input(page, "Ilmoitusteksti")).to_have_value(NOTICE_SENTENCE)

    # And it survives leaving the section and coming back, which is where a
    # value held only in an unsaved DOM node would be lost.
    page.locator(".muut-osiot-list li").first.click()
    expect(page.locator(".ilmoitus-row")).to_be_hidden()
    page.locator(".muut-osiot-list li").filter(
        has=page.locator(".muut-osiot-name", has_text="Yhteydenottolomake")
    ).first.click()
    expect(panel_input(page, "Ilmoitusteksti")).to_have_value(NOTICE_SENTENCE)
    expect(page.locator(".ilmoitus-toggle")).not_to_be_checked()


def test_peruuta_puts_the_notice_box_back_to_what_is_stored(page, expect, live_app):
    """The toggle is the fourth writer of `draft`, so Peruuta owes it the
    same refresh it already pays refreshImageRows and the style mark.

    The route is what makes the tick optimistic: the click writes
    draft.notice_on = "on" and saves at once, the PUT never lands, so
    lastSaved still holds the seeded "". Peruuta then restores that draft
    and the box must follow it down. Without refreshNoticeRow() in the
    Peruuta handler the box stays ticked over a store that says off — the
    panel promises a notice every later save writes away, and it heals
    only by leaving the section and coming back.

    An abort rather than a rejected payload, for the reason the style test
    gives: it makes the failed write deterministic instead of a race.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)
    page.locator(".muut-osiot-list li").filter(
        has=page.locator(".muut-osiot-name", has_text="Yhteydenottolomake")
    ).first.click()
    expect(page.locator(".section-name")).to_have_text("Yhteydenottolomake")
    expect(page.locator(".ilmoitus-toggle")).not_to_be_checked()

    page.route("**/api/sections/*/draft", lambda route: route.abort())
    with page.expect_event("requestfailed"):
        page.click(".ilmoitus-toggle")
    # The click itself ticks the box — that much is the browser's own doing.
    expect(page.locator(".ilmoitus-toggle")).to_be_checked()
    assert yhteydenotto_draft(live_app)["notice_on"] == ""
    page.unroute("**/api/sections/*/draft")

    page.click(".peruuta-button")
    expect(page.locator(".peruuta-note")).to_be_visible()
    expect(page.locator(".ilmoitus-toggle")).not_to_be_checked()

    # And the second half, so "unticked" is not merely true of a panel whose
    # toggle never moves: the same click, with the write allowed through.
    with page.expect_response("**/api/sections/*/draft"):
        page.click(".ilmoitus-toggle")
    expect(page.locator(".ilmoitus-toggle")).to_be_checked()
    assert yhteydenotto_draft(live_app)["notice_on"] == "on"
    page.click(".peruuta-button")
    expect(page.locator(".ilmoitus-toggle")).to_be_checked()


# --- the section picture row and its shape (LLM-COP-28) --------------------


def computed(locator, prop, pseudo=None):
    """One CSS property as the BROWSER computed it, not as a file declares it.

    The whole reason this test is in this directory. A server test can read a
    stylesheet and a rendered class attribute and still be wrong about both
    of the things that matter here: whether a row with [hidden] is actually
    drawn, and what border-radius a .portrait ends up with once the cascade
    has run. Four incidents in this project have been exactly that collision
    — an author-origin `display` beating the UA sheet's [hidden] rule — and
    none of them was findable from markup.
    """
    return locator.evaluate(
        "(el, a) => getComputedStyle(el, a.pseudo).getPropertyValue(a.name)",
        {"name": prop, "pseudo": pseudo},
    )


def test_the_section_picture_and_shape_rows_belong_to_the_kinds_that_declare_them(
    page, expect, live_app, tmp_path
):
    """The panel's newest two rows, asked of a real browser: which sections
    show them, and what the shape they store actually does to the page.

    FIVE CLAIMS, and each fails on its own line.

    1. VISIBILITY IS PER-FIELD NOW, not per-section. Until this artifact
       edit.js applied ONE boolean to every picture row — `section.kind !==
       "hero"` — which was right only while the hero was the only kind with a
       picture. It asks the SCHEMA now: does the open section's kind declare
       this row's field? So on the hero the two hero rows show and the
       section row does not, and on Tietoa the reverse. Both directions are
       asserted, in one rendering each, because a rule that showed everything
       would satisfy either half alone.

    2. HIDDEN MEANS HIDDEN, NOT ABSENT. `expect(...).to_be_hidden()` passes
       for an element that is not in the document at all, so the row count is
       what makes the claim mean something: three .kuva-rows exist on both
       sections and their visibility is what changes. This is the assertion
       that would have caught the shipped defect .kuva-row had once — edit.js
       set `hidden` while an author-origin `display: flex` beat the UA
       sheet's `[hidden] { display: none }` by origin, so the row was drawn on
       every section and no server test could see it.

    3. THE SHAPE ROW IS NOT A .kuva-row and gets the same treatment anyway.
       It has no uploader and no error element, and .kuva-row is both
       edit.js's picture-row loop and this suite's scoping handle, so it
       carries its own classes and its own toggle — and therefore its own
       `[hidden]` rule, which is the line that has been forgotten four times.

    4. THE CLICK IS THE WRITE. Neliö saves at once rather than on the
       debounce, so the stored draft is read straight after the response
       without advancing the clock. The neighbouring keys are asserted
       untouched, and so is the WHOLE HERO PAYLOAD: the row belongs to the
       section it is visible for, so a write that reached the hero would be
       the "which section is open" bug this design exists to avoid.

    5. THE SHAPE REACHES THE PAGE, and this is asserted from COMPUTED STYLE
       in the preview frame rather than from the class attribute. A class
       named `square` with no rule behind it is a picture that is still
       round, and markup cannot tell the two apart.

       The comparison is TEMPORAL — 50% before the click, 0px after, the same
       element — rather than two .portrait elements side by side. That is
       deliberate: a second band carrying a picture would give
       `.v2-band-media img.portrait-image` two matches, and Playwright's
       expect() is STRICT, so the sibling test in this file that reads that
       locator would break for a reason having nothing to do with its
       subject. One element observed twice needs no second band at all.

    V2 is chosen through the real Ulkoasu control first, because the band
    that draws this picture exists only on that skin.
    """
    section_file = tmp_path / "osiokuva.png"
    section_file.write_bytes(png_bytes(72, 56, (0x4C, 0x8B, 0x5A)))

    page.goto(f"{live_app.base_url}/muokkaa")
    freeze_clock(page)

    page.click('.panel-tab[data-tab="ulkoasu"]')
    with page.expect_response("**/api/sections/*/draft"):
        page.click('.tyyli-option[data-style="v2"]')
    page.click('.panel-tab[data-tab="sisalto"]')
    expect(
        page.frame_locator(".preview").locator(V2_STYLESHEET)
    ).to_have_count(1)

    portrait_row = page.locator(".muotokuva-row")
    background_row = page.locator(".taustakuva-row")
    section_row = page.locator(".osiokuva-row")
    shape_row = page.locator(".muoto-row")

    # --- claim 1a and 2: the hero -----------------------------------------
    expect(page.locator(".kuva-row")).to_have_count(3)
    expect(shape_row).to_have_count(1)
    expect(portrait_row).to_be_visible()
    expect(background_row).to_be_visible()
    expect(section_row).to_be_hidden()
    expect(shape_row).to_be_hidden()

    # --- claim 1b and 3: Tietoa -------------------------------------------
    open_a_section_that_is_not_the_hero(page, expect)
    expect(page.locator(".kuva-row")).to_have_count(3)
    expect(portrait_row).to_be_hidden()
    expect(background_row).to_be_hidden()
    expect(section_row).to_be_visible()
    expect(shape_row).to_be_visible()
    # The row is drawn as a row, not collapsed to nothing by the [hidden]
    # rule that was just lifted. Read from computed style for the reason
    # `computed` gives.
    assert computed(shape_row, "display") == "flex"

    # Nothing is stored yet, and "" IS the circle — so the row marks Pyöreä
    # rather than marking neither. The mark shows the RESOLVER's answer, not
    # the raw stored value, which is a deliberate divergence from the Ulkoasu
    # tab's style list (where "" is a third, meaningful state).
    circle_option = page.locator('.muoto-option[data-shape="circle"]')
    square_option = page.locator('.muoto-option[data-shape="square"]')
    expect(circle_option).to_have_class(re.compile(r"\bactive\b"))
    expect(square_option).not_to_have_class(re.compile(r"\bactive\b"))

    # --- the picture, through the row's own scoped input ------------------
    #
    # .vaihda-input matches THREE times in this document, and page-level
    # selector methods are not strict in Playwright, so an unscoped call
    # would silently upload into whichever row came first in the DOM.
    with page.expect_response("**/api/sections/*/draft"):
        page.set_input_files(".osiokuva-row .vaihda-input", str(section_file))
    expect(page.locator(".osiokuva-row .osiokuva-error")).to_be_hidden()

    stored = section_draft(live_app, "tietoa")
    assert len(stored["image"]) == 64, stored["image"]
    assert set(stored["image"]) <= set("0123456789abcdef"), stored["image"]
    assert stored["image_shape"] == ""

    # --- claim 5, first half: the circle the "" shape resolves to ---------
    portrait = page.frame_locator(".preview").locator(".portrait")
    expect(portrait).to_have_class(re.compile(r"\bcircle\b"))
    expect(portrait).to_have_class(re.compile(r"\bhas-image\b"))
    before = computed(portrait, "border-radius")
    assert "50%" in before, before

    # --- claim 4: the click is the write ----------------------------------
    with page.expect_response("**/api/sections/*/draft"):
        square_option.click()
    expect(square_option).to_have_class(re.compile(r"\bactive\b"))
    expect(circle_option).not_to_have_class(re.compile(r"\bactive\b"))

    after_click = section_draft(live_app, "tietoa")
    assert after_click["image_shape"] == "square"
    # The neighbours are untouched: the shape write is one key.
    assert after_click["image"] == stored["image"]
    assert after_click["image_alt"] == stored["image_alt"] == ""

    # The HERO is untouched, whole. The row belongs to the section it is
    # visible for, so `draft` is always that section's payload and none of
    # setHeroValue's "which section is open" branching is needed — this is
    # where that claim is falsifiable.
    hero = hero_draft(live_app)
    assert hero["portrait"] == ""
    assert hero["background"] == ""
    for key in ("image", "image_alt", "image_shape"):
        assert key not in hero, key

    # --- claim 5, second half: the same element, now square ---------------
    expect(portrait).to_have_class(re.compile(r"\bsquare\b"))
    expect(portrait).not_to_have_class(re.compile(r"\bcircle\b"))
    after = computed(portrait, "border-radius")
    assert after == "0px", after
    assert after != before

    # 0, not a soft radius: the design says "Square", and an invented corner
    # radius would be an invented design.
    #
    # The dashed inner ring is the ::before pseudo-element, and it has to
    # follow the outer edge or the picture reads as a circle inside a square.
    # A pseudo-element has no node, so no locator and no markup assertion can
    # reach it at all — getComputedStyle's second argument is the only way to
    # ask, which is the sharpest example in this file of why the claim is
    # made in a browser.
    ring = computed(portrait, "border-radius", "::before")
    assert ring == "0px", ring

    page.screenshot(
        path=str(tmp_path / "cop28-paneeli-kuvan-muoto.png"), full_page=True
    )
