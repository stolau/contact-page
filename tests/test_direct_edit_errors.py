"""The direct-edit error note (LLM-COP-17) — the code half of the artifact.

`.direct-errors` is the note in direct-edit mode's publish bar that tells the
owner a save or a publish failed. Two merged artifacts (LLM-COP-6, LLM-COP-12)
rest their central promise on it, and until this file nothing in the suite
observed it at all: deleting the span from the template left all 539 tests
green while breaking every save in the browser. `query()` is a bare
`document.querySelector` (app/static/direct-edit.js:41-43), `errorNote` binds
at :55, and `showMessages` dereferences it unguarded at :397-398 — so a
missing element is a TypeError on the first save, not a degraded note.

The fix is not a null guard. `if (!errorNote) return;` would trade a loud
crash for a silent loss, which is precisely the failure this artifact exists
to make observable. The fix is that something watches, and this file is it.

Nothing here plants a fixture to make a test pass: the markup assertions read
the one document the real route really serves, and the source-text assertions
read app/static/direct-edit.js off disk.
"""

import re
from pathlib import Path

import pytest

from app.seed import SEED_SECTIONS
from tests.conftest import ADMIN_PASSWORD, create_admin, element_text, login

SEED_BY_KIND = dict(SEED_SECTIONS)
DIRECT_URL = "/muokkaa/sivu"

# The spec address these tests speak for, named in every failure message so a
# red run points at the contract rather than at a class token.
#
# NOTE FOR THE NEXT READER: this region DOES NOT EXIST on the SpecWeaver
# server yet. The artifact's whole finding is that `.direct-errors` has no
# spec region and no test; the spec half is being written separately. If you
# GET cp-main-direct-edit and cannot find this address, the test is not stale
# — you have found the other half of the same gap.
#
# Each test spells the address out in its docstring rather than referring to
# this constant. That is deliberate: a docstring cannot interpolate, and an
# f-string in the first statement position is not a docstring at all — it
# would leave every test in this file with __doc__ of None.
REGION = "cp-main-direct-edit.publish-bar.error-note"

# Byte-exact, attribute order included. See test_error_note_markup_is_exact.
ERROR_NOTE_MARKUP = '<span class="direct-errors" hidden></span>'

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"

# The account name is derived from the seeded hero title rather than written
# as a literal, the same indirection test_direct_edit.py:50 uses: LLM-COP-10
# stripped a persona out of this product, and a fresh name literal here would
# quietly put one back.
PAGE_NAME_OWNER = SEED_BY_KIND["hero"]["title"]


# --- fixtures, all local to this file ---------------------------------------


@pytest.fixture
def direct_admin(app):
    """A test client holding a real admin session on the seeded app."""
    create_admin(app, username=PAGE_NAME_OWNER, password=ADMIN_PASSWORD)
    client = app.test_client()
    response = login(client, username=PAGE_NAME_OWNER, password=ADMIN_PASSWORD)
    assert response.status_code == 302
    return client


@pytest.fixture
def direct_html(direct_admin):
    """The document GET /muokkaa/sivu really serves, whole."""
    response = direct_admin.get(DIRECT_URL)
    assert response.status_code == 200
    return response.get_data(as_text=True)


# --- helpers ----------------------------------------------------------------


def publish_bar_markup(html):
    """The <footer class="direct-publishbar">…</footer> slice, byte-exact.

    Scoped rather than document-wide so an assertion cannot pass from some
    other element that happens to carry the same substring.
    """
    start = html.index('<footer class="direct-publishbar">')
    end = html.index("</footer>", start) + len("</footer>")
    return html[start:end]


def script_source():
    return (STATIC / "direct-edit.js").read_text(encoding="utf-8")


def strip_comments(source):
    """`source` with /*…*/ blocks and WHOLE-LINE // comments removed.

    Whole-line only, deliberately. direct-edit.js:367 reads
    `window.prompt("Linkin osoite", "https://")` — a stripper that cut at the
    first `//` anywhere on a line would eat into that string literal and
    leave an unbalanced quote behind. Do not "improve" this into a trailing
    comment stripper.
    """
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.DOTALL)
    return "\n".join(
        "" if line.lstrip().startswith("//") else line
        for line in source.split("\n")
    )


def string_literals(source):
    """Every double-quoted literal in `source`, quotes included."""
    return re.findall(r'"(?:[^"\\\n]|\\.)*"', source)


# --- the served markup ------------------------------------------------------


