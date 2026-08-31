"""Contact messages (LLM-COP-3): the dialog's POST /api/messages endpoint,
the admin inbox at /yllapito/viestit, and the mail notification.

Every message is stored first and always; the SMTP notification is a
best-effort extra whose failure never costs the visitor their message.

Privacy: no message field value is ever logged — not the name, not the
body, not the email, not the phone. Log lines carry the row id only.

Rate limiting assumes the app is reached directly (README runs
`flask --app app run`), so request.remote_addr is the visitor. The window
store is an in-process dict, so a restart clears every window; that is
acceptable for a single-process site and keeps the limiter dependency-free.
Behind a reverse proxy, set TRUSTED_PROXY to key on the rightmost
X-Forwarded-For entry (the one the trusted proxy itself appended). With
TRUSTED_PROXY unset the header is ignored entirely, so a spoofed
X-Forwarded-For cannot mint a fresh window.
"""

import os
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from . import auth
from . import db as database

bp = Blueprint("messages", __name__)

MAX_BODY_BYTES = 64 * 1024
RATE_LIMIT = 5
RATE_WINDOW = 3600  # seconds — one fixed window per client key

NAME_MAX = 200
EMAIL_MAX = 200
PHONE_MAX = 50
MESSAGE_MAX = 5000

TIME_FORMAT = "%d.%m.%Y %H.%M"

# Injection point so tests can drive the rate-limit window without waiting
# (mirrors auth._sleep).
_now = time.time

# client key -> (window_start, count). Process-local; see the module docstring.
_rate_windows = {}


def reset_rate_limiter():
    """Empty the rate-limit store — the seam tests use between cases."""
    _rate_windows.clear()


def _connect():
    return database.connect(current_app.config["DATABASE"])


def _client_key():
    """The identity a rate-limit window belongs to.

    TRUSTED_PROXY is read here, per request, so the deployment can be
    changed without a restart and so a test can set it around one call.
    """
    if os.environ.get("TRUSTED_PROXY"):
        forwarded = request.headers.get("X-Forwarded-For", "")
        entries = [part.strip() for part in forwarded.split(",")]
        entries = [entry for entry in entries if entry]
        if entries:
            # The rightmost entry is the one our own trusted proxy appended;
            # everything left of it is client-supplied and forgeable.
            return entries[-1]
    return request.remote_addr


def _rate_limited():
    """Consume one slot for this client and answer whether it is over.

    Every arrival that reaches this check consumes a slot, including ones
    later rejected as malformed — garbage buys no free retries.
    """
    key = _client_key()
    now = _now()
    start, count = _rate_windows.get(key, (now, 0))
    if now - start >= RATE_WINDOW:
        start, count = now, 0
    count += 1
    _rate_windows[key] = (start, count)
    return count > RATE_LIMIT


def _text(payload, field):
    """The field as a stripped string, or None when it is not a string."""
    value = payload.get(field)
    if not isinstance(value, str):
        return None
    return value.strip()


def _validate(payload):
    """The first field error in the payload, or None when it is sound."""
    name = _text(payload, "name")
    message = _text(payload, "message")
    email = _text(payload, "email")
    if not name:
        return "name is required"
    if not message:
        return "message is required"
    if not email:
        return "email is required"
    if payload.get("consent") is not True:
        return "consent is required"
    if len(name) > NAME_MAX:
        return "name is too long"
    if len(email) > EMAIL_MAX:
        return "email is too long"
    if "@" not in email:
        return "email is not an address"
    phone = payload.get("phone")
    if phone is not None:
        if not isinstance(phone, str):
            return "phone is not text"
        if len(phone.strip()) > PHONE_MAX:
            return "phone is too long"
    if len(message) > MESSAGE_MAX:
        return "message is too long"
    return None


def _store(conn, payload):
    """Insert the message and answer its id."""
    now = int(_now())
    phone = _text(payload, "phone") or None
    cursor = conn.execute(
        "INSERT INTO messages"
        " (name, body, email, phone, consented_at, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            _text(payload, "name"),
            _text(payload, "message"),
            _text(payload, "email"),
            phone,
            now,
            now,
        ),
    )
    conn.commit()
    return cursor.lastrowid


def _notify(message_id, payload):
    """Best-effort mail notification. Never raises, never logs field values.

    Every mail setting is read here, per request, so a deployment (or a
    test) can change one without reimporting the module.
    """
    host = os.environ.get("SMTP_HOST")
    mail_to = os.environ.get("MAIL_TO")
    if not host:
        return
    if not mail_to:
        # Field-free on purpose: the operator needs the misconfiguration,
        # not the visitor's message.
        current_app.logger.warning(
            "SMTP_HOST is set but MAIL_TO is not; no notification sent"
        )
        return
    mail = EmailMessage()
    mail["Subject"] = "Uusi yhteydenotto"
    mail["From"] = os.environ.get("MAIL_FROM") or mail_to
    mail["To"] = mail_to
    mail.set_content(
        "Nimi: {name}\n"
        "Sähköposti: {email}\n"
        "Puhelin: {phone}\n\n"
        "{body}\n".format(
            name=_text(payload, "name"),
            email=_text(payload, "email"),
            phone=_text(payload, "phone") or "-",
            body=_text(payload, "message"),
        )
    )
    port = int(os.environ.get("SMTP_PORT") or 25)
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    try:
        with smtplib.SMTP(host, port) as server:
            if user and password:
                server.login(user, password)
            server.send_message(mail)
    # Deliberately broad: the message is already stored, so no failure of
    # the mail hop — however exotic — may cost the visitor their answer.
    except Exception:  # noqa: BLE001
        # A broken mail hop is the operator's problem, not the visitor's.
        # Id only — never the message.
        current_app.logger.warning(
            "contact message notification failed id=%s", message_id
        )


@bp.route("/api/messages", methods=["POST"])
def post_message():
    """Take one contact message. Refusal order is pinned and each rejection
    is reachable on its own: oversize body, then the rate limit (before any
    parsing, so garbage costs a slot too), then the JSON shape, then the
    fields."""
    length = request.content_length
    if length is not None and length > MAX_BODY_BYTES:
        return jsonify(error="too large"), 413
    if _rate_limited():
        return jsonify(error="too many requests"), 429
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="invalid json"), 400
    error = _validate(payload)
    if error is not None:
        return jsonify(error=error), 400
    conn = _connect()
    try:
        message_id = _store(conn, payload)
    finally:
        conn.close()
    _notify(message_id, payload)
    return jsonify(ok=True), 201


@bp.route("/yllapito/viestit")
@auth.require_admin
def viestit():
    """The admin inbox: newest message first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    messages = [
        {
            "id": row["id"],
            "name": row["name"],
            "body": row["body"],
            "email": row["email"],
            "phone": row["phone"],
            # Stored as UTC epoch seconds, shown in the server's local
            # time — the clock the admin reading the inbox is on.
            "created_at": datetime.fromtimestamp(
                row["created_at"], tz=timezone.utc
            ).astimezone().strftime(TIME_FORMAT),
        }
        for row in rows
    ]
    return render_template("inbox.html", messages=messages)


@bp.route("/yllapito/viestit/<int:message_id>/poista", methods=["POST"])
@auth.require_admin
def poista_viesti(message_id):
    """Delete one message for real, then return to the inbox."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT id FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        if row is None:
            return jsonify(error="not found"), 404
        conn.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        conn.commit()
        # Id only: an audit row must never carry the message it is about.
        auth.audit(conn, f"message deleted id={message_id}")
    finally:
        conn.close()
    return redirect(url_for("messages.viestit"))
