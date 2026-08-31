"""Plan step 2 — app/db.py: connection + PRAGMA user_version migrations."""

from app import db as database


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
