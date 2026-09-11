"""Source-text fences over the stylesheets' half of USR-COP-2, LLM-COP-40
and LLM-COP-44.

app/palette.py writes eleven `:root` declarations into a `<style>` block on
V1 and twelve on V2 — nine scalar tokens on either skin, plus one ring per
ground a primary button is painted on (LLM-COP-44), of which V1 has two and
V2 three. That block is worth nothing unless two things are true of the
stylesheets, and neither is visible from Python's side of the change:

* every token it writes is DECLARED, with a default that is exactly the
  literal or the `var()` that supplied the value before this change — which
  is the whole of the "a site that chose no colour renders what it rendered
  before" claim, and
* every rule that owns a visible colour REFERENCES the token rather than the
  old value — because a token nothing references is a declaration that
  reaches nothing, and no rendered page reports it.

tests/test_palette.py already asserts that each token appears in `:root` and
that ROLE_TOKENS' two frozen literals are still the stylesheets' own. This
file asserts the two things that one cannot see: what the new tokens DEFAULT
to, and which RULES read them. `--header-bg` declared `var(--card)` while
`.site-header` still said `background: var(--card)` would pass every
assertion in test_palette.py and ship a header the owner cannot colour.

SINCE LLM-COP-40 A THIRD STYLESHEET IS READ. direct-edit.css declares none
of these tokens and never could — it is loaded only by /muokkaa/sivu, after
style.css, in the same document — but it READS one, at the editable
affordance and the focus ring, so the "every rule that owns a visible colour
references the token" half of the claim now reaches it.

The walkers are imported from tests/test_direct_edit_css.py rather than
copied. `_rules` and `_declarations` take any source; only `_css()` there is
bound to direct-edit.css. That file's own docstring states the walker's
limits — no nested CSS, no selector carrying a comma inside parentheses —
and none of the three stylesheets read here uses either.

WHAT THIS FILE CANNOT DO, said once: pytest paints nothing. Every assertion
below is about the bytes that ship, never about a resolved pixel. The pixels
are tests/browser/test_browser_colors.py's job, and the two halves are
deliberately different kinds of evidence: this one fails on a revert of the
retarget, that one fails on a colour that does not reach the screen.
"""

import re

import pytest

from tests.test_direct_edit_css import STATIC, _declarations, _rules

