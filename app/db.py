"""SQLite connection and PRAGMA user_version migrations."""

import json
import sqlite3


def connect(path):
    """Open a connection with row access by column name."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _migration_1(conn):
    conn.execute(
        """
        CREATE TABLE sections (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            position INTEGER NOT NULL,
            state TEXT NOT NULL,
            draft TEXT,
            published TEXT,
            previous_published TEXT
        )
        """
    )


def _migration_2(conn):
    # Auth layer (LLM-COP-2). Every timestamp column below (at, created_at,
    # last_seen_at, expires_at) is an integer Unix epoch in seconds — the one
    # representation shared by app.auth and any test that rewinds a session.
    conn.execute(
        """
        CREATE TABLE admin_user (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            token_hash TEXT NOT NULL UNIQUE,
            created_at INTEGER NOT NULL,
            last_seen_at INTEGER NOT NULL,
            remember INTEGER NOT NULL,
            expires_at INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            at INTEGER NOT NULL,
            event TEXT NOT NULL
        )
        """
    )


def _migration_3(conn):
    # Contact messages (LLM-COP-3). consented_at and created_at are integer
    # Unix epochs in seconds, the same representation migration 2 uses.
    # body holds the visitor's free description (the "message" field of the
    # dialog); phone is the one optional column.
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            body TEXT NOT NULL,
            email TEXT NOT NULL,
            phone TEXT,
            consented_at INTEGER NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )


def _migration_4(conn):
    # Site chrome becomes stored data (LLM-COP-10): brand, page_title and
    # footer move out of the templates onto the hero payload, so existing rows
    # need the keys or validate_payload's required-key check rejects the first
    # save. The defaults are FROZEN LITERALS on purpose: a migration that
    # imports app.fields or app.seed changes behaviour whenever the schema
    # later changes, which is not a migration. setdefault appends, so a row
    # that already has the keys is untouched and a backfilled row's key order
    # still equals FIELDS["hero"] declaration order — which is what keeps
    # draft == published byte-equal and every badge on Julkaistu.
    # previous_published is backfilled too: /api/sections/<id>/restore copies
    # it verbatim into draft, and a short payload there would 400 the next
    # save.
    defaults = {
        "brand": "Yrityksen nimi",
        "page_title": "Yrityksen nimi",
        "footer": "© 2026 Yrityksen nimi",
    }
    columns = ("draft", "published", "previous_published")
    rows = conn.execute(
        "SELECT id, draft, published, previous_published FROM sections"
        " WHERE kind = 'hero'"
    ).fetchall()
    for row in rows:
        # Indexed positionally: a migration must not depend on the caller
        # having set sqlite3.Row, which is a property of connect() and not of
        # the database file this runs against.
        section_id = row[0]
        for offset, column in enumerate(columns, start=1):
            text = row[offset]
            if not text:
                continue
            payload = json.loads(text)
            for key, value in defaults.items():
                payload.setdefault(key, value)
            conn.execute(
                f"UPDATE sections SET {column} = ? WHERE id = ?",
                (json.dumps(payload, ensure_ascii=False), section_id),
            )


MIGRATIONS = [_migration_1, _migration_2, _migration_3, _migration_4]


def migrate(conn):
    """Apply every migration above the current user_version, then stamp it."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number > version:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {number}")
    conn.commit()
