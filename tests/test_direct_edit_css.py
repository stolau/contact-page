"""Source-text fences over app/static/direct-edit.css (LLM-COP-11).

Two occlusions were measured in real Chrome 142 and fixed by one declaration
each; two of the four assertions here fence those fixes, and the other two
fence decisions that are *already* correct and that a future reader is
actively invited to get wrong. Each test says in its own docstring which kind
it is, because "all four go red on revert" would be false and a fence nobody
trusts is worse than no fence:

* R1 and R2 are REGRESSION fences. Neither declaration exists in the file
  before this unit, so both fail on revert.
* F1 and F2 are FORWARD fences. Both pass on the pre-change file. Their value
  is entirely in the edit they stop next — F1 especially, see its docstring.

Source-text assertions are precedented at tests/test_wizard.py:632-659 and
carry that precedent's limitation: pytest drives a test client that executes
no CSS and paints nothing, so this file proves the declarations SHIP, never
that they RESOLVE. The geometry they were derived from — clipped pixels, hit
targets, the footer's 83px under the publish bar — was measured in a browser
during the run-for-real phase and is recorded in the CSS comments and the PR
body, which is the only place that evidence can live.

_rules() below is a structural brace walker, NOT a CSS parser. It knows about
comments, brace depth, at-rules and comma groups, and nothing else. It would
need extending for nested CSS, @supports, or a selector carrying a comma
inside parentheses (`:not(a, b)`) — none of which this file uses today.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

MEDIA_PHONE = "@media (max-width: 720px)"


def _rules(source):
    """Every style rule in `source` as (at_rules, selectors, declarations_text).

    A structural walk, and the four rules it implements are each here because
    the naive version produces a FALSE FAILURE on this particular file:

    1. Comments are stripped first. The file opens with a nine-line contract
       comment and carries several more, and their prose contains both braces
       and the word `body.direct-edit`.
    2. A prelude is the text since the last `{`, `}` or `;` — so declarations
       inside a block are discarded rather than mistaken for selectors.
    3. A prelude starting with `@` is an at-rule: it is NOT a selector, but
       its body is descended into, because the rules nested inside it are.
       `@media (max-width: 720px)` holds three of them.
    4. Preludes are whitespace-collapsed and split on `,`. Comma groups in
       this file span lines, so a line-oriented reader would see half a
       selector.

    `at_rules` is the tuple of enclosing at-rule preludes, which is what lets
    R1 assert that a declaration sits INSIDE the phone breakpoint rather than
    merely somewhere in the file.
    """
    src = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    found = []
    stack = []
    buf = ""
    for index, char in enumerate(src):
        if char == "{":
            prelude = " ".join(buf.split())
            buf = ""
            kind = "at" if prelude.startswith("@") else "rule"
            stack.append((kind, prelude, index + 1))
        elif char == "}":
            buf = ""
            if stack:
                kind, prelude, start = stack.pop()
                if kind == "rule":
                    found.append(
                        (
                            tuple(p for k, p, _ in stack if k == "at"),
                            [s.strip() for s in prelude.split(",") if s.strip()],
                            src[start:index],
                        )
                    )
        elif char == ";":
            buf = ""
        else:
            buf += char
    return found


def _declarations(body):
    """(property, value) for a rule body, lowercased and space-collapsed."""
    pairs = []
    for chunk in body.split(";"):
        prop, sep, value = chunk.partition(":")
        if sep:
            pairs.append((prop.strip().lower(), " ".join(value.split())))
    return pairs


def _css():
    return _rules((STATIC / "direct-edit.css").read_text(encoding="utf-8"))


# --- R1, R2: regression fences — these fail on the pre-change file ----------


def test_the_phone_breakpoint_reserves_the_publish_bars_dirty_height():
    """REGRESSION fence: fails on revert, the declaration is absent today.

    The 4.4rem reserved on body.direct-edit was set against the publish bar's
    IDLE height, and the bar has two of them. direct_edit_chrome.html:53-55
    ships .direct-changes, .direct-autosave and .direct-errors hidden;
    direct-edit.js:110-115 unhides them on the first change, and below 720 the
    bar wraps and grows. Measured dirty in Chrome 142 at 375 wide, scrolled to
    the very end of the document: 83px of the site footer sits under the bar
    with no scroll position that frees it. That is content-LOSS with no user
    workaround, which is why it was worth a literal.

    Asserted inside the media block deliberately: above 720 the bar is
    structurally one row at 54px and the 4.4rem already over-reserves, so a
    padding-bottom that leaked out of the breakpoint would be a different
    (and wrong) change that a file-wide substring search would call green.

    Maintenance note, since the number is not a constant of nature: 175 is the
    worst case across 320-720 with this owner name and no error text, and the
    CSS comment says so. A re-measure that legitimately moves it should move
    this fence with it, as a deliberate edit rather than a surprise.
    """
    declared = [
        value
        for at_rules, selectors, body in _css()
        if MEDIA_PHONE in at_rules and "body.direct-edit" in selectors
        for prop, value in _declarations(body)
        if prop == "padding-bottom"
    ]
    assert declared == ["175px"], declared


def test_the_sticky_public_header_is_pinned_below_the_fixed_top_bar():
    """REGRESSION fence: fails on revert, the rule is absent today.

    .site-header is `position: sticky; top: 0` (style.css:43-52) and
    `grep -n z-index app/static/style.css` returns nothing, so it loses
    unconditionally to .direct-topbar's z-index: 30. Measured at 1280 wide:
    once scrolled, 65 of its 76px are clipped and the header stops hit-testing
    to itself — the centre of .header-contact resolves to BUTTON.direct-poistu.
    That header link is deliberately live in edit mode
    (direct-edit.js:340-341), so the misclick is destructive: an owner aiming
    at "Ota yhteyttä" is thrown out of edit mode instead.

    Only the header's own `top` can reach this. `top` is a viewport offset and
    body padding does not move a sticky one, which is the reason this fence
    and F1 are not the same fence wearing two hats.
    """
    declared = [
        value
        for _at_rules, selectors, body in _css()
        if "body.direct-edit .site-header" in selectors
        for prop, value in _declarations(body)
        if prop == "top"
    ]
    assert declared == ["65px"], declared


# --- F1, F2: forward fences — these already pass on the pre-change file -----


def test_direct_edit_mode_never_raises_the_bodys_top_padding():
    """FORWARD fence: passes on the pre-change file. The most important test
    in this file anyway, because it fences a measured regression that the
    project's own brief instructs the next implementer to commit.

    LLM-COP-11 prescribes, in as many words, giving the editable canvas top
    padding equal to the fixed bar's height. That is wrong twice over. It
    cannot work in principle — .direct-publishbar is `fixed; bottom: 0`, and
    top padding cannot move a viewport-fixed bottom bar, it only slides the
    document underneath it. And it actively breaks working cases: raising
    padding-top from 54.4 to 65 shifts .cta-contact's centre from 844 to 854,
    which moves the occlusion band ONTO viewport heights 900 and 905 where the
    hero CTA is clickable today. Measured, not reasoned.

    So the two padding edges are not symmetric, and that asymmetry is the
    whole lesson of this unit: R1 moves the BOTTOM edge, which extends where
    the document ends without moving anything above it (.cta-contact's
    document offset is 877 before and 877 after), while the TOP edge moves
    every element on the page down and into the bar.

    A future implementer reading the artifact will be told to make exactly
    this mistake. This is the cheapest thing that stops them, and the failure
    message should send them here rather than to the artifact.

    Scoped to rules whose selector is `body.direct-edit` itself: a descendant
    rule like `body.direct-edit .site-header` styles the header, not the body.
    The shorthand is checked as well as the longhand because `padding:` rewrites
    the top edge silently, and the presence assertion is not decoration — it
    stops this test passing vacuously if the declaration is deleted outright.
    """
    tops = []
    for _at_rules, selectors, body in _css():
        if "body.direct-edit" not in selectors:
            continue
        for prop, value in _declarations(body):
            if prop == "padding":
                tops.append(value.split()[0])
            elif prop == "padding-top":
                tops.append(value)
    assert tops, "no rule sets body.direct-edit's top padding at all"
    assert set(tops) == {"3.4rem"}, tops


def test_every_selector_stays_inside_direct_edit_mode():
    """FORWARD fence: passes on the pre-change file, and on every file before
    it — which is precisely what makes it worth writing now.

    This stylesheet opens (direct-edit.css:1-9) by promising it cannot reach
    the public page or the draft preview: everything hangs off body.direct-edit
    or a .direct- class, and nothing here applies without them. R2's rule is
    the first in the file's history to name a public-page selector at all
    (.site-header), and it keeps the promise only because it is still prefixed
    with body.direct-edit, which nothing outside /muokkaa/sivu carries.

    Having opened that door once, the fence keeps the next rule through it
    scoped the same way. A bare `.site-header { top: 65px; }` would look
    almost identical in a diff, pass both regression fences above, and restyle
    the live public page for every visitor.

    Deliberately asserts containment and NOT a selector count. The count moves
    with this PR and with every honest edit after it; a fence that goes red on
    a legitimately added rule teaches people to delete the fence.
    """
    offenders = [
        selector
        for _at_rules, selectors, _body in _css()
        for selector in selectors
        if not (
            selector == ":root"
            or selector.startswith(("body.direct-edit", ".direct-"))
        )
    ]
    assert offenders == [], offenders
