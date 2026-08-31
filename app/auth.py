"""Admin sessions and the audit log.

The seam other units build on: current_admin_session(conn) answers the valid
session row (or None) for the request's cookie, and require_admin wraps a view
so only an authenticated admin reaches it.

Sessions are server-side rows keyed by the SHA-256 of a random token; the raw
token lives only in the visitor's cookie — the database never holds it, so a
database read cannot leak a usable session. All timestamps are integer Unix
epoch seconds (see app/db.py migration 2).
"""

import hashlib
import secrets
import time
from functools import wraps

from flask import current_app, jsonify, redirect, request, url_for

from . import db as database

SESSION_COOKIE = "admin_session"
IDLE_LIMIT = 30 * 60  # "Istunto päättyy 30 min käyttämättömyyden jälkeen."
REMEMBER_LIFETIME = 30 * 24 * 60 * 60  # remember-me: 30 days absolute
AUDIT_KEEP = 1000  # the audit log keeps only the newest rows (trim on write)
FAILURE_WINDOW = 5 * 60
FAILURE_THRESHOLD = 3
FAILURE_DELAY = 1.0  # seconds

# Injection point so tests can observe or disarm the rate-limit delay.
_sleep = time.sleep


def _now():
    return int(time.time())


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def mint_session(conn, remember):
    """Insert a session row and return the raw token for the cookie.

    Only sha256(token) is stored; remember=1 gets an absolute expiry of
    created_at + 30 days, remember=0 gets none (the idle rule governs it).
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + REMEMBER_LIFETIME if remember else None
    conn.execute(
        "INSERT INTO sessions"
        " (token_hash, created_at, last_seen_at, remember, expires_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (_hash_token(token), now, now, 1 if remember else 0, expires_at),
    )
    conn.commit()
    return token


def current_admin_session(conn):
    """The valid session row for the request's cookie, or None.

    The remember/idle interaction, as decided in LLM-COP-2: remember-me
    extends the absolute lifetime to 30 days — remember-me simply replaces
    the idle rule with the absolute one, which is what the checkbox means to
    a user. So remember=0 is refused once now - last_seen_at exceeds 30
    minutes (sliding, refreshed on every valid request), and remember=1 is
    refused only past expires_at = created_at + 30 days.

    An expired row is deleted here, so the refusal is real: the token can
    never validate again, not merely fail cosmetically on this request.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM sessions WHERE token_hash = ?", (_hash_token(token),)
    ).fetchone()
    if row is None:
        return None
    now = _now()
    if row["remember"]:
        expired = now > row["expires_at"]
    else:
        expired = now - row["last_seen_at"] > IDLE_LIMIT
    if expired:
        conn.execute("DELETE FROM sessions WHERE id = ?", (row["id"],))
        conn.commit()
        return None
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (now, row["id"])
    )
    conn.commit()
    return row


def delete_session(conn, session_id):
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    conn.commit()


def audit(conn, event):
    """Append one audit event, trimming the log to the newest AUDIT_KEEP rows."""
    conn.execute(
        "INSERT INTO audit_log (at, event) VALUES (?, ?)", (_now(), event)
    )
    conn.execute(
        "DELETE FROM audit_log WHERE id NOT IN"
        " (SELECT id FROM audit_log ORDER BY id DESC LIMIT ?)",
        (AUDIT_KEEP,),
    )
    conn.commit()


def throttle_failures(conn):
    """Rate limit: with >= FAILURE_THRESHOLD login failures inside the last
    FAILURE_WINDOW seconds, sleep a fixed beat before answering."""
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM audit_log"
        " WHERE at > ? AND event LIKE 'login failed%'",
        (_now() - FAILURE_WINDOW,),
    ).fetchone()
    if count >= FAILURE_THRESHOLD:
        _sleep(FAILURE_DELAY)


def _prefers_json():
    accepts = request.accept_mimetypes
    return accepts["application/json"] > accepts["text/html"]


def require_admin(view):
    """Only an authenticated admin reaches the view: browser requests are
    redirected to the login dialog at /yllapito, requests that prefer JSON
    get a 401 JSON answer."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        conn = database.connect(current_app.config["DATABASE"])
        try:
            row = current_admin_session(conn)
        finally:
            conn.close()
        if row is None:
            if _prefers_json():
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("yllapito"))
        return view(*args, **kwargs)

    return wrapped
