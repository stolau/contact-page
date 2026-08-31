"""Direct edit mode (LLM-COP-6): /muokkaa/sivu — the real page, rendered
from the drafts, with editing chrome over it and every bound scalar field
carrying its section id and field name as data attributes.

There is no write route here on purpose. Direct mode saves through the
same PUT /api/sections/<id>/draft and POST /api/publish the side panel
uses (app/edit.py), so one route validates, one sanitizer runs, and the
two editors cannot drift apart.

The identity in the top bar is the *account* — admin_user.username, one
row (app/__init__.py refuses a second) — not page copy: hero.title is a
field this very mode edits, so deriving the label from it would rename
the owner as they type their own heading.
"""

from flask import Blueprint, current_app, render_template

from . import auth
from . import db as database
from .fields import ANCHORS, FIELD_LABELS, FIELDS, NAV_LABELS, SECTION_NAMES
from .sections import draft_sections

bp = Blueprint("direct_edit", __name__)


def _connect():
    return database.connect(current_app.config["DATABASE"])


@bp.route("/muokkaa/sivu")
@auth.require_admin
def sivu():
    """Direct edit mode over the draft page."""
    conn = _connect()
    try:
        # Hidden sections excluded, the same call the draft preview makes:
        # direct mode edits what the page shows, nothing invisible.
        sections = draft_sections(conn)
        owner = conn.execute("SELECT username FROM admin_user").fetchone()
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
        "page.html",
        sections=sections,
        nav_labels=NAV_LABELS,
        anchors=ANCHORS,
        direct_edit=True,
        owner_name=owner["username"] if owner is not None else "",
        section_names=SECTION_NAMES,
        bootstrap=bootstrap,
    )
