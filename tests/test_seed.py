"""Plan step 5 — app/seed.py: neutral placeholder content, seeded once.

The trap strings are built from explicit escapes copied out of the governing
spec JSON (cp-main.about-facts, cp-main-phone.phone-hours) so no editor or
tool can silently swap an en dash (U+2013) or thin space (U+2009) for an
ASCII look-alike.

Since LLM-COP-10 the seed is a template, not a person: these tests assert its
SHAPE and that its trap typography survives, never what its copy says. A test
that pinned a seeded sentence would be re-asserting the mockup persona the
artifact removed.
"""

import json
import re

from app.fields import FIELDS
from app.sections import badge
from app.seed import seed_if_empty

EN_DASH = "–"
THIN_SPACE = " "
DURATION = f"45{EN_DASH}90 min"  # cp-main.about-section.about-facts
DAYS = f"Ma{EN_DASH}To"  # cp-main-phone.phone-vastaanotto.phone-hours
HOURS = f"9.00{THIN_SPACE}{EN_DASH}{THIN_SPACE}16.00"  # phone-hours


def _rows(conn):
    return conn.execute(
        "SELECT kind, position, state, draft, published, previous_published"
        " FROM sections ORDER BY position"
    ).fetchall()


def test_seeds_six_published_sections_in_page_order(conn):
    seed_if_empty(conn)
    rows = _rows(conn)
    assert [row["kind"] for row in rows] == [
        "hero",
        "tietoa",
        "palvelut",
        "vastaanottoajat",
        "yhteydenotto",
        "sijainti",
    ]
    assert all(row["state"] == "published" for row in rows)
    assert all(row["previous_published"] is None for row in rows)


def test_every_seeded_section_badge_reads_julkaistu(conn):
    seed_if_empty(conn)
    for row in _rows(conn):
        assert row["draft"] == row["published"]
        assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"


def test_hero_facts_are_the_four_desktop_cards(conn):
    seed_if_empty(conn)
    (published,) = conn.execute(
        "SELECT published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    facts = json.loads(published)["facts"]
    assert [fact["label"] for fact in facts] == [
        "KOULUTUS",
        "KOKEMUS",
        "OSAAMINEN",
        "ASIAKKAAT",
    ]
    values = [fact["value"] for fact in facts]
    # Shape, not copy: four cards, every one filled with something the owner
    # will replace, and the first still a two-line value — .fact-value is
    # white-space: pre-line, so the newline is designed behaviour.
    assert len(values) == 4
    assert all(value.strip() for value in values)
    assert "\n" in values[0]


def test_tietoa_facts_are_the_three_plain_strings(conn):
    seed_if_empty(conn)
    (published,) = conn.execute(
        "SELECT published FROM sections WHERE kind = 'tietoa'"
    ).fetchone()
    facts = json.loads(published)["facts"]
    assert len(facts) == 3
    assert all(isinstance(fact, str) and fact.strip() for fact in facts)
    # The one place the en-dash guarantee is anchored to a field rather than
    # to the whole stored blob.
    assert DURATION in facts[0]


def test_stored_json_carries_the_trap_typography_byte_exact(conn):
    seed_if_empty(conn)
    blob = "".join(
        row["published"] for row in conn.execute("SELECT published FROM sections")
    )
    assert DURATION in blob
    assert DAYS in blob
    assert HOURS in blob


def test_hero_carries_the_three_site_chrome_keys_last(conn):
    """LLM-COP-10: brand, page_title and footer are seeded, non-empty, and
    LAST in hero's key order. Order is load-bearing — validate_payload rebuilds
    a payload in FIELDS declaration order, so a key stored out of order makes
    the first no-op save rewrite the row and flip its badge to Luonnos."""
    seed_if_empty(conn)
    (published,) = conn.execute(
        "SELECT published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    payload = json.loads(published)
    assert list(payload)[-3:] == ["brand", "page_title", "footer"]
    assert all(payload[key].strip() for key in ("brand", "page_title", "footer"))
    assert list(payload) == list(FIELDS["hero"])


def test_no_identity_string_survives_anywhere_in_the_seed(conn):
    """The standing guard for LLM-COP-10. This is a GENERIC contact page: the
    shipped seed must name no person, practice, registration or register. The
    pattern is deliberately wider than the artifact's own gate, which misses
    'anna.virtanen' because it has a dot where the pattern had a space."""
    seed_if_empty(conn)
    blob = "".join(
        row["published"] + row["draft"]
        for row in conn.execute("SELECT draft, published FROM sections")
    )
    forbidden = re.compile(
        r"anna|puheterap|2938471|valvira|virtanen|logopedia|afasia",
        re.IGNORECASE,
    )
    assert forbidden.findall(blob) == []


def test_second_seed_call_inserts_nothing(conn):
    seed_if_empty(conn)
    before = [tuple(row) for row in _rows(conn)]
    seed_if_empty(conn)
    after = [tuple(row) for row in _rows(conn)]
    assert len(before) == 6
    assert after == before
