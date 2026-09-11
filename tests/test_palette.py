"""app/palette.py — the derivations, swept rather than asserted (USR-COP-2).

WHY SWEEPS AND NOT EXAMPLES. Every function in app/palette.py exists to make
a claim about a colour the owner picks, and the picker admits sixteen million
of them. A test that checks three of those checks three of those. So the
claims here are quantified over a grid, and the grid found a real defect the
plan for this change did not have: no single black-or-white button label
clears 4.5:1 against both the rest and the hover ground — hence the two ink
tokens, and hence this file.

THE GRID, and what it is not. _GRID is the 4096 colours of the #RGB shorthand
expanded to #RRGGBB (#0f8 -> #00ff88), a spread that touches every corner and
the middle of the cube. It is not exhaustive: a claim's TRUE worst case can
sit off it, so every sweep below reports the worst case OF THE SET IT ACTUALLY
SWEEPS, and any colour named in prose is put into the swept set rather than
quoted from a wider run that this file does not do. The wider runs — the full
grid where the committed test uses a subgrid, and 50 000 random pairs — sit
behind COP_COLOR_SWEEP=1 so a suspicious reader can run them without every
run paying for them.

WHAT NO TEST HERE CAN DO, said once rather than implied. These are contrast
NUMBERS. They say nothing about whether the result is pleasant. Since
LLM-COP-40 they cover non-text contrast too — visible_on's 3:1 for the accent
drawn as an EDGE, swept in its own section below at the same grid and in the
same idiom — but they still say nothing about the sites app/palette.py's own
comment records as deliberately NOT retargeted, and nothing about whether a
colour that clears a ratio here reaches the screen. That second gap is
tests/browser/test_browser_colors.py's, and it is the one that matters: a
ratio computed here is a statement about this module, not about a page.
"""

import functools
import os
import random
import re

import pytest

from app.palette import (
    MAIN,
    NON_TEXT_RATIO,
    ROLE_TOKENS,
    V1_SURFACES,
    V2_SURFACES,
    contrast,
    luminance,
    on_color,
    palette_css,
    readable_on,
    resolve_color,
    ring_on,
    shade,
    visible_on,
)
from tests.test_direct_edit_css import STATIC, _declarations, _rules

# The 4096-colour grid, and a coarser 729-colour one for the sweeps whose
# cost is quadratic in the set rather than linear.
_GRID = [
    f"#{r}{r}{g}{g}{b}{b}"
    for r in "0123456789abcdef"
    for g in "0123456789abcdef"
    for b in "0123456789abcdef"
]
_SUBGRID = [
    f"#{r}{r}{g}{g}{b}{b}"
    for r in "013579bdf"
    for g in "013579bdf"
    for b in "013579bdf"
]

# Colours that are NOT on the grid — no channel of either is a multiple of 17
# — and that this file's prose names, so they are put into the swept sets
# rather than cited from a run nobody here made. #3f2a4b is where shade's
# floor is tightest and #e400f3 is where a single button ink is worst.
_OFF_GRID = ("#000000", "#ffffff", "#010101", "#000011", "#3f2a4b", "#e400f3")

# Both shipped accents, which every derivation must leave alone.
_SHIPPED = ("#1f6f5c", "#a8431c")

_WIDE = pytest.mark.skipif(
    not os.environ.get("COP_COLOR_SWEEP"),
    reason="set COP_COLOR_SWEEP=1 for the full-grid and random-pair sweeps",
)


def _worst(pairs):
    """The lowest ratio of an iterable of (ratio, *what), with what it was."""
    return min(pairs)


# --- resolve_color: the whitelist, and the hostile table -------------------

# Every one of these must resolve to "". They are the values an API client
# can put in the store — app/styles.py's "the store is not the app's alone"
# — and each is a DIFFERENT failure mode, which is why they are listed rather
# than summarised: a short hex, a colour NAME, a scheme, a bare closing
# brace, a bad digit, trailing whitespace, an absurd length, and five
# non-strings that a regex-first implementation would raise TypeError on.
HOSTILE = (
    "#fff",
    "red",
    "javascript:alert(1)",
    "}",
    "}</style><script>window.__pwned=1</script>",
    "#12345g",
    "#aabbcc ",
    "x" * 200,
    "",
    None,
    123,
    {"a": 1},
    ["#aabbcc"],
    True,
)


@pytest.mark.parametrize("value", HOSTILE, ids=lambda v: repr(v)[:40])
def test_resolve_color_rejects_everything_that_is_not_six_hex_digits(value):
    """Rejected means "", never a repair and never a raise.

    NOT RAISING is half the claim and the half a naive implementation gets
    wrong: re.fullmatch raises TypeError on a non-str, so a stored colour
    that is null, a number, an object or an array would 500 the public page
    before any fallback ran. isinstance goes FIRST, exactly as
    app/styles.py's resolve_style orders its own guard, and the five
    non-string entries above are what holds that ordering in place.

    NOT REPAIRING is the other half. "#fff" is not expanded and "#aabbcc "
    is not stripped: every repair is another string shape that reaches a
    <style> block, and a value the app did not write is not a value to guess
    the intent of.
    """
    assert resolve_color(value) == ""


def test_resolve_color_accepts_six_hex_digits_and_lowercases_them():
    assert resolve_color("#AABBCC") == "#aabbcc"
    assert resolve_color("#aabbcc") == "#aabbcc"
    assert resolve_color("#1f6f5c") == "#1f6f5c"


# --- luminance and contrast ------------------------------------------------


def test_contrast_is_symmetric_and_spans_the_full_range():
    """The two ends are the specification's own, so a wrong knee or a wrong
    exponent moves them."""
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast("#123456", "#123456") == pytest.approx(1.0)


def test_luminance_is_the_wcag_curve_at_its_named_points():
    assert luminance("#000000") == pytest.approx(0.0)
    assert luminance("#ffffff") == pytest.approx(1.0)
    # Mid grey is 0.2158, not 0.5: the gamma curve is the whole reason the
    # contrast maths cannot be done on raw channel values.
    assert luminance("#808080") == pytest.approx(0.2158, abs=0.0005)


# --- on_color: the theorem the rest of the module rests on -----------------


