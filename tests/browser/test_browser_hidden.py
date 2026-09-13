"""`hidden` means hidden — proved in a real Chrome, on every screen that has
an element the product ever hides (LLM-COP-48).

THE DEFECT SHAPE. `[hidden] { display: none }` lives in the UA stylesheet, and
UA declarations lose to author ones outright — specificity never enters into
it. So the moment a rule gives a class a `display`, the attribute stops
hiding that class: `element.hidden = true` sets an attribute nobody honours,
the element stays on screen, and the script that set it carries on believing
it is gone. The fix is always one line, `.thing[hidden] { display: none }`,
and the hard part has never been the fix.

The hard part is SEEING it. This project has shipped the same collision five
times — LLM-COP-5's Poista button, LLM-COP-31's picture row (uploads answered
"tuntematon kenttä" because the row for a field the kind does not declare was
drawn anyway), LLM-COP-32's sent contact form (still visible, still
re-submittable, twice: V1 and V2), and LLM-COP-48's formatting toolbar — with
a sixth, the row menus, caught only by a reviewer. Every one of them shipped
past a green suite, because the element is in the SERVED HTML either way and
nothing that reads markup can tell the two apart. Only a browser computes a
style.

SO EVERY ASSERTION IN THIS FILE READS getComputedStyle(...).display. Not the
attribute, not the class list, not the template text, and not a locator's
is_visible() — which folds in clipping, opacity and viewport, and would go
green on an element merely scrolled out of sight. The one thing measured is
the value the cascade actually resolved.

TWO PROBES PER SCREEN, and the second is the one that earns its keep.

  (a) AT REST. Every element the served document renders with `hidden` must
      compute `display: none`. This is what catches a rule added to a class
      that ships hidden — the COP-5, COP-31 and COP-48 shape.

  (b) FORCED. For every selector in tests/browser/hidden_registry.py that is
      rendered on this screen, the probe sets `hidden` on each match, reads
      the computed display back, and restores the attribute to what it was.
      This reaches the states only the runtime produces, and it is the ONLY
      thing here that catches LLM-COP-32: neither contact form carries
      `hidden` at rest on any screen, so probe (a) never looks at one.

The registry is a table of every `X.hidden = ...` assignment site in
app/static/*.js and app/templates/*.html — 32 of them — and
tests/test_hidden_registry.py re-derives that set from the sources so the
table cannot silently fall behind the code. The case list below is DERIVED
from the registry's own screen names, so there is no second list to drift.

THE SEVEN CASES, and the screen that is deliberately not among them.
/yllapito/viestit renders zero `[hidden]` elements and loads no script that
assigns `.hidden`, so a "no offenders here" case would assert nothing — and
worse, it would keep asserting nothing after a 404, a redirect to the login
form, or a template rewrite, because an empty sweep over an empty document
looks exactly like a clean one. A case that cannot fail is not covered; it is
covered-looking. It is left out and said so.

ONE CASE CANNOT REPORT AN OFFENDER TODAY, deliberately. wizard.css:18 carries
a blanket `[hidden] { display: none !important }`, so on /yllapito/alustus no
per-element rule can lose to an author `display` — both probes are
structurally green while that line stands. The case is kept because it is the
fence on that line: delete the blanket and `wizard-only` reddens (measured).
It guards one declaration, not the wizard's elements, and it should not be
read as the latter.

THREE NON-EMPTINESS GUARDS, for the same reason. This project states the rule
twice already — test_browser_colors.py's "a sweep that finds nothing proves
nothing" and test_sectionlist.py's `assert parser.classes` — and a sweep like
this one is exactly where a wrong route, a failed login or a stale selector
turns into a green run over an empty document. So: the registry must name at
least one selector for the screen; every selector it names must match at least
one real element there; and the at-rest `[hidden]` set must be non-empty.
Measured twice, identically, across the seven cases: 4, 4, 11, 11, 29, 12, 11
elements hidden at rest. Those numbers are recorded, not asserted — pinning
them would make every honest template edit a red test — but a drop to zero
fails.

WHAT IS NEVER ASSERTED HERE IS A DISPLAY LITERAL. The positive test says
`display !== "none"` and a rendered width greater than zero; it does not say
"flex", and it does not say 230px or 218px, which is what the toolbar
measured on V1 and V2 on this machine. CI runs a different Chrome, and this
repository has already been bitten by pinning a UA-supplied value: a test
that pinned computed `outline-width` read 0px on Chrome 142 and 3px on
Chrome 152, with `outline-style: none` suppressing the ring in both. The
claim worth making is the one the defect falsifies.

THE V2 TRAP, which has caught two agents on this feature already.
conftest.py's set_hero_draft_style writes the DRAFT column only. That is right
for /muokkaa/sivu, which renders the draft, and silently wrong for `/`, which
renders the published style — a V2 case planted that way keeps being served
V1, every probe below runs against a V1 document, and the case passes without
having looked at V2 once. So the skin is planted with tests/conftest.py's
edit_published_payload, which writes both columns (the same seam
test_browser_colors.py:58 imports), and EVERY case asserts the served
document's V2 stylesheet-link count — 1 for a v2 case, 0 for a v1 case —
before it probes anything. resolve_style turns an unknown value into "v1"
rather than raising, by design, so nothing but that count can tell a served
V2 from a fallback.
"""

