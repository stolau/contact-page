"""Plan step 4 — app/sections.py: the badge mapping and visible_sections."""

import json

from app.sections import badge, visible_sections


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
