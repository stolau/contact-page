"""Plan step 2 — app/db.py: connection + PRAGMA user_version migrations."""

import copy
import json
import re
import sqlite3

from app import db as database
from app.fields import FIELDS
from app.sanitize import validate_payload
from app.sections import badge
from app.seed import SEED_SECTIONS
from tests.conftest import PERSONA_PATTERN, assert_absent_from_app


def _schema_dump(c):
    return c.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()


def test_migrate_creates_sections_and_stamps_user_version(tmp_path):
    c = database.connect(str(tmp_path / "fresh.sqlite3"))
    database.migrate(c)
    columns = {
        row["name"] for row in c.execute("PRAGMA table_info(sections)")
    }
    assert columns == {
        "id",
        "kind",
        "position",
        "state",
        "draft",
        "published",
        "previous_published",
    }
    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS)
    c.close()


def test_migration_2_creates_the_auth_tables(tmp_path):
    c = database.connect(str(tmp_path / "auth.sqlite3"))
    database.migrate(c)
    (version,) = c.execute("PRAGMA user_version").fetchone()
    # >= 2, not == 2: migrate() stamps len(MIGRATIONS), so pinning the exact
    # number here breaks on every migration added after this one. No coverage
    # is lost — the version-independent form (version == len(MIGRATIONS)) is
    # asserted in test_migrate_creates_sections_and_stamps_user_version, and
    # the exact stamp for migration 3 is asserted in tests/test_messages.py.
    # This test's real content is the three auth-table column checks below.
    assert version >= 2

    def columns(table):
        return {row["name"] for row in c.execute(f"PRAGMA table_info({table})")}

    # Exact equality, and it stays exact: this is the one place the auth
    # table's shape is pinned, so migration 13's three second-factor columns
    # are NAMED here rather than the assertion being loosened to a subset.
    assert columns("admin_user") == {
        "id",
        "username",
        "password_hash",
        "totp_secret",
        "totp_enabled",
        "totp_last_step",
    }
    assert columns("sessions") == {
        "id",
        "token_hash",
        "created_at",
        "last_seen_at",
        "remember",
        "expires_at",
    }
    assert columns("audit_log") == {"id", "at", "event"}
    c.close()


def test_migrate_second_run_is_a_noop(tmp_path):
    c = database.connect(str(tmp_path / "twice.sqlite3"))
    database.migrate(c)
    (version_before,) = c.execute("PRAGMA user_version").fetchone()
    schema_before = _schema_dump(c)

    # If the no-op path re-ran migration 1, CREATE TABLE would raise here.
    database.migrate(c)

    (version_after,) = c.execute("PRAGMA user_version").fetchone()
    assert version_after == version_before
    assert _schema_dump(c) == schema_before
    c.close()


# --- migration 4: site chrome backfilled onto existing hero rows -------------
#
# LLM-COP-10 moved brand, page_title and footer out of the templates onto the
# hero payload. Existing stored payloads have none of those keys, so without a
# backfill validate_payload's required-key check rejects the owner's first
# save. These cases pin the three things that can go wrong: the keys must land
# LAST (or the first no-op save reorders the JSON and every badge flips to
# Luonnos), they must land in previous_published too (or a restore poisons the
# next save), and re-running migrate() must change nothing.


def _v3_database(path, hero_payload, previous=None):
    """A database at exactly user_version 3, with one hero row — i.e. a store
    written by the code as it stood before this artifact."""
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:3]:
        migration(c)
    c.execute("PRAGMA user_version = 3")
    text = json.dumps(hero_payload, ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('hero', 1, 'published', ?, ?, ?)",
        (text, text, previous),
    )
    c.commit()
    return c


def _v3_hero_payload():
    """A hero payload as a user_version-3 store actually held one: the ten
    keys of that era, in that era's order.

    A FROZEN LITERAL, never derived from the live seed. It was derived once,
    and LLM-COP-22 is the proof of what that costs: appending hero.style to
    FIELDS put "style" into the middle of this synthetic pre-migration-4
    payload — a key a v3 store could not possibly have contained — and the
    key-order assertion below failed. This is _migration_4's own rule
    (app/db.py: no migration reads the live schema) applied to the test that
    exercises it. Extend it only if a store really did hold another key at
    v3; a key added to FIELDS today belongs nowhere in here.
    """
    return {
        "kicker": "AMMATTINIMIKE · PAIKKAKUNTA · LISÄTIETO",
        "title": "Nimi tähän",
        "subtitle": "Ammattinimike · lisätieto",
        # ingress and ingress_mobile are RICH: plain text with no markup, or
        # sanitize_rich rewrites it and the round-trip assertion below fails.
        "ingress": (
            "Kerro tässä lyhyesti, kenelle palvelusi on ja mitä teet. "
            "Korvaa tämä teksti omalla esittelylläsi."
        ),
        "ingress_mobile": "Kerro lyhyesti, kenelle palvelusi on ja mitä teet.",
        # Items are exactly {label, value} in that key order: _validate_item
        # rebuilds them in declared order, so any other order round-trips to
        # different bytes.
        "facts": [
            {"label": "KOULUTUS", "value": "Täydennä koulutus\nja tutkinnot"},
            {"label": "KOKEMUS", "value": "Täydennä työkokemus"},
            {"label": "OSAAMINEN", "value": "Täydennä osaamisalueet"},
            {"label": "ASIAKKAAT", "value": "Täydennä asiakasryhmät"},
        ],
        "credentials": (
            "Yritysmuoto · Y-tunnus · Rekisteritiedot · Suomi · English"
        ),
        "contact_label": "Ota yhteyttä",
        "services_label": "Lue palveluista",
        "portrait": "",
    }