# --- the eighteen new tokens -----------------------------------------------
#
# (stylesheet, token, the declared default, the literal it resolves to).
#
# The third column is the SOURCE TEXT of the new declaration; the fourth is
# the colour that declaration produces once every var() in the chain is
# followed. Both are asserted, and they answer different questions: the third
# says the token was wired to the thing it replaced rather than to some other
# token of the same colour, the fourth says the value that reaches the page
# is byte-for-byte the pre-change one.
#
# The fourth column's literals are frozen from the pre-change file — the
# value each retargeted site rendered at 08062b3, read off `git show
# 08062b3:app/static/style.css`. They are not read back out of the same
# :root they are checking, which would assert nothing.
NEW_TOKENS = (
    # V1. --header-bg is the token this change ADDS rather than reuses:
    # the header's ground was var(--card), and var(--card) is eleven
    # surfaces on that page, so repainting --card would repaint all eleven.
    ("style.css", "--header-bg", "var(--card)", "#ffffff"),
    ("style.css", "--header-ink", "var(--ink)", "#22333b"),
    ("style.css", "--header-accent", "var(--accent)", "#1f6f5c"),
    # The two label inks replace a hardcoded `color: #fff`, so their default
    # is a literal and not a var() — there was no token to point at.
    ("style.css", "--accent-ink", "#ffffff", "#ffffff"),
    ("style.css", "--accent-dark-ink", "#ffffff", "#ffffff"),
    ("style.css", "--accent-fg", "var(--accent)", "#1f6f5c"),
    # V2 needs no --header-bg twin: --v2-header is referenced exactly once,
    # at .v2-header, so the main colour already had a token of its own.
    ("style-v2.css", "--v2-header-ink", "var(--v2-ink)", "#14293d"),
    ("style-v2.css", "--v2-header-accent", "var(--v2-rust)", "#a8431c"),
    ("style-v2.css", "--v2-rust-ink", "#ffffff", "#ffffff"),
    ("style-v2.css", "--v2-rust-dark-ink", "#ffffff", "#ffffff"),
    ("style-v2.css", "--v2-rust-fg", "var(--v2-rust)", "#a8431c"),
    # LLM-COP-40's two, and their fourth column has a DIFFERENT PROVENANCE
    # from the eleven above. Those eleven replaced a declaration that already
    # existed, so their frozen literal is the value that declaration carried.
    # There was no --accent-edge or --v2-rust-edge before this change at all;
    # what is frozen instead is the colour the RETARGETED SITES rendered at
    # 78d5d8e — `git show 78d5d8e:app/static/style.css` --accent #1f6f5c and
    # style-v2.css --v2-rust #a8431c, the raw values .button.secondary's
    # border, the two card rules, the ::after bar and the direct-edit
    # outlines all named directly before they were pointed at a token.
    ("style.css", "--accent-edge", "var(--accent)", "#1f6f5c"),
    ("style-v2.css", "--v2-rust-edge", "var(--v2-rust)", "#a8431c"),
    # LLM-COP-44's five rings, and their fourth column has a THIRD
    # provenance — or rather none. The eleven above replaced a declaration
    # that existed; the two edges froze the colour their retargeted sites
    # rendered at 78d5d8e. NOTHING rendered a ring before this change: there
    # was no box-shadow on any button in either stylesheet. So all five rows
    # below are :root PINS and not regression pins, and the third and fourth
    # columns are the same string by construction — the declared default IS
    # the literal, because there is no var() and no earlier value to resolve
    # back to. What they buy is still the thing this table exists for: the
    # declared default cannot drift without somebody being told, and
    # test_the_ring_defaults_are_what_the_derivation_would_write below is
    # what says those defaults are the RIGHT ones rather than merely stable.
    #
    # Four of the five are `transparent`, which is the derivation's identity
    # case reaching :root: both shipped accents already clear 3:1 on those
    # grounds, so a page that has chosen no colour paints no ring and renders
    # what it rendered before. --v2-rust-ring-navy is the ONE deliberate
    # exception in either stylesheet and the whole reason LLM-COP-44 exists:
    # the shipped rust is 2.1987:1 on the navy contact card at rest and
    # 1.6753:1 on hover, so #c05b34 is painted there by default.
    ("style.css", "--accent-ring", "transparent", "transparent"),
    ("style.css", "--accent-ring-header", "transparent", "transparent"),
    ("style-v2.css", "--v2-rust-ring", "transparent", "transparent"),
    ("style-v2.css", "--v2-rust-ring-navy", "#c05b34", "#c05b34"),
    ("style-v2.css", "--v2-rust-ring-header", "transparent", "transparent"),
)

# --- LLM-COP-44: the five rules that paint the ring ------------------------
#
# (stylesheet, selector, the box-shadow the rule must declare).
#
# NOT part of RETARGETED, because no rule was retargeted: these five
# declarations are new, on selectors two of which are new as well. The shape
# asserted is the whole value — `0 0 0 1px var(<token>)` — because all three
# of its parts carry the claim. `0 0 0` is no offset and no blur, so the ring
# is a crisp line rather than a shadow; `1px` is a spread, which is what puts
# the ring OUTSIDE the border box where its ground is the container and not
# the button's own fill; and the var() is what makes the colour the derived
# one instead of a literal somebody chose by eye.
#
# THE TWO OVERRIDES ARE MORE SPECIFIC THAN THE BASE, which is what lets the
# base rule serve every primary button that walks to a light surface while
# the header's and the navy card's take their own ground. `.v2-header
# .button.primary` and `.site-header .button.primary` are (0,3,0) against
# `.button.primary`'s (0,2,0), so they win whatever the source order — and
# test_each_ring_rule_names_its_token asserts the LAST value anyway, so a
# later re-declaration at equal specificity would be caught too.
RING_RULES = (
    ("style.css", ".button.primary", "0 0 0 1px var(--accent-ring)"),
    (
        "style.css",
        ".site-header .button.primary",
        "0 0 0 1px var(--accent-ring-header)",
    ),
    ("style-v2.css", ".button.primary", "0 0 0 1px var(--v2-rust-ring)"),
    (
        "style-v2.css",
        ".v2-contact-card .button.primary",
        "0 0 0 1px var(--v2-rust-ring-navy)",
    ),
    (
        "style-v2.css",
        ".v2-header .button.primary",
        "0 0 0 1px var(--v2-rust-ring-header)",
    ),
)

