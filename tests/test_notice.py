"""The contact band's availability notice, resolved (USR-COP-4) —
app/notice.py alone, as a pure function.

Shaped after tests/test_style_selection.py's test_template_for_resolves_every
_input, because it guards the same failure in the same way, and for the same
reason app/styles.py records: `in` on a dict HASHES its operand and .strip()
on one raises AttributeError, so a stored value that is a JSON object or
array takes a different path from a merely unknown string. Before
resolve_style tested isinstance, exactly that pair of shapes answered 500 for
every visitor to the public page.

THE WRONGLY-TYPED CASES ARE THE POINT, and they are what make this module
worth its own file. An unknown STRING ("kyllä", "ON") can never catch a
missing isinstance — every one of those falls through the membership test
politely while the page is one stored object away from going down. So the
table below is written in two halves, and the second half is the half that
fails against the two implementations a later refactor would reach for:

  * `value in {"on", "true", "1"}`      -> TypeError on {} and []
  * `payload["notice_text"].strip()`    -> AttributeError on {} and []

Both of those are natural simplifications of what app/notice.py does now.
They are named here so the next person to write one finds a red test rather
than a 500.

Nothing about the PAGE is asserted here — which element, which class, which
skin. That belongs to tests/test_page.py and tests/test_page_v2.py; this file
owns the decision, not the rendering of it.
"""

import pytest

from app.notice import NOTICE_ON, contact_notice, notice_shown

TEXT = "Valitettavasti tällä hetkellä ei ole aikoja"
# The author's second example, and it is in here on purpose: it is a PROMISE,
# not a warning, and the resolver must treat the two identically. Anything
# that special-cased "unavailable" wording would fail on this one.
PROMISE = "Seuraavat ajat mm.yyyy alussa"


def payload(**overrides):
    """A yhteydenotto payload carrying the two notice keys and nothing else
    this module reads. The other eight declared keys are irrelevant here —
    contact_notice looks at exactly two, which is itself a claim the tests
    below make by never supplying the rest."""
    base = {"notice_text": TEXT, "notice_on": NOTICE_ON}
    base.update(overrides)
    return base


# --- the flag ---------------------------------------------------------------


def test_the_flag_is_recognised_only_as_the_exact_stored_value():
    """One spelling means shown, and every other value means not shown.

    The near-misses are deliberate. "ON" and "On" are what a case-insensitive
    implementation would accept; "on " is what a trimming one would; "true",
    "1" and "kyllä" are what an owner would type if the field were ever drawn
    as a text box — which is exactly why yhteydenotto.notice_on carries no
    FIELD_LABELS entry (tests/test_fields.py).
    """
    assert notice_shown("on") is True
    assert NOTICE_ON == "on"

    assert notice_shown("ON") is False
    assert notice_shown("On") is False
    assert notice_shown("on ") is False
    assert notice_shown(" on") is False
    assert notice_shown("true") is False
    assert notice_shown("1") is False
    assert notice_shown("kyllä") is False
    assert notice_shown("") is False


@pytest.mark.parametrize("value", [None, 1, 0, True, {}, [], {"on": True}, ["on"]])
def test_a_wrongly_typed_flag_is_not_shown_and_does_not_raise(value):
    """The isinstance guard, made executable.

    {} and [] are the two that matter: they are not merely unknown flags,
    they are wrongly TYPED ones, and `value in {...}` would raise TypeError
    on them before any fallback was reached. Nothing in the app writes such a
    value — validate_payload admits only str for a plain field — but the
    store is not the app's alone, and a 500 on the public page is what
    app/styles.py's own comment exists to prevent.
    """
    assert notice_shown(value) is False


# --- the whole decision -----------------------------------------------------


def test_the_notice_is_the_owners_text_when_the_flag_is_on():
    assert contact_notice(payload()) == TEXT
    assert contact_notice(payload(notice_text=PROMISE)) == PROMISE


def test_the_text_is_returned_verbatim():
    """Not trimmed, not normalised, not truncated. It is a plain field and
    Jinja escapes it at render time like every other one; changing the
    owner's own words on the way to the page is not this function's job."""
    spaced = "  Seuraavat ajat  toukokuun alussa  "
    assert contact_notice(payload(notice_text=spaced)) == spaced


@pytest.mark.parametrize(
    "flag", ["", "ON", "kyllä", "1", "true", "on ", "off", "no"]
)
def test_an_unrecognised_flag_hides_the_notice_and_keeps_the_text(flag):
    """The whole feature, in one assertion: the resolver returns "" while
    notice_text still holds the owner's sentence. Switching the notice off
    must not cost them the words, which is why there are two fields rather
    than one."""
    stored = payload(notice_on=flag)
    assert contact_notice(stored) == ""
    assert stored["notice_text"] == TEXT


@pytest.mark.parametrize("flag", [None, 1, {}, [], {"notice_on": "on"}, ["on"]])
def test_a_wrongly_typed_flag_renders_nothing_rather_than_raising(flag):
    assert contact_notice(payload(notice_on=flag)) == ""


@pytest.mark.parametrize("text", [None, 1, {}, [], {"text": "x"}, ["x"]])
def test_a_wrongly_typed_text_renders_nothing_rather_than_raising(text):
    """The SECOND guard, and the one an implementation that only copied
    resolve_style would miss. The flag is checked first, so this reaches
    .strip() with the flag recognised — which is precisely the state in which
    an unguarded `text.strip()` raises AttributeError. Same 500, one line
    further down.
    """
    assert contact_notice(payload(notice_text=text)) == ""


@pytest.mark.parametrize("text", ["", " ", "   ", "\t", "\n", "  \n "])
def test_an_empty_or_blank_text_renders_nothing_even_with_the_flag_on(text):
    """A notice with nothing to say is no notice. This is also what keeps a
    freshly seeded site clean: app/seed.py stores "" for both keys, and a
    migrated store gets "" for both from migration 12."""
    assert contact_notice(payload(notice_text=text)) == ""


def test_a_payload_missing_the_keys_renders_nothing():
    """The state every store is in between the deploy and the migration, and
    the state blank_payload is in for a kind's preview
    (tests/test_sectionlist.py renders one through page.html's macro)."""
    assert contact_notice({}) == ""
    assert contact_notice({"notice_text": TEXT}) == ""
    assert contact_notice({"notice_on": "on"}) == ""
    assert contact_notice({"body": "jotain muuta"}) == ""


@pytest.mark.parametrize("value", [None, "", "on", 7, [], ["notice_on"]])
def test_a_payload_that_is_not_a_dict_renders_nothing_rather_than_raising(
    value,
):
    """.get() on a str is an AttributeError and on a list a TypeError. No
    caller in the app passes one — both templates hand the macro's `p` — but
    this function's whole contract is that it never raises, and a contract
    with an untested edge is a comment."""
    assert contact_notice(value) == ""
