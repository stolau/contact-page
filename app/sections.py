"""Section state: the badge mapping and loading the visible sections."""

import json


def badge(state, draft, published):
    """The admin-panel badge for a section row.

    Piilotettu wins over everything; a published section whose draft equals
    its published payload is Julkaistu; anything else (a dirty draft, or a
    published state with nothing published yet) is Luonnos.
    """
    if state == "hidden":
        return "Piilotettu"
    if state == "published" and published is not None and draft == published:
        return "Julkaistu"
    return "Luonnos"


def visible_sections(conn):
    """The published sections in page order, payload = parsed published JSON."""
    rows = conn.execute(
        "SELECT id, kind, position, published FROM sections"
        " WHERE state = 'published' ORDER BY position"
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "payload": json.loads(row["published"]) if row["published"] else {},
        }
        for row in rows
    ]
