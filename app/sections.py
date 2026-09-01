"""Section state: the badge mapping, the section loaders, and publish."""

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


def draft_sections(conn, include_hidden=False):
    """The sections in page order, payload = parsed draft JSON.

    Hidden rows are excluded by default, mirroring visible_sections'
    visibility rule, so the draft preview hides what the public page
    hides; include_hidden=True keeps them for the edit panel, where a
    hidden section stays editable.
    """
    where = "" if include_hidden else " WHERE state != 'hidden'"
    rows = conn.execute(
        "SELECT id, kind, position, state, draft, published FROM sections"
        + where
        + " ORDER BY position"
    ).fetchall()
    return [
        {
            "id": row["id"],
            "kind": row["kind"],
            "state": row["state"],
            "badge": badge(row["state"], row["draft"], row["published"]),
            "payload": json.loads(row["draft"]) if row["draft"] else {},
        }
        for row in rows
    ]


def initials(brand):
    """The avatar's letters: the first letter of each of the first two words,
    upper-cased. An empty brand gives "" rather than an IndexError."""
    return "".join(word[0] for word in brand.split()[:2]).upper()


def site_chrome(conn, column="published"):
    """The page-wide chrome the templates render — brand, browser title and
    footer — plus the avatar initials derived from the brand (LLM-COP-10).

    Read from the hero row by kind and *ignoring state*, so hiding the
    Aloitusosio does not blank the header and the tab title. A missing row or
    missing keys give empty strings: a pre-migration or blank row must not
    raise.

    Returned as flat scalars, never a dict. page.html is imported as a macro
    module by _section_row.html with a context that binds none of these, and
    there an undefined bare name renders empty while attribute access on one
    raises UndefinedError — which would 500 the section-list routes.
    """
    row = conn.execute(
        f"SELECT {column} AS payload FROM sections WHERE kind = 'hero'"
    ).fetchone()
    payload = {}
    if row is not None and row["payload"]:
        payload = json.loads(row["payload"])
    brand = payload.get("brand", "")
    return {
        "site_brand": brand,
        "site_title": payload.get("page_title", ""),
        "site_footer": payload.get("footer", ""),
        "site_initials": initials(brand),
    }


def publish_dirty(conn):
    """Publish exactly the dirty sections (draft text != published text):
    previous_published takes the old published, published takes the draft.
    Returns the affected section ids in page order."""
    rows = conn.execute(
        "SELECT id, draft, published FROM sections ORDER BY position"
    ).fetchall()
    ids = [row["id"] for row in rows if row["draft"] != row["published"]]
    for section_id in ids:
        conn.execute(
            "UPDATE sections SET previous_published = published,"
            " published = draft WHERE id = ?",
            (section_id,),
        )
    conn.commit()
    return ids