def test_migration_4_backfills_chrome_without_flipping_any_badge(tmp_path):
    c = _v3_database(tmp_path / "old.sqlite3", _v3_hero_payload())
    database.migrate(c)

    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS)

    row = c.execute(
        "SELECT state, draft, published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    draft = json.loads(row["draft"])
    for key in ("brand", "page_title", "footer"):
        assert key in draft
        assert key in json.loads(row["published"])

    # Key ORDER is the whole hazard: stored order must still equal the schema's
    # declaration order, or the first save rewrites the row.
    assert list(draft) == list(FIELDS["hero"])
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"

    # The row the migration produced is exactly what a no-op save would store.
    clean, errors = validate_payload("hero", draft)
    assert errors == {}
    assert json.dumps(clean, ensure_ascii=False) == row["draft"]
    c.close()


def test_migration_4_backfills_previous_published_so_restore_can_save(tmp_path):
    old = _v3_hero_payload()
    old["title"] = "Vanha otsikko"
    c = _v3_database(
        tmp_path / "prev.sqlite3",
        _v3_hero_payload(),
        previous=json.dumps(old, ensure_ascii=False),
    )
    database.migrate(c)

    previous = json.loads(
        c.execute(
            "SELECT previous_published FROM sections WHERE kind = 'hero'"
        ).fetchone()["previous_published"]
    )
    # The owner's own stored content is untouched...
    assert previous["title"] == "Vanha otsikko"
    # ...but the new keys are there, so restoring it and saving cannot 400.
    for key in ("brand", "page_title", "footer"):
        assert key in previous
    assert validate_payload("hero", previous)[1] == {}
    c.close()


def test_migration_4_survives_a_hero_row_with_no_published_text(tmp_path):
    c = _v3_database(tmp_path / "null.sqlite3", _v3_hero_payload())
    c.execute("UPDATE sections SET published = NULL WHERE kind = 'hero'")
    c.commit()

    database.migrate(c)

    row = c.execute(
        "SELECT draft, published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    assert row["published"] is None
    assert "brand" in json.loads(row["draft"])
    c.close()


def test_migration_4_is_idempotent_byte_for_byte(tmp_path):
    c = _v3_database(tmp_path / "twice.sqlite3", _v3_hero_payload())
    database.migrate(c)
    before = c.execute(
        "SELECT draft, published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    before = (before["draft"], before["published"])

    database.migrate(c)

    after = c.execute(
        "SELECT draft, published FROM sections WHERE kind = 'hero'"
    ).fetchone()
    assert (after["draft"], after["published"]) == before
    c.close()


def test_migration_4_does_not_plant_an_identity_string(tmp_path):
    """The backfill defaults are neutral placeholders, never the old template
    literals. Backfilling those would re-plant the persona in every existing
    store and hard-code an identity string into app/db.py."""
    c = _v3_database(tmp_path / "neutral.sqlite3", _v3_hero_payload())
    database.migrate(c)
    blob = "".join(
        str(value)
        for row in c.execute("SELECT draft, published FROM sections")
        for value in tuple(row)
        if value
    )
    assert re.search(PERSONA_PATTERN, blob, re.IGNORECASE) is None
    c.close()


# --- migration 5: tietoa.facts becomes a list of {label, value} pairs --------
#
# LLM-COP-20 gave every tietoa fact its own label, so a caption is owner data
# rather than a positional guess. Existing stores hold bare strings, and
# validate_payload's item check rejects them the moment the owner saves — so
# the rows have to be wrapped in place, in all three payload columns.
#
# The hazard these cases exist for is badge(): it compares the RAW STORED TEXT
# of draft and published (app/sections.py:15), so a rewrite that touches one
# column and not the other flips every tietoa row to Luonnos on deploy. Both
# arms are pinned below — a clean row must stay Julkaistu, and a dirty row
# must stay Luonnos. The empty backfilled label is pinned too: a positional
# default is precisely the lie LLM-COP-5 refused to ship.


def _v4_database(path, tietoa_payload, previous=None):
    """A database at exactly user_version 4, with one tietoa row — i.e. a
    store written by the code as it stood before this artifact.

    MIGRATIONS[:4] rather than migrate(), so the stamp really is 4 and
    migration 5 is the only thing under test. Migration 4 runs over an empty
    table here and does nothing; the row is inserted after it.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:4]:
        migration(c)
    c.execute("PRAGMA user_version = 4")
    text = json.dumps(tietoa_payload, ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('tietoa', 2, 'published', ?, ?, ?)",
        (text, text, previous),
    )
    c.commit()
    return c


def _tietoa_with_string_facts():
    """The seeded tietoa payload with its facts flattened back to the bare
    positional strings the code stored before this artifact."""
    payload = copy.deepcopy(dict(SEED_SECTIONS)["tietoa"])
    payload["facts"] = [fact["value"] for fact in payload["facts"]]
    return payload


def _tietoa_row(c):
    return c.execute(
        "SELECT state, draft, published, previous_published FROM sections"
        " WHERE kind = 'tietoa'"
    ).fetchone()


def test_migration_5_wraps_tietoa_facts_without_flipping_any_badge(tmp_path):
    old = _tietoa_with_string_facts()
    c = _v4_database(tmp_path / "old.sqlite3", old)
    database.migrate(c)

    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS)

    row = _tietoa_row(c)
    draft = json.loads(row["draft"])
    # Every stored string is now the VALUE of a pair, byte-equal, in order.
    assert draft["facts"] == [
        {"label": "", "value": value} for value in old["facts"]
    ]
    assert json.loads(row["published"])["facts"] == draft["facts"]

    # Key ORDER is the whole hazard: assigning to the existing "facts" key
    # keeps its position, so the stored order still equals declaration order.
    assert list(draft) == list(FIELDS["tietoa"])
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"

    # The row the migration produced is exactly what a no-op save would store.
    clean, errors = validate_payload("tietoa", draft)
    assert errors == {}
    assert json.dumps(clean, ensure_ascii=False) == row["draft"]
    c.close()


def test_migration_5_leaves_a_dirty_row_on_luonnos(tmp_path):
    """The other arm of the badge hazard, which the migration-4 suite does not
    cover: a row whose draft already differs from its published text must not
    become Julkaistu. It could only do so if the migration's rewrite collapsed
    two distinct stored texts into one."""
    c = _v4_database(tmp_path / "dirty.sqlite3", _tietoa_with_string_facts())
    dirty = _tietoa_with_string_facts()
    dirty["nostolause"] = "Kesken oleva luonnos, ei vielä julkaistu."
    c.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'tietoa'",
        (json.dumps(dirty, ensure_ascii=False),),
    )
    c.commit()
    before = _tietoa_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == \
        "Luonnos"

    database.migrate(c)

    row = _tietoa_row(c)
    assert row["draft"] != row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Luonnos"
    # …and the dirty draft was migrated too, not skipped for being dirty.
    draft = json.loads(row["draft"])
    assert draft["nostolause"] == "Kesken oleva luonnos, ei vielä julkaistu."
    assert draft["facts"][0] == {"label": "", "value": dirty["facts"][0]}
    c.close()


def test_migration_5_backfills_previous_published_so_restore_can_save(tmp_path):
    old = _tietoa_with_string_facts()
    old["nostolause"] = "Vanha nostolause"
    c = _v4_database(
        tmp_path / "prev.sqlite3",
        _tietoa_with_string_facts(),
        previous=json.dumps(old, ensure_ascii=False),
    )
    database.migrate(c)

    previous = json.loads(_tietoa_row(c)["previous_published"])
    # The owner's own stored content is untouched...
    assert previous["nostolause"] == "Vanha nostolause"
    # ...but the facts are reshaped, so restoring it and saving cannot 400.
    assert previous["facts"] == [
        {"label": "", "value": value} for value in old["facts"]
    ]
    assert validate_payload("tietoa", previous)[1] == {}
    c.close()


def test_migration_5_survives_a_tietoa_row_with_no_published_text(tmp_path):
    c = _v4_database(tmp_path / "null.sqlite3", _tietoa_with_string_facts())
    c.execute("UPDATE sections SET published = NULL WHERE kind = 'tietoa'")
    c.commit()

    database.migrate(c)

    row = _tietoa_row(c)
    assert row["published"] is None
    assert row["previous_published"] is None
    assert json.loads(row["draft"])["facts"][0] == {
        "label": "", "value": _tietoa_with_string_facts()["facts"][0]
    }
    c.close()


def test_migration_5_is_idempotent_byte_for_byte(tmp_path):
    """_migration_5 is called DIRECTLY, twice, rather than migrate() twice.

    migrate() twice is a no-op by PRAGMA user_version alone (app/db.py), so
    running it again proves nothing about what the migration does to a row it
    has already reshaped — which is exactly the branch that has to be
    byte-stable if a store ever migrates on a newer build's data.
    test_migration_4_is_idempotent_byte_for_byte is weaker for that reason.
    """
    old = _tietoa_with_string_facts()
    c = _v4_database(
        tmp_path / "twice.sqlite3",
        old,
        previous=json.dumps(old, ensure_ascii=False),
    )
    database._migration_5(c)
    first = tuple(_tietoa_row(c))
    # The first pass really did change the row — otherwise the second pass
    # matching it would be true of a migration that does nothing at all.
    assert json.loads(first[1])["facts"][0] == {
        "label": "", "value": old["facts"][0]
    }

    database._migration_5(c)

    assert tuple(_tietoa_row(c)) == first
    c.close()


def test_migration_5_labels_nothing_it_cannot_know(tmp_path):
    """The LLM-COP-5 record in migration form. The migration knows what
    POSITION an entry had and nothing about what it MEANS, so every backfilled
    label is the empty string. This goes red the moment somebody "improves"
    the default into a positional guess — which on the author's own store
    would print "Koulutus" over "Käynnit 45–90 min"."""
    old = _tietoa_with_string_facts()
    c = _v4_database(
        tmp_path / "blank.sqlite3",
        old,
        previous=json.dumps(old, ensure_ascii=False),
    )
    database.migrate(c)

    row = _tietoa_row(c)
    for column in ("draft", "published", "previous_published"):
        facts = json.loads(row[column])["facts"]
        assert facts, column
        assert [fact["label"] for fact in facts] == [""] * len(facts), column
    c.close()


def test_migration_5_leaves_a_row_that_is_already_reshaped_byte_identical(
    tmp_path
):
    """A store written by a build that already has the new shape — or one
    migrated once before — comes out byte-for-byte unchanged, labels and all.

    The second half is what makes the already-reshaped branch worth having
    rather than folding into the leave-it-alone fallthrough: it rebuilds the
    item as {key: item[key] for key in shape}, so the migration's output is in
    declared key order whatever order the input was in. Without it the two
    branches are indistinguishable, and the property that a migrated row is
    byte-identical to what a no-op save through validate_payload would store
    (app/sanitize.py, _validate_item) holds only by luck of the input.

    _migration_5 ALONE, called directly, since LLM-COP-25 — the byte-identity
    claim here is about migration 5's already-reshaped branch, and migrate()
    now also runs migration 8, which legitimately appends section_label to
    tietoa. It happens to stay green under migrate() today only because this
    fixture is built from the live SEED_SECTIONS, which already carries that
    key, so the setdefault is a no-op on it; that is an accident of the
    fixture, not a property of migration 5. Splicing section_label onto
    `before` instead would be the cheaper fix and would leave the test
    asserting nothing about migration 5's branch at all.
    """
    payload = copy.deepcopy(dict(SEED_SECTIONS)["tietoa"])
    c = _v4_database(
        tmp_path / "already.sqlite3",
        payload,
        previous=json.dumps(payload, ensure_ascii=False),
    )
    before = tuple(_tietoa_row(c))

    database._migration_5(c)

    assert tuple(_tietoa_row(c)) == before
    # And the owner's labels survived, rather than being blanked by the
    # string branch's backfill.
    assert json.loads(_tietoa_row(c)["draft"])["facts"] == payload["facts"]
    c.close()

    reversed_keys = copy.deepcopy(dict(SEED_SECTIONS)["tietoa"])
    reversed_keys["facts"] = [
        {"value": fact["value"], "label": fact["label"]}
        for fact in reversed_keys["facts"]
    ]
    c = _v4_database(tmp_path / "reversed.sqlite3", reversed_keys)
    database._migration_5(c)

    row = _tietoa_row(c)
    facts = json.loads(row["draft"])["facts"]
    assert [tuple(fact) for fact in facts] == [("label", "value")] * len(facts)
    assert facts == payload["facts"]
    clean, errors = validate_payload("tietoa", json.loads(row["draft"]))
    assert errors == {}
    assert json.dumps(clean, ensure_ascii=False) == row["draft"]
    c.close()


def test_migration_5_leaves_an_unwritable_item_alone_and_does_not_hide_it(
    tmp_path
):
    """The migration's third branch, stated and tested rather than left as an
    undefended fallthrough.

    An item no writer in this repository can produce is left ALONE: coercing
    it would mean inventing owner text, which is the defect this artifact
    exists to remove, and raising would take the whole site down inside
    create_app over one bad row. The condition is neither created nor
    laundered — validate_payload rejects the payload before the migration and
    still rejects it after, so the section reads as unsavable in the editor
    either way.
    """
    payload = _tietoa_with_string_facts()
    payload["facts"] = [payload["facts"][0], 123]
    assert "facts" in validate_payload("tietoa", payload)[1]

    c = _v4_database(tmp_path / "unwritable.sqlite3", payload)
    database.migrate(c)

    row = _tietoa_row(c)
    facts = json.loads(row["draft"])["facts"]
    # The string beside it was still reshaped; the bad item is untouched, and
    # no invented string stands in its place.
    assert facts == [{"label": "", "value": payload["facts"][0]}, 123]
    assert facts == json.loads(row["published"])["facts"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"
    assert "facts" in validate_payload(
        "tietoa", json.loads(row["draft"])
    )[1]
    c.close()


# --- migration 7: the site-wide style backfilled onto hero rows -------------
#
# LLM-COP-22 made the site's style stored data: hero.style names which public
# template renders the page (app/styles.py). Existing hero payloads have no
# such key, so without a backfill validate_payload's required-key check
# rejects the owner's first save — migration 4's hazard, exactly.
#
# The cases below pin what can go wrong, and they are the migration-4 set plus
# one. The key must land LAST (or the first no-op save reorders the stored
# JSON and every hero badge flips to Luonnos); it must land in
# previous_published too (or a restore poisons the next save); a NULL column
# must be skipped rather than crashed on; and re-running must change nothing.
#
# The extra case is the DIRTY row: migration 4's suite never asserts that a
# row whose draft already differs from its published text stays Luonnos, and
# a rewrite that collapsed two distinct texts into one would pass everything
# else here. migration 5's suite added that arm for the same reason.
#
# tests/test_prechange_upgrade.py asks the same questions of a real captured
# install with six rows in it; these ask them of the branches that install
# cannot reach — a NULL published column, and a non-NULL previous_published.


def _v6_database(path, hero_payload, previous=None, state="published"):
    """A database at exactly user_version 6 with one hero row — a store
    written by the code as it stood before this artifact.

    MIGRATIONS[:6] rather than migrate(), so the stamp really is 6 and
    migration 7 is the only thing left to run. Migrations 4 and 5 run over an
    empty table here and do nothing; the row is inserted after them.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:6]:
        migration(c)
    c.execute("PRAGMA user_version = 6")
    text = json.dumps(hero_payload, ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('hero', 1, ?, ?, ?, ?)",
        (state, text, text, previous),
    )
    c.commit()
    return c


def _v6_hero_payload():
    """A hero payload as a user_version-6 store actually held one: the
    thirteen keys of that era, in that era's order — the ten of the v3 era
    plus LLM-COP-10's chrome three, and no style.

    A FROZEN LITERAL for the reason _v3_hero_payload() states above, which
    this artifact is the live proof of. It is built from _v3_hero_payload()
    only because that one is itself frozen; the three keys appended here are
    written out rather than read from FIELDS or the seed.
    """
    payload = _v3_hero_payload()
    payload["brand"] = "Yrityksen nimi"
    payload["page_title"] = "Yrityksen nimi"
    payload["footer"] = "© 2026 Yrityksen nimi"
    return payload


def _hero_row(c):
    return c.execute(
        "SELECT state, draft, published, previous_published FROM sections"
        " WHERE kind = 'hero'"
    ).fetchone()


def test_migration_7_backfills_style_without_flipping_any_badge(tmp_path):
    c = _v6_database(tmp_path / "style.sqlite3", _v6_hero_payload())
    before = _hero_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == \
        "Julkaistu"

    database.migrate(c)

    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == len(database.MIGRATIONS)

    row = _hero_row(c)
    draft = json.loads(row["draft"])
    assert draft["style"] == ""
    assert json.loads(row["published"])["style"] == ""

    # Key ORDER is the whole hazard, and the claim is that each backfilled key
    # lands where FIELDS declares it, so a setdefault that appended anywhere
    # else would rewrite this row on the first save. style was the tail when
    # migration 7 shipped; LLM-COP-25's migration 8 — which migrate() runs
    # here too — appended portrait_alt after it, so the TAIL moved to the
    # newest key while the rule ("appended, never inserted") did not change.
    # LLM-COP-30's migration 9 is the third link in that same chain: it
    # appended background and background_alt after portrait_alt, so the tail
    # moved once more and the rule again did not.
    #
    # USR-COP-2's migration 11 is the fourth link, and it arrived exactly as
    # this comment predicted: two more keys on the tail, the rule unchanged
    # again. (Migration 10 creates the login_attempts table and appends
    # nothing to any payload — see app/db.py's _migration_10.)
    #
    # Named as the WHOLE tail rather than by index, so the claim survives the
    # fifth link without an index chase: style is still there, portrait_alt
    # is still there, and nothing was inserted between any of them.
    assert list(draft)[-6:] == [
        "style",
        "portrait_alt",
        "background",
        "background_alt",
        "color_main",
        "color_accent",
    ]
    assert list(draft) == list(FIELDS["hero"])
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"

    # The row the migration produced is exactly what a no-op save would store.
    clean, errors = validate_payload("hero", draft)
    assert errors == {}
    assert json.dumps(clean, ensure_ascii=False) == row["draft"]
    c.close()


def test_migration_7_leaves_a_dirty_hero_row_on_luonnos(tmp_path):
    """The other arm of the badge hazard, which migration 4's suite does not
    cover: a row whose draft already differs from its published text must not
    become Julkaistu. It could only do so if the rewrite collapsed two
    distinct stored texts into one — which appending one key with one constant
    value cannot do, and this is the test that says so rather than the
    comment."""
    c = _v6_database(tmp_path / "dirty.sqlite3", _v6_hero_payload())
    dirty = _v6_hero_payload()
    dirty["title"] = "Kesken oleva luonnos"
    c.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'hero'",
        (json.dumps(dirty, ensure_ascii=False),),
    )
    c.commit()
    before = _hero_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == \
        "Luonnos"

    database.migrate(c)

    row = _hero_row(c)
    assert row["draft"] != row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Luonnos"
    # ...and the dirty draft was migrated too, not skipped for being dirty.
    draft = json.loads(row["draft"])
    assert draft["title"] == "Kesken oleva luonnos"
    assert draft["style"] == ""
    c.close()


def test_migration_7_backfills_previous_published(tmp_path):
    """A NON-NULL previous_published gains the key.

    This case earns its place because every previous_published in the captured
    pre-change install is NULL (tests/test_prechange_upgrade.py), so the
    end-to-end gate cannot exercise this branch at all — and the branch
    matters: Palauta copies previous_published verbatim into draft
    (app/sectionlist.py), so a short payload there 400s the owner's next save.
    """
    old = _v6_hero_payload()
    old["title"] = "Vanha otsikko"
    c = _v6_database(
        tmp_path / "prev.sqlite3",
        _v6_hero_payload(),
        previous=json.dumps(old, ensure_ascii=False),
    )

    database.migrate(c)

    previous = json.loads(_hero_row(c)["previous_published"])
    # The owner's own stored content is untouched...
    assert previous["title"] == "Vanha otsikko"
    # ...but the new key is there, so restoring it and saving cannot 400.
    assert previous["style"] == ""
    assert list(previous) == list(FIELDS["hero"])
    assert validate_payload("hero", previous)[1] == {}
    c.close()


def test_migration_7_survives_a_hero_row_with_no_published_text(tmp_path):
    """A NULL column is skipped, not crashed on and not turned into "{}".

    json.loads(None) raises, so the falsy-text guard is load-bearing: without
    it create_app takes the whole site down on any store holding a hero row
    that was never published.
    """
    c = _v6_database(tmp_path / "null.sqlite3", _v6_hero_payload())
    c.execute("UPDATE sections SET published = NULL WHERE kind = 'hero'")
    c.commit()

    database.migrate(c)

    row = _hero_row(c)
    assert row["published"] is None
    assert row["previous_published"] is None
    assert json.loads(row["draft"])["style"] == ""
    c.close()


def test_migration_7_is_idempotent_byte_for_byte(tmp_path):
    """_migration_7 is called DIRECTLY, twice, rather than migrate() twice.

    migrate() twice is a no-op by PRAGMA user_version alone, so running it
    again proves nothing about what the migration does to a row it has already
    rewritten — which is exactly the branch that has to be byte-stable if a
    store ever migrates on a newer build's data.

    What this pins is that the rewrite APPENDS via setdefault rather than
    assigning. Byte-stability alone cannot tell the two apart — on a row
    whose style is still "" an assignment writes the same bytes — so the
    last block below plants a CHOSEN style on the migrated row and re-runs.
    setdefault leaves it; an assignment silently resets it to "", which is
    an owner's skin quietly reverting on an upgrade.

    It does NOT pin the `if new_text == text: continue` guard, and no
    behavioural test can: when the texts are equal the UPDATE writes
    identical bytes, so deleting the guard leaves the whole suite green.
    That guard is a redundant-write optimisation, not a behaviour, and
    asserting it would mean counting UPDATE statements — testing the
    implementation rather than what it does.
    """
    c = _v6_database(
        tmp_path / "twice.sqlite3",
        _v6_hero_payload(),
        previous=json.dumps(_v6_hero_payload(), ensure_ascii=False),
    )
    database._migration_7(c)
    first = tuple(_hero_row(c))
    # The first pass really did change the row — otherwise a second pass
    # matching it would be true of a migration that does nothing at all.
    assert json.loads(first[1])["style"] == ""

    database._migration_7(c)

    assert tuple(_hero_row(c)) == first

    # And a style the owner has CHOSEN survives a re-run: setdefault leaves
    # it alone, an assignment would silently reset it to "".
    chosen = dict(json.loads(first[1]), style="v2")
    c.execute(
        "UPDATE sections SET draft = ? WHERE kind = 'hero'",
        (json.dumps(chosen, ensure_ascii=False),),
    )
    c.commit()
    database._migration_7(c)
    assert json.loads(_hero_row(c)["draft"])["style"] == "v2"
    c.close()


def test_migration_7_touches_no_other_kind(tmp_path):
    """WHERE kind = 'hero' means what it says.

    style is declared on the hero schema only, so a stray backfill onto
    another kind makes that payload fail validate_payload's unknown-key check
    the moment the owner saves it — a section that cannot be saved, produced
    by an upgrade.

    _migration_7 ALONE, called directly, since LLM-COP-25. _migration_8 is
    the first migration in this codebase that touches more than one kind, and
    it legitimately backfills tietoa, so migrate() here asks about migration 8
    as much as about migration 7. It happens to stay green under migrate()
    today only because the fixture is built from the live SEED_SECTIONS, which
    already carries section_label, so migration 8's setdefault is a no-op on
    it — an accident of the fixture, not a property of migration 7. The scoped
    call is what makes the claim in the name true again. Re-baselining the
    expected `text` against migration 8's output would be the cheaper fix and
    would delete this guard permanently; it is written down here so nobody
    takes it later.
    """
    c = _v6_database(tmp_path / "others.sqlite3", _v6_hero_payload())
    tietoa = copy.deepcopy(dict(SEED_SECTIONS)["tietoa"])
    text = json.dumps(tietoa, ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('tietoa', 2, 'published', ?, ?, ?)",
        (text, text, text),
    )
    c.commit()

    database._migration_7(c)

    row = c.execute(
        "SELECT draft, published, previous_published FROM sections"
        " WHERE kind = 'tietoa'"
    ).fetchone()
    assert (row["draft"], row["published"], row["previous_published"]) == (
        text,
        text,
        text,
    )
    c.close()


# --- migration 8: the schema round, on six kinds at once (LLM-COP-25) ------
#
# tests/test_prechange_upgrade.py asks the headline questions of a REAL
# captured install: badges unchanged, validate_payload clean, byte-for-byte
# splices, idempotence, and the served page still carrying the kickers. This
# file's standing job is the branches that install cannot reach, and its
# docstring at the top of the migration-7 block says so: a NULL column, and a
# NON-NULL previous_published. Every previous_published in the artifact is
# NULL, so nothing there exercises the third column at all.
#
# test_migration_7_backfills_previous_published already covers that column
# for the HERO kind, and it covers it for migration 8 too — migrate() runs
# both, and its `list(previous) == list(FIELDS["hero"])` goes red if
# _migration_8 leaves previous_published out of its column tuple. What it
# cannot cover is the five OTHER kinds, which is precisely where migration
# 8's reach is new: it is the first migration in this file that touches more
# than one kind. Restore copies previous_published verbatim into draft
# (app/sectionlist.py), so a short payload there 400s the owner's next save —
# on five kinds nothing else in the suite asks about.


def _v7_hero_payload():
    """A hero payload as a user_version-7 store actually held one: the
    thirteen keys of the v6 era plus LLM-COP-22's style, and no portrait_alt.

    A FROZEN LITERAL by construction, for the reason _v3_hero_payload states
    — it extends _v6_hero_payload(), which is itself frozen, with the one key
    migration 7 appends, written out here rather than read from FIELDS.
    """
    payload = _v6_hero_payload()
    payload["style"] = ""
    return payload


# The four non-hero payloads as a v7 store held them, written out rather than
# copied from SEED_SECTIONS. The live seed is not a pre-change fixture: it
# already carries section_label, so a fixture built from it would hand
# migration 8 rows that need no backfill and every assertion below would pass
# against a migration that did nothing. (That is not hypothetical — it is
# exactly why test_migration_7_touches_no_other_kind stayed green under
# migrate() when it should not have.) The strings are an owner's, not the
# seed's, so a backfill that overwrote stored content would be visible.
_V7_NON_HERO_PAYLOADS = {
    "tietoa": {
        "nostolause": "Autan sinua löytämään sanat.",
        "leipäteksti": "Työskentelen rauhallisesti ja pitkäjänteisesti.",
        "facts": [
            {"label": "Koulutus", "value": "Filosofian maisteri"},
            {"label": "Kokemus", "value": "Kaksitoista vuotta"},
        ],
    },
    "yhteydenotto": {
        "name_label": "Nimi",
        "email_label": "Sähköposti tai puhelin",
        "message_label": "Viesti",
        "send_label": "Lähetä",
        "thanks": "Kiitos! Palaan asiaan pian.",
    },
    "sijainti": {"address": "Kauppakatu 1, Turku"},
}


# One key per kind whose value belongs to the OWNER, so "the migration left
# stored content alone" is asserted against a value the migration has no
# default for.
_OWNER_MARKER = {
    "hero": "title",
    "tietoa": "nostolause",
    "yhteydenotto": "thanks",
    "sijainti": "address",
}

# What the older, restorable version says in that key. Distinct from anything
# in the current payloads, so a previous_published that had merely been
# overwritten with the draft would be visible rather than plausible.
_RESTORABLE_MARKER = "Vanha teksti"


def _v7_database(path, kinds):
    """A database at exactly user_version 7 with one row per named kind, each
    carrying a NON-NULL previous_published that differs from its published
    text — the state a restore reads.

    MIGRATIONS[:7] and an explicit PRAGMA, the idiom the fixtures above use,
    so _migration_8 really is the only thing that has not run yet.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:7]:
        migration(c)
    c.execute("PRAGMA user_version = 7")
    for position, kind in enumerate(kinds, start=1):
        if kind == "hero":
            payload = _v7_hero_payload()
            older = _v7_hero_payload()
        else:
            payload = copy.deepcopy(_V7_NON_HERO_PAYLOADS[kind])
            older = copy.deepcopy(_V7_NON_HERO_PAYLOADS[kind])
        older[_OWNER_MARKER[kind]] = _RESTORABLE_MARKER
        text = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "INSERT INTO sections (kind, position, state, draft, published,"
            " previous_published) VALUES (?, ?, 'published', ?, ?, ?)",
            (
                kind,
                position,
                text,
                text,
                json.dumps(older, ensure_ascii=False),
            ),
        )
    c.commit()
    return c


def test_migration_8_backfills_previous_published_on_every_kind(tmp_path):
    """The branch the captured install cannot reach, on the five kinds
    migration 8 is the first migration ever to touch.

    Palauta edellinen versio copies previous_published verbatim into draft
    (app/sectionlist.py), so a payload short of a declared key there is not a
    cosmetic gap: the owner restores a version and the very next save 400s,
    with nothing on screen to explain why. The failure this pins is a
    _migration_8 whose column tuple names only draft and published — which
    would leave every other assertion in the suite green.
    """
    kinds = ("hero", "tietoa", "yhteydenotto", "sijainti")
    c = _v7_database(tmp_path / "prev8.sqlite3", kinds)
    before = {
        row["kind"]: badge(row["state"], row["draft"], row["published"])
        for row in c.execute(
            "SELECT kind, state, draft, published FROM sections"
        )
    }
    assert set(before.values()) == {"Julkaistu"}

    database.migrate(c)

    rows = {
        row["kind"]: row
        for row in c.execute(
            "SELECT kind, state, draft, published, previous_published"
            " FROM sections"
        )
    }
    for kind in kinds:
        row = rows[kind]
        previous = json.loads(row["previous_published"])
        # The owner's own stored content is untouched...
        assert previous[_OWNER_MARKER[kind]] == _RESTORABLE_MARKER, kind
        # ...but every declared key is there, in declaration order, so a
        # restore followed by a save cannot 400.
        assert list(previous) == list(FIELDS[kind]), kind
        assert validate_payload(kind, previous)[1] == {}, kind
        # And restoring it really would store those exact bytes back: a
        # payload that validates but re-serialises differently would flip the
        # badge on the save after the restore.
        clean, _errors = validate_payload(kind, previous)
        assert json.dumps(clean, ensure_ascii=False) == (
            row["previous_published"]
        ), kind
        # The other two columns moved together, so no badge moved with them.
        assert row["draft"] == row["published"], kind
        assert badge(row["state"], row["draft"], row["published"]) == (
            before[kind]
        ), kind
    c.close()


# --- migration 9: the hero's second picture (LLM-COP-30) -------------------
#
# Same standing job as the block above, and the same reason: every
# previous_published in tests/test_prechange_upgrade.py's captured artifact is
# NULL, so nothing there can reach migration 9's third column at all.
#
# THE GUARD ALREADY EXISTS TWICE, AND INCIDENTALLY — which is the honest case
# for the test below rather than an argument against it.
# test_migration_7_backfills_previous_published (above) and
# test_migration_8_backfills_previous_published_on_every_kind both call
# database.migrate(), which now runs migration 9 too, and both then assert
# `list(previous) == list(FIELDS["hero"])` — at tests/test_db.py:703 and :973
# respectively. A migration 9 whose column tuple named only draft and
# published would turn both of those lines red today.
#
# So why write this one. Because an incidental guard is one refactor away
# from deletion: a reader tidying migration 7's suite has every reason to
# think :703 is about migration 7, and nothing on the line says otherwise. It
# also names the wrong migration when it fails, sending the next person to
# _migration_7's body to look for a bug that is in _migration_9's. This test
# makes the guard STATED — it fails with migration 9 in its name, over a
# store stamped at exactly 8 — at the cost of one fixture modelled on the one
# directly above it.


# A digest-shaped reference and an owner's own sentence: neither is a value
# any migration has a default for, so "the copy took the row's own portrait"
# is asserted against something no constant could produce.
_V8_PORTRAIT = "d" * 64
_V8_PORTRAIT_ALT = "Kasvokuva työhuoneen ikkunan ääressä"


def _v8_hero_payload():
    """A hero payload as a user_version-8 store actually held one: the
    fifteen keys of that era — the fourteen of the v7 era plus LLM-COP-25's
    portrait_alt — and no background.

    A FROZEN LITERAL by construction, for the reason _v3_hero_payload states
    — it extends _v7_hero_payload(), which is itself frozen, with the one key
    migration 8 appends to the hero kind, written out here rather than read
    from FIELDS.

    THE PORTRAIT IS NOT EMPTY, and that is deliberate. Every other fixture in
    this file inherits _v3_hero_payload's `"portrait": ""`, and against an
    empty portrait migration 9's copy and a constant-"" backfill produce the
    same bytes — so a fixture that kept it would let the test below pass
    against the very migration the design rejects. This is an owner who has
    uploaded a picture, which is the only owner migration 9 can harm.
    """
    payload = _v7_hero_payload()
    payload["portrait"] = _V8_PORTRAIT
    payload["portrait_alt"] = _V8_PORTRAIT_ALT
    return payload


def _v8_database(path, previous=None, state="published"):
    """A database at exactly user_version 8 with one hero row, carrying a
    NON-NULL previous_published that differs from its published text — the
    state a restore reads, and the one the captured artifact cannot express.

    MIGRATIONS[:8] and an explicit PRAGMA, the idiom every fixture above
    uses, so _migration_9 really is the only thing that has not run yet.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:8]:
        migration(c)
    c.execute("PRAGMA user_version = 8")
    text = json.dumps(_v8_hero_payload(), ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('hero', 1, ?, ?, ?, ?)",
        (state, text, text, previous),
    )
    c.commit()
    return c


