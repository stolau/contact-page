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


def hero_row(app):
    return next(row for row in section_rows(app) if row["kind"] == "hero")


def hero_draft(app):
    return json.loads(hero_row(app)["draft"])


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
