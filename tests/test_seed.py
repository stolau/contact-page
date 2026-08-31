"""Plan step 5 — app/seed.py: mockup content, byte-exact, seeded once.

The trap strings are built from explicit escapes copied out of the governing
spec JSON (cp-main.about-facts, cp-main-phone.phone-hours) so no editor or
tool can silently swap an en dash (U+2013) or thin space (U+2009) for an
ASCII look-alike.
"""

import json

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
        "ERITYISOSAAMINEN",
        "ASIAKKAAT",
    ]
    values = [fact["value"] for fact in facts]
    assert "FM, logopedia" in values[0]
    assert "Turun yliopisto" in values[0]
    assert values[1] == "15 vuotta kliinistä työtä"
    assert values[2] == "Änkytys ja afasiakuntoutus"
    assert values[3] == "Lapset, nuoret ja aikuiset"


def test_tietoa_facts_are_the_three_plain_strings(conn):
    seed_if_empty(conn)
    (published,) = conn.execute(
        "SELECT published FROM sections WHERE kind = 'tietoa'"
    ).fetchone()
    assert json.loads(published)["facts"] == [
        f"Käynnit {DURATION}",
        "Lausunnot neuvolalle, koululle ja Kelalle",
        "Etäkäynnit mahdollisia",
    ]


def test_stored_json_carries_the_trap_typography_byte_exact(conn):
    seed_if_empty(conn)
    blob = "".join(
        row["published"] for row in conn.execute("SELECT published FROM sections")
    )
    assert DURATION in blob
    assert DAYS in blob
    assert HOURS in blob


def test_second_seed_call_inserts_nothing(conn):
    seed_if_empty(conn)
    before = [tuple(row) for row in _rows(conn)]
    seed_if_empty(conn)
    after = [tuple(row) for row in _rows(conn)]
    assert len(before) == 6
    assert after == before