# --- the retargeted rules --------------------------------------------------
#
# (stylesheet, selector, property, the var() the rule must now name).
#
# Every row is a rule that owned a colour before this change and now owns a
# token instead. The selector is matched EXACTLY against a rule's own
# selector list, so `.nav-links a` and `.nav-links a:hover` are two rows and
# not one substring.
RETARGETED = (
    # V1 — the header. .brand sets no colour of its own, so the header ink
    # lives on .site-header and .brand inherits it; the other three header
    # elements each set their own and are named individually.
    ("style.css", ".site-header", "background", "var(--header-bg)"),
    ("style.css", ".site-header", "color", "var(--header-ink)"),
    ("style.css", ".nav-links a", "color", "var(--header-ink)"),
    ("style.css", ".menu-toggle", "color", "var(--header-ink)"),
    ("style.css", ".nav-links a:hover", "color", "var(--header-accent)"),
    # V1 — the accent as a button ground, with a derived label at rest and
    # another on hover.
    ("style.css", ".button.primary", "color", "var(--accent-ink)"),
    ("style.css", ".button.primary:hover", "color", "var(--accent-dark-ink)"),
    ("style.css", ".brand-avatar", "color", "var(--accent-ink)"),
    # V1 — the accent as TEXT, at all five sites.
    ("style.css", "a", "color", "var(--accent-fg)"),
    ("style.css", ".button.secondary", "color", "var(--accent-fg)"),
    ("style.css", ".section-kicker", "color", "var(--accent-fg)"),
    ("style.css", ".portrait-browse", "color", "var(--accent-fg)"),
    ("style.css", ".password-show", "color", "var(--accent-fg)"),
    # V2 — the header. .brand sets its OWN colour here, which is exactly why
    # naming the ink once on .v2-header would not reach it.
    ("style-v2.css", ".brand", "color", "var(--v2-header-ink)"),
    ("style-v2.css", ".nav-links a", "color", "var(--v2-header-ink)"),
    ("style-v2.css", ".menu-toggle", "color", "var(--v2-header-ink)"),
    (
        "style-v2.css",
        ".nav-links a:hover",
        "color",
        "var(--v2-header-accent)",
    ),
    # V2 — the rust as a button ground.
    ("style-v2.css", ".button.primary", "color", "var(--v2-rust-ink)"),
    (
        "style-v2.css",
        ".button.primary:hover",
        "color",
        "var(--v2-rust-dark-ink)",
    ),
    # V2 — the rust as TEXT.
    ("style-v2.css", "a", "color", "var(--v2-rust-fg)"),
    ("style-v2.css", ".button.secondary", "color", "var(--v2-rust-fg)"),
    ("style-v2.css", ".v2-hero-kicker", "color", "var(--v2-rust-fg)"),
    ("style-v2.css", ".v2-band-link", "color", "var(--v2-rust-fg)"),
    ("style-v2.css", ".password-show", "color", "var(--v2-rust-fg)"),
    # LLM-COP-40 — the accent as an EDGE. Six rules, three stylesheets, and
    # the selector of each is the NARROW one: `.button.secondary`, never the
    # bare `.button` those two rules sit beside. NOT_RETARGETED below is the
    # other half of that boundary.
    ("style.css", ".button.secondary", "border-color", "var(--accent-edge)"),
    ("style.css", ".fact-card", "border-top", "3px solid var(--accent-edge)"),
    (
        "style.css",
        ".service-card",
        "border-top",
        "3px solid var(--accent-edge)",
    ),
    (
        "style-v2.css",
        ".button.secondary",
        "border-color",
        "var(--v2-rust-edge)",
    ),
    (
        "style-v2.css",
        ".v2-band-media-left .v2-section-label::after",
        "background",
        "var(--v2-rust-edge)",
    ),
    # direct-edit.css, which style.css loads before in the same document —
    # so it reads --accent-edge and declares nothing. The idle affordance
    # and the focus ring are separate rows because they are separate rules
    # and only one of them is the STATE indicator SC 1.4.11 is really about.
    (
        "direct-edit.css",
        "body.direct-edit [data-field]",
        "outline",
        "1px dashed var(--accent-edge)",
    ),
    (
        "direct-edit.css",
        "body.direct-edit [data-field]:focus",
        "outline",
        "2px solid var(--accent-edge)",
    ),
)

