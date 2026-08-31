"""Flask application factory for the public contact page."""

import os

from flask import Flask, render_template
from markupsafe import Markup

from . import db as database
from .fields import ANCHORS, NAV_LABELS
from .sections import visible_sections
from .seed import seed_if_empty


def create_app(instance_path=None):
    app = Flask(__name__, instance_path=instance_path)
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.setdefault(
        "DATABASE", os.path.join(app.instance_path, "site.sqlite3")
    )

    conn = database.connect(app.config["DATABASE"])
    try:
        database.migrate(conn)
        seed_if_empty(conn)
    finally:
        conn.close()

    @app.template_filter("render_rich")
    def render_rich(value):
        # The one place rich fields become markup. Today the only writer is
        # the trusted seed; the sanitizer plugs in here with the first
        # untrusted write path (LLM-COP-4/6).
        return Markup(value)

    @app.route("/")
    def page():
        conn = database.connect(app.config["DATABASE"])
        try:
            sections = visible_sections(conn)
        finally:
            conn.close()
        return render_template(
            "page.html",
            sections=sections,
            nav_labels=NAV_LABELS,
            anchors=ANCHORS,
        )

    return app
