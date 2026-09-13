"""The call button's dial target, resolved (LLM-COP-45) — app/telephone.py
alone, as a pure function.

Shaped after tests/test_notice.py, for the same reason: one small module
decides one thing for both public renderings, so the decision is tested here
and the RENDERING of it in tests/test_page_v2.py. Nothing about which
element, which class or which skin is asserted in this file.

THE ASSERTION THAT MATTERS IS THE PROPERTY, not the table. Two earlier
versions of this rule shipped wrong numbers in review — one concatenated
every digit in the field, one let a word precede the number — and both were
sound against every string anybody had written down. A hand-listed corpus
only ever contains the contaminants somebody thought of. So the rows below
are regressions, and

    tel_href(v) == "" or digits(tel_href(v)) == digits(squash(v))

asserted over every one of them, plus the "+" agreement, is the claim: the
href IS the field, or there is no href. A rule that selects a sub-run out of
the field fails that assertion; neither table alone would catch it.

(The FULL generated space — every 2- and 3-way combination of the fragments
these strings are built from — belongs to the proof suite beside this one.
This file asserts the property over the strings it lists, which is what
makes each listed row a property check and not only an expectation.)

THE WRONGLY-TYPED ROWS ARE NOT DECORATION, and app/notice.py's own docstring
is the precedent they are written from: "isinstance BEFORE any .strip() …
that is a 500 on the public page … the store is not the app's alone." A
payload whose published column is empty yields {} (app/sections.py), so
`p.phone` is a Jinja Undefined and every one of re.sub, .strip() and
"".join(... c.isspace() ...) raises on it — a 500 where `{{ p.phone }}`
renders "" today. Unreachable through the app, and pinned all the same,
because that is exactly what was said about the three modules that now carry
the guard.
"""

import re

import pytest
from jinja2 import ChainableUndefined, StrictUndefined, Undefined

from app.seed import SEED_SECTIONS
from app.telephone import _NUMBER, tel_href

# The shipped placeholder, READ OFF THE SEED rather than copied here: it is
# owner-facing content, and a test that pins it pins data it does not own.
# What is asserted about it is a SHAPE — prose gets no link — and the value
# is whatever the seed says it is today.
SEEDED_PHONE = next(
    payload["phone"] for kind, payload in SEED_SECTIONS if kind == "yhteydenotto"
)

# --- the fields that dial -------------------------------------------------
#
# Every string here is one the TEST chose to probe a shape. None is owner
# data and none is read back out of the store.
DIALS = {
    # The plain forms, with each separator the grammar admits.
    "040 123 4567": "tel:0401234567",
    "0401234567": "tel:0401234567",
    "040-1234567": "tel:0401234567",
    "040.123.4567": "tel:0401234567",
    "09-123 456": "tel:09123456",
    # The international form. The "+" survives into the href because the
    # FIELD begins with one — never because one was found further in.
    "+358 40 123 4567": "tel:+358401234567",
    # An NBSP between the groups: handled by the squash, not missed. A word
    # processor inserts these and the owner cannot see them.
    "040\xa0123\xa04567": "tel:0401234567",
    # Surrounding whitespace is stripped, so a trailing newline out of a
    # textarea does not cost the link.
    "  040 123 4567\n": "tel:0401234567",
    # THE HONEST RESIDUALS, pinned as deliberate. A human would not dial
    # either of these, and both are FAITHFUL: the whole field really is
    # digits and separators, and the href is exactly those digits in order.
    # The product has not chosen a reading here, it has rendered the only
    # one — a strictly weaker failure than a rule that welds, drops or
    # invents a digit, and the button's own label shows the owner what it
    # will dial.
    "9-16 040 123 4567": "tel:9160401234567",
    "20100 040 123 4567": "tel:201000401234567",
    # The E.164 ends, both sides of both of them.
    "123456": "tel:123456",
    "123456789012345": "tel:123456789012345",
}