# The border rules that KEEP the owner's raw colour, and must. Asserted as
# the WHOLE list of values the property takes, so a second declaration added
# later fails here rather than winning silently in the cascade.
#
# THIS IS A REGRESSION GUARD WITH A MEASURED PRICE ATTACHED. app/palette.py's
# own site list used to call style.css:95 and style-v2.css:131
# `.button.secondary`; they are the BARE `.button`, which the primary variant
# inherits too. Retargeting them would have put the edge token on every
# primary button's border. The v2 primary button's grounds are --v2-navy
# #14324a on the contact card and --v2-header #d9e8f2 in the header, neither
# of which is in V2_SURFACES; v1's sits on --paper, which IS in V1_SURFACES,
# so the ground argument is v2's alone and the reason that covers both skins
# is that the border equals its own fill. Measured: the navy card falls from
# 11.0249:1 to 3.7287:1 for a pale pick and 4.8397:1 to 3.7691:1 for a mid
# one, and the header reaches only 2.8386:1 — still short of the 3:1 the
# retarget was for.
NOT_RETARGETED = (
    ("style.css", ".button", "border", ["1px solid var(--accent)"]),
    ("style-v2.css", ".button", "border", ["1px solid var(--v2-rust)"]),
    (
        "style-v2.css",
        ".button.primary:hover",
        "border-color",
        ["var(--v2-rust-dark)"],
    ),
)

# The selectors whose ground the OWNER'S accent actually becomes, and which
# therefore may not carry a hardcoded label colour.
#
# SCOPED, and the scope is the point. `.button.primary` in both files takes
# `background: var(--accent)` / `var(--v2-rust)`, and V1's `.brand-avatar`
# takes `background: var(--accent)` — those three grounds move with the
# owner's pick, so a `color: #fff` on them is a label that can become white
# on pale yellow.
#
# V2's `.brand-avatar` (style-v2.css:124) and `.v2-contact-kicker` (:456)
# still read `color: #fff` and are RIGHT to: their grounds are --v2-navy and
# the navy contact card, neither of which is an owner role, and neither
# moves when a colour is chosen. A fence that failed on them would be a
# fence that fails on correct code, which is worse than no fence at all.
OWNER_GROUNDED = (
    ("style.css", ".button.primary"),
    ("style.css", ".button.primary:hover"),
    ("style.css", ".brand-avatar"),
    ("style-v2.css", ".button.primary"),
    ("style-v2.css", ".button.primary:hover"),
)

_LITERAL_WHITE = re.compile(r"^(#fff|#ffffff|white)$", re.IGNORECASE)

_VAR = re.compile(r"^var\((--[a-z0-9-]+)\)$")


def _source(filename):
    return (STATIC / filename).read_text(encoding="utf-8")


def _root(filename):
    """The `:root` block of a stylesheet as {property: value}."""
    for at_rules, selectors, body in _rules(_source(filename)):
        if not at_rules and selectors == [":root"]:
            return dict(_declarations(body))
    raise AssertionError(f"no :root rule in {filename}")


def _resolve(root, value):
    """Follow a var() chain through `:root` down to the literal it yields."""
    seen = set()
    while True:
        match = _VAR.match(value)
        if match is None:
            return value
        token = match.group(1)
        assert token not in seen, f"var() cycle at {token}"
        seen.add(token)
        assert token in root, f"{token} is declared by no :root"
        value = root[token]


