"""Edit mode (LLM-COP-4): the /muokkaa shell, the draft preview, and the
draft/publish API. Every route is admin-gated with auth.require_admin.

Draft serialization convention: drafts are written with
json.dumps(..., ensure_ascii=False), keys in FIELDS[kind] declaration
order — the seed's own convention — so a no-op save is byte-identical to
the stored text and the badge/publish text-equality comparisons stay
honest.
"""

import json
import time

from flask import Blueprint, current_app, jsonify, render_template, request

from . import auth
from . import db as database
from .fields import ANCHORS, FIELD_LABELS, FIELDS, NAV_LABELS, SECTION_NAMES
from .sanitize import validate_payload
from .sections import badge, draft_sections, publish_dirty

bp = Blueprint("edit", __name__)


def _connect():
    return database.connect(current_app.config["DATABASE"])


@bp.route("/muokkaa")
@auth.require_admin
def muokkaa():
    """The edit shell: server-rendered chrome plus a JSON bootstrap the
    panel controller (edit.js) builds the per-kind forms from."""
    conn = _connect()
    try:
        sections = draft_sections(conn, include_hidden=True)
    finally:
        conn.close()
    bootstrap = {
        "sections": sections,
        "fields": FIELDS,
        "field_labels": FIELD_LABELS,
        "section_names": SECTION_NAMES,
        "anchors": ANCHORS,
    }
    return render_template(
        "edit.html",
        sections=sections,
        section_names=SECTION_NAMES,
        bootstrap=bootstrap,
    )


@bp.route("/muokkaa/esikatselu")
@auth.require_admin
def esikatselu():
    """The real page, rendered from the drafts — the preview iframe's
    document, and Esikatsele's full-page target."""
    conn = _connect()
    try:
        sections = draft_sections(conn)
    finally:
        conn.close()
    return render_template(
        "page.html",
        sections=sections,
        nav_labels=NAV_LABELS,
        anchors=ANCHORS,
        preview=True,
    )


@bp.route("/api/sections/<int:section_id>/draft", methods=["PUT"])
@auth.require_admin
def put_draft(section_id):
    """Whole-payload draft write: validate against FIELDS[kind], sanitize
    rich fields, store. Last write wins; no server-side field merge."""
    payload = request.get_json(silent=True)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id, kind, state, published FROM sections WHERE id = ?",
            (section_id,),
        ).fetchone()
        if row is None:
            return jsonify(error="not found"), 404
        clean, errors = validate_payload(row["kind"], payload)
        if errors:
            return jsonify(errors=errors), 400
        text = json.dumps(clean, ensure_ascii=False)
        conn.execute(
            "UPDATE sections SET draft = ? WHERE id = ?", (text, section_id)
        )
        conn.commit()
        auth.audit(conn, f"draft saved section={section_id}")
        return jsonify(
            saved_at=int(time.time()),
            badge=badge(row["state"], text, row["published"]),
        )
    finally:
        conn.close()


@bp.route("/api/publish", methods=["POST"])
@auth.require_admin
def publish():
    """Julkaise: publish exactly the sections whose draft differs from
    their published payload."""
    conn = _connect()
    try:
        ids = publish_dirty(conn)
        auth.audit(
            conn,
            "publish sections=" + (",".join(str(i) for i in ids) or "none"),
        )
        return jsonify(published=ids)
    finally:
        conn.close()
