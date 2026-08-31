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


MIGRATIONS = [_migration_1]


def migrate(conn):
    """Apply every migration above the current user_version, then stamp it."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number > version:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {number}")
    conn.commit()
