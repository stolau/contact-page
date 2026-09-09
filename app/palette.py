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
and button sit on. So five of the eight values the override writes are
DERIVED here, in Python, from the two the owner picked — the hover shade, the
two button label inks, the header's link-hover colour and the accent as
readable body text. Deriving them in CSS with color-mix() was not an option
worth taking: the derivations that matter are contrast decisions, and a
contrast decision that cannot be swept in a test is a decision nobody has
checked.

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


# THE SURFACES THE ACCENT RENDERS AS TEXT ON, per skin — frozen literals,
# fenced against drift by tests/test_palette.py, which reads each
# stylesheet's own :root and asserts every literal here is still one of its
# token values.
#
# V1: --paper and --card. Enumerated by elimination, not by assumption —
# `grep -n background app/static/style.css`, minus every `var(--card)` and
# `var(--paper)`, minus `none`, `transparent` and the `background-*`
# longhands, leaves exactly ONE line: :285, the login dialog's
# rgba(34,51,59,0.55) scrim, which carries no text at all.
V1_SURFACES = ("#faf7f2", "#ffffff")

# V2: --v2-page, --v2-card and --v2-tint. The same elimination, run against
# style-v2.css, leaves ELEVEN non-token backgrounds rather than one, and
# every one of them is listed here because "no rust text sits on any of
# them" is a claim about a set, and a set stated loosely is a set nobody can
# re-check:
#
#   :164 .v2-hero-photo      gradient standing in for the hero photograph;
#                            the card that carries the text floats OVER it
#                            on --v2-card (:194)
#   :178 .v2-hero-fade       the fade at the foot of the band — no text
#   :219 .v2-hero-rule       a 1px gradient rule — no text
#   :326 .v2-section-label::after   the short rust bar — no text; it is one
#                            of the non-text-contrast sites this change
#                            deliberately leaves unconstrained (below)
#   :403 .portrait           #eceff1; its placeholder text is --v2-muted
#   :426 .portrait.has-image `background: none` — the photograph itself
#   :468 .v2-contact-card    --v2-navy; its one <a>, .gdpr-open, is
#                            overridden to #c3d5e3 at :538, and its result
#                            and error lines to #eaf2f8 / #ffb4a2
#   :519 .v2-contact-form input/textarea  rgba(255,255,255,0.07); the field
#                            text is #eaf2f8
#   :569 .v2-footer          --v2-navy-deep; its link is #b8cbdb at :589
#   :662 .v2-contact-band    `background: none` inside the phone breakpoint
#   :680 .dialog-backdrop    the scrim — no text
#
# So the rust colour renders as text on --v2-page, --v2-card and --v2-tint,
# and on nothing else.
V2_SURFACES = ("#f7fafc", "#ffffff", "#e6eef6")

# WHAT IS FENCED AND WHAT IS NOT, said plainly because the gap outlives this
# change. tests/test_palette.py fences the VALUES above against drift: it
# reads each stylesheet's :root and fails the day somebody recolours a skin
# without coming here. NOTHING FENCES THE SET. A future rule that puts
# accent-coloured text on --v2-navy, or on a new dark band, would pass every
# test in this change while rendering at roughly 1.5:1, because no test can
# ask a STYLESHEET which of its backgrounds a colour is ever painted on.
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

# WHAT THIS MODULE DELIBERATELY DOES NOT CONSTRAIN: NON-TEXT CONTRAST. The
# accent is also drawn as lines and edges, and every one of those sites keeps
# the RAW chosen colour rather than a derived one — so a very pale pick gives
# a readable label inside an all-but-invisible outline. WCAG 1.4.11 wants 3:1
# there. The sites, enumerated so the boundary of this change's claim can be
# checked rather than taken on trust:
#
#   style.css     :57  .button.secondary   border: 1px solid var(--accent)
#                 :150 .fact-card          border-top: 3px solid var(--accent)
#                 :199 .service-card       border-top: 3px solid var(--accent)
#   style-v2.css  :84  .button.secondary   border: 1px solid var(--v2-rust)
#                 :93  .button.primary:hover
#                                     border-color: var(--v2-rust-dark)
#                 :326 .v2-section-label::after   the short rust bar
#
# Left unconstrained on purpose: the claim this change makes is about TEXT,
# none of these carries any, and a token at a 3:1 ratio is a second
# derivation and six more sites — a separate piece of work, filed rather than
# smuggled in here.

ROLE_TOKENS = {
    # Per skin: the eight token names the override writes, the skin's own
    # frozen main and accent (needed for the CROSS TERMS — a chosen main
    # with an unset accent still has to derive the header's link-hover
    # colour from the skin's own accent, against the chosen ground), and the
    # surface set the accent renders as text on.
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
    lowercase "#rrggbb". No <, no quote and no closing brace can appear in
    it, which is what makes emitting it inside <style> safe. The templates
    emit it WITHOUT |safe all the same — see page.html.
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
    )
    body = "".join(f"{name}:{value};" for name, value in declarations)
    return ":root{" + body + "}"
