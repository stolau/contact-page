"""The owner's two colours, and everything derived from them (USR-COP-2).

hero.color_main and hero.color_accent are values on the hero payload, so they
follow draft and publish exactly as section content does — the hero.style
precedent (app/styles.py): no settings table, no second publish participant,
no second badge story. Each is an owner-chosen "#rrggbb" or the empty string,
and "" means "skin default", not "black".

WHAT THIS MODULE IS FOR. A chosen colour cannot simply be dropped into the
stylesheet's --accent and --header-bg and left there: the accent is a button
BACKGROUND at two sites, a button LABEL's ground at two more, and plain TEXT
at eleven others, and the main colour is the ground the header's brand, links
and button sit on. So NINE of the eleven values the override writes on V1,
and TEN of the twelve it writes on V2, are DERIVED here, in Python, from the
two the owner picked — the hover shade, the two button label inks, the
header's own ink, the header's link-hover colour, the accent as readable body
text, the accent as a visible EDGE (LLM-COP-40, at SC 1.4.11's 3:1 rather
than 1.4.3's 4.5) and the primary button's boundary RING, one per ground the
button is ever painted on (LLM-COP-44, the same 3:1 against the ground rather
than against the surface set). The rings are also why the two skins' counts
DIFFER for the first time: V1 puts a primary button on two grounds and V2 on
three. Only --accent/--v2-rust and --header-bg/--v2-header are written
through unchanged, and both counts have moved twice: the DERIVED count was
six before the header ink, which on_color derives exactly as it derives the
two label inks, and seven before the rings; the TOTAL was nine on BOTH skins
before the rings, which is the last time the two wrote the same number of
declarations. Deriving them in CSS with color-mix() was not an option worth
taking: the derivations that matter are contrast decisions, and a contrast
decision that cannot be swept in a test is a decision nobody has checked.

THE ONE TABLE, IN THE ONE PLACE. ROLE_TOKENS below is the whole mapping from
the two owner roles to the two skins' token vocabularies. Neither template
nor stylesheet names a role, and no second copy of this mapping exists: a
skin recoloured without touching this file is caught by
tests/test_palette.py's frozen-literal test, which reads the stylesheets'
own :root blocks.

SECURITY, and it is the reason resolve_color is shaped the way it is. The
value this module is handed reaches a <style> block on the PUBLIC page. It
is whitelisted — "#rrggbb" and nothing else — and a value that fails the
whitelist becomes "", never a sanitised or repaired approximation of itself.
There is one code path out of resolve_color for every rejection, and it is
the same one "" takes, so a hostile value renders exactly as an unset one.
"""

import re
from functools import cache

from .styles import resolve_style

# The whole admissible alphabet: six hex digits behind a hash, nothing else.
# Not a normalising parser — "#fff" is REJECTED rather than expanded, and
# "#aabbcc " with its trailing space is rejected rather than stripped.
# Repairing a value the app did not write is guessing at an intent that may
# not exist, and every guess is another string shape that reaches a <style>
# block.
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def resolve_color(value):
    """The stored colour, lowercased — or "" when it is not one.

    isinstance BEFORE the regex, and it is load-bearing for the same
    mechanical reason app/styles.py's resolve_style states for its own
    ordering: re.fullmatch raises TypeError on a non-str, so a stored colour
    that is a JSON object, array, number or null would raise BEFORE the
    fallback is ever reached — which is a 500 on the public page, the one
    thing this function exists to prevent. Nothing in the app writes such a
    value (validate_payload admits only str for a plain field, and the
    panel's control is an <input type="color"> that can emit nothing else),
    but the store is not the app's alone.

    "" is the value the rest of this module reads as "skin default", so an
    unset colour and a rejected one are the same case downstream. That is
    deliberate: a rejected value must not be able to render as ANYTHING.
    """
    return (
        value.lower()
        if isinstance(value, str) and _COLOR.fullmatch(value)
        else ""
    )


