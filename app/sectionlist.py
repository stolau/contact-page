"""Section-list mode (LLM-COP-5): the /muokkaa/osiot screen, the row
fragment route, and the reorder / add / hide-show / restore API. Every
route is admin-gated with auth.require_admin.

Two conventions this module inherits rather than invents. Drafts are
written with json.dumps(..., ensure_ascii=False) in FIELDS[kind]
declaration order (app/edit.py:4-8) — a new section's blank draft and a
restore both go through it, so the badge's and publish's text-equality
comparisons stay honest. And the badge itself is app.sections.badge; this
module computes no badge of its own.

The row fragment is why there is a route per row: the draft PUT answers
only saved_at and badge (app/edit.py:96-99), so a client that wanted a
fresh summary or a fresh preview card would build both itself — the
summary strings in JavaScript beside app/summary.py, the six sections'
markup beside app/templates/page.html. Instead the client re-fetches
GET /muokkaa/osiot/rivi/<id> after every mutation and swaps two subtrees
out of it, and the server stays the only place either exists.

The refusal strings below are free text, not spec addresses: no criterion
in cp-main-edit-sections or cp-section-row asserts any of them.
"""

import json
import time

from flask import Blueprint, current_app, jsonify, render_template, request

from . import auth
from . import db as database
from .fields import ANCHORS, FIELD_LABELS, FIELDS, SECTION_NAMES
from .images import collect_unreferenced
from .sanitize import validate_payload
from .sections import badge
from .summary import blank_payload, summarize

bp = Blueprint("sectionlist", __name__)

# Näytä osio is refused when the row has nothing publishable to show.
# Each refusal carries the reason and the one thing that clears it, and
# the row menu renders the hint as its visible disabled reason.
NO_PUBLISHED = "osiolla ei ole julkaistua sisältöä"
NO_PUBLISHED_HINT = "Julkaise osio ensin"
BLANK_PUBLISHED = "osion sisältö on tyhjä"
BLANK_PUBLISHED_HINT = "Lisää sisältöä ja julkaise"

NO_PREVIOUS = "osiolla ei ole edellistä julkaistua versiota"
NO_PREVIOUS_HINT = "Julkaise osio ensin"

# PUT /api/sections/order takes the whole order or nothing: a partial
# list is a lost row, not a smaller write.
ORDER_MALFORMED = "ids puuttuu tai ei ole lista kokonaislukuja"
ORDER_NOT_WHOLE = "listassa on oltava jokainen osio täsmälleen kerran"

UNKNOWN_KIND = "tuntematon osiotyyppi"
KIND_PRESENT = "osiotyyppi on jo sivulla"
UNKNOWN_STATE = "tuntematon tila"
NOT_FOUND = "not found"


def _connect():
    return database.connect(current_app.config["DATABASE"])


def page_label(count):
    """"Etusivu · 6 osiota" — the topbar's count with its plural.

    Here rather than inline in edit_sections.html because adding a section
    changes it without a reload: the add response carries the fresh string
    and the client writes it in, exactly as it carries the badge and the
    summary. A client that counted its own rows would have to carry the
    Finnish plural rule too, and the two would drift.
    """
    return f"Etusivu · {count} {'osio' if count == 1 else 'osiota'}"


def _show_refusal(kind, published):
    """Why this row may not be flipped to state='published', or None.

    The public page gates on state alone and falls back to an empty
    payload (app/sections.py:22-24 and :30), so a row whose published
    column is NULL or blank renders as literally nothing once it is shown.
    The gate is on the transition, and it is this one expression — used
    both to answer the flip and to draw the menu item that requests it.
    """
    if published is None:
        return NO_PUBLISHED, NO_PUBLISHED_HINT
    if json.loads(published) == blank_payload(kind):
        return BLANK_PUBLISHED, BLANK_PUBLISHED_HINT
    return None


