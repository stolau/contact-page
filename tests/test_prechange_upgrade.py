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
from app.fields import FIELDS
from app.sanitize import validate_payload
from app.sections import badge
from app.styles import STYLE_TEMPLATES
from tests.conftest import assert_absent_from_app

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

# What _migration_8 must then produce from THAT (LLM-COP-25): portrait_alt
# appended after style, again by SPLICE rather than a round trip, for the
# same reason. This is what a full migrate() leaves in the hero's draft
# column, so it is what any test that runs migrate() must expect.
FULLY_UPGRADED_HERO_DRAFT = (
    UPGRADED_HERO_DRAFT[:-1] + ', "portrait_alt": ""}'
)

# What _migration_9 must then produce from THAT (LLM-COP-30): the V2 hero's
# own picture reference and its alt text, appended after portrait_alt, again
# by SPLICE rather than a round trip. This — not FULLY_UPGRADED_HERO_DRAFT —
# is now what a full migrate() leaves in the hero's draft column, so it is
# what any test that runs migrate() must expect.
#
# Both values are "" here, and that is a PROPERTY OF THIS FIXTURE rather than
# of the migration: the frozen hero draft carries `"portrait": ""` and
# portrait_alt arrives from the splice above as "", so migration 9 copies two
# empty strings and a constant-"" migration would write the same bytes. This
# constant therefore pins the serialiser and the key order and NOTHING about
# the copy. The copy is a separate claim and needs a row where the two
# disagree — the same blind spot test_migration_8_is_idempotent names in its
# own docstring.
MIGRATED_9_HERO_DRAFT = (
    FULLY_UPGRADED_HERO_DRAFT[:-1]
    + ', "background": "", "background_alt": ""}'
)

# What _migration_11 must then produce from THAT (USR-COP-2): the owner's two
# colours, appended after the background pair, again by SPLICE rather than a
# round trip. Migration 10 adds the login_attempts TABLE and writes no
# payload at all (app/db.py's _migration_10), so this is the fourth link of
# a four-migration chain and the fifth literal in it — and it is what a full
# migrate() now leaves in the hero's draft column.
#
# THE SAME BLIND SPOT MIGRATED_9_HERO_DRAFT NAMES, and it is worth naming
# again rather than assuming a reader carries it down the file: both defaults
# here are "" by design, so this constant pins the serialiser and the key
# order and NOTHING WHATEVER about the default VALUE. A migration that wrote
# a constant "" and one that wrote something derived-but-empty are
# indistinguishable against it. That gap is covered elsewhere, by
# tests/test_db.py's test_migration_11_leaves_a_colour_the_owner_already_chose
# — a row where the stored value and the default disagree, which no row of
# this captured artifact can be.
MIGRATED_11_HERO_DRAFT = (
    MIGRATED_9_HERO_DRAFT[:-1] + ', "color_main": "", "color_accent": ""}'
)

# The row the captured install cannot give us, and the values planted in it.
#
# A digest-shaped reference and a sentence of ordinary Finnish, neither of
# which appears anywhere in the frozen literal — so a migration that copied
# the wrong key, or copied nothing, cannot produce them by accident.
PLANTED_DIGEST = "a" * 64
PLANTED_ALT = "Kasvokuva ikkunan ääressä, rajattu olkapäistä"

# DERIVED, not captured — and deliberately NOT named FROZEN_*.
#
# The FROZEN_* literals above are a historical artifact of an install created
# by the unmodified app at 874c685, never to be regenerated. These two are
# not that: they are a SYNTHESISED row, built by a single unambiguous string
# replacement over the captured one, so that migration 9 is handed a row on
# which the copy and a constant "" DISAGREE.
#
# Why one is needed at all: the frozen hero draft carries `"portrait": ""`
# and portrait_alt arrives from the splice above as "", so against that row
# `payload.setdefault("background", payload.get("portrait", ""))` and
# `payload.setdefault("background", "")` write BYTE-IDENTICAL text.
# MIGRATED_9_HERO_DRAFT therefore pins the serialiser and the key order and
# nothing whatever about the copy — and the copy is the whole design decision
# (a constant "" would blank the hero photograph of every deployed V2 site on
# the day this ships). This pair is the only thing in the suite that tells
# the two migrations apart.
#
# The discipline the module exists to hold is still held: the expectation is
# a pure string transform of a LITERAL, never a round trip through the code
# under test, so a separator / sort_keys / ensure_ascii mistake still shows
# up as a diff. What is NOT claimed is that any real install ever held these
# bytes — no install did, which is why the FROZEN_ prefix would be a lie. If
# the frozen literal ever legitimately grows, this may be re-derived from it;
# the frozen literal may not.
#
# `"portrait": ""` cannot collide with `"portrait_alt": ""` — a different
# character follows `portrait` in each — so the transform is unambiguous, and
# the test below asserts that rather than trusting this sentence.
HERO_DRAFT_WITH_A_PLANTED_PICTURE = FULLY_UPGRADED_HERO_DRAFT.replace(
    '"portrait": ""', f'"portrait": "{PLANTED_DIGEST}"'
).replace('"portrait_alt": ""', f'"portrait_alt": "{PLANTED_ALT}"')

MIGRATED_9_HERO_DRAFT_WITH_A_PLANTED_PICTURE = (
    HERO_DRAFT_WITH_A_PLANTED_PICTURE[:-1]
    + f', "background": "{PLANTED_DIGEST}", "background_alt": "{PLANTED_ALT}"}}'
)

# len(', "style": ""'). Stated as a number so a changed separator fails with
# an arithmetic complaint rather than a wall of JSON.
STYLE_KEY_LENGTH = 13

# What _migration_8 appends to each kind's stored text, written as the exact
# SUFFIX the text grows — separators, spacing, order and unescaped Ä included.
#
# These are the module's discipline applied to the second migration: the
# expectation is a string, spliced in front of the frozen row's closing brace,
# while the actual comes out of the migration's json.loads -> setdefault ->
# json.dumps round trip. ensure_ascii=True would turn Ä into Ä here,
# sort_keys=True would move section_label out of last place, and a changed
# separator would write ',"section_label"' — every one of them shows up as a
# diff, and none of them would be visible to an expectation built the way the
# code builds it.
#
# The VALUES are the other half of the claim: each section label is the
# literal the template used to own, because a default of "" would blank five
# kickers on every existing site the moment it deployed. The contact four and
# portrait_alt are "" because they rendered nothing before the upgrade, and
# backfilling the seed's instructive copy would make a live published page
# suddenly read "Lisää puhelinnumero".
MIGRATION_8_SUFFIXES = {
    "hero": ', "portrait_alt": ""}',
    "tietoa": ', "section_label": "NÄIN TYÖSKENTELEN"}',
    "palvelut": ', "section_label": "PALVELUT"}',
    "vastaanottoajat": ', "section_label": "VASTAANOTTOAJAT"}',
    "yhteydenotto": (
        ', "section_label": "YHTEYDENOTTO", "phone": "", "email": "",'
        ' "body": "", "caveat": ""}'
    ),
    "sijainti": ', "section_label": "SIJAINTI"}',
}