# --- the fields that get no href at all -----------------------------------
#
# (the field, why it is refused). The reason is carried in the table because
# every one of these is a deliberate miss, and the next reader's instinct on
# several of them will be to "fix" it.
REFUSED = {
    # THE STRING THAT KILLED THE SECOND RULE. "(0)" is the Finnish trunk
    # zero: dial it domestically, omit it internationally — a CONDITIONAL
    # digit. The rule that accepted parentheses answered
    # tel:+3580401234567, welding the zero into the middle of an E.164
    # number. Admit parentheses to the grammar and this row goes red at
    # exactly that value.
    "+358 (0)40 123 4567": "the trunk-zero convention; parentheses are out",
    # The second rule dropped this "+" silently, downgrading an
    # international number to a domestic one. The grammar's "+" is anchored
    # at position 0 by the fullmatch, so a "+" anywhere else fails the
    # whole string. Un-anchor it and this row goes red at tel:358401234567.
    "(+358) 40 123 4567": "a '+' that is not at position 0",
    # The second rule FABRICATED a leading "+" here — it read the "+" out
    # of the tail rather than out of the field — and answered tel:+358040
    # for a field that does not begin with one.
    "tai +358 040": "prose, and the '+' is not the field's first character",
    # The first rule's exact bug with no letter in the contaminant to break
    # the run: opening hours promoted into the dial target
    # (tel:9160401234567 — a number nobody has).
    "Arkisin 9-16 040 123 4567": "opening hours in front of the number",
    # A PREFIX OF ANY KIND, and this one is the design's own sample label.
    # Refusing it is the deliberate trade recorded in app/telephone.py: a
    # visitor tapping a wrong number is worse than a button that does not
    # dial, and prefix support is the convenience two wrong rules were
    # bought with. DO NOT "FIX" THIS ROW.
    "Soita 040 123 4567": "a prefix; the whole field must be the number",
    # Anything at all after the number, which is where the first rule's
    # digits came from.
    "040 123 4567 (arkisin 9-16)": "opening hours after the number",
    "040 123 4567 tai 050 765 4321": "two numbers; which one would it dial",
    # Near misses — the grammar admits exactly one separator between two
    # digit groups, and nothing after the last one.
    "(09) 123 456": "parentheses, in the domestic form this time",
    "040  123  4567": "a double space",
    "+ 358 40 123 4567": "a space after the '+'",
    "040 123 4567.": "a trailing separator",
    "": "the empty field — a fresh or migrated store",
    "   ": "whitespace only",
    "+": "a '+' and no digits",
    # E.164, both ends. Drop the ceiling and the first of these goes red.
    "0" * 45: "45 digits is not a phone number (E.164 allows 15)",
    "12345": "five digits is not a number worth offering to dial",
    # ASCII-ONLY EXTRACTION. That last character is U+0667, an Arabic-Indic
    # seven. A grammar written with \d would ADMIT this field and the
    # [^0-9] extraction would then quietly drop the digit, dialling a
    # number one digit short of the one the owner typed. Written [0-9] on
    # both sides, the field simply gets no link.
    "040 123 456٧": "a non-ASCII digit; [0-9] refuses the whole field",
    "０４０１２３": "fullwidth digits, same reason",
    # An address is not a phone number, and it is the most likely thing to
    # end up in this field by a paste.
    "Yliopistonkatu 24 A 12, 20100 Turku": "an address",
    # Hostile shapes. None of them can reach the href, but the closed
    # alphabet below is what says so for all of them at once.
    '"><script>alert(1)</script>': "markup",
    "javascript:alert(1)": "another scheme",
    "tel:0401234567": "a scheme the owner typed; the field is a number, not a URL",
    "040 123\x00 4567": "an embedded NUL",
    "\u202e040 123 4567": "an RTL override in front of the number",
    "040\u200b123\u200b4567": (
        "zero-width spaces, which are not whitespace"
    ),
}


def digits(text):
    """Every ASCII digit of a string, in order. [^0-9] and never \\D — the
    same choice app/telephone.py makes, and for the same reason: \\D in str
    mode keeps Arabic-Indic digits, so a helper written with it would be
    wrong in the same direction as the code it checks and would agree with
    it about a number neither should emit."""
    return re.sub(r"[^0-9]", "", text)


def squash(value):
    """The field as the rule sees it before the grammar: Unicode spaces
    flattened, ends stripped."""
    return "".join(" " if c.isspace() else c for c in value).strip()


@pytest.mark.parametrize("field,expected", sorted(DIALS.items()))
def test_a_field_that_is_a_number_dials_exactly_its_own_digits(field, expected):
    assert tel_href(field) == expected


@pytest.mark.parametrize("field,reason", sorted(REFUSED.items()))
def test_a_field_that_is_not_a_number_gets_no_href(field, reason):
    assert tel_href(field) == "", f"{field!r} was accepted, and {reason}"


