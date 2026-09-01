"""The upgrade a REAL pre-change install takes (LLM-COP-22) — Tier A.

WHAT THE LITERALS BELOW ARE, and the one rule about them.

FROZEN_V6_ROWS and FROZEN_BADGES are a HISTORICAL ARTIFACT: the six section
rows of an install created by the UNMODIFIED app at 874c685, captured before a
line of this change existed and copied verbatim out of the captured store's
text. They are never to be regenerated from the live seed, never rebuilt by
applying the inverse of _migration_7 to a current payload, and never "fixed"
to match app/seed.py after some later change.

That is _migration_4's own rule (app/db.py: a migration that imports
app.fields or app.seed changes behaviour whenever the schema next changes)
applied to a test fixture — and this repository has already paid once for
ignoring it. tests/test_db.py's pre-migration-4 hero payload WAS derived from
the live seed, so appending hero.style to FIELDS dropped "style" into the
middle of a synthetic user_version-3 payload that could never have contained
it, and that file's key-order assertion failed. The fix was to freeze that
fixture too.

The point of freezing is that the expected value is built INDEPENDENTLY of the
code under test. test_migration_7_appends_style_to_the_frozen_hero_text builds
its expectation by string SPLICE — FROZEN_HERO_DRAFT[:-1] + ', "style": ""}' —
while the actual comes out of the migration's json.loads -> setdefault ->
json.dumps round trip. A separator, sort_keys or ensure_ascii mistake shows up
as a diff; an expectation derived the same way the code derives it would agree
with the code whatever the code did.

Provenance and units, so a later reader can check the artifact is the one
described: hero draft 808 characters / 838 UTF-8 bytes, equal to its published
text; tietoa deliberately dirty at 412 draft / 456 published characters;
palvelut 106, vastaanottoajat 186, yhteydenotto 185, sijainti 58; every
previous_published NULL — which is why the non-NULL previous_published branch
is covered in tests/test_db.py rather than here, because this fixture cannot
exercise it.

Ruff runs with no config file in this repository, so E501 is not selected and
the long literals below are clean.
"""

import json

from app import create_app
from app import db as database
from app.sanitize import validate_payload
from app.sections import badge
from app.styles import STYLE_TEMPLATES

