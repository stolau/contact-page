"""Plan step 2 — app/db.py: connection + PRAGMA user_version migrations."""

import copy
import json
import re

from app import db as database
from app.fields import FIELDS
from app.sanitize import validate_payload
from app.sections import badge
from app.seed import SEED_SECTIONS


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
    assert re.search(r"anna|puheterap|virtanen|valvira|2938471", blob, re.IGNORECASE) is None
    c.close()