def test_on_color_clears_four_and_a_half_against_every_colour_on_the_grid():
    """THE THEOREM, swept: black-or-white always clears 4.5:1.

    It is a property of luminance alone. The two candidates' ratios cross
    where L + 0.05 == sqrt(0.0525), and at that crossing both are 4.5826, so
    the better of the two can never fall below it. Everything else in this
    module leans on that: readable_on's walk terminates because its endpoint
    is guaranteed to clear, and the two button ink tokens are covered by it
    rather than by a sweep of their own.

    It is also the sharpest test of luminance() there is. BT.601 weights, a
    gamma applied on the wrong side of the 0.03928 knee, or channels left
    un-linearised each drop this worst case below 4.5.

    Swept set: the 4096-colour grid plus the six off-grid colours this file
    names. Worst measured here: 4.5843 at #8855ee.
    """
    ratio, color = _worst(
        (contrast(on_color(c), c), c) for c in _GRID + list(_OFF_GRID)
    )
    assert ratio >= 4.5, (ratio, color)
    assert (round(ratio, 4), color) == (4.5843, "#8855ee")


@_WIDE
def test_on_color_clears_four_and_a_half_over_the_whole_cube_coarsely():
    """The same theorem over the whole sRGB cube at a step of 5 — 132 651
    colours, and a tighter worst case than the grid finds because it lands
    nearer the crossing point. Worst measured: 4.5827 at #4b7d87."""
    values = range(0, 256, 5)
    ratio, color = _worst(
        (contrast(on_color(hexed), hexed), hexed)
        for hexed in (
            f"#{r:02x}{g:02x}{b:02x}"
            for r in values
            for g in values
            for b in values
        )
    )
    assert ratio >= 4.5, (ratio, color)
    assert (round(ratio, 4), color) == (4.5827, "#4b7d87")


# --- shade: the hover ground -----------------------------------------------


def test_shade_rounds_rather_than_truncates():
    """A one-line claim with a visible consequence: #1f6f5c x 0.8 is #19594a
    under round() and #185849 under int(). Both are plausible; only one is
    what this module returns, and pinning it is what stops a later "tidy"
    from silently shifting every owner's hover state."""
    assert shade("#1f6f5c") == "#19594a"
    assert shade("#a8431c") == "#863616"


def test_shade_moves_the_colour_by_at_least_the_stated_floor():
    """The hover ground is VISIBLY different from the rest ground.

    A plain darken does not guarantee that and the sweep says so: shade
    defined as x0.8 alone returns #000000 for black, and #000011 darkens to a
    ratio of 1.0017 — a hover state nobody can see. So shade lightens instead
    when darkening fails to clear 1.15:1, and this is the sweep that holds
    the floor.

    Swept set: the 4096-colour grid plus the six off-grid colours, both
    shipped accents included. Worst measured here: exactly 1.15000 at
    #3f2a4b, which is on the swept set because it is listed in _OFF_GRID —
    the floor is REACHED, so a floor stated any higher would be false.
    """
    ratio, color = _worst(
        (contrast(shade(c), c), c)
        for c in _GRID + list(_OFF_GRID) + list(_SHIPPED)
    )
    assert ratio >= 1.15, (ratio, color)
    assert (round(ratio, 5), color) == (1.15, "#3f2a4b")


def test_the_hover_label_reads_on_the_hover_ground():
    """on_color(shade(c)) clears 4.5:1 against shade(c) — the second ink
    token doing the job it exists for. Worst measured: 4.5830 at #6699bb."""
    ratio, color = _worst(
        (contrast(on_color(shade(c)), shade(c)), c)
        for c in _GRID + list(_OFF_GRID) + list(_SHIPPED)
    )
    assert ratio >= 4.5, (ratio, color)
    assert (round(ratio, 4), color) == (4.583, "#6699bb")


def test_one_button_ink_cannot_serve_both_grounds():
    """WHY THERE ARE TWO INK TOKENS, proven rather than asserted.

    For each colour, take the BEST single black-or-white label and score it
    by its WORST ratio across the rest ground and the hover ground. If one
    token could serve both, that best-of-worst would clear 4.5 everywhere.
    It does not: 3.7680 at #e400f3, which is on the swept set because
    _OFF_GRID lists it.

    Delete --accent-dark-ink and this is the number the button's hover label
    renders at. The test is written as a REFUTATION on purpose — it fails if
    somebody ever makes one ink work, which would be news worth having.
    """
    ratio, color = _worst(
        (
            max(
                min(contrast(ink, c), contrast(ink, shade(c)))
                for ink in ("#000000", "#ffffff")
            ),
            c,
        )
        for c in _GRID + list(_OFF_GRID) + list(_SHIPPED)
    )
    assert ratio < 4.5, (ratio, color)
    assert (round(ratio, 4), color) == (3.768, "#e400f3")


# --- readable_on: the accent as text ---------------------------------------


@pytest.mark.parametrize(
    "color,surfaces",
    ((_SHIPPED[0], V1_SURFACES), (_SHIPPED[1], V2_SURFACES)),
)
def test_readable_on_is_the_identity_on_the_shipped_accents(color, surfaces):
    """THE ASSERTION THAT GOES RED IF THIS DERIVATION EVER STARTS REWRITING
    THE AUTHOR'S OWN COLOURS.

    Both shipped accents already clear 4.5:1 on every surface of their own
    skin — 5.6363 and 6.0231 for V1; 5.7495, 6.0265 and 5.1441 for V2, the
    tint being the tightest today — so readable_on returns them untouched and
    the shipped palette is byte-identical. The ratios are asserted alongside
    the identity, because "unchanged" would also be true of a function that
    had stopped checking anything.
    """
    assert readable_on(color, surfaces) == color
    assert min(contrast(color, s) for s in surfaces) >= 4.5


@pytest.mark.parametrize(
    "skin,surfaces,expected",
    (("v1", V1_SURFACES, (4.5001, "#aa6677")),
     ("v2", V2_SURFACES, (4.5001, "#996644"))),
)
def test_readable_on_clears_every_surface_of_its_skin(skin, surfaces, expected):
    """The central claim of this change, per skin: for EVERY colour the
    picker admits, the accent as TEXT clears 4.5:1 on every surface it
    actually renders on.

    The sweep proves two things at once, and the second is the one an
    assertion could not give. That the floor is respected — and that the walk
    TERMINATES having cleared it, for all 4096 colours, rather than falling
    out of its loop at an unproven step.

    Swept set: the 4096-colour grid. Worst measured here: 4.5001 at #aa6677
    for V1 and 4.5001 at #996644 for V2 — the floor is 4.5 by construction
    and the sweep shows it is essentially reached, which is what makes it a
    floor rather than a hope.
    """
    assert ROLE_TOKENS[skin]["surfaces"] == surfaces
    ratio, color = _worst(
        (min(contrast(readable_on(c, surfaces), s) for s in surfaces), c)
        for c in _GRID
    )
    assert ratio >= 4.5, (ratio, color)
    assert (round(ratio, 4), color) == expected


