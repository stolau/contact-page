"""Admin sessions and the audit log.

The seam other units build on: current_admin_session(conn) answers the valid
session row (or None) for the request's cookie, and require_admin wraps a view
so only an authenticated admin reaches it.

Sessions are server-side rows keyed by the SHA-256 of a random token; the raw
token lives only in the visitor's cookie — the database never holds it, so a
database read cannot leak a usable session. All timestamps are integer Unix
epoch seconds (see app/db.py migration 2).

client_key() lives here rather than in app/messages.py because both limiters
need it: TRUSTED_PROXY is read per request, and with it unset the
X-Forwarded-For header is ignored entirely, so a spoofed header cannot mint a
fresh window on either route.

Failed admin logins are counted per client key in the login_attempts table
(app/db.py migration 10) rather than in a process dict, so the count is shared
by every worker and thread and survives a restart — the property the audit_log
count this replaces already had, and which app/messages.py's process-local
_rate_windows does not.
"""

import hashlib
import os
import secrets
import time
from functools import wraps

from flask import current_app, jsonify, redirect, request, url_for

from . import db as database

SESSION_COOKIE = "admin_session"
IDLE_LIMIT = 30 * 60  # "Istunto päättyy 30 min käyttämättömyyden jälkeen."
REMEMBER_LIFETIME = 30 * 24 * 60 * 60  # remember-me: 30 days absolute
AUDIT_KEEP = 1000  # the audit log keeps only the newest rows (trim on write)
LOGIN_FAILURE_WINDOW = 15 * 60
LOGIN_FAILURE_THRESHOLD = 5


def _now():
    return int(time.time())


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def client_key():
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


def bucket_key(key):
    """The storage form of a client key — the single place it is normalised.

    login_attempts.client_key is NOT NULL, and client_key() returns
    request.remote_addr unchanged, which can be None. Such a request must
    fail CLOSED onto one shared bucket rather than onto no limit at all.
    "" rather than a sentinel word because "" cannot collide with a real
    key: remote_addr is never empty when it is present, and client_key()
    filters empty X-Forwarded-For entries out.
    """
    return key or ""


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


def admit_login_attempt(conn, key):
    """Decide whether this login attempt may be evaluated, and record it if so.

    Returns (admitted, crossed). `crossed` is True only on the attempt that
    brings this client to LOGIN_FAILURE_THRESHOLD; the caller consults it on
    the failure branch only, because an attempt that crosses and then SUCCEEDS
    clears the counter and is not a lockout.

    Called BEFORE check_password_hash, on purpose. The count is read and the
    row written as one step, so no second request can pass the gate on a count
    this one has already consumed. Doing it after the hash would put a full
    scrypt between the read and the write — an interval an order of magnitude
    longer than the storage work either side of it — and the documented server
    (`flask --app app run`) is thread-per-connection with no ceiling, so the
    overshoot would be the attacker's socket count.

    The first count is deliberately OUTSIDE the transaction: a client already
    over the threshold is refused there and never touches the write lock, so a
    flood costs one indexed read and no lock contention. Readers are not
    blocked by a writer holding RESERVED, so that read cannot stall behind a
    login that is mid-insert.

    A failure to take the write lock (BEGIN IMMEDIATE past the busy timeout)
    is NOT swallowed into an admission: it propagates, the request errors, and
    no password is evaluated. Refusing to decide must never read as "allowed".
    """
    key = bucket_key(key)
    cutoff = _now() - LOGIN_FAILURE_WINDOW
    (count,) = conn.execute(
        "SELECT COUNT(*) FROM login_attempts WHERE client_key = ? AND at > ?",
        (key, cutoff),
    ).fetchone()
    if count >= LOGIN_FAILURE_THRESHOLD:
        return False, False
    conn.execute("BEGIN IMMEDIATE")
    try:
        (count,) = conn.execute(
            "SELECT COUNT(*) FROM login_attempts"
            " WHERE client_key = ? AND at > ?",
            (key, cutoff),
        ).fetchone()
        if count >= LOGIN_FAILURE_THRESHOLD:
            conn.rollback()
            return False, False
        conn.execute("DELETE FROM login_attempts WHERE at <= ?", (cutoff,))
        conn.execute(
            "INSERT INTO login_attempts (client_key, at) VALUES (?, ?)",
            (key, _now()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True, count + 1 == LOGIN_FAILURE_THRESHOLD


def clear_login_attempts(conn, key):
    """Drop one client's recorded attempts — called on a successful login.

    It matters BELOW the threshold only, and that is its whole role: an owner
    who mistyped four times and then got it right must not be one typo from a
    lockout. A client already past the threshold never reaches this, because
    the route refuses before the password is checked — so a correct password
    does not end a lockout, deliberately (the refusal must not pay for a
    scrypt, and must not touch the username). The window, or login-unlock, is
    the way out.

    It also deletes the row this very attempt inserted, so a success leaves
    the key with zero rows.
    """
    conn.execute(
        "DELETE FROM login_attempts WHERE client_key = ?", (bucket_key(key),)
    )
    conn.commit()


def clear_all_login_attempts(conn):
    """Empty the whole table and answer how many rows went — the seam the
    login-unlock CLI command needs.

    Every statement against login_attempts lives in this module, which is why
    this is a function here rather than SQL in the command.
    """
    cursor = conn.execute("DELETE FROM login_attempts")
    conn.commit()
    return cursor.rowcount


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
