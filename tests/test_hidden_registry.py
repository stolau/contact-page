"""The registry of `.hidden` assignment sites cannot fall behind the code
(LLM-COP-48).

tests/browser/hidden_registry.py lists every place this product assigns to an
element's `.hidden` property, and tests/browser/test_browser_hidden.py drives
a real Chrome over it to prove each of those elements actually disappears.
That guard is worth exactly as much as the table is current. A table is a
snapshot; this test is what turns it into a fence.

So: re-derive the set of (file, left-hand side) pairs straight from
app/static/*.js and app/templates/*.html with a regex, and require it to equal
the registry's. A new `foo.hidden = true` anywhere in the product fails here,
by name, with the file it is in — and whoever adds it has to say which screen
the element is on and what selector finds it, which is what puts it under the
browser sweep.

NO BROWSER, no app import, no fixtures: stdlib and the registry module. It
lives in tests/ rather than tests/browser/ for that reason — it is a fact
about source text, it runs in the fast `-m "not browser"` loop, and a source
fence that only ran with Chrome available would be the wrong shape.

WHAT THE REGEX MATCHES, and why each piece is there.

    ([A-Za-z_$][\\w$]*(?:\\.[A-Za-z_$][\\w$]*|\\([^()]*\\))*)\\.hidden\\s*=(?!=)

The capture is the whole left-hand side, not just the last name, because two
different files legitimately use the same variable name for different elements
— edit.js's `error` is `.kuva-error` and contact_dialog.html's `error` is
`.contact-error` — and because the product writes through one call expression,
`row.querySelector(".expanded-editor").hidden = false`. The alternation is
what lets a member chain and a no-nesting call chain both ride along.

THE `(?!=)` LOOKAHEAD is a guard against comparisons: without it,
`el.hidden === true` matches, because `\\s*=` happily takes the first `=` of
`===`, and the registry would grow an entry for a line that assigns nothing.
Measured on this tree, honestly: dropping the lookahead changes NOTHING today
— the derived set is identical with and without it, because no `.hidden ==` or
`.hidden ===` comparison currently exists in app/static or app/templates. (The
two lines sometimes cited for it, edit.js's `section.state === "hidden"` and
sectionlist.js's `setState(id, "hidden")`, are string literals with no `.hidden`
member access in them and never matched either way.) It stays because the
shape it guards is one line of ordinary JavaScript away, and a false entry
would send the next reader hunting for an element nobody hides.

WHAT IT DOES NOT SEE, said rather than implied. `setAttribute("hidden", "")`,
`toggleAttribute("hidden")`, a `hidden` written into a template's markup by
a loop, and any element hidden through a class instead of the attribute are
all outside this regex. Each of those is a real way to hide something and
none of them is covered here; the browser sweep's at-rest probe catches the
markup case, and the rest are a gap this file states rather than papers over.
"""

import re
from pathlib import Path

from tests.browser.hidden_registry import KEYS, SITES

ROOT = Path(__file__).resolve().parent.parent

# The two source directories the product's client-side code lives in. The
# templates are here because two dialogs carry their script inline, on
# purpose: contact_dialog.html must name POST /api/messages exactly once in
# the served document, so its sender cannot move to app/static/.
SOURCES = (("app/static", "*.js"), ("app/templates", "*.html"))

ASSIGNMENT = re.compile(
    r"([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*|\([^()]*\))*)\.hidden\s*=(?!=)"
)


def derived_keys():
    """Every (file name, left-hand side) pair the sources actually contain."""
    found = set()
    for directory, pattern in SOURCES:
        for path in sorted((ROOT / directory).glob(pattern)):
            text = path.read_text(encoding="utf-8")
            for match in ASSIGNMENT.finditer(text):
                found.add((path.name, match.group(1)))
    return found


def test_the_registry_lists_every_hidden_assignment_in_the_product():
    """The table and the source agree, in both directions.

    Both directions matter and they fail for opposite reasons. An extra site
    in the source is a new element nobody has said how to find, so the browser
    sweep has silently stopped being complete. An extra entry in the table is
    a selector that no longer has an assignment behind it — dead weight the
    sweep still probes, which will go red for the wrong reason the day the
    element is deleted from the template too.
    """
    derived = derived_keys()

    # The non-emptiness guard this project asks for everywhere it sweeps: a
    # regex that has stopped matching would otherwise make both sets empty on
    # the day someone reorganises app/static/, and an empty == empty
    # comparison is the greenest possible way to prove nothing.
    assert derived, (
        "the regex found no `.hidden =` assignment anywhere in app/static or "
        "app/templates. There were 49 of them across 32 distinct sites when "
        "this was written, so this is a broken sweep, not a tidy codebase"
    )

    missing = sorted(derived - KEYS)
    stale = sorted(KEYS - derived)
    assert (missing, stale) == ([], []), (
        f"tests/browser/hidden_registry.py has drifted from the product.\n"
        f"  in the source but NOT in the registry: {missing}\n"
        f"    -> add a Site() for each: the screen(s) it renders on and the "
        f"selector that finds it, so tests/browser/test_browser_hidden.py "
        f"proves the element actually disappears.\n"
        f"  in the registry but NOT in the source: {stale}\n"
        f"    -> the assignment is gone; drop the Site()."
    )

    # An entry that names no screen contributes no probe anywhere while still
    # looking like coverage in the table, so the only one allowed to do it is
    # the one marked unreachable — and that one has to say why in its own
    # note, because an omission a reader cannot check is a silent skip.
    silent = [site for site in SITES if site.reachable and not site.screens]
    assert silent == [], (
        f"these registry entries name no screen, so nothing probes them: "
        f"{silent}"
    )
    unexplained = [site for site in SITES if not site.reachable and not site.note]
    assert unexplained == [], (
        f"these entries are marked unreachable without saying why: "
        f"{unexplained}"
    )