def test_readable_on_clears_an_owner_chosen_header_both_ways():
    """The header's ground is no longer a frozen literal — the owner picks it
    — so the claim is swept in BOTH directions: many colours against two
    hostile grounds, and two hostile colours against many grounds.

    The two grounds are the values that break a naive implementation:
    #ffe9a8, a pale yellow that renders at 1.1247 on --paper if it is used
    raw, and #1f6f5c, the shipped green. The two colours going the other way
    are white and the on_color worst case.

    The committed sweep uses the 729-colour subgrid; the full-grid and
    random-pair forms are behind COP_COLOR_SWEEP=1. Worst measured here:
    4.5001 at (#330011 on #1f6f5c) one way, 4.5000 at (#ffffff on #ffbbbb)
    the other.
    """
    ratio, color, ground = _worst(
        (contrast(readable_on(c, (bg,)), bg), c, bg)
        for c in _SUBGRID
        for bg in ("#ffe9a8", "#1f6f5c")
    )
    assert ratio >= 4.5, (ratio, color, ground)
    assert (round(ratio, 4), color, ground) == (4.5001, "#330011", "#1f6f5c")

    ratio, color, ground = _worst(
        (contrast(readable_on(c, (bg,)), bg), c, bg)
        for bg in _SUBGRID
        for c in ("#ffffff", "#1a1a2e", "#8855ee")
    )
    assert ratio >= 4.5, (ratio, color, ground)
    assert (round(ratio, 4), color, ground) == (4.5, "#ffffff", "#ffbbbb")


@_WIDE
def test_readable_on_clears_an_owner_chosen_header_over_the_full_grid():
    """The same claim over the 4096-colour grid in both directions, and over
    50 000 random (colour, ground) pairs from a seeded generator — the form
    the committed test above subsamples. Worst measured: 4.5001, 4.5000 and
    4.5000 respectively."""
    ratio, color, ground = _worst(
        (contrast(readable_on(c, (bg,)), bg), c, bg)
        for c in _GRID
        for bg in ("#ffe9a8", "#1f6f5c")
    )
    assert ratio >= 4.5, (ratio, color, ground)

    ratio, color, ground = _worst(
        (contrast(readable_on(c, (bg,)), bg), c, bg)
        for bg in _GRID
        for c in ("#ffffff", "#1a1a2e", "#8855ee")
    )
    assert ratio >= 4.5, (ratio, color, ground)

    rnd = random.Random(0)
    pairs = [
        (f"#{rnd.randrange(1 << 24):06x}", f"#{rnd.randrange(1 << 24):06x}")
        for _ in range(50000)
    ]
    ratio, color, ground = _worst(
        (contrast(readable_on(c, (bg,)), bg), c, bg) for c, bg in pairs
    )
    assert ratio >= 4.5, (ratio, color, ground)


def test_readable_on_raises_when_no_endpoint_clears_every_background():
    """THE CONTRACT, not an oversight: it fails loudly rather than looping or
    returning something it cannot vouch for.

    Black clears a light surface and white clears a dark one. A tuple mixing
    the two can have NO common endpoint, and there is then no honest answer:
    returning the last walked step would ship a colour this module has just
    shown does not read, and walking on would not terminate.

    The app cannot reach this today — palette_css passes either a single
    background, where the on_color theorem guarantees an endpoint, or one of
    the two all-light frozen surface sets, where black clears every member
    (asserted below, so "cannot reach" is a checked claim and not a
    sentence). The branch is covered anyway, because an uncovered raise is a
    comment.
    """
    with pytest.raises(ValueError):
        readable_on("#808080", ("#ffffff", "#000000"))

    # And the reason the app never gets there: black clears every surface of
    # both skins, so an endpoint always exists for the sets palette_css uses.
    for surfaces in (V1_SURFACES, V2_SURFACES):
        assert all(contrast("#000000", s) >= 4.5 for s in surfaces)


# --- visible_on: the accent as a line ---------------------------------------
#
# LLM-COP-40. The THIRD derivation, and the sweeps below are written to be
# read beside readable_on's above: same grid, same _worst idiom, same shape of
# claim — a different NUMBER against a different WCAG success criterion. 4.5
# is SC 1.4.3 and it is about reading glyphs; 3.0 is SC 1.4.11 and it is about
# perceiving that a boundary is drawn at all.
#
# THE WORST CASE IS TAKEN ON UNROUNDED RATIOS, and that is not pedantry. V2's
# two closest grid colours are #dd6600 at 3.00004028 and #33aa66 at
# 3.00004683 — they TIE at four decimal places, so a sweep that rounded before
# taking the min would return whichever the tie-break reached first and the
# pinned pair below would go red for a reason with nothing to do with the
# derivation. min() over the raw float picks #dd6600 every time.


@pytest.mark.parametrize(
    "color,surfaces,floor",
    (
        (_SHIPPED[0], V1_SURFACES, 5.6363),
        (_SHIPPED[1], V2_SURFACES, 5.1441),
    ),
)
def test_visible_on_is_the_identity_on_the_shipped_accents(
    color, surfaces, floor
):
    """A SITE THAT CHOSE NO COLOUR IS UNTOUCHED BY THIS DERIVATION.

    Both shipped accents clear 3:1 on every surface of their own skin by a
    wide margin, so visible_on hands them back unchanged and every edge the
    new token paints resolves to the byte the stylesheet shipped. The margin
    is pinned alongside the identity because "unchanged" is also true of a
    function that has stopped checking anything — and because the day
    somebody recolours a skin, this is where they are told a browser
    assertion in tests/browser/test_browser_colors.py is pinned to the old
    literal too.
    """
    assert visible_on(color, surfaces) == color
    assert min(contrast(color, s) for s in surfaces) >= NON_TEXT_RATIO
    assert round(min(contrast(color, s) for s in surfaces), 4) == floor


@pytest.mark.parametrize(
    "skin,surfaces,expected",
    (("v1", V1_SURFACES, (3.0001, "#22aa55")),
     ("v2", V2_SURFACES, (3.0, "#dd6600"))),
)
def test_visible_on_clears_three_to_one_on_every_surface_of_its_skin(
    skin, surfaces, expected
):
    """The central claim of LLM-COP-40, per skin: for EVERY colour the picker
    admits, the accent as an EDGE clears 3:1 on every surface it is drawn on.

    Same two things at once as readable_on's sweep, and the second is again
    the one an example could not give: the floor holds, and the walk
    TERMINATES having cleared it for all 4096 colours rather than falling out
    of its loop at an unproven step.

    Swept set: the 4096-colour grid. Worst measured: 3.0001 at #22aa55 for V1
    and 3.0000 at #dd6600 for V2 — the floor is 3.0 by construction and the
    sweep shows it essentially reached, which is what makes it a floor rather
    than a hope.

    Set NON_TEXT_RATIO to 2.9 and the pinned pair goes red at
    (2.9001, '#ff11ff') on V1. The ratio assertion above it does NOT — it is
    stated against the constant, so it follows the constant down; the pinned
    pair is what holds the number itself.
    """
    assert ROLE_TOKENS[skin]["surfaces"] == surfaces
    ratio, color = _worst(
        (min(contrast(visible_on(c, surfaces), s) for s in surfaces), c)
        for c in _GRID
    )
    assert ratio >= NON_TEXT_RATIO, (ratio, color)
    assert (round(ratio, 4), color) == expected


