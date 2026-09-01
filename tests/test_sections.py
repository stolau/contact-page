"""Plan step 4 — app/sections.py: the badge mapping and visible_sections."""

import json

from app.sections import badge, initials, site_chrome, visible_sections
from app.seed import SEED_SECTIONS


def test_badge_hidden_wins_over_everything():
    assert badge("hidden", '{"a": 1}', '{"a": 1}') == "Piilotettu"


def test_badge_hidden_with_dirty_draft_is_still_piilotettu():
    assert badge("hidden", '{"a": 2}', '{"a": 1}') == "Piilotettu"


def test_badge_new_section_default_is_piilotettu():
    # A new section defaults to state=hidden with nothing published yet.
    assert badge("hidden", None, None) == "Piilotettu"


def test_badge_published_and_clean_draft_is_julkaistu():
    assert badge("published", '{"a": 1}', '{"a": 1}') == "Julkaistu"


def test_badge_published_with_dirty_draft_is_luonnos():
    assert badge("published", '{"a": 2}', '{"a": 1}') == "Luonnos"


def test_badge_published_state_with_nothing_published_is_luonnos():
    assert badge("published", '{"a": 1}', None) == "Luonnos"


def test_visible_sections_orders_by_position_and_skips_hidden(conn):
    rows = [
        ("tietoa", 2, "published", json.dumps({"nostolause": "b"})),
        ("hero", 1, "published", json.dumps({"title": "a"})),
        ("sijainti", 3, "hidden", json.dumps({"address": "x"})),
    ]
    for kind, position, state, published in rows:
        conn.execute(
            "INSERT INTO sections (kind, position, state, draft, published,"
            " previous_published) VALUES (?, ?, ?, ?, ?, NULL)",
            (kind, position, state, published, published),
        )
    conn.commit()

    visible = visible_sections(conn)
    assert [s["kind"] for s in visible] == ["hero", "tietoa"]
    assert visible[0]["payload"] == {"title": "a"}
    assert visible[1]["payload"] == {"nostolause": "b"}


# --- site chrome (LLM-COP-10) ------------------------------------------------


def test_initials_takes_the_first_letter_of_the_first_two_words():
    assert initials("Yrityksen nimi") == "YN"
    assert initials("yksi kaksi kolme") == "YK"


def test_initials_of_a_blank_brand_is_empty_not_an_error():
    # A hero row can hold an empty brand, and the avatar must not explode.
    assert initials("") == ""
    assert initials("   ") == ""


def _seeded(conn):
    from app.seed import seed_if_empty

    seed_if_empty(conn)
    return conn


def test_site_chrome_reads_the_stored_hero_payload(conn):
    chrome = site_chrome(_seeded(conn))
    hero = dict(SEED_SECTIONS)["hero"]
    assert chrome["site_brand"] == hero["brand"]
    assert chrome["site_title"] == hero["page_title"]
    assert chrome["site_footer"] == hero["footer"]
    assert chrome["site_initials"] == initials(hero["brand"])


def test_site_chrome_still_reads_a_hidden_hero(conn):
    """The header and the browser title must not blank out because the owner
    hid the Aloitusosio, so the row is read by kind and not through
    visible_sections."""
    _seeded(conn)
    conn.execute("UPDATE sections SET state = 'hidden' WHERE kind = 'hero'")
    conn.commit()
    assert site_chrome(conn)["site_brand"] == dict(SEED_SECTIONS)["hero"]["brand"]


def test_site_chrome_of_a_store_with_no_hero_row_is_empty_not_an_error(conn):
    _seeded(conn)
    conn.execute("DELETE FROM sections WHERE kind = 'hero'")
    conn.commit()
    assert site_chrome(conn) == {
        "site_brand": "",
        "site_title": "",
        "site_footer": "",
        "site_initials": "",
    }


def test_site_chrome_reads_the_draft_column_when_asked(conn):
    _seeded(conn)
    row = conn.execute(
        "SELECT id, draft FROM sections WHERE kind = 'hero'"
    ).fetchone()
    payload = json.loads(row["draft"])
    payload["brand"] = "Luonnosnimi"
    conn.execute(
        "UPDATE sections SET draft = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), row["id"]),
    )
    conn.commit()
    assert site_chrome(conn, "draft")["site_brand"] == "Luonnosnimi"
    assert site_chrome(conn)["site_brand"] != "Luonnosnimi"