def _values_for(filename, selector, prop):
    """Every value `prop` takes in top-level rules whose selector list
    contains `selector` exactly, in source order."""
    found = []
    for at_rules, selectors, body in _rules(_source(filename)):
        if at_rules or selector not in selectors:
            continue
        found.extend(
            value for name, value in _declarations(body) if name == prop
        )
    return found


# --- the eighteen new tokens -----------------------------------------------


@pytest.mark.parametrize(
    "filename,token,declared,literal",
    NEW_TOKENS,
    ids=[f"{f.split('.')[0]}{t}" for f, t, _, _ in NEW_TOKENS],
)
def test_each_new_token_defaults_to_what_it_replaced(
    filename, token, declared, literal
):
    """The "renders exactly as before" claim, made checkable.

    Both halves are asserted because they fail differently. The DECLARED
    text going wrong is a wiring mistake — `--header-ink: var(--muted)` is
    the right shape and the wrong token, and a reader skimming for `var(--`
    would not catch it. The RESOLVED literal going wrong is a recolour: the
    day somebody changes --accent from #1f6f5c, this row goes red and the
    person who changed it is told that a frozen literal in app/palette.py
    and a browser assertion both depend on the old value.

    The literals in the fourth column come from the pre-change file at
    08062b3, not from the :root being checked — reading them back out of the
    same block would make this test true by construction.
    """
    root = _root(filename)
    assert root.get(token) == declared, (
        f"{filename} :root declares {token} as {root.get(token)!r}, not "
        f"{declared!r} — the value this token replaced"
    )
    assert _resolve(root, declared) == literal


def test_the_eighteen_tokens_are_all_of_them():
    """A count, so a nineteenth token added without a row here is noticed.

    Cheap and worth it: the failure this file exists to catch is a token
    nobody wired up, and a token nobody listed is the same mistake one step
    earlier. The two numbers are 9 and 9 — USR-COP-2's 6 and 5, where V1
    needed the --header-bg split and V2 did not, plus one edge token each
    from LLM-COP-40, plus LLM-COP-44's rings: TWO on V1 and THREE on V2,
    one per ground a primary button is painted on. The two files land on the
    same number by arithmetic and not by symmetry — V1 is 7 + 2 and V2 is
    6 + 3 — so they are written as two assertions rather than one.
    """
    per_file = {}
    for filename, token, _, _ in NEW_TOKENS:
        per_file.setdefault(filename, []).append(token)
    assert len(per_file["style.css"]) == 9
    assert len(per_file["style-v2.css"]) == 9
    for filename, tokens in per_file.items():
        declared = _root(filename)
        assert len(set(tokens)) == len(tokens)
        for token in tokens:
            assert token in declared


# --- the rules that read them ----------------------------------------------


@pytest.mark.parametrize(
    "filename,selector,prop,expected",
    RETARGETED,
    ids=[f"{f.split('.')[0]}-{s}-{p}" for f, s, p, _ in RETARGETED],
)
def test_each_retargeted_rule_names_its_token(
    filename, selector, prop, expected
):
    """The assertion that fails on a revert, and the one test_palette.py
    cannot make.

    The LAST value wins, not "some rule somewhere says this": CSS of equal
    specificity is decided by source order, so a later rule re-declaring the
    property with the old literal would leave the token unread while a
    membership test still passed.
    """
    values = _values_for(filename, selector, prop)
    assert values, f"{filename} has no top-level rule `{selector}`"
    assert values[-1] == expected, (
        f"{filename} `{selector}` resolves {prop} to {values[-1]!r}, so the "
        f"owner's colour never reaches it through {expected}"
    )