# The six rows, verbatim: (kind, position, state, draft, published,
# previous_published).
FROZEN_V6_ROWS = (
    (
        'hero',
        1,
        'published',
        '{"kicker": "AMMATTINIMIKE · PAIKKAKUNTA · LISÄTIETO", "title": "Nimi tähän", "subtitle": "Ammattinimike · lisätieto", "ingress": "Kerro tässä lyhyesti, kenelle palvelusi on ja mitä teet. Korvaa tämä teksti omalla esittelylläsi.", "ingress_mobile": "Kerro lyhyesti, kenelle palvelusi on ja mitä teet.", "facts": [{"label": "KOULUTUS", "value": "Täydennä koulutus\\nja tutkinnot"}, {"label": "KOKEMUS", "value": "Täydennä työkokemus"}, {"label": "OSAAMINEN", "value": "Täydennä osaamisalueet"}, {"label": "ASIAKKAAT", "value": "Täydennä asiakasryhmät"}], "credentials": "Yritysmuoto · Y-tunnus · Rekisteritiedot · Suomi · English", "contact_label": "Ota yhteyttä", "services_label": "Lue palveluista", "portrait": "", "brand": "Yrityksen nimi", "page_title": "Yrityksen nimi", "footer": "© 2026 Yrityksen nimi"}',
        '{"kicker": "AMMATTINIMIKE · PAIKKAKUNTA · LISÄTIETO", "title": "Nimi tähän", "subtitle": "Ammattinimike · lisätieto", "ingress": "Kerro tässä lyhyesti, kenelle palvelusi on ja mitä teet. Korvaa tämä teksti omalla esittelylläsi.", "ingress_mobile": "Kerro lyhyesti, kenelle palvelusi on ja mitä teet.", "facts": [{"label": "KOULUTUS", "value": "Täydennä koulutus\\nja tutkinnot"}, {"label": "KOKEMUS", "value": "Täydennä työkokemus"}, {"label": "OSAAMINEN", "value": "Täydennä osaamisalueet"}, {"label": "ASIAKKAAT", "value": "Täydennä asiakasryhmät"}], "credentials": "Yritysmuoto · Y-tunnus · Rekisteritiedot · Suomi · English", "contact_label": "Ota yhteyttä", "services_label": "Lue palveluista", "portrait": "", "brand": "Yrityksen nimi", "page_title": "Yrityksen nimi", "footer": "© 2026 Yrityksen nimi"}',
        None,
    ),
    (
        'tietoa',
        2,
        'published',
        '{"nostolause": "Muokattu luonnos, ei julkaistu", "leipäteksti": "Kerro tarkemmin palveluistasi ja siitä, miten yhteistyö etenee. Korvaa tämä esimerkkiteksti omalla sisällölläsi.", "facts": [{"label": "Koulutus", "value": "Täydennä tutkintosi"}, {"label": "Kokemus", "value": "Täydennä työhistoriasi"}, {"label": "Osaaminen", "value": "Täydennä erityisosaamisesi"}, {"label": "Tapaamiset", "value": "45–90 min"}]}',
        '{"nostolause": "Kirjoita tähän lyhyt esittely: kuka olet, mitä teet ja miten työskentelet.", "leipäteksti": "Kerro tarkemmin palveluistasi ja siitä, miten yhteistyö etenee. Korvaa tämä esimerkkiteksti omalla sisällölläsi.", "facts": [{"label": "Koulutus", "value": "Täydennä tutkintosi"}, {"label": "Kokemus", "value": "Täydennä työhistoriasi"}, {"label": "Osaaminen", "value": "Täydennä erityisosaamisesi"}, {"label": "Tapaamiset", "value": "45–90 min"}]}',
        None,
    ),
    (
        'palvelut',
        3,
        'published',
        '{"services": ["Ensimmäinen palvelu", "Toinen palvelu", "Kolmas palvelu"], "more_label": "Kaikki palvelut"}',
        '{"services": ["Ensimmäinen palvelu", "Toinen palvelu", "Kolmas palvelu"], "more_label": "Kaikki palvelut"}',
        None,
    ),
    (
        'vastaanottoajat',
        4,
        'published',
        '{"days": [{"label": "Ma–To", "hours": "9.00 – 16.00"}, {"label": "Pe", "hours": "Etävastaanotto"}], "booking_note": "Verkossa ei ole varausjärjestelmää – kerro lomakkeella, mitä etsit."}',
        '{"days": [{"label": "Ma–To", "hours": "9.00 – 16.00"}, {"label": "Pe", "hours": "Etävastaanotto"}], "booking_note": "Verkossa ei ole varausjärjestelmää – kerro lomakkeella, mitä etsit."}',
        None,
    ),
    (
        'yhteydenotto',
        5,
        'published',
        '{"name_label": "Nimi", "email_label": "Sähköposti tai puhelin", "message_label": "Viesti", "send_label": "Lähetä", "thanks": "Kiitos yhteydenotosta! Palaan asiaan mahdollisimman pian."}',
        '{"name_label": "Nimi", "email_label": "Sähköposti tai puhelin", "message_label": "Viesti", "send_label": "Lähetä", "thanks": "Kiitos yhteydenotosta! Palaan asiaan mahdollisimman pian."}',
        None,
    ),
    (
        'sijainti',
        6,
        'hidden',
        '{"address": "Lisää käyntiosoite ja saapumisohjeet tähän."}',
        '{"address": "Lisää käyntiosoite ja saapumisohjeet tähän."}',
        None,
    ),
)