@pytest.mark.parametrize("field", sorted(DIALS) + sorted(REFUSED))
def test_the_href_is_the_field_or_it_is_nothing(field):
    """THE PROPERTY. Every digit of the field appears in the href, in order,
    and none is dropped; the "+" is there if and only if the field begins
    with one.

    This is the assertion both earlier rules would have failed, and it is
    the one that cannot be satisfied by a rule that selects a sub-run of the
    field — because such a rule has a selection to get wrong, and this says
    there is no selection at all.

    ABLE TO FAIL: make tel_href scan from the first digit instead of
    fullmatching and this goes red on "Arkisin 9-16 040 123 4567", naming
    the digits the href carries that the field's own reading does not.
    """
    href = tel_href(field)
    if href == "":
        return
    body = href[len("tel:"):]
    text = squash(field)
    assert digits(body) == digits(text), (
        f"{field!r} dialled {href!r}, whose digits are not the field's own — "
        "a digit was dropped, welded in or reordered"
    )
    assert body.startswith("+") == text.startswith("+"), (
        f"{field!r} dialled {href!r}: the '+' is present in the href and not "
        "in the field, or the other way round"
    )


@pytest.mark.parametrize("field", sorted(DIALS) + sorted(REFUSED))
def test_the_output_alphabet_is_closed(field):
    """"" or "tel:" followed by an optional "+" and ASCII digits, whatever is
    stored. This is what makes the value safe as an href attribute: no
    quote, no space, no second scheme and no non-ASCII digit can reach it,
    so the corpus above can carry markup and a NUL without any of it being
    a question about escaping.

    ABLE TO FAIL: admit non-ASCII digits to the grammar (write it \\d) and
    the Arabic-Indic row goes red with its own digits inside the href.
    """
    assert re.fullmatch(r"|tel:\+?[0-9]+", tel_href(field)), tel_href(field)


def test_the_grammar_is_written_with_ascii_digits_and_not_backslash_d():
    """THE [0-9]/\\D PAIR, and this is the half that is observable.

    MEASURED, and it corrects a claim worth correcting: swapping the
    EXTRACTION's [^0-9] for a bare \\D changes nothing that tel_href can
    show, because the grammar has already refused every field carrying a
    non-ASCII digit — the whole corpus above stays green under that
    mutation. The two clauses are a PAIR, and the grammar is the one that
    load-bears: a \\d grammar admits a mixed-script field, and the [^0-9]
    extraction then drops the non-ASCII digits out of it, so the href is a
    number one digit shorter than the one the owner typed. A property test
    whose own digits() helper is also written [^0-9] agrees with that
    mistake instead of catching it, which is why this is asserted against
    the grammar directly rather than left to the corpus.

    ABLE TO FAIL: write _NUMBER with \\d and every row below goes red.
    """
    for field in ("٠٤٠١٢٣", "०३०१२३", "０４０１２３", "040 123 456٧"):
        assert _NUMBER.fullmatch(field) is None, (
            f"{field!r} matches the grammar, so its non-ASCII digits reach "
            "an extraction that keeps only [0-9] and the href loses them"
        )
    # And the ASCII twin of the first one does match, so the rows above fail
    # for the script and not for the shape.
    assert _NUMBER.fullmatch("040123")


def test_the_seeded_placeholder_gets_no_href():
    """A NEW SITE SHIPS NO DEAD LINK. The seed deliberately stores prose
    rather than a plausible number (app/seed.py says why), so the call
    button on a fresh install renders its placeholder with nothing to dial.

    The value is read off the seed, not pinned: what is asserted is the
    shape, and the words are the owner's to change.
    """
    assert tel_href(SEEDED_PHONE) == ""


# --- the wrongly-typed cases ----------------------------------------------
#
# Jinja's three Undefined flavours are in here individually because they
# fail differently: StrictUndefined raises on almost any operation, the
# other two on some. All three reach this function the same way — a payload
# whose published column is empty.
NOT_STRINGS = (
    None,
    123,
    0,
    12.5,
    True,
    {},
    [],
    {"phone": "040 123 4567"},
    ["040 123 4567"],
    b"040 123 4567",
    Undefined(name="phone"),
    ChainableUndefined(name="phone"),
    StrictUndefined(name="phone"),
)


@pytest.mark.parametrize("value", NOT_STRINGS, ids=lambda v: repr(v)[:40])
def test_a_value_that_is_not_a_string_is_no_number_and_no_raise(value):
    """THE isinstance, and app/notice.py's docstring is where the argument
    for it is written: "isinstance BEFORE any .strip() … that is a 500 on
    the public page … the store is not the app's alone."

    The Undefined rows are the reachable half. app/sections.py hands the
    template {} for a section whose published column is empty, so `p.phone`
    is an Undefined and `{{ p.phone|tel_href }}` would raise TypeError out
    of the squash — on the page where `{{ p.phone }}` renders "" today. The
    rest are what an API client can put in a JSON column.

    ABLE TO FAIL: delete the isinstance and every row here raises
    TypeError or AttributeError instead of returning "".
    """
    assert tel_href(value) == ""
