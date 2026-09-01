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


def _migration_5(conn):
    # tietoa.facts becomes a list of {label, value} pairs (LLM-COP-20). The
    # stored list carried no label, so a fact's caption could only ever be a
    # positional guess.
    #
    # Existing entries are wrapped with an EMPTY label ON PURPOSE. This
    # migration knows what POSITION an entry had and nothing whatever about
    # what it MEANS; a positional default would print "Koulutus" over
    # "Käynnit 45–90 min" on the author's own store, which is exactly the lie
    # LLM-COP-5 refused to ship (tests/test_sectionlist.py). The owner fills
    # the labels in, and page.html omits an empty label, so a migrated page
    # shows the same text it showed before.
    #
    # The shape is a FROZEN LITERAL — no import of app.fields — for the
    # reason _migration_4 states: a migration that reads the live schema
    # changes behaviour whenever the schema next changes, which is not a
    # migration. label comes first because that is FIELDS declaration order
    # and _validate_item rebuilds items in it (app/sanitize.py:150).
    #
    # All three columns are rewritten in ONE pass by ONE pure function of
    # the stored text, so draft == published before implies draft ==
    # published after and badge() (app/sections.py:15) cannot flip a
    # Julkaistu row. The converse hazard — a Luonnos row silently becoming
    # Julkaistu — needs two DISTINCT stored texts to collapse to one, and
    # there are exactly two ways that could happen. First, two payloads
    # differing only in JSON formatting: every writer serializes with
    # json.dumps(..., ensure_ascii=False) and default separators
    # (app/seed.py, app/edit.py, app/sectionlist.py, and this module), and
    # restore copies bytes verbatim, so no such pair exists. Second, and
    # only because the already-reshaped branch below rebuilds an item in
    # declared key order, two payloads differing only in a fact item's key
    # ORDER. That pair cannot exist either: every write path runs through
    # validate_payload, and _validate_item already rebuilds every object
    # item as {key: item[key] for key in shape} (app/sanitize.py:150), so
    # a stored item is in declared order before this migration ever sees it.
    columns = ("draft", "published", "previous_published")
    rows = conn.execute(
        "SELECT id, draft, published, previous_published FROM sections"
        " WHERE kind = 'tietoa'"
    ).fetchall()
    for row in rows:
        # Indexed positionally: a migration must not depend on the caller
        # having set sqlite3.Row (app/db.py:110-113).
        section_id = row[0]
        for offset, column in enumerate(columns, start=1):
            text = row[offset]
            if not text:
                continue
            payload = json.loads(text)
            facts = payload.get("facts")
            if not isinstance(facts, list):
                continue
            reshaped = []
            for fact in facts:
                if isinstance(fact, str):
                    # The only shape any writer in this repo could have
                    # stored under item: "plain". _validate_item admits
                    # nothing but str for a plain item (app/sanitize.py:
                    # 141-144), and every write path to these columns goes
                    # through validate_payload — PUT draft (app/edit.py:92),
                    # POST sections (app/sectionlist.py:290), publish
                    # (app/edit.py:106) — or is a byte-verbatim copy
                    # (restore, app/sectionlist.py:369-374). The seed
                    # (app/seed.py:76-81) writes str too.
                    reshaped.append({"label": "", "value": fact})
                elif isinstance(fact, dict) and set(fact) == {"label", "value"}:
                    # Already reshaped: this row was migrated before, or the
                    # file came from a newer build. Rebuilt in DECLARED key
                    # order so the output is byte-identical either way —
                    # that is what makes this migration idempotent.
                    reshaped.append(
                        {"label": fact["label"], "value": fact["value"]}
                    )
                else:
                    # Unreachable from any writer above. Left ALONE rather
                    # than coerced or raised on, deliberately:
                    #   - coercing would need a string this migration would
                    #     have to invent, and inventing owner text is the
                    #     defect this artifact exists to remove;
                    #   - raising would take the whole site down inside
                    #     create_app (app/__init__.py:52-57), which calls
                    #     migrate() before the app can serve anything, over
                    #     one bad row in one section;
                    #   - validate_payload already rejected such a row
                    #     BEFORE this migration and still rejects it after,
                    #     so the section shows as unsavable in the editor
                    #     either way. This migration neither creates nor
                    #     hides the condition, and a test asserts exactly
                    #     that (test_migration_5_leaves_an_unwritable_item_
                    #     alone_and_does_not_hide_it).
                    reshaped.append(fact)
            payload["facts"] = reshaped
            new_text = json.dumps(payload, ensure_ascii=False)
            if new_text == text:
                continue
            conn.execute(
                f"UPDATE sections SET {column} = ? WHERE id = ?",
                (new_text, section_id),
            )

def _migration_6(conn):
    # Uploaded images (LLM-COP-21). One row per stored file, addressed by
    # the SHA-256 of the bytes we stored, so the same picture uploaded twice
    # is one row and one file.
    #
    # RENUMBERED, and this is no longer hypothetical: this was written as
    # migration 5, LLM-COP-20's tietoa.facts reshape landed on main first and
    # took that number, and moving this function later in MIGRATIONS was the
    # whole of the change. That is what it was shaped for — it reads no row,
    # writes no payload, and nothing depends on it.
    #
    # IF NOT EXISTS is what makes the renumber safe rather than merely
    # tidy, and it is now load-bearing: a developer whose database ran this
    # as 5 before the rebase is stamped at user_version 5, so migrate() runs
    # it again as 6. Without IF NOT EXISTS that is "table uploads already
    # exists" on startup — the app dead in the water on the machine of
    # whoever tested the branch early.
    #
    # created_at is an integer Unix epoch in seconds, the representation
    # migrations 2 and 3 use. byte_size is the length of the bytes we
    # STORED, which for a JPEG carrying an appendix is shorter than the
    # request body — see app/imagecheck.py on canonicalisation. width and
    # height are the dimensions the validator read out of IHDR or SOF and
    # bounded; they make that bound auditable after the fact.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploads (
            id           INTEGER PRIMARY KEY,
            digest       TEXT NOT NULL UNIQUE,
            stored_name  TEXT NOT NULL,
            content_type TEXT NOT NULL,
            byte_size    INTEGER NOT NULL,
            width        INTEGER NOT NULL,
            height       INTEGER NOT NULL,
            created_at   INTEGER NOT NULL
        )
        """
    )


MIGRATIONS = [
    _migration_1,
    _migration_2,
    _migration_3,
    _migration_4,
    _migration_5,
    _migration_6,
]


def migrate(conn):
    """Apply every migration above the current user_version, then stamp it."""
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    for number, migration in enumerate(MIGRATIONS, start=1):
        if number > version:
            migration(conn)
            conn.execute(f"PRAGMA user_version = {number}")
    conn.commit()
