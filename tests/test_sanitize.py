"""Plan step 1 (LLM-COP-4) — app/sanitize.py: the one sanitizer and the
payload validator.

Brief hazards covered: a draft <script> in a rich field is stripped
server-side (with its content — LLM-COP-4 "What a reviewer must check"),
and the 60-char cap is enforced server-side from the schema module, not
only by the counter. The valid payloads come from the real seed
(app.seed.SEED_SECTIONS), not hand-built fixtures.
"""

import copy

import pytest

from app.sanitize import sanitize_rich, validate_payload
from app.seed import SEED_SECTIONS

SEED_BY_KIND = dict(SEED_SECTIONS)


def hero_payload():
    return copy.deepcopy(SEED_BY_KIND["hero"])


# --- sanitize_rich -----------------------------------------------------------


def test_script_is_dropped_with_its_content_and_b_becomes_strong():
    # The plan's own criterion string, verbatim.
    assert (
        sanitize_rich("<script>alert(1)</script>x<b>y</b>")
        == "x<strong>y</strong>"
    )


def test_i_normalizes_to_em():
    assert sanitize_rich("a<i>b</i>c") == "a<em>b</em>c"


def test_style_is_dropped_with_its_content():
    assert sanitize_rich("a<style>body { display: none }</style>b") == "ab"


@pytest.mark.parametrize(
    "raw",
    [
        "<p>Hei <b>a</b><script>alert(2)</script></p>",
        "<p>Hei <b>a</b><style>.x{color:red}</style></p>",
        "<div><span><script>alert(2)</script></span>Hei <b>a</b></div>",
    ],
)
def test_script_and_style_are_dropped_with_content_inside_a_block(raw):
    """script/style go with their content wherever they sit, block
    wrapper included — not just leading or between bare text nodes.

    This is the rule the paste filter's client twin in
    app/static/editor.js mirrors (its DROP_WITH_CONTENT is this set). It
    is pinned here because a client that strips the tag but keeps the
    text hands the server script source as ordinary characters, which
    the server can no longer tell apart and so stores as page copy —
    the divergence found in the live browser pass, where a *leading*
    <style> hid the bug because DOMParser hoists that one into <head>.

    pytest executes no JavaScript: this locks the server invariant the
    twin is written against. The twin itself is proven only by the live
    browser pass.
    """
    result = sanitize_rich(raw)
    assert "<script" not in result
    assert "<style" not in result
    assert "alert" not in result
    assert "color:red" not in result
    assert result.endswith("Hei <strong>a</strong>")


def test_attributes_are_stripped_from_allowed_tags():
    assert (
        sanitize_rich('<strong class="x" onclick="evil()">y</strong>')
        == "<strong>y</strong>"
    )
    assert sanitize_rich('a<br class="x" data-y="z">b') == "a<br>b"


def test_disallowed_tags_are_stripped_but_their_text_kept():
    # This used <a href> as its disallowed tag until LLM-COP-6 allowed
    # a[href]; span is still disallowed, so what the test was written to
    # assert is unchanged. The <a> shapes moved to the block below.
    assert sanitize_rich("<div><span>linkki</span></div>") == "linkki"


# --- a[href] (LLM-COP-6) -----------------------------------------------------
#
# Linkki in the direct-edit toolbar needs the one sanitizer to allow one
# tag with one attribute. Every rejection below drops the <a> and keeps
# its text — the shape every disallowed tag already had.


def test_https_link_survives_with_its_href():
    assert (
        sanitize_rich('<a href="https://x.fi/">k</a>')
        == '<a href="https://x.fi/">k</a>'
    )


def test_mailto_and_tel_and_fragment_links_survive():
    assert (
        sanitize_rich('<a href="mailto:posti@x.fi">k</a>')
        == '<a href="mailto:posti@x.fi">k</a>'
    )
    assert (
        sanitize_rich('<a href="TEL:+358401234567">k</a>')
        == '<a href="TEL:+358401234567">k</a>'
    )
    assert sanitize_rich('<a href="#palvelut">k</a>') == '<a href="#palvelut">k</a>'