@pytest.mark.parametrize(
    "skin,surfaces,moved_edge,moved_text",
    (("v1", V1_SURFACES, 1940, 2745),
     ("v2", V2_SURFACES, 2110, 2898)),
)
def test_the_edge_derivation_is_not_the_text_one(
    skin, surfaces, moved_edge, moved_text
):
    """THE ANTI-FOLD ASSERTION, and it is written as an INEQUALITY on purpose.

    visible_on delegates to readable_on, which is one line and one linear
    scan rather than two — the saving that made a named function worth having
    instead of a second walk. The price of delegating is that aliasing the
    two, or dropping the constant and letting the default stand, is a small
    and plausible edit that would ship edges walked to 4.5 and text walked to
    3. So the claim is stated as `visible_on(c, S) != readable_on(c, S)`,
    which no such edit can satisfy.

    THREE COLOURS, and the third is the sharp one. #cc4400 already clears 3:1
    on both skins' surfaces, so the edge derivation is the IDENTITY on it
    while the text derivation still has to move (#cb4300 on V1, #c33b00 on
    V2) — a pair a "they are nearly the same anyway" reading would miss.

    And the counts, over the grid: 1940 of 4096 colours move at 3.0 against
    2745 at 4.5 for V1, 2110 against 2898 for V2. Two ratios, two populations.
    """
    for color in ("#ffe9a8", "#66aa88", "#cc4400"):
        edge = visible_on(color, surfaces)
        text = readable_on(color, surfaces)
        assert edge != text, (skin, color, edge, text)
        assert min(contrast(edge, s) for s in surfaces) >= NON_TEXT_RATIO
    assert visible_on("#cc4400", surfaces) == "#cc4400"

    assert sum(1 for c in _GRID if visible_on(c, surfaces) != c) == moved_edge
    assert sum(1 for c in _GRID if readable_on(c, surfaces) != c) == moved_text
    assert moved_edge < moved_text


def test_visible_on_never_reaches_the_raise():
    """The raise is readable_on's, inherited — and it stays dead here for a
    WIDER margin than the 4.5 caller already relies on.

    Mirrors test_readable_on_raises_when_no_endpoint_clears... deliberately:
    the branch is covered, because an uncovered raise is a comment, and then
    the reason the app cannot get there is asserted rather than stated. Black
    clears every surface of both skins at 3.0 — 19.6513 and 21.0000 for V1,
    20.0347, 21.0000 and 17.9252 for V2 — so an endpoint always exists for
    the only sets palette_css passes.

    THE PROBE COLOUR IS NOT #808080, AND THE REASON IS A FINDING RATHER THAN
    A DETAIL. That is what the 4.5 test uses, and at 3.0 it does not reach
    the endpoint search at all: mid grey measures 3.9494 against white and
    5.3172 against black, so the IDENTITY branch returns it and the mixed
    tuple never asks for an endpoint. A test copied across unchanged would
    have passed for the wrong reason — the raise would go uncovered while
    the assertion read as if it were covered. #cccccc is 1.6059 against
    white, so it fails the identity branch and the search runs; then neither
    endpoint clears (white is 1.0000 against white, black 1.0000 against
    black) and the contract fires.
    """
    with pytest.raises(ValueError):
        visible_on("#cccccc", ("#ffffff", "#000000"))
    # And the colour the 4.5 test probes with is the identity here, which is
    # why it could not be reused: a band of mid greys is a legible EDGE
    # against both black and white even though no such colour is legible
    # TEXT on both. The two ratios have different geometry, which is the
    # whole reason this is a second derivation.
    assert visible_on("#808080", ("#ffffff", "#000000")) == "#808080"
    with pytest.raises(ValueError):
        readable_on("#808080", ("#ffffff", "#000000"))

    for surfaces in (V1_SURFACES, V2_SURFACES):
        assert all(contrast("#000000", s) >= NON_TEXT_RATIO for s in surfaces)


# --- ring_on: the primary button's boundary ---------------------------------
#
# LLM-COP-44. The FOURTH derivation, and the first that can decline to
# produce a colour at all. visible_on walks the accent until it is a visible
# LINE against a set of surfaces; ring_on asks a different question about a
# filled button — does the fill ALREADY carry the boundary against the one
# ground this button sits on, and if it does, paint nothing.
#
# SO THE CLAIM HAS TWO HALVES AND THEY FAIL DIFFERENTLY. The IFF half is what
# keeps a compliant button from being re-drawn: "transparent" must mean
# "every fill already clears 3:1 on every ground", in both directions, so a
# derivation that painted defensively goes red here rather than quietly
# putting a rim on eleven buttons nobody asked to change. The GUARANTEE half
# is the accessibility claim: when a ring IS painted it reaches 3:1 against
# every ground it was derived for.
#
# BOTH FILLS. `fills` is (accent, shade(accent)) at every call site, because
# the hover fill is the worse of the two and it is where the shipped defect
# actually lives: #a8431c is 2.1987 on the navy contact card and its hover
# shade #863616 is 1.6108. A sweep over the rest fill alone would pass on a
# derivation that goes blind exactly on hover, so every case below carries
# both.
#
# THE RAISE IS FENCED STRUCTURALLY, NOT SWEPT. ring_on delegates to
# visible_on, whose raise is readable_on's, and a raise on the public page is
# a 500. The two clauses of test_no_ring_ground_tuple_can_reach_the_raise
# below partition every tuple shape the table can hold, so the property holds
# for the five rows that exist AND for a row somebody adds later — which no
# sweep of picks, however wide, could say.

# The seeded sets the two sweeps share. Seeded rather than gridded because a
# ring's ground is not the 4096-colour grid's business: two of the five rows
# take the OWNER's main colour as their ground, so the sweep ranges over
# (ground, pick) PAIRS and a full grid on both axes is 16.7M cases.
_RING_SEED = 44
_RING_PICKS = tuple(
    f"#{_rand.randrange(1 << 24):06x}"
    for _rand in (random.Random(_RING_SEED),)
    for _ in range(2000)
)
# The colours the MAIN sentinel is bound to. Forty arbitrary ones plus four
# that matter by name: the two skins' own default mains, and black and white,
# the two grounds where on_color's choice of endpoint flips.
_RING_MAINS = tuple(
    f"#{_rand.randrange(1 << 24):06x}"
    for _rand in (random.Random(_RING_SEED + 1),)
    for _ in range(40)
) + ("#ffffff", "#d9e8f2", "#000000", "#14324a")

