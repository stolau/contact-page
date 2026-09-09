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
from .images import collect_unreferenced
from .palette import ROLE_TOKENS
from .sanitize import validate_payload
from .sections import (
    badge,
    contact_dialog_copy,
    draft_sections,
    publish_dirty,
    site_chrome,
)
from .shapes import SHAPE_CHOICES
from .styles import STYLE_CHOICES, resolve_style, template_for

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
        # The RAW drafted style, deliberately not resolve_style'd: the
        # Ulkoasu tab marks an option active only when the owner has
        # actually chosen one, and resolve_style("") would mark Perus on a
        # fresh install before anything was ever written (LLM-COP-22).
        active_style = site_chrome(conn, "draft")["site_style"]
    finally:
        conn.close()
    # The skin's OWN two colours, so the Ulkoasu tab's swatches show the real
    # header and button colours before the owner has chosen anything — an
    # <input type="color"> has no empty state to show instead, and defaulting
    # it to #000000 would tell the owner their header was black.
    #
    # resolve_style'd here, unlike active_style above: the mark on the style
    # list has to tell "" apart from "v1", but the swatch has to show the
    # colours of the skin that is ACTUALLY rendering, which for "" is the
    # default one. The values are ROLE_TOKENS' frozen literals, so there is
    # one copy of them and it is the one app/palette.py derives from.
    skin = ROLE_TOKENS[resolve_style(active_style)]
    color_defaults = {
        "main": skin["default_main"],
        "accent": skin["default_accent"],
    }
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
        styles=STYLE_CHOICES,
        # The two crops the Kuvan muoto row offers (LLM-COP-28), passed the
        # way styles is: the vocabulary lives in one Python module
        # (app/shapes.py) and the template renders whatever it names, so
        # offering a third crop is one tuple there and nothing here.
        #
        # No active_shape beside it, unlike the style: image_shape belongs to
        # the section the row is visible for, so the mark comes from the open
        # section's draft in edit.js rather than from a server-rendered
        # attribute — the arrangement the Ilmoitus row already has.
        shapes=SHAPE_CHOICES,
        active_style=active_style,
        color_defaults=color_defaults,
    )


@bp.route("/muokkaa/esikatselu")
@auth.require_admin
def esikatselu():
    """The real page, rendered from the drafts — the preview iframe's
    document, and Esikatsele's full-page target."""
    conn = _connect()
    try:
        sections = draft_sections(conn)
        chrome = site_chrome(conn, "draft")
        dialog_copy = contact_dialog_copy(conn, "draft")
    finally:
        conn.close()
    return render_template(
        # The DRAFT style (LLM-COP-22). A preview that ignored the drafted
        # skin would show the owner a page they are not about to publish.
        template_for(chrome["site_style"]),
        sections=sections,
        nav_labels=NAV_LABELS,
        anchors=ANCHORS,
        preview=True,
        **chrome,
        **dialog_copy,
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
        # This write can have dropped the previous draft's digest
        # (LLM-COP-27). The picture goes only if no other column of any
        # section still names it and it is past the retention floor.
        collect_unreferenced(conn)
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
        # Publishing a dirty section overwrites its previous_published, and
        # that is the exact moment a picture reachable only by a rollback
        # becomes garbage (LLM-COP-27). Collect here rather than inside
        # publish_dirty: this route is its only caller, and app/sections.py
        # stays untouched. A publish with nothing dirty moves no column and
        # collects nothing, correctly.
        collect_unreferenced(conn)
        return jsonify(published=ids)
    finally:
        conn.close()
