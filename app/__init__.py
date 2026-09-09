"""Flask application factory for the public contact page."""

import os

import click
from flask import (
    Flask,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

from . import auth, totp
from . import db as database
from .direct_edit import bp as direct_edit_bp
from .edit import bp as edit_bp
from .fields import ANCHORS, NAV_LABELS
from .images import bp as images_bp
from .images import image_url
from .messages import bp as messages_bp
from .notice import contact_notice
from .sanitize import sanitize_rich
from .sectionlist import bp as sectionlist_bp
from .sections import contact_dialog_copy, site_chrome, visible_sections
from .seed import seed_if_empty
from .shapes import resolve_shape
from .styles import template_for
from .wizard import bp as wizard_bp
from .wizard import login_target

# One generic failure string: wrong password and unknown username answer
# byte-identically, so the response never reveals whether a username exists.
LOGIN_ERROR = "Väärä käyttäjätunnus tai salasana."

# Verified against when the username is unknown, so both failure paths pay
# the same hashing cost — skipping check_password_hash for unknown usernames
# answers measurably faster and leaks user existence through response timing
# (timing-based user enumeration). Generated once at import.
_DUMMY_HASH = generate_password_hash("dummy")


def _looks_like_a_totp_code(code):
    """Is this input shaped like a TOTP code rather than a recovery code?

    isascii() as well as isdigit() deliberately: str.isdigit() is True for
    non-ASCII digit characters (Arabic-Indic, fullwidth) that could never
    match a candidate hotp() produced, so without the guard those inputs
    would be treated as codes and never reach the recovery path.

    A generated recovery code fails this STRUCTURALLY — 23 characters with
    three hyphens (auth.issue_recovery_codes) — not probabilistically.
    """
    return (
        len(code) == totp.TOTP_DIGITS and code.isascii() and code.isdigit()
    )


def create_app(instance_path=None):
    app = Flask(__name__, instance_path=instance_path)
    # Keep |tojson in declaration order: the edit panel draws a section's
    # fields in the key order of the bootstrap JSON, so alphabetising it
    # reorders the form (app/fields.py). This policy — not
    # app.json.sort_keys — is the knob that path reads: sort_keys on the
    # provider only defaults a missing kwarg, and Jinja always passes this
    # policy explicitly, so the provider attribute never gets consulted and
    # setting it does nothing here. Rebind the key rather than mutating it:
    # Environment.policies is a shallow copy of Jinja's module-level
    # defaults, so assigning into the existing dict would flip sorting off
    # for every Jinja environment in the process, ours or not.
    app.jinja_env.policies["json.dumps_kwargs"] = {"sort_keys": False}
    os.makedirs(app.instance_path, exist_ok=True)
    app.config.setdefault(
        "DATABASE", os.path.join(app.instance_path, "site.sqlite3")
    )
    # Uploaded images live beside the database, under the instance
    # directory: gitignored, and lost on redeploy exactly as the database
    # is (README.md says so out loud). No app-wide MAX_CONTENT_LENGTH —
    # the upload cap is per-request in app/images.py, so no other route's
    # behaviour changes.
    app.config.setdefault(
        "UPLOAD_DIR", os.path.join(app.instance_path, "uploads")
    )
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)

    conn = database.connect(app.config["DATABASE"])
    try:
        database.migrate(conn)
        seed_if_empty(conn)
    finally:
        conn.close()

    app.register_blueprint(edit_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(sectionlist_bp)
    app.register_blueprint(wizard_bp)
    app.register_blueprint(direct_edit_bp)
    app.register_blueprint(images_bp)

    # A stored reference to a URL, or None. Registered as a filter so the
    # public template can ask for one without importing anything.
    app.add_template_filter(image_url, "image_url")

    # The contact band's availability notice, resolved from the whole
    # payload (USR-COP-4). Registered once, here, and that covers BOTH
    # skins and all three renderers: the public page, the draft preview
    # (app/edit.py) and direct edit (app/direct_edit.py) all render through
    # template_for, so there is one filter registry between them.
    app.add_template_filter(contact_notice, "contact_notice")

    # How a section's own picture is cropped (LLM-COP-28), resolved from the
    # stored value and never trusted raw (app/shapes.py). Registered here for
    # the reason contact_notice's registration gives directly above: one
    # filter registry covers the public page, the draft preview and direct
    # edit, because all three render through template_for. Named image_shape
    # after the FIELD it resolves, not after resolve_shape, so a template
    # reads `p.image_shape|image_shape` — the field's raw value in, the
    # renderable one out.
    app.add_template_filter(resolve_shape, "image_shape")

    @app.template_filter("render_rich")
    def render_rich(value):
        # The one place rich fields become markup. Drafts are sanitized on
        # write (app/edit.py) — that stays primary; sanitizing again here
        # is defense in depth for anything already in the store.
        return Markup(sanitize_rich(value))

    def render_page(**dialog):
        """The public page, optionally with the login dialog overlaid."""
        conn = database.connect(app.config["DATABASE"])
        try:
            sections = visible_sections(conn)
            chrome = site_chrome(conn)
            dialog_copy = contact_dialog_copy(conn)
        finally:
            conn.close()
        # The PUBLISHED style picks the template (LLM-COP-22). Selection is a
        # template-name choice in Python, never an {% if %} inside page.html,
        # so V1's served bytes cannot move when no style is stored.
        return render_template(
            template_for(chrome["site_style"]),
            sections=sections,
            nav_labels=NAV_LABELS,
            anchors=ANCHORS,
            **chrome,
            **dialog_copy,
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
        # Set only on the second-factor branch; the answer for it is built
        # after the connection is closed, where every other render_page
        # return in this file already lives.
        pending_token = None
        conn = database.connect(app.config["DATABASE"])
        try:
            key = auth.bucket_key(auth.client_key())
            # The gate is taken BEFORE the username is looked up and before
            # any hash is computed. Three things follow, all deliberate:
            #   - nothing on the refused path depends on the username, so a
            #     throttled attempt cannot answer "does this user exist?";
            #   - a flood costs one indexed read and no write lock instead of
            #     a full scrypt;
            #   - the count is read and the row written as one atomic step,
            #     so concurrent requests cannot all pass the gate on the same
            #     count (see auth.admit_login_attempt).
            # The price of that ordering is that a correct password cannot end
            # a lockout either — see LOGIN_FAILURE_WINDOW in app/auth.py and
            # the login-unlock command below.
            # The single shared return at the end is what makes the throttled
            # and failed responses identical.
            admitted, crossed = auth.admit_login_attempt(conn, key)
            if admitted:
                user = conn.execute(
                    "SELECT * FROM admin_user WHERE username = ?", (username,)
                ).fetchone()
                # Hash-check even for an unknown username (against
                # _DUMMY_HASH) so both failure paths take the same time; see
                # _DUMMY_HASH.
                stored = (
                    user["password_hash"] if user is not None else _DUMMY_HASH
                )
                ok = check_password_hash(stored, password) and user is not None
                if ok and user["totp_enabled"]:
                    # A correct password on an enrolled account buys ONE
                    # thing: the code step. No sessions row is written here.
                    auth.audit(
                        conn,
                        "login password ok, code required"
                        f" username={username}",
                    )
                    # NOT clear_login_attempts, and this is the whole
                    # brute-force story: clearing here would let an attacker
                    # holding the password re-post it before every code
                    # guess and get unlimited attempts at six digits. The
                    # counter is cleared only when the WHOLE login
                    # completes, in koodi() below.
                    pending_token = auth.mint_pending(
                        conn, user["id"], remember
                    )
                elif ok:
                    auth.audit(conn, f"login ok username={username}")
                    # Deletes this attempt's own row too: a success leaves the
                    # client with a clean counter. `crossed` is ignored here —
                    # an attempt that crossed and then succeeded is not a
                    # lockout.
                    auth.clear_login_attempts(conn, key)
                    token = auth.mint_session(conn, remember)
                    response = redirect(login_target(conn))
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
                else:
                    # The two audit rows differ; the two responses must not.
                    if user is None:
                        auth.audit(
                            conn,
                            "login failed (unknown username)"
                            f" username={username}",
                        )
                    else:
                        auth.audit(
                            conn,
                            "login failed (wrong password)"
                            f" username={username}",
                        )
                if crossed:
                    # Once per lockout, not once per refused request — see
                    # app/auth.py on why the refused path writes nothing.
                    # The one-step success returned above and never reaches
                    # this; the second-factor branch does, and should, because
                    # it did NOT clear the counter — crossing there is a real
                    # lockout, and the code step is the next thing refused.
                    auth.audit(conn, f"login throttled client_key={key}")
        finally:
            conn.close()
        if pending_token is not None:
            # make_response because render_page answers a STRING (it ends
            # in render_template), and only a Response carries a cookie.
            response = make_response(
                render_page(login_dialog=True, totp_step=True)
            )
            # A session cookie (no max_age): the pending row carries its own
            # 5-minute expiry, and this half-state should not outlive the
            # browser. Secure is omitted for the reason given above.
            response.set_cookie(
                auth.PENDING_COOKIE,
                pending_token,
                httponly=True,
                samesite="Lax",
            )
            return response
        return render_page(
            login_dialog=True,
            login_error=LOGIN_ERROR,
            login_username=username,
        )

    @app.route("/yllapito/koodi", methods=["POST"])
    def koodi():
        """The second step: a TOTP code, or a single-use recovery code.

        Same discipline as kirjaudu above — the rate-limit gate is taken
        before anything is verified, every refusal answers the same bytes,
        and the render_page return sits outside the try so only one
        connection is ever open.
        """
        code = request.form.get("koodi", "").strip()
        response = None  # set only when the whole login completed
        conn = database.connect(app.config["DATABASE"])
        try:
            key = auth.bucket_key(auth.client_key())
            # A request with no pending cookie still consumes a slot, so the
            # code endpoint cannot be hammered for free. /yllapito/kirjaudu
            # already behaves this way.
            admitted, crossed = auth.admit_login_attempt(conn, key)
            if admitted:
                pending = auth.current_pending_login(conn)
                if pending is not None:
                    user = conn.execute(
                        "SELECT * FROM admin_user WHERE id = ?",
                        (pending["user_id"],),
                    ).fetchone()
                    # Bound on EVERY path below, including the ordinary
                    # wrong-six-digit typo, which takes neither branch.
                    accepted = False
                    how = ""
                    step = totp.accepted_step(
                        totp.decode_secret(user["totp_secret"]),
                        code,
                        user["totp_last_step"],
                    )
                    if step is not None:
                        # The replay guard, advanced on the TOTP branch only
                        # — a recovery code says nothing about a time step.
                        conn.execute(
                            "UPDATE admin_user SET totp_last_step = ?"
                            " WHERE id = ?",
                            (step, user["id"]),
                        )
                        conn.commit()
                        accepted = True
                        how = "2fa"
                    elif not _looks_like_a_totp_code(code):
                        # The recovery path is tried only when the input is
                        # not six ASCII digits. That keeps ten scrypt
                        # verifications off the ordinary-typo path, where
                        # five attempts a window would otherwise cost fifty
                        # hashes — a CPU amplifier an attacker gets for
                        # free. It is not an oracle: it reveals only the
                        # shape of the input the caller just typed.
                        accepted = auth.consume_recovery_code(
                            conn, user["id"], code
                        )
                        how = "recovery code"
                    if accepted:
                        auth.audit(
                            conn,
                            f"login ok ({how})"
                            f" username={user['username']}",
                        )
                        auth.delete_pending(conn, pending["id"])
                        # Only now: the WHOLE login completed.
                        auth.clear_login_attempts(conn, key)
                        # remember rides on the pending row rather than
                        # being resubmitted, so it cannot be tampered with
                        # between the two steps.
                        token = auth.mint_session(conn, pending["remember"])
                        response = redirect(login_target(conn))
                        response.set_cookie(
                            auth.SESSION_COOKIE,
                            token,
                            httponly=True,
                            samesite="Lax",
                            max_age=(
                                auth.REMEMBER_LIFETIME
                                if pending["remember"]
                                else None
                            ),
                        )
                        response.delete_cookie(auth.PENDING_COOKIE)
                    else:
                        auth.audit(
                            conn,
                            "login failed (wrong code)"
                            f" username={user['username']}",
                        )
                if crossed and response is None:
                    # `response is None` is the failure branch, which is the
                    # only branch that may consult `crossed` — an attempt
                    # that crossed and then SUCCEEDED cleared the counter
                    # and is not a lockout (auth.admit_login_attempt).
                    auth.audit(conn, f"login throttled client_key={key}")
        finally:
            conn.close()
        if response is not None:
            return response
        # One shared return: a wrong code, a missing pending cookie and a
        # throttled request are byte-identical, kirjaudu's rule.
        return render_page(
            login_dialog=True,
            totp_step=True,
            login_error=LOGIN_ERROR,
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

    @app.cli.command("admin-totp-enable")
    def admin_totp_enable():
        """Turn on the two-step sign-in for the admin account.

        Enrolment is a SERVER CLI command and not an admin page on purpose.
        The site is served over plain HTTP; an enrolment page would put the
        base32 secret AND the ten recovery codes — a permanent second factor
        and ten permanent bypasses — into an HTTP response body, handing an
        eavesdropper strictly more than the password-only status quo it is
        meant to improve. Printed on the server's own terminal, they never
        touch the network.
        """
        conn = database.connect(app.config["DATABASE"])
        try:
            row = conn.execute(
                "SELECT id, username, totp_enabled FROM admin_user"
            ).fetchone()
            if row is None:
                raise click.ClickException(
                    "no admin account exists; use admin-create"
                )
            if row["totp_enabled"]:
                raise click.ClickException(
                    "two-step sign-in is already on;"
                    " use admin-totp-disable first"
                )
            brand = site_chrome(conn)["site_brand"] or row["username"]
            secret = totp.random_secret()
            click.echo(f"Secret: {secret}")
            click.echo(
                "URI:    "
                + totp.otpauth_uri(secret, row["username"], brand)
            )
            entered = click.prompt("Code from the app")
            step = totp.accepted_step(
                totp.decode_secret(secret), entered.strip(), None
            )
            if step is None:
                # Nothing is written on this path: an account left with a
                # secret it cannot prove would be a lockout dressed as an
                # enrolment.
                raise click.ClickException(
                    "that code did not verify; nothing was changed"
                )
            conn.execute(
                "UPDATE admin_user SET totp_secret = ?, totp_enabled = 1,"
                " totp_last_step = ? WHERE id = ?",
                (secret, step, row["id"]),
            )
            conn.commit()
            codes = auth.issue_recovery_codes(conn, row["id"])
        finally:
            conn.close()
        click.echo("two-step sign-in enabled")
        click.echo("Recovery codes (shown once, they cannot be shown again):")
        for code in codes:
            click.echo(f"  {code}")

    @app.cli.command("admin-totp-disable")
    def admin_totp_disable():
        """Turn the two-step sign-in back off (server not needed).

        The lockout backstop: a lost or wiped authenticator is a shell
        session, never a dead site.
        """
        conn = database.connect(app.config["DATABASE"])
        try:
            row = conn.execute("SELECT id FROM admin_user").fetchone()
            if row is None:
                raise click.ClickException(
                    "no admin account exists; use admin-create"
                )
            conn.execute(
                "UPDATE admin_user SET totp_secret = NULL, totp_enabled = 0,"
                " totp_last_step = NULL WHERE id = ?",
                (row["id"],),
            )
            conn.execute(
                "DELETE FROM recovery_codes WHERE user_id = ?", (row["id"],)
            )
            conn.commit()
            # A half-authenticated token minted a moment ago must not stay
            # redeemable at a code step that no longer exists.
            auth.delete_pending_for_user(conn, row["id"])
        finally:
            conn.close()
        click.echo("two-step sign-in disabled")

    @app.cli.command("login-unlock")
    def login_unlock():
        """Clear every login rate-limit lockout (server not needed).

        The refusal in kirjaudu() is decided before the password is checked,
        so a correct password cannot end a lockout — this command is the
        owner's escape when they have locked themselves out and do not want
        to wait out LOGIN_FAILURE_WINDOW. It is reachable only from the
        server's command line, so it is not an oracle and not something an
        attacker on the network can reach.
        """
        conn = database.connect(app.config["DATABASE"])
        try:
            removed = auth.clear_all_login_attempts(conn)
        finally:
            conn.close()
        click.echo(f"cleared {removed} recorded login attempt(s)")

    return app
