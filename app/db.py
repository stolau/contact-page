"""SQLite connection and PRAGMA user_version migrations."""

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


MIGRATIONS = [_migration_1, _migration_2, _migration_3]


def migrate(conn):
    """Apply every migration above the current user_version, then stamp it."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number > version:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {number}")
    conn.commit()