def test_migration_9_backfills_previous_published(tmp_path):
    """The branch the captured install cannot reach, said of migration 9 by
    name.

    Palauta edellinen versio copies previous_published VERBATIM into draft
    (app/sectionlist.py), so a payload short of a declared key there is not a
    cosmetic gap: the owner restores a version and the very next save 400s,
    with nothing on screen to explain why. The failure this pins is a
    _migration_9 whose column tuple names only draft and published — and
    which would leave every assertion in tests/test_prechange_upgrade.py
    green, because every previous_published in that artifact is NULL.

    The older version is an owner's OWN earlier picture, different from the
    current one. So this asks two things of the third column at once: that it
    gained the keys at all, and that it gained them from ITS OWN portrait
    rather than from the row's draft or from a constant — three columns, one
    pure function of each column's own text.
    """
    older = _v8_hero_payload()
    older[_OWNER_MARKER["hero"]] = _RESTORABLE_MARKER
    older["portrait"] = "e" * 64
    older["portrait_alt"] = "Vanha kasvokuva"
    c = _v8_database(
        tmp_path / "prev9.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
    )
    before = _hero_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == (
        "Julkaistu"
    )
    # The premise: nothing here carries the new keys yet, so every assertion
    # below is migration 9's doing and not the fixture's.
    assert "background" not in json.loads(before["previous_published"])

    database.migrate(c)

    row = _hero_row(c)
    previous = json.loads(row["previous_published"])
    # The owner's own stored content is untouched...
    assert previous[_OWNER_MARKER["hero"]] == _RESTORABLE_MARKER
    # ...but every declared key is there, in declaration order, so a restore
    # followed by a save cannot 400.
    assert list(previous) == list(FIELDS["hero"])
    assert validate_payload("hero", previous)[1] == {}
    # And restoring it really would store those exact bytes back: a payload
    # that validates but re-serialises differently would flip the badge on
    # the save after the restore.
    clean, _errors = validate_payload("hero", previous)
    assert json.dumps(clean, ensure_ascii=False) == row["previous_published"]

    # Each column was backfilled from ITS OWN portrait. A migration that read
    # the draft's portrait for all three, or wrote a constant, passes the two
    # assertions above and fails here.
    assert previous["background"] == "e" * 64
    assert previous["background_alt"] == "Vanha kasvokuva"
    assert json.loads(row["draft"])["background"] == _V8_PORTRAIT
    assert json.loads(row["published"])["background"] == _V8_PORTRAIT
    assert json.loads(row["draft"])["background_alt"] == _V8_PORTRAIT_ALT

    # The other two columns moved together, so no badge moved with them.
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"
    c.close()