@pytest.mark.parametrize(
    "raw",
    [
        # Scripting schemes, including the shapes html.parser decodes for
        # us before the handler ever sees them.
        '<a href="javascript:alert(1)">k</a>',
        '<a href="JaVaScRiPt:alert(1)">k</a>',
        '<a href="java\tscript:alert(1)">k</a>',
        '<a href="java&Tab;script:alert(1)">k</a>',
        '<a href="javascript&#58;alert(1)">k</a>',
        (
            '<a href="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;'
            '&#116;&#58;alert(1)">k</a>'
        ),
        '<a href="java\x00script:alert(1)">k</a>',
        '<a href="  javascript:alert(1)  ">k</a>',
        '<a href="data:text/html,<h1>x">k</a>',
        '<a href="vbscript:msgbox(1)">k</a>',
        '<a href="tuntematon:x">k</a>',
        # Every path-relative shape, rejected as a class.
        '<a href="//evil.example/">k</a>',
        '<a href="/\\evil.example/">k</a>',
        '<a href="\\evil.example/">k</a>',
        '<a href="/kaikki">k</a>',
        '<a href="kaikki">k</a>',
        # Missing, empty or blank hrefs — ('href', None), attrs == [] and
        # the whitespace-only value must all drop the tag, never raise.
        "<a href>k</a>",
        "<a>k</a>",
        '<a href="">k</a>',
        '<a href="   ">k</a>',
    ],
)
def test_unsafe_or_absent_href_drops_the_tag_and_keeps_the_text(raw):
    assert sanitize_rich(raw) == "k"


def test_every_attribute_but_href_is_dropped():
    assert (
        sanitize_rich('<a href="#a" class="x" onclick="e()">k</a>')
        == '<a href="#a">k</a>'
    )


def test_the_normalized_href_is_the_one_stored():
    # What was checked and what is emitted are the same string.
    assert (
        sanitize_rich('<a href=" https://x.fi/ ">k</a>')
        == '<a href="https://x.fi/">k</a>'
    )


def test_quotes_in_an_href_cannot_break_out_of_the_attribute():
    result = sanitize_rich("<a href='https://x/?a=\"b\"'>k</a>")
    inside = result[len('<a href="') : result.index('">')]
    assert '"' not in inside
    assert result == '<a href="https://x/?a=&quot;b&quot;">k</a>'


@pytest.mark.parametrize(
    "raw",
    [
        '<a href="https://x.fi/">k</a>',
        '<a href="javascript:alert(1)">k</a>',
        '<a href="//evil.example/">k</a>',
        "<a href>k</a>",
        '<a href="#a" class="x" onclick="e()">k</a>',
        '<a href=" https://x.fi/ ">k</a>',
        "<a href='https://x/?a=\"b\"'>k</a>",
        '<a href="https://x/?a=1&b=2">k</a>',
        'teksti <a href="https://x.fi/"><b>k</b></a> jatkuu',
    ],
)
def test_link_sanitizing_is_idempotent(raw):
    once = sanitize_rich(raw)
    assert sanitize_rich(once) == once


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>x<b>y</b>",
        '<div><a href="#">linkki</a></div>',
        "a<i>b</i><br>c &amp; d",
        SEED_BY_KIND["hero"]["ingress"],  # real seed copy, "ä" included
        "<em>auki",  # unclosed allowed tag gets balanced
    ],
)
def test_sanitize_is_idempotent(raw):
    once = sanitize_rich(raw)
    assert sanitize_rich(once) == once


def test_plain_text_with_finnish_characters_passes_through():
    text = SEED_BY_KIND["hero"]["ingress"]
    assert "ä" in text  # the trap the serialization convention guards
    assert sanitize_rich(text) == text


# --- validate_payload --------------------------------------------------------


def test_seeded_hero_payload_validates_clean():
    clean, errors = validate_payload("hero", hero_payload())
    assert errors == {}
    assert clean == hero_payload()


def test_61_char_title_is_rejected_and_nothing_returned():
    # Brief hazard: the 60-char cap (app/fields.py hero.title "cap": 60)
    # enforced server-side, not only by the counter.
    payload = hero_payload()
    payload["title"] = "x" * 61
    clean, errors = validate_payload("hero", payload)
    assert clean is None
    assert "title" in errors


def test_60_char_title_is_accepted():
    payload = hero_payload()
    payload["title"] = "x" * 60
    clean, errors = validate_payload("hero", payload)
    assert errors == {}
    assert clean["title"] == "x" * 60


def test_missing_key_is_rejected():
    payload = hero_payload()
    del payload["kicker"]
    clean, errors = validate_payload("hero", payload)
    assert clean is None
    assert "kicker" in errors


def test_unknown_key_is_rejected():
    payload = hero_payload()
    payload["tuntematon"] = "x"
    clean, errors = validate_payload("hero", payload)
    assert clean is None
    assert "tuntematon" in errors


def test_non_list_facts_is_rejected():
    payload = hero_payload()
    payload["facts"] = "ei lista"
    clean, errors = validate_payload("hero", payload)
    assert clean is None
    assert "facts" in errors


def test_rich_field_is_sanitized_by_validation():
    payload = hero_payload()
    payload["ingress"] = "Hei<script>alert(1)</script> <b>maailma</b>"
    clean, errors = validate_payload("hero", payload)
    assert errors == {}
    assert clean["ingress"] == "Hei <strong>maailma</strong>"
