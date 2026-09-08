"""The contact band's availability notice: is it shown, and what does it say?

USR-COP-4. Two plain fields carry it. yhteydenotto.notice_text is the
owner's own sentence — "Valitettavasti tällä hetkellä ei ole aikoja",
"Seuraavat ajat mm.yyyy alussa" — and yhteydenotto.notice_on is the flag
that decides whether the page shows it.

TWO FIELDS, NOT ONE, and that is the feature rather than a refinement of it:
the author asked for a notice that can be switched off WITHOUT LOSING ITS
TEXT. The one-field version, where an empty string means off, destroys the
sentence the moment the owner takes the notice down and makes them retype it
three weeks later.

The flag is a `plain` field because there IS no boolean in the schema
(app/fields.py declares plain, rich and list and nothing else), and adding
one for a single flag is a schema change nothing else asked for. It follows
the precedent hero.style (app/styles.py) and hero.color_main
(app/palette.py) already set instead: a plain value with a constrained
vocabulary, resolved in Python and never trusted raw.

isinstance BEFORE any membership test and before any .strip(), and it is
load-bearing for exactly the reason resolve_style states in as many words: a
stored value that is a JSON object or array raises — TypeError out of `in`,
AttributeError out of .strip() — BEFORE the fallback is ever reached, and
that is a 500 on the public page. Nothing in the app writes such a value
(validate_payload admits only str for a plain field), but the store is not
the app's alone. Both reads below are guarded, the flag and the text, and
tests/test_notice.py pins both shapes so a later refactor to
`value in NOTICE_VALUES` or to a bare `text.strip()` is caught.
"""

# The one stored value that means shown. Anything else — "", "ON", "kyllä",
# "1", "on " with a stray space, a value some later build stopped writing,
# or a JSON object an API client stored — means not shown. An unrecognised
# flag FALLS BACK; it never raises and never shows.
NOTICE_ON = "on"


def notice_shown(value):
    """True only for the exact stored flag that means shown.

    The isinstance is not redundant decoration even though `==` on a str is
    safe: it states the contract this module is written to, and the natural
    "simplification" of this function is a membership test against a set of
    accepted spellings, which is exactly what would 500 on a stored object.
    """
    return isinstance(value, str) and value == NOTICE_ON


def contact_notice(payload):
    """The notice line the contact band should render, or "" — never a raise.

    Takes the whole PAYLOAD rather than either field, so the entire decision
    — flag recognised AND text a non-empty string — lives in one Python
    function and neither public template can end up holding half of it.

    Returns the owner's text verbatim; it is a plain field and Jinja escapes
    it like every other one. Whitespace-only text is nothing to say, so it
    resolves to "" and the template's `{% if %}` skips the element.
    """
    if not isinstance(payload, dict):
        return ""
    if not notice_shown(payload.get("notice_on")):
        return ""
    text = payload.get("notice_text")
    if not isinstance(text, str) or not text.strip():
        return ""
    return text