def list_rows(conn):
    """Every section in page order, with all a row needs to render itself.

    Its own SELECT rather than app.sections.draft_sections, because a row
    needs two flags the edit panel never wanted — can_restore and can_show
    — and app/sections.py is a shared file the units landing beside this
    one are also editing. The duplication is knowing, and named here.
    """
    rows = conn.execute(
        "SELECT id, kind, position, state, draft, published,"
        " previous_published FROM sections ORDER BY position"
    ).fetchall()
    out = []
    for row in rows:
        # The third copy of this fallback (app/sections.py:56 is the
        # sibling to keep it in step with): a row whose draft was never
        # written reads as the empty payload rather than raising.
        payload = json.loads(row["draft"]) if row["draft"] else {}
        refusal = _show_refusal(row["kind"], row["published"])
        out.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "position": row["position"],
                "state": row["state"],
                "badge": badge(row["state"], row["draft"], row["published"]),
                "payload": payload,
                "summary": summarize(row["kind"], payload),
                "can_restore": row["previous_published"] is not None,
                "can_show": refusal is None,
                "show_reason": None if refusal is None else refusal[1],
            }
        )
    return out


def _one_row(conn, section_id):
    """One row in exactly the shape list_rows gives it.

    Deliberately the same builder rather than a second SELECT: the row
    fragment and the row inside the page document must be byte-identical,
    and the cheapest way to guarantee that is one code path.
    """
    for row in list_rows(conn):
        if row["id"] == section_id:
            return row
    return None


def _render_row(section):
    return render_template(
        "_row_fragment.html",
        section=section,
        section_names=SECTION_NAMES,
        anchors=ANCHORS,
    )


@bp.route("/muokkaa/osiot")
@auth.require_admin
def osiot():
    """The section list: every row server-rendered in position order.

    The context is deliberately narrow. _section_row.html imports
    page.html to reuse the public macros, and an import with context
    executes that template's module body — which iterates `sections` and
    dereferences `nav_labels` while doing it. Neither name is bound here
    (the row list is `rows`), so the module body's loops find an undefined
    iterable, yield nothing, and their output is discarded. `anchors` is
    bound because every public macro dereferences it.
    """
    conn = _connect()
    try:
        rows = list_rows(conn)
    finally:
        conn.close()
    bootstrap = {
        "rows": rows,
        "fields": FIELDS,
        "field_labels": FIELD_LABELS,
        "section_names": SECTION_NAMES,
        "anchors": ANCHORS,
    }
    return render_template(
        "edit_sections.html",
        rows=rows,
        page_label=page_label(len(rows)),
        section_names=SECTION_NAMES,
        anchors=ANCHORS,
        bootstrap=bootstrap,
    )


@bp.route("/muokkaa/osiot/rivi/<int:section_id>")
@auth.require_admin
def rivi(section_id):
    """One row's HTML, re-fetched by the client after every mutation."""
    conn = _connect()
    try:
        section = _one_row(conn, section_id)
    finally:
        conn.close()
    if section is None:
        return jsonify(error=NOT_FOUND), 404
    return _render_row(section)


def _order_error(conn, body):
    """Why this reorder is refused, or None — checked before any write.

    The whole order arrives or nothing does: a list that is missing a row,
    names one twice, or names a row that does not exist would silently
    leave positions behind, and a position nobody set is a page order
    nobody chose.
    """
    if not isinstance(body, dict):
        return ORDER_MALFORMED
    ids = body.get("ids")
    if not isinstance(ids, list):
        return ORDER_MALFORMED
    for section_id in ids:
        # bool is an int in Python; it is not a section id.
        if not isinstance(section_id, int) or isinstance(section_id, bool):
            return ORDER_MALFORMED
    if len(set(ids)) != len(ids):
        return ORDER_NOT_WHOLE
    known = {
        row["id"] for row in conn.execute("SELECT id FROM sections").fetchall()
    }
    if set(ids) != known:
        return ORDER_NOT_WHOLE
    return None


@bp.route("/api/sections/order", methods=["PUT"])
@auth.require_admin
def put_order():
    """Whole-order write: positions 1..n follow the ids as sent.

    sqlite3 opens the implicit transaction at the first UPDATE and holds
    it to the single commit below, so every position lands or none does.
    auth.audit runs after that commit, never between the updates, because
    it commits internally (app/auth.py:103-113) — the ordering
    app/edit.py:94-95 already uses.
    """
    body = request.get_json(silent=True)
    conn = _connect()
    try:
        error = _order_error(conn, body)
        if error is not None:
            return jsonify(error=error), 400
        ids = body["ids"]
        for position, section_id in enumerate(ids, start=1):
            conn.execute(
                "UPDATE sections SET position = ? WHERE id = ?",
                (position, section_id),
            )
        conn.commit()
        auth.audit(
            conn, "sections reordered ids=" + ",".join(str(i) for i in ids)
        )
        return jsonify(ids=ids)
    finally:
        conn.close()