# The badge each row showed on that install, HARD-CODED rather than computed.
# A badge recomputed from the same rows would agree with a migration that
# flipped every one of them. tietoa is Luonnos because its draft really did
# differ from its published text; sijainti is Piilotettu because it is hidden.
FROZEN_BADGES = {
    "hero": "Julkaistu",
    "tietoa": "Luonnos",
    "palvelut": "Julkaistu",
    "vastaanottoajat": "Julkaistu",
    "yhteydenotto": "Julkaistu",
    "sijainti": "Piilotettu",
}

# The hero row's stored draft text, named once so the splice below reads as
# the arithmetic it is.
FROZEN_HERO_DRAFT = FROZEN_V6_ROWS[0][3]

# What _migration_7 must produce from it: exactly one key appended before the
# closing brace, with json.dumps' own separator. Built by SPLICE, deliberately
# not by json.loads/json.dumps — see the module docstring.
UPGRADED_HERO_DRAFT = FROZEN_HERO_DRAFT[:-1] + ', "style": ""}'

# len(', "style": ""'). Stated as a number so a changed separator fails with
# an arithmetic complaint rather than a wall of JSON.
STYLE_KEY_LENGTH = 13


def frozen_v6_store(path):
    """The frozen install rebuilt: a database stopped at user_version 6 with
    the six literal rows in it.

    MIGRATIONS[:6] and an explicit PRAGMA — the idiom tests/test_db.py uses —
    so _migration_7 really is the only thing that has not run yet.
    """
    conn = database.connect(str(path))
    for migration in database.MIGRATIONS[:6]:
        migration(conn)
    conn.execute("PRAGMA user_version = 6")
    conn.executemany(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES (?, ?, ?, ?, ?, ?)",
        FROZEN_V6_ROWS,
    )
    conn.commit()
    return conn


def rows_by_kind(conn):
    return {
        row["kind"]: row
        for row in conn.execute(
            "SELECT kind, position, state, draft, published,"
            " previous_published FROM sections"
        ).fetchall()
    }