def test_error_note_ships_empty(direct_html):
    """cp-main-direct-edit.publish-bar.error-note — the note ships, and it
    ships with no text in it.

    element_text returns None when no such element exists and "" when it
    exists and is empty (tests/conftest.py:142-149), so this one line pins
    presence AND emptiness and cannot pass on a deleted element.
    """
    assert element_text(direct_html, "span", cls="direct-errors") == "", (
        f"{REGION}: <span class=\"direct-errors\"> must ship in the served"
        " document and must ship empty. element_text returned"
        f" {element_text(direct_html, 'span', cls='direct-errors')!r} —"
        " None means the element is absent, which is the deletion this"
        " artifact exists to catch (direct-edit.js:397 dereferences it"
        " unguarded, so an absent note is a TypeError on the first save)."
    )


def test_error_note_markup_is_exact(direct_html):
    """cp-main-direct-edit.publish-bar.error-note — the note's markup,
    byte-exact, inside the publish bar.

    This pins attribute order BY DESIGN, which is a stricter contract than
    the criterion needs — see the failure message.
    """
    bar = publish_bar_markup(direct_html)
    assert ERROR_NOTE_MARKUP in bar, (
        f"{REGION}: the publish bar must contain, byte for byte,"
        f" {ERROR_NOTE_MARKUP!r}.\n"
        "This is an INTENTIONAL-EDIT FENCE, not a bug report. It pins"
        " attribute order on purpose so that adding an attribute —"
        ' aria-live="polite" is the likely one — is a deliberate act with a'
        " one-line constant to update (ERROR_NOTE_MARKUP in this file)"
        " rather than an unnoticed change to an element two merged"
        " artifacts (LLM-COP-6, LLM-COP-12) depend on. If you meant the"
        " edit, update the constant."
        f"\nPublish bar as served:\n{bar}"
    )


# --- the shipped script -----------------------------------------------------


@pytest.mark.parametrize(
    "prefix", ["tallennus epäonnistui", "julkaisu epäonnistui"]
)
def test_failure_prefix_ships(prefix):
    """cp-main-direct-edit.publish-bar.error-note — the failure text the note
    is filled with really ships.

    HONESTY, and do not trim it: pytest drives a test client that executes
    no JavaScript. This proves the strings SHIP in app/static/direct-edit.js,
    never that they RENDER into the note. Only a browser can prove the
    second, and no browser runs in this suite.

    Only the stable PREFIX is pinned. "(500)", "(yhteysvirhe)",
    "Aloitusosio" and the field labels are DATA — they are composed at
    runtime from a status code or a lookup table, and pinning them is the
    LLM-COP-8 defect (a fence over data that has to move).
    """
    literals = string_literals(strip_comments(script_source()))
    assert any(lit[1:-1].startswith(prefix) for lit in literals), (
        f"{REGION}: no string literal in app/static/direct-edit.js starts"
        f" with {prefix!r}. The publish bar's error note is filled from"
        " these literals, so without one the note can only ever show an"
        " empty failure. Pin the prefix only — the parenthetical and the"
        " section and field names after it are data and must stay free."
    )


def test_error_note_is_bound_and_written():
    """cp-main-direct-edit.publish-bar.error-note — the class token in the
    template is the one the script binds, and the bound note is actually
    filled and revealed.

    This is the only assertion in the repository tying
    `<span class="direct-errors">` to the JavaScript that selects it. The
    binding name is captured rather than assumed, so renaming `errorNote` to
    anything else is a legitimate refactor this test does not punish.

    HONESTY, and do not trim it: pytest executes no JavaScript. This proves
    the binding and the writes SHIP in the source text, never that they RUN.
    """
    src = strip_comments(script_source())

    # var|const|let, though the file is ES5 throughout: the point of this
    # test is the binding, not the declaration keyword, and modernising the
    # line is a legitimate edit that must not turn it red.
    match = re.search(
        r'(?:var|const|let)\s+(\w+)\s*=\s*query\("\.direct-errors"\);', src
    )
    assert match is not None, (
        f"{REGION}: app/static/direct-edit.js does not bind"
        ' `<name> = query(".direct-errors");`. The template ships that'
        " class token, so an unbound note means the publish bar's failure"
        " note is dead markup and every save failure is silent."
    )
    name = match.group(1)

    for attribute, why in (
        ("textContent", "the failure text is never put into the note"),
        ("hidden", "the note is never revealed (or never re-hidden)"),
    ):
        pattern = re.escape(name) + r"\." + attribute + r"\s*="
        assert re.search(pattern, src) is not None, (
            f"{REGION}: `{name}` is bound to .direct-errors but"
            f" `{name}.{attribute}` is never written, so {why}."
        )