# The five kickers this migration turns from template literals into stored
# data. Named once, here, so the two tests below cannot disagree about them.
SECTION_LABELS = {
    "tietoa": "NÄIN TYÖSKENTELEN",
    "palvelut": "PALVELUT",
    "vastaanottoajat": "VASTAANOTTOAJAT",
    "yhteydenotto": "YHTEYDENOTTO",
    "sijainti": "SIJAINTI",
}

# The yhteydenotto row's stored draft text, named once so the splices below
# read as the arithmetic they are. FROZEN_V6_ROWS[4] is that row and [3] is
# its draft column; the two are asserted rather than trusted, in
# test_migration_12_rewrites_the_frozen_yhteydenotto_text_byte_for_byte.
FROZEN_YHTEYDENOTTO_DRAFT = FROZEN_V6_ROWS[4][3]

# What _migration_8 leaves in that column: the frozen text with its own
# five-key suffix spliced in front of the closing brace. The [:-1] is not
# cosmetic — MIGRATION_8_SUFFIXES["yhteydenotto"] already ENDS in `}`, so
# concatenating without it yields `..."caveat": ""}}` and json.loads raises.
# This is the module's own idiom (`draft[:-1] + suffix`), spelled out once
# here rather than inline in four tests.
YHTEYDENOTTO_AFTER_8 = (
    FROZEN_YHTEYDENOTTO_DRAFT[:-1] + MIGRATION_8_SUFFIXES["yhteydenotto"]
)

# What _migration_12 must then produce from THAT (USR-COP-4): the send_label
# renamed away from the old default, and the two notice keys appended after
# caveat. Built by SPLICE and REPLACE over the frozen literal, deliberately
# not by a json.loads/json.dumps round trip — see the module docstring.
# ensure_ascii=True would turn the ä of "Ota yhteyttä" into ä,
# sort_keys=True would move notice_on out of last place, and a changed
# separator would write ',"notice_text"'; every one of them is a diff here
# and none of them is visible to an expectation built the way the code
# builds it.
#
# WHAT THIS LITERAL PINS, and what it does NOT — stated because the two
# halves of migration 12 differ here, which is the first time in this file
# that has been true.
#
# The RENAME half is genuinely exercised, and it is the ONLY link of this
# chain that is. MIGRATED_9_HERO_DRAFT and MIGRATED_11_HERO_DRAFT each name
# their own blind spot: their defaults are "" and the frozen row's values
# are "" too, so a constant-writing migration and the real one produce
# identical bytes against them. Not here. This row's stored send_label is
# the OLD DEFAULT "Lähetä" and the expected text says "Ota yhteyttä", so
# these bytes can only be produced by a migration that actually renamed it —
# and a migration that renamed the wrong rows, or renamed unconditionally,
# is caught elsewhere rather than here.
#
# The BACKFILL half has exactly the blind spot its predecessors have: both
# notice defaults are "", so this literal pins the serialiser and the key
# order and NOTHING WHATEVER about the default VALUE. That gap is covered in
# tests/test_db.py, on a store whose previous_published is non-NULL and whose
# send_label is the owner's own — neither of which any row of this captured
# artifact can be.
MIGRATED_12_YHTEYDENOTTO = (
    YHTEYDENOTTO_AFTER_8.replace(
        '"send_label": "Lähetä"', '"send_label": "Ota yhteyttä"'
    )[:-1]
    + ', "notice_text": "", "notice_on": ""}'
)

# DERIVED, not captured — and deliberately NOT named FROZEN_*, for the reason
# HERO_DRAFT_WITH_A_PLANTED_PICTURE states above.
#
# "Varaa aika soittamalla" is an OWNER's own words: it appears nowhere in
# app/ (asserted in the test below rather than claimed here), so migration 12
# has no default that could produce it and no equality guard that could match
# it. The frozen row cannot ask this question — its send_label IS the old
# default, which is exactly what makes it good for the rename test and
# useless for this one.
OWNERS_SEND_LABEL = "Varaa aika soittamalla"

YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL = YHTEYDENOTTO_AFTER_8.replace(
    '"send_label": "Lähetä"', f'"send_label": "{OWNERS_SEND_LABEL}"'
)

MIGRATED_12_YHTEYDENOTTO_WITH_AN_OWNERS_LABEL = (
    YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL[:-1]
    + ', "notice_text": "", "notice_on": ""}'
)


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


