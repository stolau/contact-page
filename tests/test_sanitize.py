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


def test_attributes_are_stripped_from_allowed_tags():
    assert (
        sanitize_rich('<strong class="x" onclick="evil()">y</strong>')
        == "<strong>y</strong>"
    )
    assert sanitize_rich('a<br class="x" data-y="z">b') == "a<br>b"


def test_disallowed_tags_are_stripped_but_their_text_kept():
    assert (
        sanitize_rich('<div><a href="https://evil.example/">linkki</a></div>')
        == "linkki"
    )


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
