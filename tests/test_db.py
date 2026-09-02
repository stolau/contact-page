"""Plan step 2 — app/db.py: connection + PRAGMA user_version migrations."""

import copy
import json
import re

from app import db as database
from app.fields import FIELDS
from app.sanitize import validate_payload
from app.sections import badge
from app.seed import SEED_SECTIONS
from tests.conftest import PERSONA_PATTERN


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

    assert columns("admin_user") == {"id", "username", "password_hash"}
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
    assert list(draft)[-1] == "portrait_alt"
    assert list(draft)[-2] == "style"
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


def test_the_migration_head_is_eight(tmp_path):
    """The head, named exactly once in the suite.

    Every other version assertion in this file is written as
    `len(database.MIGRATIONS)` on purpose, so migrations added later do not
    break tests that are not about them. This one is deliberately literal: it
    is the single place a person adding migration 9 is told, by a red test,
    that a stamped store now upgrades one step further — and it pins that
    MIGRATIONS ends where the list says rather than where a stale PRAGMA does.
    """
    assert len(database.MIGRATIONS) == 8
    assert database.MIGRATIONS[7] is database._migration_8

    c = database.connect(str(tmp_path / "head.sqlite3"))
    database.migrate(c)
    (version,) = c.execute("PRAGMA user_version").fetchone()
    assert version == 8
    c.close()