@bp.route("/api/sections", methods=["POST"])
@auth.require_admin
def post_section():
    """Add one section of a kind the page does not have yet.

    It arrives hidden, last in the order, with a blank draft and nothing
    published — badge Piilotettu — so adding a section and then never
    publishing it leaves the public page exactly as it was.
    """
    body = request.get_json(silent=True) or {}
    kind = body.get("kind")
    conn = _connect()
    try:
        if kind not in FIELDS:
            return jsonify(error=UNKNOWN_KIND), 400
        present = {
            row["kind"]
            for row in conn.execute("SELECT kind FROM sections").fetchall()
        }
        if kind in present:
            return jsonify(error=KIND_PRESENT), 400
        # Through the same validator the draft PUT uses, so the row's
        # first stored text is exactly what a no-op save would produce.
        clean, errors = validate_payload(kind, blank_payload(kind))
        if errors:  # pragma: no cover - the schema's own zero values
            return jsonify(errors=errors), 400
        (top,) = conn.execute(
            "SELECT COALESCE(MAX(position), 0) FROM sections"
        ).fetchone()
        cursor = conn.execute(
            "INSERT INTO sections (kind, position, state, draft, published,"
            " previous_published) VALUES (?, ?, 'hidden', ?, NULL, NULL)",
            (kind, top + 1, json.dumps(clean, ensure_ascii=False)),
        )
        conn.commit()
        section_id = cursor.lastrowid
        auth.audit(conn, f"section added kind={kind} id={section_id}")
        rows = list_rows(conn)
        section = next(row for row in rows if row["id"] == section_id)
        count = len(rows)
    finally:
        conn.close()
    return (
        jsonify(
            id=section["id"],
            kind=section["kind"],
            state=section["state"],
            badge=section["badge"],
            # The blank payload the row's form starts from, so the client
            # never has to build one and keep a copy of the schema.
            payload=section["payload"],
            # The topbar's count, freshly rendered: the row the client is
            # about to append makes the served one wrong, and this is the
            # same string the reloaded screen would show.
            page_label=page_label(count),
            html=_render_row(section),
        ),
        201,
    )


@bp.route("/api/sections/<int:section_id>/state", methods=["POST"])
@auth.require_admin
def post_state(section_id):
    """Hide or show one section — state only, nothing else is touched."""
    body = request.get_json(silent=True) or {}
    state = body.get("state")
    if state not in ("hidden", "published"):
        return jsonify(error=UNKNOWN_STATE), 400
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, kind, draft, published FROM sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if row is None:
            return jsonify(error=NOT_FOUND), 404
        if state == "published":
            refusal = _show_refusal(row["kind"], row["published"])
            if refusal is not None:
                return jsonify(error=refusal[0], hint=refusal[1]), 409
        conn.execute(
            "UPDATE sections SET state = ? WHERE id = ?", (state, section_id)
        )
        conn.commit()
        auth.audit(conn, f"section state {state} id={section_id}")
        return jsonify(badge=badge(state, row["draft"], row["published"]))
    finally:
        conn.close()


@bp.route("/api/sections/<int:section_id>/restore", methods=["POST"])
@auth.require_admin
def post_restore(section_id):
    """Palauta edellinen versio: previous_published back into the DRAFT.

    One step, and only that step — published, previous_published and
    state are left alone, so the restore still needs a Julkaise to reach
    the public page and the screen says so. The bytes are copied
    verbatim rather than re-validated and re-serialized: they were
    produced by the same json.dumps convention, so a restore followed by
    Julkaise puts back a published payload byte-identical to the one that
    was there before.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, state, published, previous_published FROM sections"
            " WHERE id = ?",
            (section_id,),
        ).fetchone()
        if row is None:
            return jsonify(error=NOT_FOUND), 404
        if row["previous_published"] is None:
            return jsonify(error=NO_PREVIOUS, hint=NO_PREVIOUS_HINT), 409
        text = row["previous_published"]
        conn.execute(
            "UPDATE sections SET draft = ? WHERE id = ?", (text, section_id)
        )
        conn.commit()
        auth.audit(conn, f"section restored id={section_id}")
        # The replaced draft's digest may have been this store's last
        # reference to a picture (LLM-COP-27).
        collect_unreferenced(conn)
        return jsonify(
            badge=badge(row["state"], text, row["published"]),
            restored_at=int(time.time()),
            payload=json.loads(text),
        )
    finally:
        conn.close()