@pytest.mark.parametrize("skin", ("v1", "v2"))
def test_every_token_the_override_writes_is_read_by_some_rule(skin):
    """A token declared and referenced nowhere is a declaration that reaches
    nothing — the silent failure this design is shaped around, and one that
    neither a rendered page nor tests/test_palette.py would report (that
    file asserts each token is DECLARED, which a dead token also is).

    Read out of ROLE_TOKENS rather than restated, so the table app/palette.py
    actually writes from is the thing being checked.
    """
    from app.palette import ROLE_TOKENS

    filename = "style.css" if skin == "v1" else "style-v2.css"
    source = _source(filename)
    # Comments stripped first: both :root blocks carry prose that names
    # every one of these tokens, so a plain substring search over the raw
    # file would pass on a stylesheet where no RULE reads any of them.
    body = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    root_start = body.index(":root")
    rules_only = body[body.index("}", root_start) + 1:]
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
        token = ROLE_TOKENS[skin][role]
        assert f"var({token})" in rules_only, (skin, role, token)
    # The rings row has its own loop because it has its own shape: a list of
    # (token, grounds) pairs rather than a scalar name (LLM-COP-44). A ring
    # token nobody reads is the same dead declaration as any other, and it
    # would be a worse one — the ring is the only boundary a primary button
    # has on a ground its fill cannot clear.
    for token, _ in ROLE_TOKENS[skin]["rings"]:
        assert f"var({token})" in rules_only, (skin, token)


# --- LLM-COP-44: the rules that paint the ring, and the value they paint ----


@pytest.mark.parametrize(
    "filename,selector,expected",
    RING_RULES,
    ids=[f"{f.split('.')[0]}-{s}" for f, s, _ in RING_RULES],
)
def test_each_ring_rule_names_its_token(filename, selector, expected):
    """The five declarations that turn a derived colour into a boundary.

    THE LAST VALUE WINS, exactly as in test_each_retargeted_rule_names_its_
    token: CSS of equal specificity is decided by source order, so a later
    `.button.primary` re-declaring box-shadow would leave the token unread
    while a membership test still passed.

    THE WHOLE VALUE IS ASSERTED, not just the var(). `0 0 0 1px` is the
    claim's geometry and each part of it is load-bearing — no offset and no
    blur, so the edge is crisp rather than a shadow, and a 1px SPREAD, which
    is what puts the ring outside the border box where its ground is the
    container. A rule that kept the token but wrote `0 0 4px var(--...)`
    would paint a soft halo whose colour is measured against a ground it is
    not actually sitting on, and every ratio test in the suite would still
    be green.

    THE PROPERTY IS NOT re-declared BY EITHER :hover RULE, which is why the
    ring survives into the state the fill is worst in. That is asserted below
    rather than here, because it is a claim about a rule that must NOT exist.
    """
    values = _values_for(filename, selector, "box-shadow")
    assert values, f"{filename} has no top-level rule `{selector}`"
    assert values[-1] == expected, (
        f"{filename} `{selector}` resolves box-shadow to {values[-1]!r}, so "
        f"the derived ring never reaches it through {expected}"
    )


def test_no_hover_rule_re_declares_the_ring():
    """THE RING SURVIVES :hover, and this is the assertion that says so from
    the source text.

    The hover fill is the WORSE of the two — the shipped rust is 2.1987:1 on
    the navy card and its hand-picked hover #8b3715 is 1.6753:1 — so a ring
    that vanished under the pointer would vanish exactly where the boundary
    is doing all the work. Both hover rules re-declare `background`, and V2's
    re-declares `border-color` as well, so a box-shadow among them is a
    plausible edit and not a fanciful one.

    Asserted as the EMPTY list, the same idiom
    test_the_button_borders_that_must_stay_the_owners_own_still_do uses: the
    claim is that no such declaration exists at all, and a declaration added
    later is the shape of the change this catches.
    """
    for filename in ("style.css", "style-v2.css"):
        assert _values_for(filename, ".button.primary:hover", "box-shadow") == [], (
            f"{filename} `.button.primary:hover` declares box-shadow, so the "
            "derived ring is replaced in the state the fill is worst in"
        )


# The hand-picked hover literal each stylesheet ships, and the token it lives
# in. shade()'s own docstring in app/palette.py says in terms that it does
# NOT reproduce these — they are a designer's colours, chosen before the
# derivation existed — so a ring default that agreed with shade() and
# disagreed with these would be right about a page nobody serves.
HOVER_LITERALS = (
    ("v1", "style.css", "--accent-dark", "#17594a"),
    ("v2", "style-v2.css", "--v2-rust-dark", "#8b3715"),
)


