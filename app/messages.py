"""Contact messages (LLM-COP-3): the dialog's POST /api/messages endpoint,
the admin inbox at /yllapito/viestit, and the mail notification.

Every message is stored first and always; the SMTP notification is a
best-effort extra whose failure never costs the visitor their message.

Privacy: no message field value is ever logged — not the name, not the
body, not the email, not the phone. Log lines carry the row id only.

The visitor's address is the one visitor-controlled value that reaches a
mail header, as Reply-To; every other field goes into the body. _set_reply_to
is that boundary, and it refuses any value it cannot turn into a header it
trusts rather than costing the owner the notification.

Rate limiting assumes the app is reached directly (README runs
`flask --app app run`), so request.remote_addr is the visitor. The window
store is an in-process dict, so a restart clears every window; that is
acceptable for a single-process site and keeps the limiter dependency-free.
Behind a reverse proxy, set TRUSTED_PROXY to key on the rightmost
X-Forwarded-For entry — auth.client_key() is where that mechanism lives, and
it is shared with the admin login's limiter.
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

# Injection point so tests can drive the rate-limit window without waiting.
_now = time.time

# client key -> (window_start, count). Process-local; see the module docstring.
_rate_windows = {}


def reset_rate_limiter():
    """Empty the rate-limit store — the seam tests use between cases."""
    _rate_windows.clear()


def _connect():
    return database.connect(current_app.config["DATABASE"])


def _rate_limited():
    """Consume one slot for this client and answer whether it is over.

    Every arrival that reaches this check consumes a slot, including ones
    later rejected as malformed — garbage buys no free retries.
    """
    key = auth.client_key()
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


def _set_reply_to(mail, address, message_id):
    """Put the visitor's address in Reply-To, or put nothing there at all.

    This is the only place a visitor-controlled value becomes a header, so
    the header boundary lives here. Three things must hold before the value
    is trusted, and none of them is redundant — stated here in the order
    the code below evaluates them. First a non-empty string, because the
    empty string is both printable and ASCII, and _text answers None for a
    non-string. Then isascii(), because a non-ASCII address serialises to
    an RFC 2047 encoded word (=?utf-8?q?m=C3=A4ria?=@esimerkki.fi), which
    looks like an address and cannot be replied to. Then isprintable(),
    which keeps out CR, LF, NUL and DEL — a CR or LF is what would let the
    sender append headers of their own, and it is the reason this boundary
    exists at all. A missing header degrades to what the owner has today;
    a mangled one is discovered only after they have hit reply.

    The assignment is guarded as well as the value, and then its *result*
    is checked, which matters more than the guard. The stdlib is not
    consistent about printable ASCII that is not an address: mail["Reply-To"]
    = "a@" raises IndexError on one 3.12 patch release and quietly stores the
    null address <> on another, and "@" stores <> on both. Whether an
    exception happens is therefore not a fact this module may build a
    decision on, so it does not: the header is kept only when it reads back
    as exactly the string that went in, which is the same answer everywhere.

    The guard is still needed, because where the stdlib does raise, this call
    sits *outside* _notify's own try, which does not open until the send. An
    unguarded raise would escape _notify and post_message alike and answer
    the visitor 500 on a message that is already stored — measured, not
    assumed. A raise leaves the message clean: no partial header survives it,
    and a header we refuse after the fact is deleted, which leaves it equally
    clean.

    isascii() is a fact about encoding, not about address grammar. It says
    nothing about whether an address is well formed, and this refuses to
    start saying so: "a@b, c@d" and "a@" pass on purpose, and nothing here
    should grow into address validation. A refused value costs the Reply-To
    and nothing else — the mail is still sent, and the body carries the
    address verbatim as the authoritative copy.
    """
    if address and address.isascii() and address.isprintable():
        try:
            mail["Reply-To"] = address
        # Narrow on purpose: the assignment is the entire crash surface.
        # S110 is suppressed rather than answered here because this refusal
        # *is* logged — by the statement below, which it shares.
        except Exception:  # noqa: BLE001, S110
            pass
        else:
            # Keep the header only when it came back as exactly what the
            # visitor typed. Whether the stdlib *raises* on a value it does
            # not like is not ours to rely on — "a@" is an IndexError on one
            # 3.12 patch release and the null address <> on another — so the
            # decision is made here, from what the header actually became,
            # and is the same on every interpreter. A value the library
            # rewrote is a value we did not recognise, and an unrecognised
            # Reply-To is worse than none: it points somewhere that is not
            # the visitor. This does not subsume isascii() above, which
            # still earns its place — a non-ASCII address reads back
            # unchanged and is caught only there.
            if str(mail["Reply-To"]) == address:
                return
            del mail["Reply-To"]
    # One statement for both refusals — the predicate's and the stdlib's —
    # so there is one log line to promise and one never-log case to prove.
    # Id only, as everywhere here: never the address.
    current_app.logger.warning(
        "contact message reply address refused id=%s", message_id
    )


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
    # The same stripped value _store wrote, so the header and the row can
    # never disagree about who wrote.
    _set_reply_to(mail, _text(payload, "email"), message_id)
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