import pytest

from tests.browser.conftest import V2_STYLESHEET
from tests.browser.hidden_registry import (
    SCREEN_ROUTES,
    SKINNED_SCREENS,
    screens,
    selectors_for,
)
from tests.conftest import edit_published_payload

# The seven cases, built from the registry's own screen names so that adding
# an entry for a new screen adds the case with it. A skinned screen is swept
# once per skin; the rest are admin templates with one rendering.
CASES = tuple(
    (screen, skin)
    for screen in screens()
    for skin in (("v1", "v2") if screen in SKINNED_SCREENS else (None,))
)

# What each case measured at rest, in this order, on two independent runs:
# public/v1 4, public/v2 4, direct/v1 11, direct/v2 11, edit 29, sections 12,
# wizard 11. Recorded so the next reader knows what "non-empty" is worth here.

# Every element the document renders with the attribute, with the display the
# browser resolved for it and enough of an identity to name it in a failure.
# el.className is a string on HTML elements and an SVGAnimatedString on SVG
# ones, hence the baseVal branch — an SVG icon shipped hidden would otherwise
# make this script throw rather than report.
AT_REST = """() => {
  const rows = [];
  document.querySelectorAll('[hidden]').forEach(el => {
    const raw = el.className;
    const names = (raw && raw.baseVal !== undefined) ? raw.baseVal : (raw || '');
    rows.push({
      what: el.tagName.toLowerCase() + (names ? '.' + names.trim().split(/\\s+/).join('.') : ''),
      display: getComputedStyle(el).display
    });
  });
  return rows;
}"""

# Set the attribute, read the computed display back, put the attribute back
# the way it was. Restoring matters: the sweep probes several selectors per
# screen in one page, and a probe that left .contact-dialog hidden would
# change what a later probe is measuring. Elements that already carried the
# attribute keep it.
FORCED = """(selector) => {
  const rows = [];
  document.querySelectorAll(selector).forEach((el, index) => {
    const had = el.hasAttribute('hidden');
    el.setAttribute('hidden', '');
    const display = getComputedStyle(el).display;
    if (!had) el.removeAttribute('hidden');
    rows.push({ index: index, had: had, display: display });
  });
  return rows;
}"""


def open_screen(page, live_app, screen, skin):
    """Navigate to one case's screen and prove the document is the one asked
    for before anything is measured.

    Two assertions, both of which have a real failure to catch: the status,
    because an admin route answered 302 to the login form would sweep a
    document with no offenders in it, and the stylesheet-link count, because
    an unknown style resolves to V1 silently (app/styles.py) and a V2 case
    would otherwise measure V1.
    """
    if skin is not None:
        # Both columns, deliberately. `/` renders published and /muokkaa/sivu
        # renders draft; a draft-only plant would serve the public case V1.
        edit_published_payload(
            live_app, "hero", lambda payload: payload.update(style=skin)
        )
    route = SCREEN_ROUTES[screen]
    response = page.goto(f"{live_app.base_url}{route}")
    assert response.status == 200, (
        f"{route} answered {response.status}; a sweep of that document would "
        f"find no offenders and mean nothing"
    )
    expected = 1 if skin == "v2" else 0
    assert page.locator(V2_STYLESHEET).count() == expected, (
        f"{route} did not serve the {skin} skin — the style fell back, and "
        f"every probe in this case would have run against the other template"
    )