@pytest.mark.parametrize(
    "skin,filename,hover_token,hover_literal",
    HOVER_LITERALS,
    ids=("v1", "v2"),
)
def test_the_ring_defaults_are_what_the_derivation_would_write(
    skin, filename, hover_token, hover_literal
):
    """THE TWO SIDES AGREE, at the one rendering no derivation can influence.

    A site that has chosen nothing serves NO <style> block at all — not an
    empty one, none — so each ring's `:root` default IS the whole of its
    rendering on the shipped page. That makes the defaults a second,
    hand-written copy of what ring_on would derive for the skin's own
    default accent, and a second copy of anything is a copy that goes stale.
    This is the test that fails when either side moves without the other.

    COMPUTED TWICE, WITH TWO DIFFERENT HOVER FILLS, and that is the point of
    the parametrisation rather than decoration. ring_on takes (accent,
    hover), and on a live request the hover fill is shade(accent). On the
    SHIPPED page it is neither — it is the literal the stylesheet's own
    :root carries, #17594a and #8b3715, which shade()'s own docstring
    records as deliberately not reproduced by it. They are different
    colours: shade("#1f6f5c") is #19594a, not #17594a. So the default has to
    be right for both, and it is: #8b3715 is 1.6753 on navy (still under 3,
    still painted, still #c05b34), 6.3181 on the v2 header and 6.7512 worst on
    V2_SURFACES (still transparent); #17594a is 7.6635 worst on V1_SURFACES
    and 8.1895 on the default header ground (still transparent).

    WHAT IT WOULD CATCH. Recolour --v2-rust-dark to something that clears
    the navy card and the shipped page would keep painting a ring for no
    reason — this goes red and names the token. Recolour --v2-navy, or
    --v2-rust itself, and #c05b34 stops being a 3:1 answer to anything; this
    goes red too. Neither would move a single ratio assertion anywhere else
    in the suite, because a page that has chosen no colour has no derived
    value to measure.
    """
    from app.palette import MAIN, ROLE_TOKENS, ring_on, shade

    root = _root(filename)
    tokens = ROLE_TOKENS[skin]
    accent, main = tokens["default_accent"], tokens["default_main"]
    assert _resolve(root, root[hover_token]) == hover_literal, (
        f"{filename} :root declares {hover_token} as "
        f"{root.get(hover_token)!r}; the ring defaults below were derived "
        f"against {hover_literal}"
    )
    assert shade(accent) != hover_literal, (
        "the two hover fills have become the same colour, so this test now "
        "computes the same thing twice and proves half of what it says"
    )
    for hover in (shade(accent), hover_literal):
        for token, grounds in tokens["rings"]:
            bound = tuple(main if g == MAIN else g for g in grounds)
            expected = ring_on((accent, hover), bound)
            declared = _resolve(root, root[token])
            assert declared == expected, (
                f"{filename} :root declares {token} as {declared!r}, but "
                f"ring_on(({accent}, {hover}), {bound}) is {expected!r} — "
                "the shipped page and the derivation disagree, and the "
                "shipped page is the one a visitor who chose nothing sees"
            )


# --- the fence -------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,selector",
    OWNER_GROUNDED,
    ids=[f"{f.split('.')[0]}-{s}" for f, s in OWNER_GROUNDED],
)
def test_no_owner_grounded_rule_hardcodes_a_white_label(filename, selector):
    """Fails on a revert, and fails again the day somebody re-hardcodes it.

    Every selector here paints its ground from the owner's accent, so a
    literal label colour on one of them is white text on whatever the owner
    picked — which for a pale pick is the exact defect this change exists to
    remove (`.button.primary` shipped `color: #fff` before it).

    DELIBERATELY NOT FENCED: V2's `.brand-avatar` and `.v2-contact-kicker`
    keep `color: #fff` and are correct. Their grounds are --v2-navy and the
    navy contact card — colours no owner role touches — so their labels
    cannot go pale, and a fence that failed on them would fail on correct
    code. The boundary of this fence is the boundary of the claim.
    """
    for value in _values_for(filename, selector, "color"):
        assert not _LITERAL_WHITE.match(value), (
            f"{filename} `{selector}` still declares color: {value} over a "
            "ground the owner can repaint"
        )