def test_migration_10_leaves_the_frozen_install_byte_for_byte_unchanged(
    tmp_path,
):
    """LLM-COP-37's migration adds a table and NOTHING else — proved, not said.

    The house standard for a migration here is a frozen-literal splice: the
    expectation is built by string arithmetic over the captured install so a
    separator, a sort_keys or an ensure_ascii mistake in the migration's own
    serialiser shows up as a diff. Migration 10 has nothing to splice — it
    reads no sections row, writes no payload and touches no
    draft/published/previous_published text — so minting a new
    MIGRATED_10_* constant would be a ritual that proves nothing: it would be
    MIGRATED_9_HERO_DRAFT with a different name.

    What has to be proved instead is that the whole stored install comes
    through THIS migration byte-for-byte, and that is what this asserts:
    against the same frozen user_version = 6 capture the rest of the file
    uses, with expectations spliced from the FROZEN LITERALS (never
    round-tripped through the migration's own serialiser) and every badge
    compared to hard-coded FROZEN_BADGES rather than to a badge recomputed
    from the migrated rows — a recomputed badge would agree with a migration
    that flipped all six.

    _migration_7 through _migration_10 are called DIRECTLY rather than
    through migrate(), the idiom every other per-migration test in this file
    uses, and since USR-COP-2's migration 11 that is load-bearing: migrate()
    would run 11 too, and the text this compares against would then be the
    text migration 11 leaves rather than the text migration 10 was handed.
    The head's own version stamp is pinned once, by
    test_the_frozen_v6_install_upgrades_with_every_badge_unchanged below.

    The last two assertions are the anti-vacuity guard. "Nothing changed" is
    also true of a migration that did nothing at all, so the new table has to
    be shown to exist — and to be EMPTY, because a migration that seeded a
    login lockout onto an upgrading install would lock the owner out of their
    own site on deploy.
    """
    conn = frozen_v6_store(tmp_path / "ten.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)
    database._migration_10(conn)

    stored = rows_by_kind(conn)
    # The hero, through the whole frozen -> +style -> +portrait_alt ->
    # +background splice chain, and no further: migration 10 must leave the
    # same literal migration 9 left.
    assert stored["hero"]["draft"] == MIGRATED_9_HERO_DRAFT
    assert stored["hero"]["published"] == MIGRATED_9_HERO_DRAFT
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        assert stored[kind]["previous_published"] == previous, kind
        if kind == "hero":
            continue
        suffix = MIGRATION_8_SUFFIXES[kind]
        assert stored[kind]["draft"] == draft[:-1] + suffix, kind
        assert stored[kind]["published"] == published[:-1] + suffix, kind
    for kind, row in stored.items():
        assert badge(row["state"], row["draft"], row["published"]) == (
            FROZEN_BADGES[kind]
        ), kind

    (count,) = conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()
    assert count == 0
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
    assert version == len(database.MIGRATIONS) == 12
    stored = rows_by_kind(conn)
    for kind, row in stored.items():
        assert badge(row["state"], row["draft"], row["published"]) == (
            FROZEN_BADGES[kind]
        ), kind
    # And the hero really was touched — otherwise "no badge moved" would be
    # true of a migration that did nothing at all.
    assert json.loads(stored["hero"]["draft"])["style"] == ""
    # Since LLM-COP-25 the same has to be said of a non-hero kind: migration 8
    # is the first migration here that reaches past one kind, so "no badge
    # moved" would otherwise be true of one that left all five of them alone.
    assert json.loads(stored["sijainti"]["draft"])["section_label"] == (
        "SIJAINTI"
    )
    # And again for LLM-COP-30's migration 9, the newest link: without this
    # line "no badge moved" would be true of a migration that skipped the
    # hero entirely. "" is what the copy produces HERE only because this
    # row's portrait is "" — see MIGRATED_9_HERO_DRAFT's note.
    assert json.loads(stored["hero"]["draft"])["background"] == ""
    # And once more for USR-COP-2's migration 11, the newest link, for the
    # same reason each of the lines above exists: without it "no badge moved"
    # would be true of a chain that stopped at migration 9.
    assert json.loads(stored["hero"]["draft"])["color_main"] == ""
    # And once more for USR-COP-4's migration 12, the newest link. This one
    # is the strongest of the five, because unlike every line above it the
    # frozen row's value is NOT already what the migration writes: this
    # store's send_label is the old default "Lähetä" (FROZEN_V6_ROWS), so
    # reading "Ota yhteyttä" here can only mean migration 12 ran and renamed
    # it. It is also what makes the badge comparison above load-bearing for
    # this migration: FROZEN_V6_ROWS' yhteydenotto row has draft ==
    # published, so a migration 12 that rewrote draft alone would leave them
    # unequal and turn FROZEN_BADGES["yhteydenotto"] == "Julkaistu" into
    # "Luonnos".
    assert json.loads(stored["yhteydenotto"]["draft"])["send_label"] == (
        "Ota yhteyttä"
    )
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

    _migration_7 ALONE, called directly, since LLM-COP-25 — exactly the
    scoping test_migration_7_appends_style_to_the_frozen_hero_text_byte_for_byte
    already uses and for the reason it states. _migration_8 is the first
    migration in this codebase that touches more than one kind, and it
    LEGITIMATELY backfills all five of these rows, so migrate() here would
    turn a true claim about migration 7 into a false alarm. Re-baselining the
    expected text against migration 8's output instead would leave the suite
    green and delete the stray-backfill guard permanently; that is the wrong
    fix and it is written down here so nobody takes it later.
    """
    conn = frozen_v6_store(tmp_path / "others.sqlite3")

    database._migration_7(conn)

    stored = rows_by_kind(conn)
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        if kind == "hero":
            continue
        assert stored[kind]["draft"] == draft, kind
        assert stored[kind]["published"] == published, kind
        assert stored[kind]["previous_published"] == previous, kind
        assert "style" not in json.loads(draft), kind
    conn.close()


def test_migration_8_appends_its_keys_to_every_frozen_row_byte_for_byte(
    tmp_path,
):
    """_migration_8 ALONE, over the real stored text of all six rows.

    The sibling of test_migration_7_appends_style..., and scoped the same
    way — but where that one asks about one kind, this one asks about six,
    because _migration_8 is the first migration in this codebase that reaches
    past a single WHERE kind = '...'. Every expectation is a SPLICE of the
    frozen literal (MIGRATION_8_SUFFIXES above), never a round trip through
    the json.dumps the migration itself calls.

    Run after _migration_7 rather than instead of it, because that is the
    order a real install upgrades in and the hero's expectation is a splice
    ON TOP of migration 7's own spliced result: FROZEN -> +style ->
    +portrait_alt, three literals, none of them produced by the code under
    test.
    """
    conn = frozen_v6_store(tmp_path / "eight.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)

    stored = rows_by_kind(conn)
    assert stored["hero"]["draft"] == FULLY_UPGRADED_HERO_DRAFT
    assert stored["hero"]["published"] == FULLY_UPGRADED_HERO_DRAFT
    for kind, _position, _state, draft, published, _previous in FROZEN_V6_ROWS:
        if kind == "hero":
            continue  # its pre-text is migration 7's output, spliced above
        suffix = MIGRATION_8_SUFFIXES[kind]
        assert stored[kind]["draft"] == draft[:-1] + suffix, kind
        assert stored[kind]["published"] == published[:-1] + suffix, kind

    # Appended LAST for every kind, which is what keeps the stored key order
    # equal to the schema's declaration order and the owner's first save a
    # no-op. This one expectation IS read from the live schema on purpose:
    # it is a different claim from the byte splices above — not "these are
    # the bytes" but "the bytes agree with what app/fields.py declares".
    #
    # The hero is read FOUR KEYS SHORT of the schema's tail, and deliberately
    # (LLM-COP-30, then USR-COP-2). This test stops at migration 8 on purpose;
    # migration 9 appended background/background_alt after portrait_alt and
    # migration 11 appended color_main/color_accent after those, so the
    # schema's tail is now four keys this test's store has not been given yet.
    # Trimming rather than spelling "portrait_alt" keeps the expectation
    # derived: the trim is itself asserted, so reordering FIELDS still fails
    # here.
    #
    # yhteydenotto is now read TWO KEYS SHORT for the same reason, and it is
    # the second kind to need a trim rather than the first to be special:
    # USR-COP-4's migration 12 appended notice_text and notice_on, so the
    # schema's yhteydenotto tail is two keys past what migration 8 leaves in
    # this store. Same idiom, same asserted trim.
    for kind, row in stored.items():
        declared = list(FIELDS[kind])
        if kind == "hero":
            assert declared[-4:] == [
                "background",
                "background_alt",
                "color_main",
                "color_accent",
            ]
            declared = declared[:-4]
        if kind == "yhteydenotto":
            assert declared[-2:] == ["notice_text", "notice_on"]
            declared = declared[:-2]
        assert list(json.loads(row["draft"]))[-1] == declared[-1], kind
        assert list(json.loads(row["draft"])) == declared, kind

    # tietoa's two columns differed before the upgrade (the artifact is
    # deliberately dirty there) and must still differ afterwards, by exactly
    # the same suffix on each — a migration that collapsed them would turn
    # that row's Luonnos into Julkaistu.
    assert stored["tietoa"]["draft"] != stored["tietoa"]["published"]
    assert len(stored["tietoa"]["draft"]) - len(FROZEN_V6_ROWS[1][3]) == (
        len(stored["tietoa"]["published"]) - len(FROZEN_V6_ROWS[1][4])
    )
    conn.close()


def test_migration_8_is_idempotent(tmp_path):
    """_migration_8 called DIRECTLY a second time moves not one byte.

    Directly, not migrate() twice: migrate() twice is a no-op by PRAGMA
    user_version alone, so it says nothing about what this migration does to
    a row it has already rewritten — the branch that matters when a store is
    migrated on a newer build's data.

    The last block is what byte-stability alone cannot show. On a row whose
    section_label still holds the migration's own default, an ASSIGNMENT
    writes the same bytes as a setdefault, so the two are indistinguishable.
    Plant a label the owner has actually chosen and re-run: setdefault leaves
    it, an assignment silently reverts the owner's rename on the next upgrade.
    """
    conn = frozen_v6_store(tmp_path / "twice8.sqlite3")
    database.migrate(conn)
    first = {kind: tuple(row) for kind, row in rows_by_kind(conn).items()}
    # The first pass really did change a non-hero row — otherwise a second
    # pass matching it would be true of a migration that does nothing at all.
    assert json.loads(first["palvelut"][3])["section_label"] == "PALVELUT"

    database._migration_8(conn)

    assert {kind: tuple(row) for kind, row in rows_by_kind(conn).items()} == first

    renamed = dict(json.loads(first["palvelut"][3]), section_label="Mitä teen")
    conn.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'palvelut'",
        (json.dumps(renamed, ensure_ascii=False),),
    )
    conn.commit()

    database._migration_8(conn)

    assert json.loads(rows_by_kind(conn)["palvelut"]["draft"])[
        "section_label"
    ] == "Mitä teen"
    conn.close()


def test_migration_9_appends_the_background_keys_byte_for_byte(tmp_path):
    """_migration_7, _8 and _9 called DIRECTLY, in the order a real install
    upgrades in, over the real stored text.

    The third link of the same splice chain, scoped the same way its two
    predecessors are: the expectation is FROZEN -> +style -> +portrait_alt ->
    +background/background_alt, four literals, none of them produced by the
    code under test. ensure_ascii=True would escape the · in this row's
    kicker, sort_keys=True would move every key, a changed separator would
    write ',"background"', and a mid-list insert would move the tail — each
    of them is a diff here and none of them is visible to an expectation
    built the way json.dumps builds it.

    WHAT THIS TEST DOES NOT PROVE, stated because the omission is the point:
    it says nothing about the COPY. This row's portrait is "" and its
    portrait_alt is "" (the splice's), so a migration that backfilled a
    constant "" writes exactly these bytes and passes. That claim needs a row
    where the two disagree, and it has its own test below.
    """
    conn = frozen_v6_store(tmp_path / "nine.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)

    hero = rows_by_kind(conn)["hero"]
    assert hero["draft"] == MIGRATED_9_HERO_DRAFT
    assert hero["published"] == MIGRATED_9_HERO_DRAFT
    # Appended LAST, as a PAIR and in declaration order — which is what keeps
    # the stored key order equal to the schema's and the owner's first save a
    # no-op. Read off the parsed payload rather than the text, so it is a
    # claim about the keys and not a second spelling of the splice.
    assert list(json.loads(hero["draft"]))[-2:] == [
        "background",
        "background_alt",
    ]
    # TWO KEYS SHORT of the schema's tail, and deliberately: this test stops
    # at migration 9, and USR-COP-2's migration 11 appended two more after it.
    # The trim is itself asserted, so reordering FIELDS still fails here —
    # the idiom test_migration_8_appends_its_keys_to_every_frozen_row_byte_for_byte
    # already uses for the same reason.
    declared = list(FIELDS["hero"])
    assert declared[-2:] == ["color_main", "color_accent"]
    assert list(json.loads(hero["draft"])) == declared[:-2]
    # draft and published moved together, so no badge can have flipped.
    assert hero["draft"] == hero["published"]
    conn.close()


def test_migration_9_leaves_every_non_hero_row_byte_untouched(tmp_path):
    """WHERE kind = 'hero' means what it says, asked of migration 9.

    A SIBLING of test_the_frozen_v6_install_leaves_every_non_hero_row_byte_untouched
    rather than an extension of it, and deliberately: that test calls
    _migration_7 alone, and its docstring says in as many words that
    re-baselining it against a later migration's output is the wrong fix.
    Extending it to run 8 and 9 would be exactly that. So the guard is made
    once per migration, each against the text its own predecessors leave.

    The five expectations are SPLICES of the frozen literals — the same
    MIGRATION_8_SUFFIXES the migration-8 test uses — never a snapshot taken
    from the database a moment earlier: a snapshot would still pass if the
    fixture and the migration were wrong in the same direction.

    What a failure here would mean in production: background is a hero key,
    so a stray backfill onto tietoa makes that payload fail
    validate_payload's unknown-key check on that owner's very next save.
    """
    conn = frozen_v6_store(tmp_path / "nine_others.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)

    stored = rows_by_kind(conn)
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        if kind == "hero":
            continue
        suffix = MIGRATION_8_SUFFIXES[kind]
        assert stored[kind]["draft"] == draft[:-1] + suffix, kind
        assert stored[kind]["published"] == published[:-1] + suffix, kind
        assert stored[kind]["previous_published"] == previous, kind
        assert "background" not in json.loads(stored[kind]["draft"]), kind
        assert "background_alt" not in json.loads(stored[kind]["draft"]), kind
    # The hero really was reached in this same call — otherwise "the other
    # five are untouched" would be true of a migration that did nothing.
    assert stored["hero"]["draft"] == MIGRATED_9_HERO_DRAFT
    conn.close()


def test_migration_11_appends_its_two_keys_to_the_frozen_hero_text_byte_for_byte(
    tmp_path,
):
    """_migration_7, _8, _9, _10 and _11 called DIRECTLY, in the order a
    real install upgrades in, over the real stored text.

    The fourth link of the same splice chain, scoped the same way its three
    predecessors are: the expectation is FROZEN -> +style -> +portrait_alt ->
    +background/background_alt -> +color_main/color_accent, five literals,
    none of them produced by the code under test. ensure_ascii=True would
    escape the · in this row's kicker, sort_keys=True would move every key, a
    changed separator would write ',"color_main"', and a mid-list insert
    would move the tail — each is a diff here and none of them is visible to
    an expectation built the way json.dumps builds it.

    _migration_10 is called with the rest even though it writes no payload —
    it creates the login_attempts table and nothing more (app/db.py) —
    because "the order a real install upgrades in" is the claim, and a chain
    that quietly skipped a slot would stop being that.

    WHAT THIS TEST DOES NOT PROVE, stated because the omission is the point:
    it says nothing about the DEFAULT VALUE. Both keys default to "", so a
    migration that wrote any other empty-string-producing expression writes
    exactly these bytes and passes. What it would catch is the value being
    non-empty, which is the failure that matters — a colour on a site whose
    owner picked none.
    """
    conn = frozen_v6_store(tmp_path / "eleven.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)
    database._migration_10(conn)
    database._migration_11(conn)

    hero = rows_by_kind(conn)["hero"]
    assert hero["draft"] == MIGRATED_11_HERO_DRAFT
    assert hero["published"] == MIGRATED_11_HERO_DRAFT
    # Appended LAST, as a PAIR and in declaration order — which is what keeps
    # the stored key order equal to the schema's and the owner's first save a
    # no-op. Read off the parsed payload rather than the text, so it is a
    # claim about the keys and not a second spelling of the splice.
    assert list(json.loads(hero["draft"]))[-2:] == [
        "color_main",
        "color_accent",
    ]
    assert list(json.loads(hero["draft"])) == list(FIELDS["hero"])
    # draft and published moved together, so no badge can have flipped.
    assert hero["draft"] == hero["published"]
    conn.close()


def test_migration_11_leaves_every_non_hero_row_byte_untouched(tmp_path):
    """WHERE kind = 'hero' means what it says, asked of migration 11.

    A SIBLING of the migration-7 and migration-9 tests above rather than an
    extension of either, for the reason migration 9's docstring gives: the
    guard is made once per migration, each against the text its own
    predecessors leave, because re-baselining an earlier test against a later
    migration's output deletes that earlier guard permanently.

    What a failure here would mean in production: color_main is a hero key,
    so a stray backfill onto tietoa makes that payload fail
    validate_payload's unknown-key check on that owner's very next save.
    """
    conn = frozen_v6_store(tmp_path / "eleven_others.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)
    database._migration_10(conn)
    database._migration_11(conn)

    stored = rows_by_kind(conn)
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        if kind == "hero":
            continue
        suffix = MIGRATION_8_SUFFIXES[kind]
        assert stored[kind]["draft"] == draft[:-1] + suffix, kind
        assert stored[kind]["published"] == published[:-1] + suffix, kind
        assert stored[kind]["previous_published"] == previous, kind
        assert "color_main" not in json.loads(stored[kind]["draft"]), kind
        assert "color_accent" not in json.loads(stored[kind]["draft"]), kind
    # The hero really was reached in this same call — otherwise "the other
    # five are untouched" would be true of a migration that did nothing.
    assert stored["hero"]["draft"] == MIGRATED_11_HERO_DRAFT
    conn.close()


def test_migration_12_rewrites_the_frozen_yhteydenotto_text_byte_for_byte(
    tmp_path,
):
    """_migration_7 through _12 called DIRECTLY, in the order a real install
    upgrades in, over the real stored text.

    The fifth link of the same chain, scoped the way its four predecessors
    are: the expectation is FROZEN -> +migration 8's five keys -> renamed
    send_label + the notice pair, three literals, none of them produced by
    the code under test. _migration_9, _10 and _11 are called with the rest
    even though none of them touches a yhteydenotto row — 9 and 11 are
    WHERE kind = 'hero' and 10 writes no payload at all — because "the order
    a real install upgrades in" is the claim, and a chain that quietly
    skipped a slot would stop being that. Their non-effect on this row is
    itself part of what the byte comparison says.

    WHAT IS DIFFERENT ABOUT THIS LINK, and it is the reason it is worth
    more than the four above it: every earlier splice pinned a default of ""
    onto a row whose value was already "", so it could not tell the real
    migration from one that wrote a constant. This row's send_label is the
    OLD DEFAULT "Lähetä" and the expected text says "Ota yhteyttä", so these
    bytes are unreachable without the rename. The backfill half still has
    the old blind spot — both notice defaults are "" — and
    MIGRATED_12_YHTEYDENOTTO's comment says so and says where it is closed.

    The provenance of the splice is asserted, not trusted: FROZEN_V6_ROWS[4]
    really is the yhteydenotto row, [3] really is its draft column, and the
    replaced substring really occurs exactly once — the discipline
    HERO_DRAFT_WITH_A_PLANTED_PICTURE states and
    test_migration_9_copies_the_stored_portrait_rather_than_blanking_it
    already applies. A second occurrence would make str.replace rewrite
    something this test never looked at.
    """
    assert FROZEN_V6_ROWS[4][0] == "yhteydenotto"
    assert FROZEN_YHTEYDENOTTO_DRAFT == FROZEN_V6_ROWS[4][3]
    assert FROZEN_YHTEYDENOTTO_DRAFT == FROZEN_V6_ROWS[4][4]  # clean row
    assert YHTEYDENOTTO_AFTER_8.count('"send_label": "Lähetä"') == 1
    assert MIGRATED_12_YHTEYDENOTTO.count('"send_label": "Ota yhteyttä"') == 1
    assert '"send_label": "Lähetä"' not in MIGRATED_12_YHTEYDENOTTO

    conn = frozen_v6_store(tmp_path / "twelve.sqlite3")

    database._migration_7(conn)
    database._migration_8(conn)
    database._migration_9(conn)
    database._migration_10(conn)
    database._migration_11(conn)
    database._migration_12(conn)

    row = rows_by_kind(conn)["yhteydenotto"]
    assert row["draft"] == MIGRATED_12_YHTEYDENOTTO
    assert row["published"] == MIGRATED_12_YHTEYDENOTTO
    # Appended LAST, as a PAIR and in declaration order — which is what keeps
    # the stored key order equal to the schema's and the owner's first save a
    # no-op. Read off the parsed payload rather than the text, so it is a
    # claim about the keys and not a second spelling of the splice.
    payload = json.loads(row["draft"])
    assert list(payload)[-2:] == ["notice_text", "notice_on"]
    assert list(payload) == list(FIELDS["yhteydenotto"])
    # The rename did not MOVE the key it rewrote: assignment to an existing
    # key leaves it where it was, and a pop-then-set would put send_label
    # last instead. Said in terms of the position, so a failure names the
    # reordering rather than a 400-character diff.
    assert list(payload).index("send_label") == 3
    assert payload["send_label"] == "Ota yhteyttä"
    # draft and published moved together, so no badge can have flipped.
    assert row["draft"] == row["published"]
    assert row["previous_published"] is None  # NULL stays NULL
    conn.close()


def test_migration_12_leaves_a_send_label_the_owner_already_wrote(tmp_path):
    """THE SAFE-RENAME RULE, and the only test in this file that can see it.

    The whole safety of migration 12 is that it renames ONLY where the stored
    value still equals the old default exactly. An owner who typed their own
    words on the button — "Varaa aika soittamalla" — keeps them; a substring
    match, a case-insensitive one, or an unconditional assignment would take
    those words away on the day the upgrade ships, silently, on a live
    published page.

    Every other migration-12 assertion in this file is BLIND to that. The
    captured install's send_label IS the old default, so against it a guarded
    rename and an unguarded one write byte-identical text. This plants a row
    where they disagree — the same blind spot
    test_migration_9_copies_the_stored_portrait_rather_than_blanking_it
    closes for the copy, closed here for the guard.

    The planted row is a DERIVED literal, not a captured one, and
    HERO_DRAFT_WITH_A_PLANTED_PICTURE's comment says why that is still sound:
    the expectation is a pure string transform of a frozen literal, never a
    round trip through the code under test.

    assert_absent_from_app is what makes the claim falsifiable rather than
    decorative: if the owner's words appeared anywhere under app/ the
    migration might have a default that produced them, and "it was left
    alone" would be indistinguishable from "it was written".
    """
    assert_absent_from_app(OWNERS_SEND_LABEL)
    # The transform's unambiguity, asserted rather than argued.
    assert YHTEYDENOTTO_AFTER_8.count('"send_label": "Lähetä"') == 1
    assert (
        YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL.count(OWNERS_SEND_LABEL) == 1
    )
    assert '"Lähetä"' not in YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL
    assert list(json.loads(YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL)) == list(
        json.loads(YHTEYDENOTTO_AFTER_8)
    )

    conn = frozen_v6_store(tmp_path / "owners.sqlite3")
    database._migration_7(conn)
    database._migration_8(conn)
    # The precondition, asserted rather than assumed: the store really is at
    # migration 8's output, so the planted text below differs from what is
    # there by exactly the one value and nothing else.
    assert rows_by_kind(conn)["yhteydenotto"]["draft"] == YHTEYDENOTTO_AFTER_8
    conn.execute(
        "UPDATE sections SET draft = ?, published = ?"
        " WHERE kind = 'yhteydenotto'",
        (
            YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL,
            YHTEYDENOTTO_DRAFT_WITH_AN_OWNERS_LABEL,
        ),
    )
    conn.commit()

    database._migration_12(conn)

    row = rows_by_kind(conn)["yhteydenotto"]
    assert row["draft"] == MIGRATED_12_YHTEYDENOTTO_WITH_AN_OWNERS_LABEL
    assert row["published"] == MIGRATED_12_YHTEYDENOTTO_WITH_AN_OWNERS_LABEL
    # Said again in terms of the value, so the failure names the decision
    # rather than a 400-character diff.
    upgraded = json.loads(row["draft"])
    assert upgraded["send_label"] == OWNERS_SEND_LABEL, (
        "migration 12 overwrote the label the owner wrote instead of leaving"
        " it"
    )
    # ...and the OTHER half of the migration still ran on this very row:
    # "left alone" must mean the rename was skipped, not that the row was.
    # Without these two lines a migration that skipped every row whose label
    # it did not recognise would pass, and that owner's next save would 400
    # on the two missing keys.
    assert upgraded["notice_text"] == ""
    assert upgraded["notice_on"] == ""
    assert list(upgraded) == list(FIELDS["yhteydenotto"])
    assert row["draft"] == row["published"]
    conn.close()


def test_migration_12_leaves_every_non_yhteydenotto_row_byte_untouched(
    tmp_path,
):
    """WHERE kind = 'yhteydenotto' means what it says, asked of migration 12.

    A SIBLING of the migration-7, -9 and -11 guards above rather than an
    extension of any of them, for the reason migration 9's docstring gives:
    the guard is made once per migration, each against the text its own
    predecessors leave, because re-baselining an earlier test against a later
    migration's output deletes that earlier guard permanently.

    _migration_12 is called ALONE here, on the raw v6 capture, and that is a
    stronger scoping than the three above use rather than a looser one: the
    five other rows are compared to their OWN FROZEN LITERALS, with no
    predecessor's suffix spliced on, so the claim is that this migration by
    itself moved not one byte of them. A snapshot taken from the database a
    moment earlier would still pass if the fixture and the migration were
    wrong in the same direction; a frozen literal cannot.

    What a failure here would mean in production: notice_text is a
    yhteydenotto key, so a stray backfill onto tietoa makes that payload fail
    validate_payload's unknown-key check on that owner's very next save — and
    a stray RENAME would be worse, because send_label exists on no other kind
    at all and the row would gain a key from nowhere.
    """
    conn = frozen_v6_store(tmp_path / "twelve_others.sqlite3")

    database._migration_12(conn)

    stored = rows_by_kind(conn)
    for kind, _position, _state, draft, published, previous in FROZEN_V6_ROWS:
        if kind == "yhteydenotto":
            continue
        assert stored[kind]["draft"] == draft, kind
        assert stored[kind]["published"] == published, kind
        assert stored[kind]["previous_published"] == previous, kind
        assert "notice_text" not in json.loads(stored[kind]["draft"]), kind
        assert "notice_on" not in json.loads(stored[kind]["draft"]), kind
        assert "send_label" not in json.loads(stored[kind]["draft"]), kind
    # The yhteydenotto row really was reached in this same call — otherwise
    # "the other five are untouched" would be true of a migration that did
    # nothing. The expected text is the v6 literal plus this migration's own
    # work and NOT migration 8's suffix, because migration 8 has not run: a
    # splice of the frozen row, spelled out here rather than reusing
    # MIGRATED_12_YHTEYDENOTTO, which is the wrong era for this store.
    assert stored["yhteydenotto"]["draft"] == (
        FROZEN_YHTEYDENOTTO_DRAFT.replace(
            '"send_label": "Lähetä"', '"send_label": "Ota yhteyttä"'
        )[:-1]
        + ', "notice_text": "", "notice_on": ""}'
    )
    conn.close()


def test_migration_12_is_idempotent(tmp_path):
    """_migration_12 called DIRECTLY a second time moves not one byte.

    Directly, not migrate() twice: migrate() twice is a no-op by PRAGMA
    user_version alone, so it says nothing about what this migration does to
    a row it has already rewritten — the branch that matters when a store is
    migrated on a newer build's data.

    The last block is what byte-stability alone cannot show, and it is
    test_migration_8_is_idempotent's and test_migration_9_is_idempotent's
    lesson applied to the newest keys. On a row whose notice_text already
    holds whatever the migration itself would write — "" — an ASSIGNMENT
    produces the same bytes as a setdefault and the two are
    indistinguishable. So plant a notice the OWNER wrote, switched ON, which
    is the entire point of USR-COP-4, and re-run: setdefault leaves it, an
    assignment silently blanks the owner's own line on the next upgrade,
    which is precisely the loss "switched off without losing its text" exists
    to prevent.

    The owner's send_label is planted in the same pass, so this asks the
    rename guard the same question the backfill is asked: the guard must be
    an EQUALITY test against the old default that this row does not match,
    not a rewrite that runs on every row it sees.
    """
    conn = frozen_v6_store(tmp_path / "twice12.sqlite3")
    database.migrate(conn)
    first = {kind: tuple(row) for kind, row in rows_by_kind(conn).items()}
    # The first pass really did reach the yhteydenotto row — otherwise a
    # second pass matching it would be true of a migration that does nothing
    # at all. migrate() runs the whole chain, so the expectation is the last
    # splice for this kind.
    assert first["yhteydenotto"][3] == MIGRATED_12_YHTEYDENOTTO

    database._migration_12(conn)

    assert {kind: tuple(row) for kind, row in rows_by_kind(conn).items()} == first

    owners = dict(
        json.loads(first["yhteydenotto"][3]),
        send_label=OWNERS_SEND_LABEL,
        notice_text="Valitettavasti tällä hetkellä ei ole aikoja",
        notice_on="on",
    )
    conn.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'yhteydenotto'",
        (json.dumps(owners, ensure_ascii=False),),
    )
    conn.commit()

    database._migration_12(conn)

    survived = json.loads(rows_by_kind(conn)["yhteydenotto"]["draft"])
    assert survived["send_label"] == OWNERS_SEND_LABEL
    assert survived["notice_text"] == (
        "Valitettavasti tällä hetkellä ei ole aikoja"
    )
    assert survived["notice_on"] == "on"
    conn.close()


def test_migration_9_copies_the_stored_portrait_rather_than_blanking_it(
    tmp_path,
):
    """THE DESIGN DECISION, and the only test in the suite that can see it.

    A V2 install rendered its full-bleed hero photograph FROM hero.portrait,
    so the value that reproduces the page it rendered a moment before the
    upgrade is the row's OWN portrait — not "". Backfilling a constant would
    blank the hero photograph of every deployed V2 site on the day this
    ships, which is the same class of harm _migration_8's "" would have been
    for the five section labels.

    Every other migration-9 assertion in this suite is BLIND to that. The
    captured install's hero carries `"portrait": ""`, so on it a copying
    migration and a constant-"" migration write byte-identical text; the
    byte-for-byte test above passes against both. This one plants a row where
    they disagree — the same blind spot test_migration_8_is_idempotent names
    in its own docstring, closed rather than merely described.

    The planted row is a DERIVED literal, not a captured one, and
    HERO_DRAFT_WITH_A_PLANTED_PICTURE's comment says why that is still sound.
    The transform's unambiguity is asserted here rather than argued: the two
    replacements each matched exactly once, and `"portrait": ""` did not eat
    `"portrait_alt": ""`.
    """
    # The fixture's own provenance, before anything is built on it.
    assert FULLY_UPGRADED_HERO_DRAFT.count('"portrait": ""') == 1
    assert FULLY_UPGRADED_HERO_DRAFT.count('"portrait_alt": ""') == 1
    assert HERO_DRAFT_WITH_A_PLANTED_PICTURE.count(PLANTED_DIGEST) == 1
    assert HERO_DRAFT_WITH_A_PLANTED_PICTURE.count(PLANTED_ALT) == 1
    planted = json.loads(HERO_DRAFT_WITH_A_PLANTED_PICTURE)
    assert planted["portrait"] == PLANTED_DIGEST
    assert planted["portrait_alt"] == PLANTED_ALT
    assert list(planted) == list(json.loads(FULLY_UPGRADED_HERO_DRAFT))

    conn = frozen_v6_store(tmp_path / "copy.sqlite3")
    database._migration_7(conn)
    database._migration_8(conn)
    # The precondition, asserted rather than assumed: the store really is at
    # migration 8's output, so the planted text below differs from what is
    # there by exactly the two values and nothing else.
    assert rows_by_kind(conn)["hero"]["draft"] == FULLY_UPGRADED_HERO_DRAFT
    conn.execute(
        "UPDATE sections SET draft = ?, published = ? WHERE kind = 'hero'",
        (
            HERO_DRAFT_WITH_A_PLANTED_PICTURE,
            HERO_DRAFT_WITH_A_PLANTED_PICTURE,
        ),
    )
    conn.commit()

    database._migration_9(conn)

    hero = rows_by_kind(conn)["hero"]
    assert hero["draft"] == MIGRATED_9_HERO_DRAFT_WITH_A_PLANTED_PICTURE
    assert hero["published"] == MIGRATED_9_HERO_DRAFT_WITH_A_PLANTED_PICTURE
    # Said again in terms of the values, so the failure message names the
    # decision rather than a 900-character diff.
    upgraded = json.loads(hero["draft"])
    assert upgraded["background"] == PLANTED_DIGEST, (
        "migration 9 blanked the hero photograph instead of copying it"
    )
    assert upgraded["background_alt"] == PLANTED_ALT
    assert upgraded["portrait"] == PLANTED_DIGEST  # the person is untouched
    assert upgraded["portrait_alt"] == PLANTED_ALT
    # And the copy did not disturb the order the byte test pins. Two keys
    # short of the schema's tail for the same reason the byte test is: this
    # chain stops at migration 9, and migration 11 appended two more.
    declared = list(FIELDS["hero"])
    assert declared[-2:] == ["color_main", "color_accent"]
    assert list(upgraded) == declared[:-2]
    assert hero["draft"] == hero["published"]
    conn.close()


def test_migration_9_is_idempotent(tmp_path):
    """_migration_9 called DIRECTLY a second time moves not one byte.

    Directly, not migrate() twice: migrate() twice is a no-op by PRAGMA
    user_version alone, so it says nothing about what this migration does to
    a row it has already rewritten — the branch that matters when a store is
    migrated on a newer build's data.

    The last block is what byte-stability alone cannot show, and it is
    test_migration_8_is_idempotent's lesson applied to the newest key. On a
    row whose background still holds whatever the migration itself would
    write, an ASSIGNMENT produces the same bytes as a setdefault and the two
    are indistinguishable. So plant a background the OWNER chose — a second
    picture, genuinely different from the portrait, which is the entire point
    of LLM-COP-30 — and re-run: setdefault leaves it, an assignment silently
    reverts the owner's second picture to a copy of their first on the next
    upgrade, which is this artifact's own defect reinstated by the migration.
    """
    conn = frozen_v6_store(tmp_path / "twice9.sqlite3")
    database.migrate(conn)
    first = {kind: tuple(row) for kind, row in rows_by_kind(conn).items()}
    # The first pass really did reach the hero — otherwise a second pass
    # matching it would be true of a migration that does nothing at all.
    # migrate() runs the whole chain, so the expectation is the LAST splice
    # (USR-COP-2's), not migration 9's own.
    assert first["hero"][3] == MIGRATED_11_HERO_DRAFT

    database._migration_9(conn)

    assert {kind: tuple(row) for kind, row in rows_by_kind(conn).items()} == first

    chosen = dict(
        json.loads(first["hero"][3]),
        portrait=PLANTED_DIGEST,
        background="b" * 64,
        background_alt="Vastaanottohuone aamuvalossa",
    )
    assert chosen["background"] != chosen["portrait"]
    conn.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'hero'",
        (json.dumps(chosen, ensure_ascii=False),),
    )
    conn.commit()

    database._migration_9(conn)

    survived = json.loads(rows_by_kind(conn)["hero"]["draft"])
    assert survived["background"] == "b" * 64
    assert survived["background_alt"] == "Vastaanottohuone aamuvalossa"
    assert survived["portrait"] == PLANTED_DIGEST
    conn.close()


def test_the_upgraded_install_still_renders_the_section_labels(tmp_path):
    """The claim an existing owner cares about: the upgrade does not blank
    their kickers.

    Everything above is about bytes in a column. This is the same install
    served through the real route by the real app, asking whether the words
    that were on the owner's page a moment before the upgrade are still on it
    afterwards. A migration that backfilled "" would pass every byte and
    badge test in this file by writing a consistent empty string into both
    columns, and would take five headings off every deployed site.

    FOUR labels off the page, not five. The captured install has sijainti
    HIDDEN (FROZEN_BADGES says Piilotettu), so its band is not on the public
    page at all — yet its stored payload must still have gained the key, or
    showing that section again would 400 on the owner's next save. So four
    are read off the served document and the fifth out of the store.

    WHAT THIS TEST DOES NOT PROVE, said plainly rather than implied: it does
    not show the words came from the store. A build that still carried the
    five template literals would render the same four strings and pass here.
    That is a different claim and it has its own test —
    tests/test_page.py:test_section_labels_are_data_the_owner_can_change,
    which rewrites all five to strings that appear nowhere in app/. The two
    together are what "renameable, and the upgrade did not blank them" means;
    neither is sufficient alone.
    """
    instance = tmp_path / "instance"
    instance.mkdir()
    frozen_v6_store(instance / "site.sqlite3").close()

    # create_app migrates the store it opens: THIS call is the upgrade.
    app = create_app(instance_path=str(instance))
    response = app.test_client().get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    for kind, label in SECTION_LABELS.items():
        if kind == "sijainti":
            continue
        assert label in html, kind

    conn = database.connect(app.config["DATABASE"])
    try:
        stored = rows_by_kind(conn)
    finally:
        conn.close()
    assert stored["sijainti"]["state"] == "hidden"
    assert json.loads(stored["sijainti"]["published"])["section_label"] == (
        "SIJAINTI"
    )
    # ...and, being hidden, its label is genuinely off the page: the upgrade
    # backfilled a hidden row without un-hiding it.
    assert "SIJAINTI" not in html


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
    # The first pass really did change the hero row. Kept, not dropped, when
    # LLM-COP-25 moved the expected text on: this line is what stops the whole
    # idempotence claim below from passing vacuously over rows nothing ever
    # touched. migrate() now runs migrations 7 AND 8, so the expectation is
    # the second splice rather than the first. LLM-COP-30 moved it on again
    # for the same reason: migrate() now runs 7, 8 AND 9, so the expectation
    # is the third splice. USR-COP-2 moved it on a third time, and the reason
    # has not changed: migrate() now runs 11 as well, so the expectation is
    # the fourth splice.
    assert before["hero"][3] == MIGRATED_11_HERO_DRAFT

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
        # The premise, not the claim: this test is about what the STYLE
        # value does, and it only needs the store to have been carried all
        # the way to the head. Written as len(MIGRATIONS) rather than a
        # literal, the house form for a premise — the head itself is pinned
        # as a literal in exactly one place, test_db.py's
        # test_the_migration_head_is_twelve. It was a literal 11 here, which
        # made this test go red for USR-COP-4's migration 12 without having
        # anything to say about it.
        assert version == len(database.MIGRATIONS)
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