# How many picks each MAIN-bound ground gets. Smaller than the frozen rows'
# 2000 because there are 44 such grounds per MAIN row and the product is what
# costs. The number is stated here rather than buried, so raising it is a
# one-line decision.
_RING_PICKS_PER_MAIN = 400


@functools.cache
def _ring_sweep(skin):
    """Every (token, grounds, accent) case of the ring sweep, measured once.

    Cached because the two tests below make two DIFFERENT claims about the
    same measurement, and running it twice buys nothing but the time. Each
    case carries what a test needs to judge it: the bound ground tuple, the
    two fills, whether every fill ALREADY clears NON_TEXT_RATIO on every
    ground — computed here from contrast, never by asking ring_on what it
    thinks — and what ring_on returned.

    Every row is swept twice over: bound to the skin's own default main, at
    the full pick count, so the SHIPPED binding is in the set whatever the
    random mains turn out to be; and bound to each of _RING_MAINS, which is
    what makes the owner-chosen ground a swept axis rather than an example.
    """
    default_main = ROLE_TOKENS[skin]["default_main"]
    bindings = []
    for token, grounds in ROLE_TOKENS[skin]["rings"]:
        bindings.append((
            token,
            tuple(default_main if g == MAIN else g for g in grounds),
            _RING_PICKS,
        ))
        if MAIN in grounds:
            for main in _RING_MAINS:
                bindings.append((
                    token,
                    tuple(main if g == MAIN else g for g in grounds),
                    _RING_PICKS[:_RING_PICKS_PER_MAIN],
                ))
    cases = []
    for token, grounds, picks in bindings:
        for accent in picks:
            fills = (accent, shade(accent))
            clears = all(
                contrast(fill, ground) >= NON_TEXT_RATIO
                for fill in fills
                for ground in grounds
            )
            cases.append(
                (token, grounds, accent, clears, ring_on(fills, grounds))
            )
    return tuple(cases)


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_the_ring_is_transparent_exactly_when_both_fills_already_clear(skin):
    """THE IDENTITY CASE, stated as an IFF because both directions are real
    defects.

    LEFT TO RIGHT — "transparent" implies the fills already clear — is the
    accessibility half. A derivation that returned "transparent" for a button
    whose fill sits at 1.0416 against its ground would ship a boundary that
    is not there, and every ratio assertion in this suite would still pass,
    because there is nothing painted to measure.

    RIGHT TO LEFT — the fills clearing implies "transparent" — is
    LLM-COP-40's promise kept for the fill: "a compliant colour is never
    dulled." A derivation that painted anyway would put a rim on the shipped
    V1 page, on V2's hero card, on both headers and on both dialog submits,
    none of which asked for one, and no contrast assertion anywhere would
    complain.

    THE PREDICATE IS COMPUTED FROM contrast, NOT FROM ring_on. `clears` in
    _ring_sweep is the sentence "every fill clears 3:1 on every ground"
    written out; the assertion is that ring_on's ANSWER agrees with it. Make
    ring_on return "transparent" unconditionally and the left-to-right half
    goes red on the first pale pick.

    BOTH OUTCOMES OCCUR, asserted, because an iff over a set where one side
    never happens is an iff nobody checked.
    """
    cases = _ring_sweep(skin)
    for token, grounds, accent, clears, ring in cases:
        assert (ring == "transparent") == clears, (
            f"{skin} {token} on {grounds} with accent={accent}: ring_on "
            f"returned {ring!r} while every fill clearing 3:1 is {clears}"
        )
    transparent = sum(1 for case in cases if case[4] == "transparent")
    assert 0 < transparent < len(cases), (skin, transparent, len(cases))


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_a_painted_ring_reaches_three_to_one_on_every_ground_it_has(skin):
    """THE ACCESSIBILITY CLAIM, swept: whenever a ring IS painted it clears
    SC 1.4.11's 3:1 against EVERY ground it was derived for.

    Every ground, not the worst one the derivation happened to look at: a
    ring token serving a tuple of surfaces is painted once and seen on all of
    them, so the claim is a min over the tuple. V2's light row is what makes
    that more than a formality — direct-edit's Julkaise walks all the way to
    --v2-page while the hero card's button sits on --v2-card, and a
    derivation that took #ffffff alone would leave the first at 2.90:1.

    The floor is NON_TEXT_RATIO, so it follows the constant if the constant
    moves. The pinned worst case is what holds the NUMBER: a sweep that
    bottoms out at 3.0000 is a floor essentially reached rather than a margin
    nobody has measured. It is taken on the UNROUNDED ratio, for the reason
    the visible_on section states above — rounding first makes a near-tie a
    coin toss between two colours and pins the loser.
    """
    painted = [
        (min(contrast(ring, ground) for ground in grounds), token, accent)
        for token, grounds, accent, _clears, ring in _ring_sweep(skin)
        if ring != "transparent"
    ]
    assert painted, skin
    worst, token, accent = _worst(painted)
    assert worst >= NON_TEXT_RATIO, (skin, worst, token, accent)
    assert round(worst, 4) == 3.0, (skin, worst, token, accent)


# The corner grid the no-raise sweep drives: the two ends of the cube, every
# frozen ground either skin's rings name, both shipped accents, and the two
# saturated picks the rest of this file already uses as its awkward cases.
_CORNERS = (
    "#000000", "#ffffff", "#14324a", "#d9e8f2", "#f7fafc", "#e6eef6",
    "#ffe9a8", "#a8431c", "#5d60ff", "#e400f3",
)


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_palette_css_raises_for_no_pair_of_colours(skin):
    """CONSTRAINT 2 OF THE ASK, measured: no derivation may raise on the
    public page.

    readable_on raises when no black-or-white endpoint clears every ground it
    was handed, and palette_css runs on every request that has a colour
    stored — so a raise here is a 500 on the public page, not a test failure
    somebody notices later. ring_on is the first caller ever to pass a ground
    the OWNER chose, which is why this sweep exists at all: before
    LLM-COP-44 every tuple palette_css passed was frozen.

    THE FENCE BELOW IS THE PROOF AND THIS IS THE CORROBORATION, in that
    order. 3100 pairs is 3100 pairs out of 16.7M x 16.7M; what makes the
    property hold for the rest is that every ring ground tuple is either a
    singleton — where the on_color theorem guarantees an endpoint for ANY
    colour — or frozen with a checked endpoint. What this sweep catches that
    the structural argument cannot see is a WIRING mistake: a ring row handed
    the other skin's surfaces, or a MAIN left unsubstituted.

    The corner grid is 10 x 10 over the colours that actually matter here;
    the 3000 random pairs come from a seeded generator, so a failure is
    reproducible from the seed alone.
    """
    rand = random.Random(4400)
    pairs = [(main, accent) for main in _CORNERS for accent in _CORNERS] + [
        (f"#{rand.randrange(1 << 24):06x}", f"#{rand.randrange(1 << 24):06x}")
        for _ in range(3000)
    ]
    assert len(pairs) == 3100
    for main, accent in pairs:
        block = palette_css(skin, main, accent)
        assert _BLOCK.fullmatch(block), (skin, main, accent, block)


