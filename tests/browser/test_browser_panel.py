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

from tests.browser.conftest import (
    V2_STYLESHEET,
    hero_draft,
    hero_row,
    set_hero_draft_style,
)
from tests.conftest import section_rows

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
