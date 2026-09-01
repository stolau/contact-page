"""The first-run wizard (LLM-COP-7): the guided five-step profile setup at
/yllapito/alustus, admin-gated like the rest of the admin surface.

The wizard invents no storage and no second form implementation. Every
step names an explicit, ordered subset of an existing kind's FIELDS, and
the browser draws those fields with the same shared builder the edit
panel uses (app/static/section-form.js), writing through the same draft
route (PUT /api/sections/<id>/draft). Finishing offers the same
POST /api/publish the panel's Julkaise posts.

The wizard never touches the public page: nothing here runs on GET /,
there is no before_app_request hook and no cookie. The offer fires at
exactly one point — login_target, called on the login success path.
"""

from flask import Blueprint, current_app, render_template, url_for

from . import auth
from . import db as database
from .fields import FIELD_LABELS, FIELDS
from .sections import draft_sections

bp = Blueprint("wizard", __name__)

# The five steps, in order. Each names the kind it writes and the exact
# ordered field subset it owns — explicit rather than "whatever the kind
# has", because validate_payload takes whole payloads and steps 1 and 2
# both write hero and so must own disjoint fields.
#
# Nav labels are SECTION_NAMES' (app/fields.py) wherever a step is a
# whole section, so a section is called the same thing in the wizard's
# nav, the edit panel and the section list. Steps 1 and 2 are the one
# exception: they split hero in two, so step 2 keeps hero's own
# "Aloitusosio" and step 1 takes the invented "Perustiedot".
#
# Steps 1, 3, 4 and 5 have no designed contents anywhere in the spec —
# their field lists and every step description below are inferred, and
# the PR body says so. Only step 2 is designed. No step names its own
# labels or counter format: the browser draws what the panel draws,
# straight from FIELD_LABELS.
STEPS = [
    {
        "label": "Perustiedot",
        "kind": "hero",
        "title": "Perustiedot",
        "description": (
            "Nimen ylä- ja alapuolen tiedot sekä yritystiedot. "
            "Voit muuttaa tekstejä myöhemmin milloin tahansa."
        ),
        "only": ["kicker", "subtitle", "credentials"],
        "helpers": {},
        "muotokuva": False,
    },
    {
        "label": "Aloitusosio",
        "kind": "hero",
        "title": "Aloitusosio",
        "description": (
            "Muotokuva, otsikko ja esittelyteksti. "
            "Voit muuttaa tekstejä myöhemmin milloin tahansa."
        ),
        "only": ["title", "ingress"],
        "helpers": {"title": "Nimi tai nimi + ammattinimike"},
        "muotokuva": True,
    },
    {
        "label": "Palvelut",
        "kind": "palvelut",
        "title": "Palvelut",
        "description": (
            "Palvelut, jotka näkyvät etusivulla. "
            "Voit muuttaa tekstejä myöhemmin milloin tahansa."
        ),
        "only": ["services", "more_label"],
        "helpers": {},
        "muotokuva": False,
    },
    {
        "label": "Vastaanottoajat",
        "kind": "vastaanottoajat",
        "title": "Vastaanottoajat",
        "description": (
            "Vastaanottopäivät ja -ajat sekä ohje ajanvaraukseen. "
            "Voit muuttaa tekstejä myöhemmin milloin tahansa."
        ),
        "only": ["days", "booking_note"],
        "helpers": {},
        "muotokuva": False,
    },
    {
        "label": "Yhteydenottolomake",
        "kind": "yhteydenotto",
        "title": "Yhteydenottolomake",
        "description": (
            "Yhteydenottolomakkeen kentät ja kiitosviesti. "
            "Voit muuttaa tekstejä myöhemmin milloin tahansa."
        ),
        "only": [
            "name_label",
            "email_label",
            "message_label",
            "send_label",
            "thanks",
        ],
        "helpers": {},
        "muotokuva": False,
    },
]


def _connect():
    return database.connect(current_app.config["DATABASE"])


def is_first_run(conn):
    """The owner has never published.

    sections.previous_published is written only by sections.publish_dirty;
    the seed leaves it NULL on every row. NULL everywhere == no Julkaise
    has ever landed.

    Not "published IS NULL", which never holds: create_app migrates and
    seeds at factory time, and seed_if_empty inserts all six kinds with
    draft == published, so a wizard gated on that would never appear.
    A Julkaise with nothing dirty leaves this True, which is correct —
    nothing was published.
    """
    row = conn.execute(
        "SELECT 1 FROM sections WHERE previous_published IS NOT NULL LIMIT 1"
    ).fetchone()
    return row is None


def login_target(conn):
    """Where a successful login lands.

    The wizard's whole offer, and the only place it is offered: an owner
    who has never published is walked into setup, everyone else lands on
    the page. A second login on a still-unconfigured site offers it
    again, which is right — the site is still unconfigured.
    """
    if is_first_run(conn):
        return url_for("wizard.alustus")
    return url_for("page")


@bp.route("/yllapito/alustus")
@auth.require_admin
def alustus():
    """The wizard shell: server-rendered chrome for all five steps, plus a
    JSON bootstrap wizard.js draws the current step's form from.

    Renders regardless of is_first_run — the wizard is a re-runnable
    guided edit reachable from the topbar forever after, never a one-shot
    gate. It writes nothing: it reads the drafts and nothing else.
    """
    conn = _connect()
    try:
        sections = draft_sections(conn, include_hidden=True)
    finally:
        conn.close()
    bootstrap = {
        "sections": sections,
        "fields": FIELDS,
        "field_labels": FIELD_LABELS,
        "steps": STEPS,
    }
    return render_template("wizard.html", steps=STEPS, bootstrap=bootstrap)