@pytest.mark.parametrize(
    "screen,skin",
    CASES,
    ids=[f"{screen}-{skin or 'only'}" for screen, skin in CASES],
)
def test_nothing_marked_hidden_is_drawn_on_this_screen(
    page, live_app, screen, skin
):
    """Probes (a) and (b) over one screen, with the three guards.

    Kept as ONE test per screen rather than two because the two probes share
    a page load and, more to the point, share the guards: a screen that fails
    to load should report that once, not twice in two different vocabularies.
    """
    open_screen(page, live_app, screen, skin)
    selectors = selectors_for(screen)

    # GUARD 1 — belt and braces. CASES is derived from screens(), so a screen
    # that reaches here always has a selector; this fires only if CASES ever
    # stops being derived from this table.
    assert selectors, (
        f"tests/browser/hidden_registry.py names no selector for the "
        f"{screen!r} screen, so this case would sweep nothing"
    )

    # --- probe (a): everything rendered hidden computes display: none ------
    at_rest = page.evaluate(AT_REST)

    # GUARD 3 — the document really did render hidden elements.
    assert at_rest, (
        f"{SCREEN_ROUTES[screen]} rendered NO element carrying `hidden`. "
        f"Every case in this file has some (4 to 29 when this was written), "
        f"so nothing here is a surprising emptiness to accept: the route, the "
        f"login or the template has changed and this case is now proving "
        f"nothing"
    )
    drawn = [row for row in at_rest if row["display"] != "none"]
    assert drawn == [], (
        f"on {SCREEN_ROUTES[screen]} ({skin or 'no skin'}) these elements "
        f"carry `hidden` and are still DRAWN: {drawn}. An author `display:` "
        f"beats the UA sheet's [hidden] rule, so each one needs its own "
        f"`.thing[hidden] {{ display: none }}` — the same one-line fix as "
        f"LLM-COP-5, LLM-COP-31, LLM-COP-32 and LLM-COP-48"
    )

    # --- probe (b): setting the attribute actually hides it ----------------
    offenders = []
    for selector in selectors:
        rows = page.evaluate(FORCED, selector)
        # GUARD 2 — the selector still finds the element it was written for.
        # This is what limits the damage a stale selector can do: the
        # anti-drift test compares assignment-site keys, not selectors, so a
        # selector left behind by a rename would pass it. Here it goes red.
        assert rows, (
            f"{selector} matched nothing on {SCREEN_ROUTES[screen]}, so the "
            f"registry entry that names it is probing nothing. Either the "
            f"element moved screens or the selector is stale — fix "
            f"tests/browser/hidden_registry.py, do not delete the case"
        )
        for row in rows:
            if row["display"] != "none":
                offenders.append((selector, row["index"], row["display"]))
    assert offenders == [], (
        f"on {SCREEN_ROUTES[screen]} ({skin or 'no skin'}) setting `hidden` "
        f"on these left them drawn: {offenders}. The script that assigns "
        f".hidden here believes the element is gone and it is not — this is "
        f"the LLM-COP-32 shape, which no at-rest sweep can see because these "
        f"elements are visible until the runtime hides them"
    )


@pytest.mark.parametrize("skin", ("v1", "v2"))
def test_the_format_toolbar_is_gone_at_rest_and_back_on_focus(
    page, live_app, skin
):
    """LLM-COP-48 itself, both skins: the thing the sweep above generalises.

    The toolbar ships with `hidden` on it (direct_edit_chrome.html) and
    .direct-toolbar declares `display: flex`, so before the fix it painted
    over the page from the moment direct mode opened — bold, italic, link,
    list and undo floating at the top left of the document with no field
    active. direct-edit.js then toggled an attribute that changed nothing.

    focus(), not click(): direct mode's own fixed chrome intercepts a
    synthetic click aimed at an element's centre, and activation is bound to
    the `focus` event anyway (direct-edit.js:315-317). The same reasoning
    test_browser_v2_direct_edit.py's `activate` states for its own sweep.

    NOTHING IS PINNED TO A LITERAL. `display !== "none"` and a box wider than
    zero pixels — both false before the fix, both true after, on a Chrome of
    any version. The measured boxes were 230x38 on V1 and 218x35 on V2 and
    those numbers belong in a commit message, not an assertion.
    """
    open_screen(page, live_app, "direct", skin)
    toolbar = page.locator(".direct-toolbar")
    assert toolbar.count() == 1

    assert toolbar.evaluate("el => getComputedStyle(el).display") == "none", (
        "the formatting toolbar is drawn with no field active. It carries "
        "`hidden` in direct_edit_chrome.html, and .direct-toolbar's own "
        "`display: flex` beats the UA sheet's [hidden] rule — "
        "direct-edit.css needs `.direct-toolbar[hidden] { display: none }`"
    )

    fields = page.locator("[data-section][data-field]")
    assert fields.count() > 0, (
        "direct mode rendered no bound field, so there is nothing to focus "
        "and this test would prove nothing about the toolbar coming back"
    )
    fields.first.focus()

    state = toolbar.evaluate(
        "el => ({ hidden: el.hidden, display: getComputedStyle(el).display })"
    )
    assert state["hidden"] is False, (
        f"focusing a bound field did not unhide the toolbar: {state}"
    )
    assert state["display"] != "none", (
        f"the toolbar lost its `hidden` attribute but is still not drawn: "
        f"{state} — a [hidden] rule written without a companion display, or "
        f"a rule hiding it by another route"
    )
    box = toolbar.bounding_box()
    assert box is not None and box["width"] > 0, (
        f"the toolbar computes a drawable display but has no box: {box}"
    )