def set_published_style(path, style):
    """Plant a style in the hero's PUBLISHED column of a store on disk."""
    conn = database.connect(str(path))
    try:
        row = conn.execute(
            "SELECT id, published FROM sections WHERE kind = 'hero'"
        ).fetchone()
        payload = json.loads(row["published"])
        payload["style"] = style
        conn.execute(
            "UPDATE sections SET published = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def test_the_frozen_artifact_is_the_install_it_claims_to_be():
    """The fixture's own provenance, asserted before anything is built on it.

    Not decoration: every test below is worth exactly as much as the claim
    that these literals are a real pre-change install. A v6 store cannot
    contain hero.style — that key is what migration 7 adds — and the tietoa
    row has to be genuinely dirty, or the badge test's Luonnos assertion would
    also hold for a migration that flipped every badge to Julkaistu.
    """
    kinds = [row[0] for row in FROZEN_V6_ROWS]
    assert kinds == [
        "hero",
        "tietoa",
        "palvelut",
        "vastaanottoajat",
        "yhteydenotto",
        "sijainti",
    ]
    assert set(kinds) == set(FROZEN_BADGES)

    hero = json.loads(FROZEN_HERO_DRAFT)
    assert "style" not in hero
    assert list(hero)[-1] == "footer"  # the chrome three were the tail then
    assert len(FROZEN_HERO_DRAFT) == 808
    assert len(FROZEN_HERO_DRAFT.encode("utf-8")) == 838

    by_kind = {row[0]: row for row in FROZEN_V6_ROWS}
    assert by_kind["hero"][3] == by_kind["hero"][4]  # clean
    assert by_kind["tietoa"][3] != by_kind["tietoa"][4]  # really dirty
    for kind, _position, state, draft, published, previous in FROZEN_V6_ROWS:
        assert previous is None, kind
        assert badge(state, draft, published) == FROZEN_BADGES[kind], kind


def test_migration_7_appends_style_to_the_frozen_hero_text_byte_for_byte(
    tmp_path,
):
    """_migration_7 ALONE, called directly, over the real stored text.

    Scoped to that one migration rather than migrate(), so a future
    _migration_8 that legitimately rewrites hero payloads cannot turn this
    into a false alarm about migration 7.

    The expected text is a SPLICE and the actual is a round trip through
    json.loads/setdefault/json.dumps. That independence is the whole test:
    ensure_ascii=True would escape the ·, sort_keys=True would reorder every
    key, a different separator would put ',"style"' on the wire — and all
    three are invisible to an expectation built the way the code builds it.
    """
    conn = frozen_v6_store(tmp_path / "frozen.sqlite3")

    database._migration_7(conn)

    hero = rows_by_kind(conn)["hero"]
    assert hero["draft"] == UPGRADED_HERO_DRAFT
    assert hero["published"] == UPGRADED_HERO_DRAFT
    assert len(hero["draft"]) == len(FROZEN_HERO_DRAFT) + STYLE_KEY_LENGTH
    # Appended LAST, which is what keeps the stored key order equal to the
    # schema's declaration order and the owner's first save a no-op.
    assert list(json.loads(hero["draft"]))[-1] == "style"
    assert json.loads(hero["draft"])["style"] == ""
    conn.close()


def test_the_frozen_v6_install_upgrades_with_every_badge_unchanged(tmp_path):
    """The headline hazard: an upgrade that marks the owner's whole site dirty.

    badge() compares the RAW STORED TEXT of draft against published
    (app/sections.py), so a migration that rewrites one column and not the
    other — or rewrites both but not identically — turns Julkaistu into
    Luonnos on deploy and invites a publish nobody asked for. Every badge is
    compared to hard-coded FROZEN_BADGES rather than to a badge recomputed
    from the migrated rows, so a migration that flipped all six cannot pass.
    """
    conn = frozen_v6_store(tmp_path / "upgrade.sqlite3")

    database.migrate(conn)

    (version,) = conn.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS) == 7
    stored = rows_by_kind(conn)
    for kind, row in stored.items():
        assert badge(row["state"], row["draft"], row["published"]) == (
            FROZEN_BADGES[kind]
        ), kind
    # And the hero really was touched — otherwise "no badge moved" would be
    # true of a migration that did nothing at all.
    assert json.loads(stored["hero"]["draft"])["style"] == ""
    conn.close()


def test_the_frozen_v6_install_leaves_every_non_hero_row_byte_untouched(
    tmp_path,
):
    """WHERE kind = 'hero' means what it says.

    The five non-hero rows are compared to their own LITERALS, not to a
    snapshot taken from the database a moment earlier: a snapshot would still
    pass if the fixture and the migration were wrong in the same direction.
    style is a hero key, so a stray backfill onto tietoa would make that
    payload fail validate_payload's unknown-key check on the next save.
    """
    conn = frozen_v6_store(tmp_path / "others.sqlite3")

    database.migrate(conn)

    stored = rows_by_kind(conn)
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        if kind == "hero":
            continue
        assert stored[kind]["draft"] == draft, kind
        assert stored[kind]["published"] == published, kind
        assert stored[kind]["previous_published"] == previous, kind
        assert "style" not in json.loads(draft), kind
    conn.close()


def test_every_stored_payload_still_round_trips_through_a_no_op_save(tmp_path):
    """After the upgrade, the owner's first save must change nothing.

    This is the hazard the whole migration exists for, asked of a real
    install: for every row and every non-NULL column, validate_payload accepts
    the stored payload with no errors AND re-serialising the cleaned result
    reproduces the stored bytes exactly. If it did not, the first save would
    rewrite the text, badge() would report Luonnos, and every section would
    ask to be published again.
    """
    conn = frozen_v6_store(tmp_path / "roundtrip.sqlite3")

    database.migrate(conn)

    checked = 0
    for kind, row in rows_by_kind(conn).items():
        for column in ("draft", "published", "previous_published"):
            text = row[column]
            if text is None:
                continue
            clean, errors = validate_payload(kind, json.loads(text))
            assert errors == {}, (kind, column, errors)
            assert json.dumps(clean, ensure_ascii=False) == text, (kind, column)
            checked += 1
    # 6 drafts + 6 published; no previous_published anywhere in the artifact,
    # asserted as a count so a silently skipped column cannot pass as green.
    assert checked == 12
    conn.close()