def test_the_two_untouched_white_labels_are_still_there():
    """The other half of the fence above, and it is here so the exclusion is
    a recorded decision rather than an omission.

    If a later change moves either of these onto an owner-coloured ground,
    this test still passes — it is a note, not a guard, and says so. What it
    does buy is that the exclusion cannot be quietly deleted and then cited
    as "the fence covers everything": deleting the rules fails this, and
    re-scoping the fence to cover them fails that.
    """
    assert _values_for("style-v2.css", ".brand-avatar", "color") == ["#fff"]
    assert _values_for("style-v2.css", ".brand-avatar", "background") == [
        "var(--v2-navy)"
    ]
    assert _values_for("style-v2.css", ".v2-contact-kicker", "color") == [
        "#fff"
    ]


# --- LLM-COP-40's boundary: the edges that must NOT move -------------------


@pytest.mark.parametrize(
    "filename,selector,prop,expected",
    NOT_RETARGETED,
    ids=[f"{f.split('.')[0]}-{s}-{p}" for f, s, p, _ in NOT_RETARGETED],
)
def test_the_button_borders_that_must_stay_the_owners_own_still_do(
    filename, selector, prop, expected
):
    """THE REGRESSION GUARD FOR THE MISTAKE THIS CHANGE NEARLY MADE.

    app/palette.py's enumeration of the unconstrained non-text sites named
    style.css:95 and style-v2.css:131 as `.button.secondary`. They are the
    BARE `.button` rule, which the primary variant inherits. A retarget aimed
    at the site list as written would therefore have repainted every primary
    button's border with the edge token — and the edge token is derived
    against --paper/--card and --v2-page/--v2-card/--v2-tint, of which
    neither of the v2 primary button's grounds is among them.

    THE GROUND ARGUMENT IS V2'S ALONE, said precisely because the loose form
    is false: V1's hero primary button sits on --paper #faf7f2, which IS in
    V1_SURFACES. What excludes all three rules in both skins is the other
    reason, and it holds everywhere — the border is byte-identical to the
    fill, so it is no boundary, and contrast(x, x) is 1.0 for every colour
    there is.

    The measured cost of getting that wrong, which is why this test carries
    numbers rather than an opinion: on --v2-navy #14324a the contact card's
    button border falls from 11.0249:1 to 3.7287:1 for #ffe9a8 and from
    4.8397:1 to 3.7691:1 for #66aa88 — a real degradation — and on
    --v2-header #d9e8f2 the widened token reaches only 2.8386:1, so the
    retarget would not even have bought the 3:1 it was for.

    Asserted as the FULL list rather than `values[-1]`, unlike the retarget
    rows above: here the claim is that no rule declares the property at all
    beyond the one that always did, and a second declaration appended later
    is exactly the shape of the change this is meant to catch.
    """
    assert _values_for(filename, selector, prop) == expected, (
        f"{filename} `{selector}` no longer declares {prop} as {expected} — "
        "if this was a deliberate widening of LLM-COP-40's retarget, these "
        "borders are byte-identical to their own fill in both skins, and on "
        "v2 they sit on grounds the surface tuple does not name"
    )


def test_the_hover_border_is_excluded_because_it_equals_its_own_fill():
    """A NOTE, NOT A GUARD, and it says so — the same idiom as
    test_the_two_untouched_white_labels_are_still_there above.

    `.button.primary:hover` sets `border-color` and `background` to the same
    token, so the border is not a boundary anyone perceives and
    contrast(x, x) is 1.0 for every colour there is. An assertion that could
    never pass is proof the site was misidentified, not proof of a defect —
    which is why this rule is outside SC 1.4.11's scope and outside the
    retarget.

    If a later change gives that rule a border colour different from its
    fill, this test still passes; it is not watching for that. What it does
    buy is that the exclusion cannot be quietly deleted and then cited as
    coverage: removing the rule fails this, and folding it into RETARGETED
    fails test_the_button_borders_that_must_stay_the_owners_own_still_do.
    """
    fill = _values_for("style-v2.css", ".button.primary:hover", "background")
    edge = _values_for("style-v2.css", ".button.primary:hover", "border-color")
    assert fill == edge == ["var(--v2-rust-dark)"]
