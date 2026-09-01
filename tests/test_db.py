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


def _hero_without_chrome():
    payload = copy.deepcopy(dict(SEED_SECTIONS)["hero"])
    for key in ("brand", "page_title", "footer"):
        payload.pop(key, None)
    return payload


def test_migration_4_backfills_chrome_without_flipping_any_badge(tmp_path):
    c = _v3_database(tmp_path / "old.sqlite3", _hero_without_chrome())
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
    old = _hero_without_chrome()
    old["title"] = "Vanha otsikko"
    c = _v3_database(
        tmp_path / "prev.sqlite3",
        _hero_without_chrome(),
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
    c = _v3_database(tmp_path / "null.sqlite3", _hero_without_chrome())
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
    c = _v3_database(tmp_path / "twice.sqlite3", _hero_without_chrome())
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
    c = _v3_database(tmp_path / "neutral.sqlite3", _hero_without_chrome())
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
    """
    payload = copy.deepcopy(dict(SEED_SECTIONS)["tietoa"])
    c = _v4_database(
        tmp_path / "already.sqlite3",
        payload,
        previous=json.dumps(payload, ensure_ascii=False),
    )
    before = tuple(_tietoa_row(c))

    database.migrate(c)

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
    database.migrate(c)

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
