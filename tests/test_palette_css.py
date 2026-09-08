"""Source-text fences over the two stylesheets' half of USR-COP-2.

app/palette.py writes eight `:root` declarations into a `<style>` block. That
block is worth nothing unless two things are true of the stylesheets, and
neither is visible from Python's side of the change:

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

The walkers are imported from tests/test_direct_edit_css.py rather than
copied. `_rules` and `_declarations` take any source; only `_css()` there is
bound to direct-edit.css. That file's own docstring states the walker's
limits — no nested CSS, no selector carrying a comma inside parentheses —
and neither stylesheet read here uses either.

WHAT THIS FILE CANNOT DO, said once: pytest paints nothing. Every assertion
below is about the bytes that ship, never about a resolved pixel. The pixels
are tests/browser/test_browser_colors.py's job, and the two halves are
deliberately different kinds of evidence: this one fails on a revert of the
retarget, that one fails on a colour that does not reach the screen.
"""

import re

import pytest

from tests.test_direct_edit_css import STATIC, _declarations, _rules

# --- the eleven new tokens -------------------------------------------------
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


# --- the eleven new tokens -------------------------------------------------


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


def test_the_eleven_tokens_are_all_of_them():
    """A count, so a twelfth token added without a row here is noticed.

    Cheap and worth it: the failure this file exists to catch is a token
    nobody wired up, and a token nobody listed is the same mistake one step
    earlier. The two numbers are 6 and 5 because V1 needed the --header-bg
    split and V2 did not.
    """
    per_file = {}
    for filename, token, _, _ in NEW_TOKENS:
        per_file.setdefault(filename, []).append(token)
    assert len(per_file["style.css"]) == 6
    assert len(per_file["style-v2.css"]) == 5
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
    ):
        token = ROLE_TOKENS[skin][role]
        assert f"var({token})" in rules_only, (skin, role, token)


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