def test_no_ring_ground_tuple_can_reach_the_raise():
    """THE FENCE, and it is why the sweep above is corroboration rather than
    the argument.

    Two clauses, read straight off ROLE_TOKENS, no colours swept:

      (i)  a ground tuple that CONTAINS MAIN must be the singleton (MAIN,);
      (ii) a ground tuple containing NO MAIN must have a member of
           ("#000000", "#ffffff") clearing 3:1 against every one of its
           grounds.

    Together they cover every tuple shape the table can hold, so the no-raise
    property holds for a row added next year as well as for the five that
    exist. Clause (i) hands the tuple to the on_color theorem, which
    guarantees an endpoint at >= 4.5826 against ANY colour, the owner's
    included — asserted below over the same mains the sweep binds, rather
    than cited. Clause (ii) hands it to a constant this file can check.

    THE SHAPE THIS REFUSES is why it is two clauses and not one. A row like
    ("--v2-rust-ring-navy", (MAIN, "#14324a")) satisfies a loose reading of
    "there is an endpoint" — white clears #14324a at 13.2503 — and raises the
    moment an owner picks a light main, because then neither black nor white
    clears both. Clause (i) refuses that row outright, and that is the one
    edit this test exists to stop.

    Clause (ii) is not vacuous: black clears V1_SURFACES at 19.6513 worst and
    V2_SURFACES at 17.9252 worst, white clears ("#14324a",) at 13.2503. Those
    margins are pinned, so adding a dark surface to either tuple is told
    about here rather than in a 500.
    """
    frozen = []
    singletons = 0
    for skin in sorted(ROLE_TOKENS):
        rows = ROLE_TOKENS[skin]["rings"]
        assert rows, skin
        for token, grounds in rows:
            assert grounds, (skin, token)
            if MAIN in grounds:
                # (i)
                assert grounds == (MAIN,), (
                    f"{skin} {token} takes {grounds}: a ring ground tuple "
                    "containing the owner's main colour must be the "
                    "singleton (MAIN,), or no endpoint is guaranteed and "
                    "visible_on can raise on the public page"
                )
                singletons += 1
            else:
                # (ii)
                margins = [
                    min(contrast(end, ground) for ground in grounds)
                    for end in ("#000000", "#ffffff")
                ]
                assert max(margins) >= NON_TEXT_RATIO, (
                    f"{skin} {token} takes {grounds}: neither black nor "
                    f"white clears every one of them at {NON_TEXT_RATIO} "
                    f"(best margins {margins})"
                )
                frozen.append((grounds, round(max(margins), 4)))

    assert singletons == 2, singletons
    assert sorted(set(frozen)) == sorted({
        (V1_SURFACES, 19.6513),
        (V2_SURFACES, 17.9252),
        (("#14324a",), 13.2503),
    }), sorted(set(frozen))

    # Clause (i)'s guarantee, asserted rather than cited: on_color clears
    # 4.5826 against every main the sweep binds, so a singleton (main,) can
    # never reach readable_on's endpoint search empty-handed.
    for main in _RING_MAINS:
        assert contrast(on_color(main), main) >= 4.5826, main


# The block palette_css returned at ba0e93d, for the pair
# test_the_block_it_writes_is_legible_at_every_derived_site already drives.
# A LITERAL, read off `git show ba0e93d:app/palette.py` and run — not
# regenerated from the current module, which would assert nothing.
_BA0E93D_BLOCK = {
    "v1": (
        ":root{--header-bg:#1a1a2e;--header-ink:#ffffff;"
        "--header-accent:#ffe9a8;--accent:#ffe9a8;--accent-dark:#ccba86;"
        "--accent-ink:#000000;--accent-dark-ink:#000000;"
        "--accent-fg:#856f2e;--accent-edge:#a38d4c;}"
    ),
    "v2": (
        ":root{--v2-header:#1a1a2e;--v2-header-ink:#ffffff;"
        "--v2-header-accent:#ffe9a8;--v2-rust:#ffe9a8;"
        "--v2-rust-dark:#ccba86;--v2-rust-ink:#000000;"
        "--v2-rust-dark-ink:#000000;--v2-rust-fg:#7f6928;"
        "--v2-rust-edge:#9c8645;}"
    ),
}

# And exactly what LLM-COP-44 appends to it. #a38d4c and #9c8645 are the same
# bytes the edge token above them carries, which is neither a coincidence nor
# a fold: on a light-surface row a painted ring IS visible_on(accent,
# surfaces), the same call. The two tokens make different PROMISES — an edge
# can never be transparent, because on .button.secondary the border is the
# only boundary there is, and a ring must be able to — and this very row,
# where the navy ring is transparent while the light one is painted, is what
# that difference looks like in the output.
_RINGS_APPENDED = {
    "v1": "--accent-ring:#a38d4c;--accent-ring-header:transparent;",
    "v2": (
        "--v2-rust-ring:#9c8645;--v2-rust-ring-navy:transparent;"
        "--v2-rust-ring-header:transparent;"
    ),
}


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_the_block_is_the_pre_change_one_with_the_rings_appended(skin):
    """BYTE IDENTITY OF WHAT DID NOT CHANGE.

    Nine values came out of palette_css before LLM-COP-44 and the same nine
    come out now, in the same order, with the rings after them. This is the
    assertion that goes red on a reordering, on a re-derivation of any
    existing token, and on a ring interleaved among them rather than
    appended — none of which any ratio test in this file could see, because
    all nine would still be legible colours and every ratio would still hold.

    The left-hand side is a LITERAL from ba0e93d, not a regeneration: a test
    that built the expected string by calling the module would pass on a
    module that had changed every value in it.
    """
    block = palette_css(skin, "#1a1a2e", "#ffe9a8")
    assert block == _BA0E93D_BLOCK[skin][:-1] + _RINGS_APPENDED[skin] + "}"
    # And the pre-change block really is a prefix, said separately so a
    # failure names which half moved.
    assert block.startswith(_BA0E93D_BLOCK[skin][:-1])