def test_the_upgraded_install_is_idempotent(tmp_path):
    """Migrating an already-upgraded store changes no byte.

    _migration_7 is called DIRECTLY a second time rather than migrate(), for
    the reason test_migration_5_is_idempotent_byte_for_byte gives: migrate()
    twice is a no-op by PRAGMA user_version alone, so it proves nothing about
    what the migration does to a row it has already rewritten — which is the
    branch that matters if a store is ever migrated on a newer build's data.
    """
    conn = frozen_v6_store(tmp_path / "twice.sqlite3")
    database.migrate(conn)
    before = {kind: tuple(row) for kind, row in rows_by_kind(conn).items()}
    # The first pass really did change the hero row.
    assert before["hero"][3] == UPGRADED_HERO_DRAFT

    database._migration_7(conn)

    after = {kind: tuple(row) for kind, row in rows_by_kind(conn).items()}
    assert after == before
    conn.close()


def test_the_style_value_changes_nothing_until_it_names_another_template(
    tmp_path,
):
    """The upgraded install, served by the real app, through the real route.

    Three unresolvable-or-default styles must produce BYTE-IDENTICAL public
    documents: "" is what the migration writes, "v1" is what the panel's first
    click writes, and "banana" is what an API client or a rolled-back build
    can leave behind. A stored style that could 500 the public page, or
    quietly change it, is the failure resolving-to-the-default avoids.

    "v2" is the other half, and it is the half that makes the first three mean
    anything: with a template that really is different, byte-identity is a
    property the code HAS rather than the only thing it can do. The assertion
    is the stylesheet link and a differing length — never a word of V2's
    appearance, which tests/test_page_v2.py owns.
    """
    instance = tmp_path / "instance"
    instance.mkdir()
    store = instance / "site.sqlite3"
    frozen_v6_store(store).close()

    # create_app migrates the store it opens: THIS call is the upgrade.
    app = create_app(instance_path=str(instance))
    conn = database.connect(app.config["DATABASE"])
    try:
        (version,) = conn.execute("PRAGMA user_version").fetchone()
        assert version == 7
    finally:
        conn.close()

    def serve_with(style):
        set_published_style(store, style)
        response = create_app(instance_path=str(instance)).test_client().get("/")
        assert response.status_code == 200, style
        return response.get_data(as_text=True)

    default = serve_with("")
    assert serve_with("v1") == default
    assert serve_with("banana") == default
    assert "style-v2.css" not in default

    v2 = serve_with("v2")
    assert "style-v2.css" in v2
    assert len(v2) != len(default)


def test_the_frozen_install_can_reach_every_template_the_renderer_offers(
    tmp_path,
):
    """Every value in STYLE_TEMPLATES serves 200 off a real upgraded install.

    Driven off the mapping rather than a written-down list, so a style added
    later is covered the day it is added instead of the day somebody remembers
    this file. It asks the weakest possible question — did the page come back
    at all — because that is the one a selection bug answers with a 500 or a
    TemplateNotFound.
    """
    instance = tmp_path / "instance"
    instance.mkdir()
    store = instance / "site.sqlite3"
    frozen_v6_store(store).close()
    create_app(instance_path=str(instance))

    for style in STYLE_TEMPLATES:
        set_published_style(store, style)
        app = create_app(instance_path=str(instance))
        assert app.test_client().get("/").status_code == 200, style
