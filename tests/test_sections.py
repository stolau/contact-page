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
    # A DICT EQUALITY on purpose, and it stays one: it names site_chrome's
    # WHOLE return value, so the next chrome key must extend it deliberately
    # — the same guard tests/test_seed.py's tail assertion is for
    # FIELDS["hero"]. It is also the only test pinning the missing-hero
    # branch of site_style: "" rather than absent, which is what keeps
    # template_for(chrome["site_style"]) from a KeyError.
    assert site_chrome(conn) == {
        "site_brand": "",
        "site_title": "",
        "site_footer": "",
        "site_initials": "",
        "site_style": "",
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


# --- the site-wide style (LLM-COP-22) ---------------------------------------


def _set_hero_style(conn, style, column="published"):
    row = conn.execute(
        "SELECT id, draft, published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    payload = json.loads(row[column])
    payload["style"] = style
    conn.execute(
        f"UPDATE sections SET {column} = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), row["id"]),
    )
    conn.commit()


def test_site_chrome_reports_the_stored_style(conn):
    """The RAW stored value, passed through untouched.

    "banana" rather than "v2" on purpose: site_chrome must not resolve, filter
    or validate the style — app/styles.py does that at the render call, and
    the panel needs the raw value to tell "" (nothing chosen) apart from a
    style it does not offer. A site_chrome that resolved would mark Perus
    active on a fresh install and make the owner's first click invisible.
    """
    _seeded(conn)
    assert site_chrome(conn)["site_style"] == ""  # seeded: nothing chosen

    _set_hero_style(conn, "banana")
    assert site_chrome(conn)["site_style"] == "banana"


def test_site_chrome_reads_the_style_from_the_requested_column(conn):
    """Draft and published are separate answers, which is the whole reason the
    style needs no route plumbing: the preview asks for "draft" and the public
    page asks for "published", and the same function serves both."""
    _seeded(conn)
    _set_hero_style(conn, "v2", "draft")

    assert site_chrome(conn, "draft")["site_style"] == "v2"
    assert site_chrome(conn)["site_style"] == ""


def test_site_chrome_returns_only_flat_scalars(conn):
    """Every value is a str, and site_style is not special.

    app/sections.py says the chrome is flat on purpose — the public templates
    bind these names directly and app/__init__.py splats them into the render
    context, so a nested dict would arrive as an unusable name in a template
    nobody would notice was broken until the page rendered it. This is the
    guard for the NEXT key, not this one.
    """
    _seeded(conn)
    _set_hero_style(conn, "v2")
    chrome = site_chrome(conn)

    assert chrome  # not vacuously true over an empty dict
    for name, value in chrome.items():
        assert isinstance(value, str), (name, type(value).__name__)