def test_palette_css_derives_every_ring_from_the_HOVER_fill_as_well():
    """THE WIRING, which neither the sweeps above nor the fence can see.

    _ring_sweep calls ring_on with both fills itself, so it proves what
    ring_on does with the arguments it is given and nothing about the
    arguments palette_css actually gives it. Drop shade(accent) from that
    call site and every test above this one stays green: the derivation is
    still correct, it is just no longer being told about the state the button
    spends half its life in.

    #ee0055 IS THE SHARPEST PICK ON THE 4096-COLOUR GRID THAT SEPARATES
    THEM, and it was found by sweeping for it rather than chosen. On
    --v2-navy its REST fill is 3.0076:1 — compliant, so a derivation that
    looked only there would return "transparent" and paint nothing — while
    its HOVER fill #be0044 is 2.0651:1, which is the button vanishing under
    the pointer. 811 of the 4096 grid colours do this and every one of them
    is on the navy card, because shade() darkens and every other ring ground
    in either skin is light.

    Asserted from the BLOCK, not from ring_on, so it is palette_css's call
    site under test. The numbers are pinned alongside the decision, because
    "not transparent" would also be true of a derivation that had stopped
    checking anything.
    """
    accent = "#ee0055"
    hover = shade(accent)
    assert round(contrast(accent, "#14324a"), 4) == 3.0076
    assert round(contrast(hover, "#14324a"), 4) == 2.0651

    written = dict(
        pair.split(":")
        for pair in palette_css("v2", "", accent)[6:-1].split(";")
        if pair
    )
    ring = written["--v2-rust-ring-navy"]
    assert ring != "transparent", (
        "the navy ring was derived from the rest fill alone: #ee0055 clears "
        "3:1 on --v2-navy at rest and 2.0651:1 on hover, so a button that "
        "looks compliant standing still disappears under the pointer"
    )
    assert contrast(ring, "#14324a") >= NON_TEXT_RATIO, ring


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_the_main_sentinel_never_reaches_the_rendered_block(skin):
    """MAIN IS A SENTINEL, NOT A COLOUR, and the day palette_css forgets to
    substitute it the page must break loudly rather than quietly.

    It is "<main>" and the "<" is deliberate: a leak fails _BLOCK's
    closed-alphabet assertion — the same assertion that keeps a stored value
    from opening a tag — instead of reaching the browser as a value no parser
    can read and no owner chose. So both halves are asserted here: that the
    sentinel still carries the character that makes a leak loud, and that it
    does not reach the output for any combination of chosen and unchosen
    roles, the unchosen being the case where substitution is easiest to skip.
    """
    assert "<" in MAIN
    tokens = ROLE_TOKENS[skin]
    for main, accent in (
        ("#1a1a2e", "#ffe9a8"),
        ("", "#ffe9a8"),
        ("#1a1a2e", ""),
        ("#ffffff", "#ffffff"),
        (tokens["default_main"], tokens["default_accent"]),
    ):
        block = palette_css(skin, main, accent)
        assert MAIN not in block, (skin, main, accent, block)
        assert "<" not in block, (skin, main, accent, block)


# --- ROLE_TOKENS: the table against the stylesheets it describes ------------


def _root_declarations(filename):
    """The :root block of a stylesheet, as {property: value}."""
    source = (STATIC / filename).read_text(encoding="utf-8")
    for at_rules, selectors, body in _rules(source):
        if not at_rules and selectors == [":root"]:
            return dict(_declarations(body))
    raise AssertionError(f"no :root rule in {filename}")


@pytest.mark.parametrize(
    "skin,filename,main_token,accent_token",
    (
        ("v1", "style.css", "--card", "--accent"),
        ("v2", "style-v2.css", "--v2-header", "--v2-rust"),
    ),
)
def test_the_frozen_defaults_are_still_the_stylesheets_own(
    skin, filename, main_token, accent_token
):
    """ROLE_TOKENS carries LITERALS, and this is what stops them drifting.

    app/palette.py needs the skin's own colours as VALUES — to derive a cross
    term when only one role is chosen, and to serve the panel's swatches — so
    they cannot be read out of CSS at runtime. That leaves a second copy, and
    a second copy of anything is a copy that goes stale. This test reads each
    stylesheet's own :root and fails the day somebody recolours a skin and
    does not come here.

    V1's main default is --card and not --header-bg on purpose: --header-bg
    is declared `var(--card)`, so --card is where the literal actually lives,
    and asserting against the indirection would assert nothing.

    WHAT THIS DOES NOT FENCE, and app/palette.py says the same beside
    V2_SURFACES: the surface VALUES are fenced, the surface SET is not. A
    future rule painting accent-coloured text on a dark band would pass every
    test in this file.

    SINCE LLM-COP-44 THE RING GROUNDS ARE FENCED THE SAME WAY, and they need
    it more than the surfaces do. A ring's ground is written into ROLE_TOKENS
    as the literal a CSS rule paints somewhere else — ("#14324a",) is
    --v2-navy, the contact card's background — so the table is asserting
    something about a colour it does not own. Recolour --v2-navy and the ring
    is still derived against #14324a, still clears 3:1 against a colour the
    card no longer has, and nothing anywhere says so. MAIN is skipped: it is
    a sentinel, not a literal, and the ground it stands for is the owner's
    and has no :root value at all.
    """
    declarations = _root_declarations(filename)
    assert ROLE_TOKENS[skin]["default_main"] == declarations[main_token]
    assert ROLE_TOKENS[skin]["default_accent"] == declarations[accent_token]
    values = set(declarations.values())
    for surface in ROLE_TOKENS[skin]["surfaces"]:
        assert surface in values, (skin, surface)
    frozen_grounds = {
        ground
        for _token, grounds in ROLE_TOKENS[skin]["rings"]
        for ground in grounds
        if ground != MAIN
    }
    assert frozen_grounds, skin
    for ground in sorted(frozen_grounds):
        assert ground in values, (
            f"{skin}: a ring is derived against {ground}, which {filename}'s "
            ":root declares nowhere — the ground moved and the derivation "
            "did not"
        )


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_every_token_the_override_writes_is_declared_by_its_stylesheet(skin):
    """A token the override writes that no :root declares is a declaration
    that reaches nothing — the silent failure this whole design is shaped to
    avoid, and one no rendered page would report.

    Two loops and not one, because "rings" is not shaped like the others:
    the nine roles above it are scalar token names, while "rings" is a list
    of (token, grounds) pairs, one per ground a primary button is painted on
    (LLM-COP-44). Folding them together would mean guessing at the shape of
    a row, which is how a table with two shapes ends up with a test that
    only checks one of them.
    """
    filename = "style.css" if skin == "v1" else "style-v2.css"
    declarations = _root_declarations(filename)
    for role in (
        "main_bg",
        "main_ink",
        "main_accent",
        "accent_bg",
        "accent_hover_bg",
        "accent_ink",
        "accent_hover_ink",
        "accent_fg",
        "accent_edge",
    ):
        assert ROLE_TOKENS[skin][role] in declarations, (skin, role)
    for token, _ in ROLE_TOKENS[skin]["rings"]:
        assert token in declarations, (skin, token)