@cache
def luminance(color):
    """WCAG 2.x relative luminance of an "#rrggbb" string.

    Cached because the tests sweep it: the four sweeps in
    tests/test_palette.py cost 75 s uncached and 5 s cached — measured, not
    guessed. The app itself calls it a handful of times per rendered page.

    The 0.03928 knee, the 2.4 exponent and the 0.2126/0.7152/0.0722 weights
    are the specification's, and they are what the on_color theorem in
    tests/test_palette.py actually tests: BT.601 weights or a gamma applied
    to the wrong side of the knee drop that sweep's worst case below 4.5.
    """
    channels = []
    for offset in (1, 3, 5):
        value = int(color[offset:offset + 2], 16) / 255
        channels.append(
            value / 12.92
            if value <= 0.03928
            else ((value + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(one, other):
    """The WCAG contrast ratio between two "#rrggbb" strings, 1.0 to 21.0."""
    lighter, darker = luminance(one), luminance(other)
    if lighter < darker:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


def on_color(background):
    """Black or white — whichever reads better on `background`.

    Never a third answer, and that is what makes it provable: the two
    candidates' ratios cross where L + 0.05 == sqrt(0.0525), and at that
    crossing both are 4.5826, so the better of the two clears 4.5:1 against
    EVERY colour there is. tests/test_palette.py sweeps that claim rather
    than restating it.
    """
    return (
        "#000000"
        if contrast("#000000", background) >= contrast("#ffffff", background)
        else "#ffffff"
    )


def shade(color):
    """The hover variant of a button background: 20 % toward black.

    ROUNDED, not truncated, and the difference is visible in the shipped
    palette: #1f6f5c x 0.8 is #19594a under round() and #185849 under int().

    THE FALLBACK IS NOT DECORATIVE. A plain darken returns the colour itself
    for black and something indistinguishable from it for #000011 — a hover
    state that does not visibly change is a hover state that is not there.
    So when darkening fails to move the colour by a stated floor of 1.15:1,
    it lightens by the same 20 % instead. tests/test_palette.py sweeps the
    floor; a criterion of 1.1 would be FALSE as written (#000011 darkens to
    a ratio of 1.0017), which is why the floor here is a measured number and
    not a hope.

    The shipped hover literals are NOT reproduced by this function and are
    not meant to be: --accent-dark is #17594a where shade("#1f6f5c") is
    #19594a. The shipped pairs are hand-picked, they stay the :root
    defaults, and this derivation applies only to a colour the owner chose.
    """
    darker = _mix(color, 0, 0.2)
    if contrast(darker, color) >= 1.15:
        return darker
    return _mix(color, 255, 0.2)


def _mix(color, endpoint, amount):
    """`color` moved `amount` of the way toward a flat endpoint channel."""
    return "#" + "".join(
        f"{round(channel + (endpoint - channel) * amount):02x}"
        for channel in (
            int(color[offset:offset + 2], 16) for offset in (1, 3, 5)
        )
    )


def readable_on(color, backgrounds, ratio=4.5):
    """`color` itself if it clears `ratio` on every background, else darkened
    or lightened just far enough that it does.

    THE IDENTITY CASE IS THE POINT. A colour that already reads is returned
    unchanged, which is what keeps the shipped palette byte-identical: both
    shipped accents clear 4.5:1 on every surface of their own skin, so this
    function never touches them. tests/test_palette.py asserts exactly that,
    and it is the assertion that goes red the day this derivation starts
    rewriting the author's own colours.

    A LINEAR SCAN, not a bisection, and deliberately. Contrast is not
    monotone along the walk when the colour starts lighter than the surface,
    so a bisection would be searching a space it has no invariant over.
    "The first step that clears" is well defined without monotonicity, and
    255 steps of arithmetic is nothing beside the render it feeds.

    IT RAISES when neither endpoint clears every background, and that is a
    deliberate contract rather than an oversight. Black clears a light
    surface and white clears a dark one; a tuple mixing a light and a dark
    surface can have NO common endpoint, and there is then no honest answer
    to return. Looping forever or returning the last unproven step would
    both ship a claim this module cannot make. The app cannot reach this
    branch today — palette_css passes either a single background (where the
    on_color theorem guarantees an endpoint at >= 4.5826) or one of the two
    frozen all-light surface sets (where black clears every member) — so
    the raise is a fence around a future surface set, not a live path. It is
    covered by a test all the same, because an uncovered raise is a comment.

    THE FROZEN SETS ARE NOW PASSED AT TWO RATIOS, 4.5 here and 3.0 through
    visible_on (LLM-COP-40), and black clears every member of both at 3.0 by
    a wider margin than it does at 4.5 — 19.6513/21.0000 for V1_SURFACES,
    20.0347/21.0000/17.9252 for V2_SURFACES. So the second caller cannot
    reach the raise the first one already cannot, and nothing about this
    function's behaviour at its default 4.5 changed to admit it.
    """
    if all(contrast(color, background) >= ratio for background in backgrounds):
        return color
    endpoint = next(
        (
            candidate
            for candidate in ("#000000", "#ffffff")
            if all(
                contrast(candidate, background) >= ratio
                for background in backgrounds
            )
        ),
        None,
    )
    if endpoint is None:
        raise ValueError(
            f"no endpoint clears {ratio}:1 against every one of "
            f"{tuple(backgrounds)}"
        )
    walked = color
    for _ in range(255):
        walked = _step(walked, endpoint)
        if all(
            contrast(walked, background) >= ratio
            for background in backgrounds
        ):
            return walked
    # Unreachable: 255 steps put `walked` AT `endpoint`, which was chosen
    # because it clears. Kept as the loop's honest exit rather than a
    # fall-through returning None, which would render as the string "None".
    return endpoint


def _step(color, endpoint):
    """One 1/255 step of every channel of `color` toward `endpoint`'s."""
    return "#" + "".join(
        f"{channel + (target > channel) - (target < channel):02x}"
        for channel, target in (
            (
                int(color[offset:offset + 2], 16),
                int(endpoint[offset:offset + 2], 16),
            )
            for offset in (1, 3, 5)
        )
    )


# WCAG 2.1 SC 1.4.11 (Non-text Contrast). 3:1, and it is a DIFFERENT number
# against a DIFFERENT claim from the 4.5 above — not a relaxation of it. 4.5
# is SC 1.4.3, about reading glyphs; 3.0 is about perceiving that a boundary
# is there at all. Two claims, two constants, and the day somebody folds them
# into one the tests below go red.
NON_TEXT_RATIO = 3.0


def visible_on(color, backgrounds):
    """`color` itself, or walked until it reaches 3:1 on every background.

    THE THIRD DERIVATION, and deliberately not a fourth mechanism. It
    delegates to readable_on rather than reimplementing the walk, so there
    is one linear scan, one identity case and one raise in this module, not
    two of each. What it adds is the CONSTANT and the claim attached to it:
    the accent drawn as a line or an edge, which SC 1.4.11 asks for 3:1 at.

    NO ratio parameter, and that is the point of having a name. A caller
    that could pass its own number could pass 1.2, and the SC citation would
    then live at the call site rather than here. readable_on keeps its ratio
    argument because it genuinely has two callers at two ratios; this one
    has one claim.

    IT IS NOT readable_on's default with a smaller number, and the tests are
    written as an inequality — visible_on(c, S) != readable_on(c, S) — so
    that aliasing the two goes red rather than quietly shipping edges walked
    to 4.5 and text walked to 3.

    IDENTITY ON BOTH SHIPPED ACCENTS: #1f6f5c clears V1_SURFACES at 5.6363
    and #a8431c clears V2_SURFACES at 5.1441, both far above 3.0, so a site
    that has chosen no colour renders exactly what it rendered before.

    It raises under exactly readable_on's condition, and that branch stays
    dead for the same reason: the only call site passes tokens["surfaces"],
    the frozen all-light sets, where black clears every member at
    19.6513/21.0000 (v1) and 20.0347/21.0000/17.9252 (v2) — a WIDER margin
    than the existing 4.5 call already relies on.
    """
    return readable_on(color, backgrounds, NON_TEXT_RATIO)


# THE GROUND THAT IS NOT FROZEN. A ring's grounds are written as literals in
# ROLE_TOKENS, but one of them is the owner's own main colour, which has no
# literal until a request arrives. This sentinel stands in its place and
# palette_css substitutes effective_main for it. It cannot collide with a
# frozen ground, because every frozen ground is "#rrggbb"; and if one ever
# escaped into the output, the "<" would fail the closed-alphabet assertion
# in tests/test_palette.py rather than render as a colour nobody chose.
MAIN = "<main>"


def ring_on(fills, grounds):
    """"transparent", or a colour that reaches 3:1 on every ground.

    THE FOURTH DERIVATION, and the one SC 1.4.11 case visible_on could not
    reach on its own (LLM-COP-44): a filled button's boundary. The boundary
    can be carried by the FILL against the ground, or by an edge drawn
    around it. The fill is the owner's literal pick and cannot be moved, so
    this returns the edge — and returns nothing at all when the fill is
    already doing the job.

    "transparent" IS THE IDENTITY CASE, and it is the whole reason this
    change repaints one button on the shipped pages instead of eleven. When
    every fill already clears 3:1 on every ground, the ring is a paint
    no-op and the rendering is byte-identical to what it was. That keeps
    LLM-COP-40's promise — "a compliant colour is never dulled" — for the
    fill as well as for the line.

    BOTH FILLS, not just the rest one. `fills` is (accent, shade(accent)),
    because the hover fill is the worse of the two and it is the state the
    defect actually lives in: shade("#a8431c") is #863616, which reaches
    1.6108 on the navy contact card where the rest fill reaches 2.1987. A
    ring derived from the rest fill alone would vanish exactly where it is
    needed.

    IT CANNOT REACH visible_on's RAISE, and that is structural rather than
    swept. Every ground tuple in ROLE_TOKENS["rings"] is either the
    singleton (MAIN,) — where the on_color theorem guarantees an endpoint at
    >= 4.5826 against ANY colour, the owner's included — or a tuple of
    frozen literals with a checked black-or-white endpoint at 3:1
    (V1_SURFACES at >= 19.6513 for black, V2_SURFACES at >= 17.9252 for
    black, ("#14324a",) at 13.2503 for white). tests/test_palette.py fences
    both clauses off the table itself, so a row somebody adds later is held
    to them too — which is what keeps readable_on's raise from becoming a
    500 on the public page.
    """
    if all(
        contrast(fill, ground) >= NON_TEXT_RATIO
        for fill in fills
        for ground in grounds
    ):
        return "transparent"
    return visible_on(fills[0], grounds)


# THE SURFACES THE ACCENT RENDERS AS TEXT ON, per skin — frozen literals,
# fenced against drift by tests/test_palette.py, which reads each
# stylesheet's own :root and asserts every literal here is still one of its
# token values.
#
# Since LLM-COP-40 these are also the surfaces the accent is drawn as an
# EDGE on, and the same tuple is passed at both ratios rather than a fourth
# frozen literal being invented. The eliminations below were run for text
# and hold for edges unchanged: every retargeted edge site's ground is a
# member of its skin's tuple, re-verified rule by rule in that change.
#
# V1: --paper and --card. Enumerated by elimination, not by assumption —
# `grep -n background app/static/style.css` answers 22 declarations. Minus
# the ELEVEN that resolve to `var(--card)` or `var(--paper)`, minus the five
# `none` and the one `transparent`, minus the four owner-role grounds
# (`var(--accent)` twice, `var(--accent-dark)`, `var(--header-bg)`), exactly
# ONE is left: :353, the login dialog's rgba(34,51,59,0.55) scrim, which
# carries no text at all. 11 + 5 + 1 + 4 + 1 == 22, so the recipe can be
# re-checked against that one grep.
V1_SURFACES = ("#faf7f2", "#ffffff")

# V2: --v2-page, --v2-card and --v2-tint. The same elimination, run against
# style-v2.css, leaves NINE non-token backgrounds rather than one, and every
# one of them is listed here because "no rust text sits on any of them" is a
# claim about a set, and a set stated loosely is a set nobody can re-check:
#
#   1. :186 .brand-avatar    --v2-navy; its label is a frozen `color: #fff`
#                            on the same rule, so no accent text sits on it
#   2. :226 .v2-hero-photo   gradient standing in for the hero photograph;
#                            the card that carries the text floats OVER it
#                            on --v2-card (:256)
#   3. :240 .v2-hero-fade    the fade at the foot of the band — no text
#   4. :281 .v2-hero-rule    a 1px gradient rule — no text
#   5. :465 .portrait        #eceff1; its placeholder text is --v2-muted
#                            (:473)
#   6. :541 .v2-contact-card --v2-navy; its one <a>, .gdpr-open, is
#                            overridden to #c3d5e3 at :608, and its result
#                            and error lines to #eaf2f8 (:612) and #ffb4a2
#                            (:613)
#   7. :595 .v2-contact-form input/textarea  rgba(255,255,255,0.07); the
#                            field text is #eaf2f8
#   8. :645 .v2-footer       --v2-navy-deep; its link is #b8cbdb at :659
#   9. :753 .dialog-backdrop the scrim — no text
#
# SUBTRACTED BY THE RECIPE, LISTED BECAUSE A READER WILL LOOK FOR THEM —
# these three stood in the eleven-item list this replaces and are gone from
# the nine because the recipe removes them, not because they vanished:
#
#   :388 .v2-band-media-left .v2-section-label::after   var(--v2-rust-edge),
#        an owner role — and var(--v2-rust), also an owner role, on the day
#        the old list was written
#   :488 .portrait.has-image   `background: none`
#   :732 .v2-contact-band      `background: none`, in the phone breakpoint
#
# .brand-avatar was never in this list: its rule landed in 874c685
# (2026-09-01) and the list in 88ca8c6 (2026-09-08), so the enumeration was
# incomplete the day it was written rather than drifting into incompleteness.
#
# So the rust colour renders as text on --v2-page, --v2-card and --v2-tint,
# and on nothing else.
V2_SURFACES = ("#f7fafc", "#ffffff", "#e6eef6")

# WHAT IS FENCED AND WHAT IS NOT, said plainly because the gap outlives this
# change. tests/test_palette.py fences the VALUES above against drift: it
# reads each stylesheet's :root and fails the day somebody recolours a skin
# without coming here.
#
# THE BACKGROUND SET IS FENCED TOO, since LLM-COP-47. In
# tests/test_palette_css.py, test_the_surface_elimination_is_still_exhaustive
# re-runs the elimination above against the stylesheet and fails when a
# background appears that no entry accounts for. A new dark band therefore
# cannot arrive in silence UNLESS its ground is an owner-role token, it
# lives in direct-edit.css, or it is written as a background-* longhand:
# step 2 drops the first, this test reads only the two skins, and it takes
# only the `background` shorthand. No longhand exists in any stylesheet
# today (`grep -rE 'background-[a-z]+' app/static/*.css` is empty). Every
# other new background survives elimination and reddens the list until
# somebody comes here and says which of the two lists it belongs in.
#
# WHAT IS STILL NOT FENCED is the other half of the claim: WHICH of those
# backgrounds accent-coloured text is ever actually painted on. No test can
# ask a STYLESHEET that, so a rule putting accent-coloured text on --v2-navy
# — a ground the list above already names — still renders at roughly 1.5:1
# with every test in this change green.
#
# A rendered DOM, though, can be asked, and the boundary is worth stating
# precisely rather than despairing at. tests/browser/test_browser_colors.py
# already carries the machine: its measurement helper walks an element's
# ancestors for the effective background. A partial fence would plant a
# sentinel accent, sweep EVERY element in the document rather than a named
# list, keep the ones whose computed colour is the sentinel's derived
# --v2-rust-fg, and assert each one's walked background is in V2_SURFACES.
# That is not circular — the tuple is what is under test, the DOM is the
# evidence — and it rots on no line number.
#
# It is not here because it is new test work, not because it is impossible.
# Its own limit is coverage rather than principle: it sees only backgrounds
# the fixture's pages actually render, so a rule that fires for absent
# content, an unhovered state or another breakpoint still escapes it. That
# is why the elimination lists above keep earning their place beside it —
# they are how the next person re-checks the set by hand.

# WHAT IS NOW CONSTRAINED, AND WHAT STILL IS NOT: NON-TEXT CONTRAST
# (LLM-COP-40). The accent is also drawn as lines and edges. Until this
# change every one of those sites kept the RAW chosen colour, so a very pale
# pick gave a readable label inside an all-but-invisible outline. WCAG 2.1
# SC 1.4.11 wants 3:1 there, and visible_on above is that number.
#
# FIRST, A CORRECTION TO USR-COP-2's OWN ENUMERATION, because it very nearly
# cost this change a regression. The list here used to name style.css:57 and
# style-v2.css:84 as `.button.secondary`. Those two numbers are as of
# 88ca8c6 and stay as written, because renumbering a claim about a past file
# makes it false (today the same two declarations are style.css:99 and
# style-v2.css:131, enumerated at the NOT RETARGETED block below). They were
# the BARE `.button`, which both button variants inherit.
# `.button.secondary` declared no border property at all. Retargeting the
# bare rule would therefore have repainted every PRIMARY button's border
# too. The v2 primary button's grounds —
# --v2-navy #14324a on the contact card, --v2-header #d9e8f2 in the header —
# are in neither surface tuple; v1's hero primary sits on --paper, which IS
# in V1_SURFACES, so the ground argument is v2's alone and the reason that
# covers both skins is that the border is byte-identical to its own fill.
# Measured, the v2 contact card falls from
# 11.0249:1 to 3.7287:1 and the v2 header reaches only 2.8386:1, still short
# of 3:1. So the border-color goes on the
# .button.secondary rules, which are (0,2,0) and later in source and win
# twice over, and the bare rules are left exactly as they were.
#
# THE SITES, and which claim each one rides on:
#
#   RETARGETED to the edge token, on SC 1.4.11 proper — a boundary a user
#   must perceive:
#     style.css     :116 .button.secondary   border-color: var(--accent-edge)
#     style-v2.css  :154 .button.secondary   border-color: var(--v2-rust-edge)
#     direct-edit.css :32 body.direct-edit [data-field]   the idle dashed
#                          affordance, and :46 the focus/active ring — a
#                          STATE indicator, on the one page that both
#                          receives the override and draws its own ring.
#
#   RETARGETED on the weaker and separately stated ground that a line drawn
#   in a colour nobody can see is not a line — an owner picks a colour in
#   order to see it, and the same token costs no extra derivation:
#     style.css     :202 .fact-card          border-top
#                   :251 .service-card       border-top
#     style-v2.css  :388 .v2-section-label::after   the short rust bar
#   These three are NOT claimed as 1.4.11 cases: the cards' perceivable
#   boundary is their 1px var(--line) frame, fixed literals are taken by
#   ordinal position — fact cards 2-4 (style.css:207-209) and service cards
#   2-3 (:255-256), which is every such rule the file declares — and the
#   bar is deleted outright at the phone breakpoint (style-v2.css:721-722,
#   `content: none`).
#
#   LLM-COP-42 — the five direct-edit.css sites the override reached and
#   nothing constrained, split by the same two claims. All five measured at
#   1.2019:1 on V1 with #ffe9a8 planted, before that change.
#
#   RETARGETED as TEXT, on SC 1.4.3's 4.5:1 — and the split between the two
#   ink tokens is the whole of the care here:
#     direct-edit.css :114 .direct-esikatsele  color: var(--accent-fg)
#                     :211 .direct-changes     color: var(--accent-fg)
#   Both sit on --card, which is NOT an owner role on V1 (ROLE_TOKENS["v1"]
#   emits --header-bg as main_bg and nothing else touches it), so --card
#   #ffffff and --line #e4ddd3 are frozen literals and readable_on's
#   V1_SURFACES is the right tuple with no new surface added. Measured after:
#   4.8718:1 each.
#     direct-edit.css :128 .direct-field-tag   color: var(--accent-ink)
#   This one takes the INK token, not the fg token, because its GROUND is the
#   accent itself (`background: var(--accent)`, :129) — the .button.primary
#   case. --accent-fg is readable_on(accent, V1_SURFACES) and makes no claim
#   about legibility ON the accent: for #ffe9a8 it is #856f2e, which on
#   #ffe9a8 measures 4.0536:1 and FAILS. --accent-ink is on_color(accent) and
#   rides the theorem's 4.5826:1 floor instead. Measured after: 17.4730:1.
#
#   RETARGETED on the weaker, separately stated ground above — a line drawn
#   in a colour nobody can see is not a line — and deliberately NOT on
#   1.4.11 proper:
#     direct-edit.css :212 .direct-changes     border: 1px solid
#                                              var(--accent-edge)
#                     :158 .direct-toolbar button:hover:not(:disabled)
#                                              border-color: var(--accent-edge)
#   The badge is framing around text that carries its own meaning, and
#   .direct-toolbar button keeps a permanent 1px solid var(--line) in every
#   state (:149), so the hover is a COLOUR CHANGE on an existing boundary and
#   not the appearance of one. Claiming 1.4.11 here would be the mistake the
#   .button.primary:hover paragraph above exists to prevent. Measured after:
#   3.2449:1 against --card, both.
#
#   The two fills in that file stay the owner's RAW pick, and both are
#   recorded rather than omitted (tests/test_palette_css.py,
#   test_the_direct_edit_fills_that_stay_the_owners_raw_pick):
#   .direct-field-tag's background IS the ground --accent-ink is derived
#   against and must stay raw, and .direct-dot (direct-edit.css:105-110) is
#   aria-hidden and redundant with the <span class="direct-mode"> text
#   beside it, so it is not a graphical object required to understand the
#   content. After LLM-COP-42 every raw var(--accent) left in
#   direct-edit.css is a FILL, and
#   every TEXT and EDGE in it reads a derived token.
#
#   ON V2, FOUR OF THE FIVE ARE INERT AND ONE IS NOT, by failure mode rather
#   than by derivation, and this is the same invalidity the --v2-rust-ring
#   comment below already records for .direct-publishbar. style-v2.css
#   declares none of --accent, --accent-fg, --accent-ink, --accent-edge,
#   --card or --line, so every direct-edit.css rule naming one is invalid at
#   computed-value time there: both borders paint nothing (0px none, before
#   and after) and both --accent-fg colours already inherited. But
#   .direct-field-tag's old `#fff` was a VALID literal and computed white on
#   --v2-page #f7fafc — 1.0482:1 — while var(--accent-ink) is invalid, and an
#   invalid declaration of an INHERITED property becomes `unset`, which for
#   color is `inherit`, NOT a fall-through to the next rule in the cascade.
#   So the tag now takes body's --v2-body #3d5f77 and measures 6.4593:1.
#   THAT IS AN ACCIDENT OF THE CASCADE AND NOT A CLAIM THIS MODULE MAKES; no
#   derivation here guarantees it, and it will change the day V2 is given the
#   token vocabulary. It is pinned as such, as a defect record rather than a
#   proof, in
#   test_the_v2_direct_edit_chrome_takes_no_colour_from_the_override.
#
#   NOT RETARGETED, deliberately, and this is a decision rather than an
#   omission:
#     style.css     :99  .button           border: 1px solid var(--accent)
#     style-v2.css  :131 .button           border: 1px solid var(--v2-rust)
#     style-v2.css  :153 .button.primary:hover  border-color: var(--v2-rust-dark)
#   On every element these actually paint alone — the primary buttons — the
#   border is byte-identical to the fill (style.css:114, style-v2.css:152-153),
#   so it is not a boundary anyone perceives, and contrast(x, x) is 1.0 for
#   every colour there is: an assertion that can never pass is proof the site
#   is misidentified, not proof of a defect.
#
# THE REAL 1.4.11 CASE, AND WHAT WAS DONE ABOUT IT (LLM-COP-44). This
# paragraph used to say the case could not be reached and to leave it filed.
# It is reached now, and by a different argument rather than by a bigger
# surface tuple.
#
# The case: a primary button's FILL against its container. On V2 that is
# --v2-navy #14324a (style-v2.css:28) and --v2-header #d9e8f2 (:32), where
# the SHIPPED rust reaches only 2.1987:1 on the navy card before any owner
# picks anything; on V1 it is --paper/--card and --header-bg, where an owner
# who gives both roles one colour gets 1.0000:1 — a button that is literally
# not there.
#
# What was NOT done, and why both were dead ends:
#   MOVE THE FILL. The fill IS the owner's pick, so darkening it overrules
#   the choice and desynchronises --v2-rust-ink, which on_color derives
#   against the raw pick. Worse, it is impossible: one fill faces three
#   grounds on V2, and a tuple holding both #ffffff and #14324a has NO
#   common endpoint — contrast("#000000", "#14324a") is 1.5849 and
#   contrast("#ffffff", "#ffffff") is 1.0000 — so readable_on's
#   documented-dead raise would become a live 500 on the public page.
#   MOVE THE GROUND. --v2-navy is the design, not an owner role, and four
#   frozen text literals read against it. And it cannot touch the header
#   site at all: --v2-header IS main_bg, the owner's own colour.
#
# What WAS done: the button gains a boundary OUTSIDE its border box, in a
# colour that IS constrained — ring_on above, read through the "rings" row
# below and painted as `box-shadow: 0 0 0 1px` in both stylesheets. A ring
# outside the border box has exactly ONE ground, the container, so each row
# takes the ground it actually sits on rather than a set: one ground per
# token, and a singleton tuple can never reach the raise. The fill still
# carries the boundary wherever it already clears 3:1, because ring_on
# returns "transparent" there and nothing is painted.
#
# NOT the border-color, and not an outline. border-color cannot express "no
# ring" — the identity value would have to be the fill, and
# .button.primary:hover re-declares it (style-v2.css:153), so preserving
# both states would cost two tokens per ground; it would also overturn the
# decision recorded just above, that the primary border is its own fill.
# outline collides with direct-edit.css's own [data-field] ring, which the
# primary buttons carry, and its computed width is the property that
# differed between two Chrome versions on CI. box-shadow follows
# border-radius, costs no layout, is re-declared by neither hover rule, and
# takes "transparent" as an exact paint no-op.
#
# ONE HONEST LIMIT of what IS constrained: the direct-edit outline sits at
# outline-offset: 3px, OUTSIDE the border box, so its ground is the container
# — and every one of the 23 [data-field] outlines in page.html lands on
# --paper, because neither the fact_card nor the service_card macro
# (page.html:22-33) carries a data-field, and no section between them and the
# body declares a background. Outline-against-container is what the tuple
# constrains. Outline-against-the-ADJACENT-FILL is not, and no tuple over
# ancestor backgrounds can constrain it: .cta-contact is itself a
# [data-field] whose own fill can be the raw accent.
#
# THAT 23 IS `grep -o 'data-field="' app/templates/page.html | wc -l`.
# tests/test_direct_edit.py's BOUND_SCALAR_COUNT is also 23 today, and it is
# a DIFFERENT measurement: it counts the FIELDS scalars whose
# data-section/data-field pair appears in the rendered /muokkaa/sivu
# document, not data-field attributes in this template. They coincide
# because every one of these 23 attributes carries a distinct
# (section, field) pair — 19 distinct field names over 23 occurrences,
# with section_label appearing five times and every other name once.
# Either can move without the other.

ROLE_TOKENS = {
    # Per skin: the nine scalar token names the override writes, the "rings"
    # row — which is a LIST of (token, grounds) pairs rather than a scalar,
    # and the reason the two skins now write a different NUMBER of
    # declarations — the skin's own frozen main and accent (needed for the
    # CROSS TERMS: a chosen main with an unset accent still has to derive
    # the header's link-hover colour from the skin's own accent, against the
    # chosen ground), and the surface set the accent renders as text on.
    #
    # THE RINGS ROW IS THE GROUND TABLE, in this one place, the way the rest
    # of this table is. Each pair names the token a rule reads and the
    # ground(s) that rule's button is painted on; MAIN stands for the
    # owner's main colour, which has no literal until a request arrives. Two
    # clauses hold over every row and tests/test_palette.py checks them off
    # the table statically, with no colour sweep: a tuple CONTAINING MAIN
    # must be the singleton (MAIN,), and a tuple containing NO MAIN must
    # have a member of ("#000000", "#ffffff") clearing 3:1 against every one
    # of its grounds. Together they are what makes ring_on structurally
    # unable to raise — for these rows and for any row added later.
    #
    # V1's main role is --header-bg, a token this change ADDS, because the
    # header's ground is var(--card) and --card is eleven other surfaces
    # too — every white panel on the page. Repainting --card would repaint
    # all eleven. V2 needed no such split: --v2-header is referenced once.
    "v1": {
        "default_main": "#ffffff",   # --card, which --header-bg defaults to
        "default_accent": "#1f6f5c",  # --accent
        "surfaces": V1_SURFACES,
        "main_bg": "--header-bg",
        "main_ink": "--header-ink",
        "main_accent": "--header-accent",
        "accent_bg": "--accent",
        "accent_hover_bg": "--accent-dark",
        "accent_ink": "--accent-ink",
        "accent_hover_ink": "--accent-dark-ink",
        "accent_fg": "--accent-fg",
        "accent_edge": "--accent-edge",
        "rings": (
            # Every .button.primary in this skin except the header's. Six
            # sites, all on a surface of V1_SURFACES: the hero .cta-contact
            # (page.html:65) and the yhteydenotto section's .cta-contact
            # (page.html:159), both of which walk to body's --paper because
            # neither .hero (style.css:161) nor .contact (:271) declares a
            # background; .cd-submit and .login-submit on --card; and
            # direct-edit's .direct-julkaise, which sits in
            # .direct-publishbar (direct-edit.css:205, NOT the topbar) on
            # that rule's var(--card).
            ("--accent-ring", V1_SURFACES),
            # .site-header .button.primary (page.html:180), whose ground is
            # --header-bg (style.css:125) — main_bg, the owner's own colour,
            # which is why this ground is MAIN and not a literal.
            ("--accent-ring-header", (MAIN,)),
        ),
        # THE DARK GROUNDS (LLM-COP-45): rows of (edge token, ink token,
        # grounds) for a .button.secondary that is painted on a dark card
        # rather than on one of `surfaces`. V1 HAS NO DARK CARD — its
        # contact section is a light band — so this table is empty, and an
        # empty table is the code saying so rather than an omission. It also
        # keeps V1's rendered block byte-identical to what it was.
        "darks": (),
    },
    "v2": {
        "default_main": "#d9e8f2",   # --v2-header
        "default_accent": "#a8431c",  # --v2-rust
        "surfaces": V2_SURFACES,
        "main_bg": "--v2-header",
        "main_ink": "--v2-header-ink",
        "main_accent": "--v2-header-accent",
        "accent_bg": "--v2-rust",
        "accent_hover_bg": "--v2-rust-dark",
        "accent_ink": "--v2-rust-ink",
        "accent_hover_ink": "--v2-rust-dark-ink",
        "accent_fg": "--v2-rust-fg",
        "accent_edge": "--v2-rust-edge",
        "rings": (
            # The primary buttons on a light surface: the hero card's
            # (page_v2.html:146) on --v2-card, .cd-submit and .login-submit
            # on --v2-card, and direct-edit's Julkaise, whose ground walks
            # all the way to body's --v2-page because .direct-publishbar's
            # `background: var(--card)` (direct-edit.css:205) is invalid on
            # a skin that declares no --card — the same invalidity
            # tests/browser/test_browser_colors.py records for
            # .direct-topbar in its SWEEP_ROUTES comment. That last site is
            # why this row takes the whole V2_SURFACES tuple rather than
            # #ffffff alone.
            ("--v2-rust-ring", V2_SURFACES),
            # .v2-contact-primary (page_v2.html:296) inside
            # .v2-contact-card, whose background is --v2-navy
            # (style-v2.css:541) — the one site that fails 3:1 before any
            # owner picks anything, at 2.1987 for the shipped rust and
            # 1.6108 for its hover shade.
            ("--v2-rust-ring-navy", ("#14324a",)),
            # .header-contact (page_v2.html:317) inside .v2-header
            # (style-v2.css:165), whose ground is main_bg — the owner's own
            # colour, hence MAIN.
            ("--v2-rust-ring-header", (MAIN,)),
        ),
        # THE FIFTH DERIVATION GROUND (LLM-COP-45). .v2-contact-call, the
        # card's outlined call button, is a .button.secondary on
        # --v2-navy — a ground no member of V2_SURFACES names, so the two
        # light-surface tokens it would otherwise read land at 2.1987:1
        # there for the shipped rust, on BOTH the border and the label. TWO
        # tokens per row and not one: on a secondary button the border is
        # the only boundary there is (3:1, SC 1.4.11) and the label is text
        # (4.5:1, SC 1.4.3), and a single token cannot answer both.
        #
        # ONE GROUND, A FROZEN LITERAL, so this can never reach
        # readable_on's raise: white clears #14324a at 13.2503, which is
        # over the 4.5 the ink is asked for and therefore over the 3.0 the
        # edge is. tests/test_palette.py fences that off the table itself,
        # the way it already does for the rings.
        "darks": (
            ("--v2-rust-edge-navy", "--v2-rust-fg-navy", ("#14324a",)),
        ),
    },
}

# TWO LABEL INKS, not one, and the sweep is why. The button's rest and hover
# grounds are different colours, and no single black-or-white choice clears
# 4.5:1 against both: the best one manages 3.7680, at #e400f3. Split in two,
# each is covered by the on_color theorem at >= 4.5826. This is a defect
# that asserting would have missed and sweeping found, which is the whole
# argument for sweeping.


def palette_css(style, main, accent):
    """The <style> block's contents for one skin, or "" when nothing is set.

    ONE CODE PATH, and no partial blocks. When either role is set the WHOLE
    block is written, with the unset role filled from that skin's frozen
    default — because the cross terms are derived from both roles at once
    and a half-written block derives them against the wrong ground. The
    visible consequence is stated rather than hidden: choosing only an
    accent also snaps the header's ink to the black-or-white on_color picks
    for the skin's own header colour, a small shift from --ink. Two code
    paths would avoid that shift and would double the surface every future
    change to this function has to be checked against.

    resolve_style is applied here as well as at the call site
    (app/sections.py). Belt-and-braces on purpose: this function's output
    goes into a page, and a KeyError on a stored style is a 500 — the same
    hazard resolve_style itself exists for.

    The output alphabet is [-a-z0-9:;#{}] by construction: token names are
    literals from the table above and every value comes out of
    resolve_color, on_color, shade or readable_on, all of which return
    lowercase "#rrggbb" — or out of ring_on, whose OTHER return is the bare
    keyword "transparent". That is the one value in the block that is not a
    hash and six hex digits, and it was checked against the alphabet rather
    than assumed into it: "transparent" is eleven lowercase letters, so it
    sits inside the same [-a-z0-9:;#]+ that tests/test_palette.py's _BLOCK
    and the browser suite's copy of that regex both already enforce, and
    neither had to be widened to admit it. No <, no quote and no closing
    brace can appear in the output, which is what makes emitting it inside
    <style> safe. The templates emit it WITHOUT |safe all the same — see
    page.html.
    """
    tokens = ROLE_TOKENS[resolve_style(style)]
    chosen_main = resolve_color(main)
    chosen_accent = resolve_color(accent)
    if not chosen_main and not chosen_accent:
        return ""
    effective_main = chosen_main or tokens["default_main"]
    effective_accent = chosen_accent or tokens["default_accent"]
    hover = shade(effective_accent)
    declarations = (
        (tokens["main_bg"], effective_main),
        (tokens["main_ink"], on_color(effective_main)),
        (
            tokens["main_accent"],
            readable_on(effective_accent, (effective_main,)),
        ),
        (tokens["accent_bg"], effective_accent),
        (tokens["accent_hover_bg"], hover),
        (tokens["accent_ink"], on_color(effective_accent)),
        (tokens["accent_hover_ink"], on_color(hover)),
        (
            tokens["accent_fg"],
            readable_on(effective_accent, tokens["surfaces"]),
        ),
        (
            tokens["accent_edge"],
            visible_on(effective_accent, tokens["surfaces"]),
        ),
    ) + tuple(
        # APPENDED, never interleaved, and the byte-identity pins in
        # tests/test_palette.py depend on that: the nine values above come
        # out in the order they came out in before LLM-COP-44, and the rings
        # follow. MAIN is substituted here and only here — it is the one
        # ground that is not a literal.
        (
            token,
            ring_on(
                (effective_accent, hover),
                tuple(
                    effective_main if ground == MAIN else ground
                    for ground in grounds
                ),
            ),
        )
        for token, grounds in tokens["rings"]
    ) + tuple(
        # APPENDED AFTER THE RINGS, for the reason the rings are appended
        # after the nine: everything written before stays where it was, so
        # the byte-identity pins keep meaning what they say. Two
        # declarations per row — the edge at 3:1 and the ink at 4.5:1
        # against the same dark ground — and no MAIN substitution, because
        # a dark ground is a frozen literal by definition.
        declaration
        for edge, ink, grounds in tokens["darks"]
        for declaration in (
            (edge, visible_on(effective_accent, grounds)),
            (ink, readable_on(effective_accent, grounds)),
        )
    )
    body = "".join(f"{name}:{value};" for name, value in declarations)
    return ":root{" + body + "}"