# --- migration 10: the login_attempts table (LLM-COP-37) --------------------


def test_migration_10_creates_the_login_attempts_table(tmp_path):
    """The table that earns the migration.

    The throttle this replaces counted audit_log rows, and audit_log is
    (id, at, event) and nothing else — there is no client column to key on,
    so per-client counting was impossible against the schema as it stood.
    That is the whole justification for a new table, and this is where its
    shape is pinned.

    client_key NOT NULL is asserted rather than assumed, because it is what
    makes auth.bucket_key's fail-closed normalisation load-bearing: a request
    with no remote_addr must land in one shared bucket, and the column is
    what refuses the alternative.
    """
    c = database.connect(str(tmp_path / "login.sqlite3"))
    database.migrate(c)

    info = {row["name"]: row for row in c.execute(
        "PRAGMA table_info(login_attempts)"
    )}
    assert set(info) == {"id", "client_key", "at"}
    assert info["client_key"]["notnull"] == 1
    assert info["at"]["notnull"] == 1

    (index_sql,) = c.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
        ("login_attempts_key_at",),
    ).fetchone()
    # The limiter's only query is WHERE client_key = ? AND at > ?, so the
    # index has to carry both columns in that order or every refused request
    # scans the table.
    assert re.search(
        r"ON\s+login_attempts\s*\(\s*client_key\s*,\s*at\s*\)", index_sql
    ), index_sql

    c.execute(
        "INSERT INTO login_attempts (client_key, at) VALUES (?, ?)",
        ("203.0.113.7", 1_700_000_000),
    )
    try:
        c.execute(
            "INSERT INTO login_attempts (client_key, at) VALUES (?, ?)",
            (None, 1_700_000_000),
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("client_key accepted NULL")
    c.commit()

    # IF NOT EXISTS is what makes the RENUMBER safe rather than merely tidy,
    # for the reason _migration_6 gives: this was written as 10 while another
    # migration was being written as 11, and a store already stamped at 10
    # would run it again under the other number. Called directly, twice, on a
    # database that already has the table.
    database._migration_10(c)
    database._migration_10(c)
    (rows,) = c.execute("SELECT COUNT(*) FROM login_attempts").fetchone()
    assert rows == 1  # and re-running kept the data rather than recreating it
    c.close()


# --- migration 11: the owner's two colours (USR-COP-2) ---------------------
#
# The same fixture shape one era later. Everything test_migration_9's block
# above says about WHY these are frozen literals rather than reads of FIELDS
# holds verbatim; only the era moves.


# A digest-shaped reference and an owner's own sentence, for the same reason
# _V8_PORTRAIT carries them: neither is a value any migration has a default
# for, so a fixture built from them cannot be produced by a constant.
_V10_BACKGROUND = "f" * 64
_V10_BACKGROUND_ALT = "Vastaanottohuone aamuvalossa"

# The colours an owner is imagined to have chosen already, planted where a
# migration must leave them. Neither is either skin's own literal and neither
# is "" — so "setdefault, not assignment" is asserted against values no
# default could produce.
_CHOSEN_MAIN = "#1a1a2e"
_CHOSEN_ACCENT = "#ffe9a8"


def _v10_hero_payload():
    """A hero payload as a user_version-10 store actually held one: the
    seventeen keys of that era — _v8_hero_payload's fifteen plus LLM-COP-30's
    background pair — and neither colour.

    A FROZEN LITERAL by construction, for the reason _v3_hero_payload states:
    it extends _v8_hero_payload(), itself frozen, with the two keys migration
    9 appends, written out here rather than read from FIELDS.
    """
    payload = _v8_hero_payload()
    payload["background"] = _V10_BACKGROUND
    payload["background_alt"] = _V10_BACKGROUND_ALT
    return payload


def _v10_database(path, previous=None, state="published", hero=None):
    """A database at exactly version 10, with one hero row — migration 11's.

    THE SLICE AND THE PRAGMA ARE EXPLICIT LITERALS, and that is the point of
    them. This fixture was written relative to the head — MIGRATIONS[:-1] and
    len(MIGRATIONS) - 1 — on the reasoning that "every migration except the
    one under test" says what it means (USR-COP-2). That reasoning was only
    ever true while 11 WAS the head, and USR-COP-4 is the change that made it
    stop being true: with a twelfth migration appended, the relative form
    stamps user_version 11 and migrate() below runs migration 12 ALONE,
    skipping the very migration these three tests exist to exercise.

    Two of them go loudly red when that happens. The third,
    test_migration_11_leaves_a_colour_the_owner_already_chose, goes SILENTLY
    GREEN AND VACUOUS: it pre-seeds both colours, so every assertion in it
    passes while the migration under test never runs at all. A dead test that
    reports success is worse than no test, and it is why this is written as
    10 and 10 now.

    The general rule the next migration inherits: a fixture that pins a
    version pins it as a LITERAL. Two siblings landing in parallel is exactly
    when head-relative arithmetic stops describing the version it names.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:10]:
        migration(c)
    c.execute("PRAGMA user_version = 10")
    text = json.dumps(hero or _v10_hero_payload(), ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('hero', 1, ?, ?, ?, ?)",
        (state, text, text, previous),
    )
    c.commit()
    return c


def test_migration_11_backfills_previous_published(tmp_path):
    """The branch the captured install cannot reach, said of migration 11.

    Palauta edellinen versio copies previous_published VERBATIM into draft
    (app/sectionlist.py), so a payload short of a declared key there is not a
    cosmetic gap: the owner restores a version and the very next save 400s,
    with nothing on screen to explain why. The failure this pins is a
    _migration_11 whose column tuple names only draft and published — which
    would leave every assertion in tests/test_prechange_upgrade.py green,
    because every previous_published in that artifact is NULL.
    """
    older = _v10_hero_payload()
    older[_OWNER_MARKER["hero"]] = _RESTORABLE_MARKER
    c = _v10_database(
        tmp_path / "prev11.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
    )
    before = _hero_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == (
        "Julkaistu"
    )
    # The premise: nothing here carries the new keys yet, so every assertion
    # below is migration 11's doing and not the fixture's.
    assert "color_main" not in json.loads(before["previous_published"])
    assert "color_main" not in json.loads(before["draft"])

    database.migrate(c)

    row = _hero_row(c)
    previous = json.loads(row["previous_published"])
    # The owner's own stored content is untouched...
    assert previous[_OWNER_MARKER["hero"]] == _RESTORABLE_MARKER
    # ...but every declared key is there, in declaration order, so a restore
    # followed by a save cannot 400.
    assert list(previous) == list(FIELDS["hero"])
    assert validate_payload("hero", previous)[1] == {}
    # And restoring it really would store those exact bytes back: a payload
    # that validates but re-serialises differently would flip the badge on
    # the save after the restore.
    clean, _errors = validate_payload("hero", previous)
    assert json.dumps(clean, ensure_ascii=False) == row["previous_published"]

    # All three columns gained BOTH keys, and both are "" — which is what
    # makes app/palette.py emit no <style> block, so the upgraded install
    # serves the bytes it served before.
    for column in ("draft", "published", "previous_published"):
        payload = json.loads(row[column])
        assert payload["color_main"] == "", column
        assert payload["color_accent"] == "", column
        assert list(payload)[-2:] == ["color_main", "color_accent"], column

    # The other two columns moved together, so no badge moved with them.
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"
    c.close()


def test_migration_11_leaves_a_colour_the_owner_already_chose(tmp_path):
    """A store whose hero ALREADY carries both colours is byte-untouched.

    The branch that matters when a store is migrated on a newer build's data,
    and the one an ASSIGNMENT would silently break: `payload["color_main"] =
    ""` writes the same bytes as setdefault on every row in the frozen
    artifact — where both values are "" — and reverts this owner's chosen
    palette to the skin default on the next upgrade. Byte-equality of all
    three columns is what makes "the migration wrote nothing" a claim about
    the stored text rather than about the parsed payload.
    """
    chosen = dict(
        _v10_hero_payload(),
        color_main=_CHOSEN_MAIN,
        color_accent=_CHOSEN_ACCENT,
    )
    older = dict(chosen, **{_OWNER_MARKER["hero"]: _RESTORABLE_MARKER})
    c = _v10_database(
        tmp_path / "chosen11.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
        hero=chosen,
    )
    before = tuple(_hero_row(c))

    database.migrate(c)

    assert tuple(_hero_row(c)) == before
    row = _hero_row(c)
    for column in ("draft", "published", "previous_published"):
        payload = json.loads(row[column])
        assert payload["color_main"] == _CHOSEN_MAIN, column
        assert payload["color_accent"] == _CHOSEN_ACCENT, column
    c.close()


def test_migration_11_is_idempotent_byte_for_byte(tmp_path):
    """_migration_11 called DIRECTLY a second time moves not one byte.

    Directly, not migrate() twice: migrate() twice is a no-op by PRAGMA
    user_version alone (app/db.py), so it says nothing about what this
    migration does to a row it has already rewritten —
    test_migration_5_is_idempotent_byte_for_byte's reason, applied to the
    newest migration as every one of its predecessors owes.
    """
    c = _v10_database(tmp_path / "twice11.sqlite3")

    database.migrate(c)
    first = tuple(_hero_row(c))
    # The first pass really did reach the hero — otherwise a second pass
    # matching it would be true of a migration that does nothing at all.
    assert json.loads(first[1])["color_main"] == ""

    database._migration_11(c)

    assert tuple(_hero_row(c)) == first
    c.close()


# --- migration 12: the button's name, and the availability notice ----------
#     (USR-COP-4)
#
# The same fixture shape one era later, on a DIFFERENT KIND. Everything
# migration 9's block above says about WHY these are frozen literals rather
# than reads of FIELDS holds verbatim; only the era and the kind move.
#
# THE STANDING JOB, restated because migration 12 needs it more than any of
# its predecessors did: every previous_published in
# tests/test_prechange_upgrade.py's captured artifact is NULL, so nothing
# there can reach the third column at all — and that artifact's send_label is
# the OLD DEFAULT, so nothing there can reach the rename's guarded branch
# either. Two branches, neither reachable from the capture, both live in
# production the day this ships.


# The words an owner is imagined to have typed on the button themselves.
# Not any default this migration has, and asserted to appear nowhere under
# app/ in the test that uses it — so "the migration left it alone" is a claim
# about a value nothing in the product could have written.
_CHOSEN_SEND_LABEL = "Varaa aika soittamalla"

# The line an owner is imagined to have written, and the flag switched on.
# Neither is a value migration 12 has a default for — both its defaults are
# "" — so "setdefault, not assignment" is asserted against text no default
# could produce.
_CHOSEN_NOTICE = "Seuraavat ajat 03.2026 alussa"
_NOTICE_ON = "on"


def _v11_yhteydenotto_payload():
    """A yhteydenotto payload as a user_version-11 store actually held one:
    the five keys of the v7 era plus LLM-COP-25's five, and neither notice
    key.

    A FROZEN LITERAL by construction, for the reason _v3_hero_payload states
    — it extends _V7_NON_HERO_PAYLOADS["yhteydenotto"], which is itself
    frozen, with the five keys migration 8 appends to this kind, WRITTEN OUT
    here rather than read from FIELDS. Reading them from the live schema
    would hand migration 12 a row that already carried whatever the schema
    grows next, and every assertion below would then pass against a migration
    that did nothing — which is the defect _V7_NON_HERO_PAYLOADS' own comment
    records having already been paid for once.

    The five values are migration 8's own, not the seed's: "YHTEYDENOTTO" is
    the kicker that migration turned from a template literal into stored
    data, and the contact four were "" because they rendered nothing before
    that upgrade.

    Migrations 9, 10 and 11 appended nothing to this kind — 9 and 11 are
    WHERE kind = 'hero' and 10 writes no payload at all — so a v8 payload and
    a v11 payload of this kind are the same ten keys, and the name says the
    era this fixture is USED at rather than the era it last grew in.
    """
    payload = copy.deepcopy(_V7_NON_HERO_PAYLOADS["yhteydenotto"])
    payload["section_label"] = "YHTEYDENOTTO"
    payload["phone"] = ""
    payload["email"] = ""
    payload["body"] = ""
    payload["caveat"] = ""
    return payload


def _v11_database(path, previous=None, state="published", payload=None):
    """A database at exactly version 11, with one yhteydenotto row —
    migration 12's.

    THE SLICE AND THE PRAGMA ARE EXPLICIT LITERALS, for the reason
    _v10_database's docstring now spells out at length: a fixture written
    relative to the head (MIGRATIONS[:-1], len(MIGRATIONS) - 1) stops
    describing the version it names the moment another migration is
    appended, and the failure mode is not always a red test — it can be a
    green and vacuous one. A fixture that pins a version pins it as a
    LITERAL. A thirteenth migration must leave these two numbers alone and
    write its own _v12_database beside this one.
    """
    c = database.connect(str(path))
    for migration in database.MIGRATIONS[:11]:
        migration(c)
    c.execute("PRAGMA user_version = 11")
    text = json.dumps(payload or _v11_yhteydenotto_payload(), ensure_ascii=False)
    c.execute(
        "INSERT INTO sections (kind, position, state, draft, published,"
        " previous_published) VALUES ('yhteydenotto', 1, ?, ?, ?, ?)",
        (state, text, text, previous),
    )
    c.commit()
    return c


def _yhteydenotto_row(c):
    return c.execute(
        "SELECT state, draft, published, previous_published FROM sections"
        " WHERE kind = 'yhteydenotto'"
    ).fetchone()


def test_migration_12_backfills_previous_published(tmp_path):
    """The branch the captured install cannot reach, said of migration 12.

    Palauta edellinen versio copies previous_published VERBATIM into draft
    (app/sectionlist.py), so a payload short of a declared key there is not a
    cosmetic gap: the owner restores a version and the very next save 400s,
    with nothing on screen to explain why. The failure this pins is a
    _migration_12 whose column tuple names only draft and published — which
    would leave EVERY assertion in tests/test_prechange_upgrade.py green,
    because every previous_published in that captured artifact is NULL and
    badge() (app/sections.py) never reads that column at all. This is the
    only place in the suite where that mutation is detectable, and it is
    written down here so nobody moves the falsifier somewhere it cannot fail.

    The older version carries the owner's own earlier thanks text, so the
    third column is asked two things at once: that it gained the keys at all,
    and that it gained them without losing what was already in it.
    """
    older = _v11_yhteydenotto_payload()
    older[_OWNER_MARKER["yhteydenotto"]] = _RESTORABLE_MARKER
    c = _v11_database(
        tmp_path / "prev12.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
    )
    before = _yhteydenotto_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == (
        "Julkaistu"
    )
    # The premise: nothing here carries the new keys yet, so every assertion
    # below is migration 12's doing and not the fixture's.
    assert "notice_text" not in json.loads(before["previous_published"])
    assert "notice_text" not in json.loads(before["draft"])

    database.migrate(c)

    row = _yhteydenotto_row(c)
    previous = json.loads(row["previous_published"])
    # The owner's own stored content is untouched...
    assert previous[_OWNER_MARKER["yhteydenotto"]] == _RESTORABLE_MARKER
    # ...but every declared key is there, in declaration order, so a restore
    # followed by a save cannot 400.
    assert list(previous) == list(FIELDS["yhteydenotto"])
    assert validate_payload("yhteydenotto", previous)[1] == {}
    # And restoring it really would store those exact bytes back: a payload
    # that validates but re-serialises differently would flip the badge on
    # the save after the restore.
    clean, _errors = validate_payload("yhteydenotto", previous)
    assert json.dumps(clean, ensure_ascii=False) == row["previous_published"]

    # All THREE columns gained BOTH keys, in declaration order, and both are
    # "" — which is what makes app/notice.py render nothing at all, so the
    # upgraded install serves the page it served before.
    for column in ("draft", "published", "previous_published"):
        payload = json.loads(row[column])
        assert payload["notice_text"] == "", column
        assert payload["notice_on"] == "", column
        assert list(payload)[-2:] == ["notice_text", "notice_on"], column
        # ...and the rename reached all three too. previous_published is the
        # column that matters here: a restore copies it into draft verbatim,
        # so a third column still reading "Lähetä" would put the old word
        # back on the owner's button the moment they restored a version.
        assert payload["send_label"] == "Ota yhteyttä", column

    # The other two columns moved together, so no badge moved with them.
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"
    c.close()


def test_migration_12_leaves_a_custom_send_label_alone(tmp_path):
    """A store whose button ALREADY says the owner's own words is left saying
    them, in all three columns.

    THE SAFE-RENAME RULE at row level, and the branch an unguarded rewrite
    would silently break: `payload["send_label"] = "Ota yhteyttä"` writes the
    same bytes as the guarded rename on every row of the captured artifact —
    where the stored value IS the old default — and takes this owner's words
    off their live published page on the day the upgrade ships. The captured
    install cannot ask the question at all, which is why it is asked here.

    assert_absent_from_app is what makes the claim falsifiable rather than
    decorative: if these words appeared anywhere under app/ the migration
    might have a default that produced them, and "left alone" would be
    indistinguishable from "written".

    The row is NOT byte-untouched, and that is the difference between this
    and test_migration_11_leaves_a_colour_the_owner_already_chose: migration
    12 does two things, and only the rename is skipped here. The backfill
    still runs, and it must, or this owner's next save would 400 on the two
    missing keys. So the assertion is on the VALUE that survived and on the
    keys that arrived, not on the bytes.
    """
    assert_absent_from_app(_CHOSEN_SEND_LABEL)
    chosen = dict(_v11_yhteydenotto_payload(), send_label=_CHOSEN_SEND_LABEL)
    older = dict(
        chosen, **{_OWNER_MARKER["yhteydenotto"]: _RESTORABLE_MARKER}
    )
    c = _v11_database(
        tmp_path / "chosen12.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
        payload=chosen,
    )
    before = _yhteydenotto_row(c)
    before_badge = badge(
        before["state"], before["draft"], before["published"]
    )
    assert before_badge == "Julkaistu"

    database.migrate(c)

    row = _yhteydenotto_row(c)
    for column in ("draft", "published", "previous_published"):
        payload = json.loads(row[column])
        assert payload["send_label"] == _CHOSEN_SEND_LABEL, column
        # The other half of the migration DID run on this very row: "left
        # alone" must mean the rename was skipped, not that the row was.
        assert payload["notice_text"] == "", column
        assert payload["notice_on"] == "", column
        assert list(payload) == list(FIELDS["yhteydenotto"]), column
    # And the badge did not move, because both columns were rewritten by the
    # same pure function of their own text.
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == before_badge
    c.close()


def test_migration_12_collapses_a_draft_that_already_says_the_new_default(
    tmp_path,
):
    """MIGRATION 12 IS NOT INJECTIVE, and this is where that is PINNED rather
    than discovered later by whoever the badge surprises.

    _migration_5, _migration_8 and _migration_11 each earn an injectivity
    claim the same way: the input is recoverable from the output, so two
    distinct stored texts cannot collapse into one and badge() cannot turn a
    Luonnos row into a Julkaistu one. Migration 12 CANNOT make that claim.
    The rename maps "Lähetä" to "Ota yhteyttä" and leaves "Ota yhteyttä"
    alone, so a row whose DRAFT already said the new words while its
    PUBLISHED still said the old ones becomes equal in both columns, and its
    badge moves Luonnos -> Julkaistu.

    THIS IS ACCEPTED, NOT OVERLOOKED. It is not a lie the badge tells: after
    the migration the two columns really ARE identical and the public page
    really does show what the draft said, because the published column was
    rewritten too — asserted below, because that is the whole difference
    between a documented collapse and a silent one. The owner's unpublished
    label edit is effectively adopted, but only where their edit was
    byte-identical to the new default, and only to the same string every
    other install gets anyway.

    BOTH ALTERNATIVES ARE WORSE, which is the reason this one is taken:
      - Rewriting draft alone keeps the row injective and flips EVERY site
        in the world to Luonnos, inviting a publish nobody asked for. That
        is the headline hazard the whole frozen-install suite exists for.
      - A row-atomic rule — rename only if every non-NULL column holds the
        old default — avoids the collapse and leaves a LIVE PUBLISHED PAGE
        reading "Lähetä" on any row with a dirty draft. A button that lies
        about what it does, on the public page, forever, is a different and
        worse lie than a badge that became accurate early.

    A future reader who thinks this test is describing a bug should read the
    two bullets above before changing anything: this behaviour was reviewed
    twice and kept deliberately. If it is ever changed, it is changed by
    choosing one of those two, with their costs, and not by patching around
    the collapse.
    """
    draft = dict(_v11_yhteydenotto_payload(), send_label="Ota yhteyttä")
    published = _v11_yhteydenotto_payload()
    assert published["send_label"] == "Lähetä"  # the frozen v7 value
    draft_text = json.dumps(draft, ensure_ascii=False)
    published_text = json.dumps(published, ensure_ascii=False)
    # The two texts differ ONLY in that one field — so the collapse below is
    # the rename's doing and not a fixture that was equal all along.
    assert draft_text != published_text
    assert draft_text.replace("Ota yhteyttä", "Lähetä") == published_text

    c = _v11_database(tmp_path / "collapse12.sqlite3")
    c.execute(
        "UPDATE sections SET draft = ?, published = ?"
        " WHERE kind = 'yhteydenotto'",
        (draft_text, published_text),
    )
    c.commit()
    before = _yhteydenotto_row(c)
    assert badge(before["state"], before["draft"], before["published"]) == (
        "Luonnos"
    )

    database.migrate(c)

    row = _yhteydenotto_row(c)
    # The collapse itself.
    assert row["draft"] == row["published"]
    assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"
    # And the badge is TELLING THE TRUTH: the published column genuinely
    # reads the new words now, so the public page shows what the badge
    # claims is published. This is the assertion that separates an accepted
    # collapse from a lie, and it is the one that would fail against an
    # implementation that moved the badge without moving the page.
    assert json.loads(row["published"])["send_label"] == "Ota yhteyttä"
    assert json.loads(row["draft"])["send_label"] == "Ota yhteyttä"
    # The backfill still ran on both columns, so the owner's next save works.
    for column in ("draft", "published"):
        payload = json.loads(row[column])
        assert list(payload) == list(FIELDS["yhteydenotto"]), column
        assert validate_payload("yhteydenotto", payload)[1] == {}, column
    c.close()


def test_migration_12_keeps_a_notice_the_owner_already_wrote(tmp_path):
    """setdefault, not assignment, asked of the newest two keys.

    The branch that matters when a store is migrated on a newer build's
    data, and the one an ASSIGNMENT would silently break: `payload
    ["notice_text"] = ""` writes the same bytes as setdefault on every row
    that has no notice — which is every row in existence the day this ships —
    and blanks this owner's line, and switches their notice off, on the next
    upgrade. That is precisely the loss "switched off WITHOUT LOSING ITS
    TEXT" exists to prevent, reinstated by the migration meant to deliver it.

    Byte-equality of all three columns is what makes "the migration wrote
    nothing" a claim about the stored text rather than about the parsed
    payload — test_migration_11_leaves_a_colour_the_owner_already_chose's
    form, and it holds here because this row needs neither half of the
    migration: its send_label is already the new default and its notice keys
    are already present.
    """
    assert_absent_from_app(_CHOSEN_NOTICE)
    written = dict(
        _v11_yhteydenotto_payload(),
        send_label="Ota yhteyttä",
        notice_text=_CHOSEN_NOTICE,
        notice_on=_NOTICE_ON,
    )
    older = dict(
        written, **{_OWNER_MARKER["yhteydenotto"]: _RESTORABLE_MARKER}
    )
    c = _v11_database(
        tmp_path / "notice12.sqlite3",
        previous=json.dumps(older, ensure_ascii=False),
        payload=written,
    )
    before = tuple(_yhteydenotto_row(c))

    database.migrate(c)

    assert tuple(_yhteydenotto_row(c)) == before
    row = _yhteydenotto_row(c)
    for column in ("draft", "published", "previous_published"):
        payload = json.loads(row[column])
        assert payload["notice_text"] == _CHOSEN_NOTICE, column
        assert payload["notice_on"] == _NOTICE_ON, column
    c.close()


def test_the_migration_head_is_thirteen(tmp_path):
    """The head, named exactly once in the suite.

    Every other version assertion in this file is written as
    `len(database.MIGRATIONS)` on purpose, so migrations added later do not
    break tests that are not about them. This one is deliberately literal: it
    is the single place a person adding migration 14 is told, by a red test,
    that a stamped store now upgrades one step further — and it pins that
    MIGRATIONS ends where the list says rather than where a stale PRAGMA does.

    It did that job for LLM-COP-30, again for USR-COP-4 and again for
    LLM-COP-39, each of which found it red and moved it here rather than
    silencing it. Rename it with the number, so the test's name keeps
    stating the head instead of a head it used to have.

    The list is named by INDEX as well as by length, because the two say
    different things: the length pins where the ladder ends, and the
    identities pin that appending a migration appended it rather than
    displacing the one before. LLM-COP-37's migration 10 and USR-COP-2's
    migration 11 landed in that order, from different branches, and these
    lines are where that order is stated once. USR-COP-4 APPENDED migration
    12 while a sibling change held 13: a collision here is resolved by
    appending both, never by renumbering either — a renumbered migration
    re-runs against a store already stamped past it. That is precisely what
    happened: USR-COP-4's real migration 12 and LLM-COP-39's migration 13
    both landed, neither number moved, and the reserved no-op that had been
    holding slot 12 was deleted rather than renumbered.
    """
    assert len(database.MIGRATIONS) == 13
    assert database.MIGRATIONS[8] is database._migration_9
    assert database.MIGRATIONS[9] is database._migration_10
    assert database.MIGRATIONS[10] is database._migration_11
    assert database.MIGRATIONS[11] is database._migration_12
    assert database.MIGRATIONS[12] is database._migration_13

    c = database.connect(str(tmp_path / "head.sqlite3"))
    database.migrate(c)
    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == 13
    c.close()