# --- palette_css: the string that reaches a <style> block ------------------

# A CLOSED ALPHABET. No "<", no quote, no "}" except the final one — so the
# output cannot open a tag or close the block early whatever is stored.
_BLOCK = re.compile(r"^:root\{[-a-z0-9:;#]+\}$")


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_palette_css_is_empty_when_neither_colour_is_chosen(skin):
    """"" is not an empty block, it is NO block — which is what makes a site
    that has chosen nothing serve the bytes it served before this change."""
    assert palette_css(skin, "", "") == ""


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
@pytest.mark.parametrize("value", HOSTILE, ids=lambda v: repr(v)[:40])
def test_a_hostile_value_produces_no_block_at_all(skin, value):
    """The whole security claim in one assertion, and it is stated as "" and
    NOT as "matches the block pattern": a hostile value must not reach the
    page in any form, sanitised or otherwise, and the pattern would be
    satisfied by a block carrying a repaired approximation of it.

    Both roles, and both at once, because a value rejected in one position
    must be rejected in the other.
    """
    assert palette_css(skin, value, "") == ""
    assert palette_css(skin, "", value) == ""
    assert palette_css(skin, value, value) == ""


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
@pytest.mark.parametrize(
    "main,accent",
    (
        ("#1a1a2e", "#ffe9a8"),
        ("#ffffff", ""),
        ("", "#e400f3"),
        ("#000000", "#000000"),
        ("#8855ee", "#8855ee"),
        ("#FFFFFF", "#AABBCC"),
    ),
)
def test_every_block_it_does_write_is_inside_the_closed_alphabet(
    skin, main, accent
):
    ruleset = palette_css(skin, main, accent)
    assert _BLOCK.fullmatch(ruleset), ruleset
    # Every declaration, always — one code path, never a partial block. The
    # count is PER SKIN since LLM-COP-44 and it is the first thing about the
    # two skins' output that differs: nine scalar tokens each, plus one ring
    # per ground a primary button is painted on, and V1 has two such grounds
    # (its light surfaces and the header's) where V2 has three (its light
    # surfaces, the navy contact card and the header's). A number that was
    # the same for both is exactly the kind of thing somebody "fixes" by
    # widening it to >= 9, so it is written as two literals.
    assert ruleset.count(";") == {"v1": 11, "v2": 12}[skin]


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_one_chosen_role_still_fills_the_other_from_the_skin(skin):
    """The cross terms are why a partial block is not on offer.

    With only an accent chosen, the header's link-hover colour still has to
    be derived against a ground — and the honest ground is the skin's own
    header colour, which is why ROLE_TOKENS carries it. A block that omitted
    the main role would leave that derivation with nothing to work from.
    """
    tokens = ROLE_TOKENS[skin]
    only_accent = palette_css(skin, "", "#e400f3")
    assert f"{tokens['main_bg']}:{tokens['default_main']};" in only_accent
    only_main = palette_css(skin, "#1a1a2e", "")
    assert f"{tokens['accent_bg']}:{tokens['default_accent']};" in only_main


@pytest.mark.parametrize("skin", sorted(ROLE_TOKENS))
def test_the_block_it_writes_is_legible_at_every_derived_site(skin):
    """The derivations, read back out of the string the page will actually
    carry — so a token wired to the wrong derivation fails here rather than
    only in a browser.

    #ffe9a8 on #1a1a2e is the pair chosen to break a naive implementation:
    the pale accent renders at 1.1247 on --paper if it is used raw as text,
    and the dark header would take dark ink if the ink were not derived.
    """
    tokens = ROLE_TOKENS[skin]
    ruleset = palette_css(skin, "#1a1a2e", "#ffe9a8")
    written = dict(
        pair.split(":") for pair in ruleset[6:-1].split(";") if pair
    )

    # Header: the ink and the link hover both read on the chosen ground.
    assert written[tokens["main_bg"]] == "#1a1a2e"
    assert contrast(written[tokens["main_ink"]], "#1a1a2e") >= 4.5
    assert contrast(written[tokens["main_accent"]], "#1a1a2e") >= 4.5
    # Buttons: the raw colour is the ground, each label reads on ITS ground.
    assert written[tokens["accent_bg"]] == "#ffe9a8"
    assert contrast(written[tokens["accent_ink"]], "#ffe9a8") >= 4.5
    hover = written[tokens["accent_hover_bg"]]
    assert contrast(hover, "#ffe9a8") >= 1.15
    assert contrast(written[tokens["accent_hover_ink"]], hover) >= 4.5
    # And the accent AS TEXT reads on every surface of the skin — the case a
    # raw #ffe9a8 fails at 1.1247, which is what --accent-fg exists for.
    for surface in tokens["surfaces"]:
        assert contrast(written[tokens["accent_fg"]], surface) >= 4.5

    # APPENDED BY LLM-COP-40, below the seven text assertions rather than
    # among them: the accent AS AN EDGE is a NINTH value carrying a DIFFERENT
    # claim, so it gets its own paragraph and its own number. Raw #ffe9a8 is
    # 1.1247 on --paper and 1.1466 on --v2-page — a border technically drawn
    # and practically invisible, which is what --accent-edge exists for.
    for surface in tokens["surfaces"]:
        assert contrast(written[tokens["accent_edge"]], surface) >= (
            NON_TEXT_RATIO
        ), (skin, surface, written[tokens["accent_edge"]])
    # Wired to its OWN derivation, not to the text one. Both are present in
    # the same block, so a token pointed at the wrong call would still be a
    # legible colour and still pass every ratio above it.
    assert written[tokens["accent_edge"]] != written[tokens["accent_fg"]]


def test_a_stored_style_that_names_no_skin_still_renders_a_block():
    """resolve_style's doctrine, applied here: an unknown style resolves to
    the default rather than raising. A KeyError on ROLE_TOKENS would be a 500
    on the public page — the one failure app/styles.py exists to prevent, and
    it would be reintroduced by indexing the table with a raw stored value.
    """
    for style in ("banana", "", "V1", None, 7, {"a": 1}):
        assert palette_css(style, "#aabbcc", "") == palette_css(
            "v1", "#aabbcc", ""
        )
