"""Flask application factory for the public contact page."""

import os

import click
from flask import Flask, redirect, render_template, request, url_for
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

from . import auth
from . import db as database
from .fields import ANCHORS, NAV_LABELS
from .sections import visible_sections
from .seed import seed_if_empty

# One generic failure string: wrong password and unknown username answer
# byte-identically, so the response never reveals whether a username exists.
LOGIN_ERROR = "Väärä käyttäjätunnus tai salasana."


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

    def render_page(**dialog):
        """The public page, optionally with the login dialog overlaid."""
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
            **dialog,
        )

    @app.route("/")
    def page():
        return render_page()

    @app.route("/yllapito")
    def yllapito():
        # The login dialog over the dimmed public page. ?unohtui=1 adds the
        # forgot-password note (the password is reset with the server CLI —
        # no mail flow, per LLM-COP-2). An already-authenticated admin was
        # left undecided in the spec; decision: render the dialog anyway —
        # it is harmless, stateless, and signing in again just mints a
        # fresh session.
        return render_page(
            login_dialog=True,
            forgot="unohtui" in request.args,
        )

    @app.route("/yllapito/kirjaudu", methods=["POST"])
    def kirjaudu():
        username = request.form.get("kayttajatunnus", "")
        password = request.form.get("salasana", "")
        remember = bool(request.form.get("pysy"))
        conn = database.connect(app.config["DATABASE"])
        try:
            auth.throttle_failures(conn)
            user = conn.execute(
                "SELECT * FROM admin_user WHERE username = ?", (username,)
            ).fetchone()
            if user is not None and check_password_hash(
                user["password_hash"], password
            ):
                auth.audit(conn, f"login ok username={username}")
                token = auth.mint_session(conn, remember)
                response = redirect(url_for("page"))
                # Secure is omitted deliberately: the site is served over
                # plain HTTP, and a Secure cookie would never come back.
                response.set_cookie(
                    auth.SESSION_COOKIE,
                    token,
                    httponly=True,
                    samesite="Lax",
                    max_age=auth.REMEMBER_LIFETIME if remember else None,
                )
                return response
            # The two audit rows differ; the two responses must not.
            if user is None:
                auth.audit(
                    conn, f"login failed (unknown username) username={username}"
                )
            else:
                auth.audit(
                    conn, f"login failed (wrong password) username={username}"
                )
        finally:
            conn.close()
        return render_page(
            login_dialog=True,
            login_error=LOGIN_ERROR,
            login_username=username,
        )

    @app.route("/yllapito/kirjaudu-ulos", methods=["POST"])
    @auth.require_admin
    def kirjaudu_ulos():
        conn = database.connect(app.config["DATABASE"])
        try:
            row = auth.current_admin_session(conn)
            if row is not None:
                auth.delete_session(conn, row["id"])
        finally:
            conn.close()
        response = redirect(url_for("page"))
        response.delete_cookie(auth.SESSION_COOKIE)
        return response

    @app.cli.command("admin-create")
    @click.argument("username")
    def admin_create(username):
        """Create the single admin account (refuses when one exists).

        Runs without the server: create_app opened and migrated the
        database directly, so this works against the file itself.
        """
        conn = database.connect(app.config["DATABASE"])
        try:
            if conn.execute("SELECT 1 FROM admin_user").fetchone():
                raise click.ClickException(
                    "an admin account already exists;"
                    " use admin-reset-password"
                )
            password = click.prompt(
                "Password", hide_input=True, confirmation_prompt=True
            )
            conn.execute(
                "INSERT INTO admin_user (username, password_hash)"
                " VALUES (?, ?)",
                (username, generate_password_hash(password)),
            )
            conn.commit()
        finally:
            conn.close()
        click.echo(f"admin account '{username}' created")

    @app.cli.command("admin-reset-password")
    def admin_reset_password():
        """Set a new password for the admin account (server not needed)."""
        conn = database.connect(app.config["DATABASE"])
        try:
            row = conn.execute("SELECT id FROM admin_user").fetchone()
            if row is None:
                raise click.ClickException(
                    "no admin account exists; use admin-create"
                )
            password = click.prompt(
                "New password", hide_input=True, confirmation_prompt=True
            )
            conn.execute(
                "UPDATE admin_user SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), row["id"]),
            )
            conn.commit()
        finally:
            conn.close()
        click.echo("admin password reset")

    return app
