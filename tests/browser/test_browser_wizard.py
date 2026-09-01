"""The first-run wizard's state machine, driven in a real browser
(LLM-COP-15) — app/static/wizard.js against /yllapito/alustus.

Nothing here asserts a string the server rendered; tests/test_wizard.py
already owns those. What only a browser can see is the machine: which
panel is open, which nav row is done, what a second click does to a step
counter, and whether Ohita really discarded an edit or merely stopped
showing it.

The walk waits on state before every click — the open panel — and never
on elapsed time. A click issued before the previous save landed IS the
double-click case, and the guard collapses it, so a sleep here would hide
the very thing test 3 exists to prove.
"""

import json

from app.seed import SEED_SECTIONS
from tests.conftest import section_rows

SEED_HERO = dict(SEED_SECTIONS)["hero"]

# Any instant; only its stillness matters.
FROZEN = "2026-01-01T09:00:00"


def freeze_clock(page):
    """Stop the page's clock dead, so no timer fires on its own.

    install() ALONE does not do this, which is easy to assume and wrong:
    the fake timers it installs still advance with real time, so a
    two-second debounce still fires two seconds later. Measured, in this
    worktree, before this helper existed. pause_at() is what actually
    stops the clock — and stopping it is how a test REMOVES a race rather
    than racing it with a short wall-clock window.
    """
    page.clock.install(time=FROZEN)
    page.clock.pause_at(time=FROZEN)


def wizard_input(page, step, label):
    """The control under one labelled field of one wizard step.

    By label rather than by position: the step rosters live in
    app/wizard.py and a reordered `only` list should not silently move
    this assertion to another field.
    """
    return (
        page.locator(f".wizard-panel[data-step='{step}'] .field")
        .filter(has=page.locator(".field-label", has_text=label))
        .locator("input, textarea")
        .first
    )


def published_count(app):
    """Rows that a publish has actually moved.

    previous_published is written only by sections.publish_dirty, so
    counting it is the one honest question "did a publish land" — the
    finish panel's note is painted whether or not any row moved
    (tests/conftest.py:181-194 documents that trap).
    """
    return sum(
        1 for row in section_rows(app) if row["previous_published"] is not None
    )


def hero_draft(app):
    row = next(row for row in section_rows(app) if row["kind"] == "hero")
    return json.loads(row["draft"])


def test_the_wizard_opens_on_step_one_with_takaisin_disabled(page, expect):
    """The opening position, stated honestly about which half of it only
    a browser can see.

    wizard.html ships panel 0 shown, every other panel and .wizard-finish
    `hidden`, and the first nav row already `is-current` — so those four
    assertions restate the template, and tests/test_wizard.py owns them
    too. They are kept as the frame the other two hang on.

    The two that are browser facts: .wizard-back is rendered with NO
    disabled attribute and wizard.js:226 disables it (the spec asserts it
    is visible, so it is disabled rather than hidden); and the panels
    ship with an EMPTY .section-form mount that only the shared builder
    fills, so a control resolving under Yläotsikko is the machine having
    booted at all. Without that last one this test rested on a single
    attribute. Measured: with wizard.js neutered the test fails.
    """
    expect(wizard_input(page, 0, "Yläotsikko")).to_be_visible()
    expect(page.locator(".wizard-panel[data-step='0']")).to_be_visible()
    expect(page.locator(".wizard-panel[data-step='1']")).to_be_hidden()
    expect(page.locator(".wizard-finish")).to_be_hidden()
    expect(page.locator(".wizard-back")).to_be_visible()
    expect(page.locator(".wizard-back")).to_be_disabled()
    expect(page.locator(".wizard-step").first).to_have_class("wizard-step is-current")


def test_tallenna_ja_jatka_advances_and_marks_the_step_done(page, expect):
    """Advancing is not a page load — it is renderProgress and openStep
    repainting the same document, and the nav row only turns is-done on a
    save the server accepted (wizard.js:140, savedSteps set inside the
    PUT's success branch)."""
    page.click(".wizard-save")
    expect(page.locator(".wizard-panel[data-step='1']")).to_be_visible()
    expect(page.locator(".wizard-panel[data-step='0']")).to_be_hidden()
    expect(page.locator(".wizard-step").first).to_have_class("wizard-step is-done")
    expect(page.locator(".wizard-back")).to_be_enabled()


def test_a_double_click_on_tallenna_ja_jatka_advances_exactly_one_step(page, expect):
    """The guard at wizard.js:283-286, and one of this project's real
    shipped defects: a double click skipped a step and blanked the screen.

    Both clicks read `current` as 0 (the first PUT has not resolved, so
    goTo has not run), and both issue a save. The first resolution
    advances; the second finds `current !== step` and does nothing. Drop
    the captured `step` and the second one advances again — panel 3.

    click_count=2, delay=0 is the whole point: two clicks inside one
    frame, which is what a person's double click actually is.
    """
    page.click(".wizard-save", click_count=2, delay=0)
    expect(page.locator(".wizard-panel[data-step='1']")).to_be_visible()
    expect(page.locator(".wizard-panel[data-step='2']")).to_be_hidden()


def test_ohita_discards_the_edit_and_takaisin_shows_the_original(page, expect):
    """skip() cancels the pending write and restores payloads from
    lastSaved (wizard.js:256-260). Coming back must therefore show the
    ORIGINAL value — a wizard that only stopped rendering the edit would
    smuggle it back into the next hero save.

    The clock is frozen, so the 2 s debounce cannot fire between the edit
    and the Ohita. That is not a wait: it is the removal of one. With a
    live clock this test would be a race against the very timer skip() is
    supposed to cancel — and a save that landed first would rebaseline
    lastSaved and make the restore restore the edit.
    """
    freeze_clock(page)
    field = wizard_input(page, 0, "Yläotsikko")
    expect(field).to_have_value(SEED_HERO["kicker"])
    field.fill("EI SAA JÄÄDÄ")

    page.click(".wizard-skip")
    expect(page.locator(".wizard-panel[data-step='1']")).to_be_visible()

    page.click(".wizard-back")
    expect(page.locator(".wizard-panel[data-step='0']")).to_be_visible()
    expect(wizard_input(page, 0, "Yläotsikko")).to_have_value(SEED_HERO["kicker"])


def test_walking_to_the_finish_and_publishing_moves_the_database(page, expect, live_app):
    """The whole five-step walk, then Julkaise — asserted against the
    store, not against the note.

    Something is typed FIRST, deliberately. On a freshly seeded database
    every row has draft == published, so publish_dirty touches zero rows
    and the finish panel still paints its published note: a test that
    asserted only the note would pass on a publish that published
    nothing. previous_published going 0 -> 1 is the publish actually
    landing.
    """
    assert published_count(live_app) == 0

    wizard_input(page, 0, "Yläotsikko").fill("UUSI YLÄOTSIKKO")
    for step in range(len(page.locator(".wizard-panel[data-step]").all())):
        # The open panel is the wait: the next click cannot be issued
        # until the previous save resolved and goTo repainted.
        expect(page.locator(f".wizard-panel[data-step='{step}']")).to_be_visible()
        page.click(".wizard-save")

    expect(page.locator(".wizard-finish")).to_be_visible()
    page.click(".wizard-julkaise")
    expect(page.locator(".wizard-published-note")).to_be_visible()
    expect(page.locator(".wizard-julkaise")).to_be_hidden()

    assert hero_draft(live_app)["kicker"] == "UUSI YLÄOTSIKKO"
    assert published_count(live_app) == 1
