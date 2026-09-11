"""Admin sessions and the audit log.

The seam other units build on: current_admin_session(conn) answers the valid
session row (or None) for the request's cookie, and require_admin wraps a view
so only an authenticated admin reaches it.

Sessions are server-side rows keyed by the SHA-256 of a random token; the raw
token lives only in the visitor's cookie — the database never holds it, so a
database read cannot leak a usable session. All timestamps are integer Unix
epoch seconds (see app/db.py migration 2).

Every session row names its owner (sessions.user_id, app/db.py migration 15),
which is what makes revoke_sessions_for_user a seam rather than a blunt
DELETE: a CLI command that changes a credential can end exactly the sessions
that credential justified. mint_session takes the owner as a required
positional argument so a session without one cannot be written by accident.

client_key() lives here rather than in app/messages.py because both limiters
need it: TRUSTED_PROXY is read per request, and with it unset the
X-Forwarded-For header is ignored entirely, so a spoofed header cannot mint a
fresh window on either route.

The optional TOTP second factor (app/totp.py) adds a second seam beside
that one: mint_pending/current_pending_login answer the HALF-authenticated
state between the password and the code. It is a separate table and a
separate cookie name from sessions, so a pending token cannot reach an
admin route by any route that forgets a filter — the row it would need is
not in the table current_admin_session reads.

Failed admin logins are counted per client key in the login_attempts table
(app/db.py migration 10) rather than in a process dict, so the count is shared
by every worker and thread and survives a restart — the property the audit_log
count this replaces already had, and which app/messages.py's process-local
_rate_windows does not.
"""

import hashlib
import os
import re
import secrets
import time
from functools import wraps

from flask import current_app, jsonify, redirect, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as database

SESSION_COOKIE = "admin_session"
IDLE_LIMIT = 30 * 60  # "Istunto päättyy 30 min käyttämättömyyden jälkeen."
REMEMBER_LIFETIME = 30 * 24 * 60 * 60  # remember-me: 30 days absolute
AUDIT_KEEP = 1000  # the audit log keeps only the newest rows (trim on write)
LOGIN_FAILURE_WINDOW = 15 * 60
LOGIN_FAILURE_THRESHOLD = 5

# The half-authenticated state between the password and the code. Its own
# cookie NAME, not just its own row: the pending token is never presented
# under the name current_admin_session reads, so there are two independent
# reasons a partial login cannot reach an admin route — the wrong table and
# the wrong cookie.
PENDING_COOKIE = "admin_pending"
PENDING_LIFETIME = 5 * 60

RECOVERY_CODE_COUNT = 10
# No i, l, o, 0 or 1: these are read off a screen and typed back by hand.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
RECOVERY_GROUPS = 4
RECOVERY_GROUP_LEN = 5
RECOVERY_PATTERN = re.compile(r"^[a-z2-9]{5}(-[a-z2-9]{5}){3}$")


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


def mint_session(conn, user_id, remember):
    """Insert a session row and return the raw token for the cookie.

    Only sha256(token) is stored; remember=1 gets an absolute expiry of
    created_at + 30 days, remember=0 gets none (the idle rule governs it).

    user_id is POSITIONAL AND REQUIRED, mirroring mint_pending. An optional
    owner would be the same "the guarantee lives in procedure" defect
    revoke_sessions_for_user exists to end: a session minted without one
    could not be revoked by account, and nothing would say so at the call
    site (app/db.py migration 15 has to allow NULL, so the database cannot
    say it either).
    """
    token = secrets.token_urlsafe(32)
    now = _now()
    expires_at = now + REMEMBER_LIFETIME if remember else None
    conn.execute(
        "INSERT INTO sessions"
        " (token_hash, user_id, created_at, last_seen_at, remember,"
        " expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            _hash_token(token),
            user_id,
            now,
            now,
            1 if remember else 0,
            expires_at,
        ),
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


def revoke_sessions_for_user(conn, user_id):
    """Sign one account out everywhere, and answer how many rows went.

    The seam admin-reset-password and admin-totp-disable need: changing a
    credential that ends a session's justification must end the session too,
    or an attacker holding a live cookie simply keeps it through the owner's
    recovery. Shaped like clear_all_login_attempts, and here for the same
    stated reason — every statement against this table lives in this module
    rather than as SQL in a command.

    `OR user_id IS NULL` IS FAIL-CLOSED AND DELIBERATE. A revocation must
    never leave a session alive merely because its owner column was empty.
    After migration 15 a NULL can only be a pre-migration row on a store that
    had sessions and no account — a state login cannot produce — so the
    clause deletes only rows that should not exist, and it deletes them at the
    one moment the owner has explicitly asked for a clean slate.
    """
    cursor = conn.execute(
        "DELETE FROM sessions WHERE user_id = ? OR user_id IS NULL",
        (user_id,),
    )
    conn.commit()
    return cursor.rowcount


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


def mint_pending(conn, user_id, remember):
    """Insert a pending-login row and return the raw token for the cookie.

    A pending row authorises exactly one thing — the code step — and it is
    NOT a session: current_admin_session reads the sessions table, and
    nothing here writes to it.

    The user's existing pending rows are deleted FIRST, so one live pending
    row per account is an invariant rather than a hope. GET /yllapito still
    renders the password step even mid-flow, so an owner who reloads and
    re-posts their password would otherwise mint a second row, and only
    current_pending_login ever deletes one — and only the one it read. The
    older token stops validating the moment a newer one is minted.

    Only sha256(token) is stored, the discipline mint_session keeps.
    """
    conn.execute("DELETE FROM pending_logins WHERE user_id = ?", (user_id,))
    token = secrets.token_urlsafe(32)
    now = _now()
    conn.execute(
        "INSERT INTO pending_logins"
        " (token_hash, user_id, remember, created_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            _hash_token(token),
            user_id,
            1 if remember else 0,
            now,
            now + PENDING_LIFETIME,
        ),
    )
    conn.commit()
    return token


def current_pending_login(conn):
    """The valid pending-login row for the request's cookie, or None.

    An expired row is DELETED here rather than merely refused, the
    discipline current_admin_session keeps: the token can never validate
    again, not just fail cosmetically on this request.
    """
    token = request.cookies.get(PENDING_COOKIE)
    if not token:
        return None
    row = conn.execute(
        "SELECT * FROM pending_logins WHERE token_hash = ?",
        (_hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    if _now() > row["expires_at"]:
        delete_pending(conn, row["id"])
        return None
    return row


def delete_pending(conn, pending_id):
    conn.execute("DELETE FROM pending_logins WHERE id = ?", (pending_id,))
    conn.commit()


def delete_pending_for_user(conn, user_id):
    """Drop every pending login for one account — the CLI disable path.

    Disabling the factor must not leave a half-authenticated token behind
    that could still be redeemed at the code step.
    """
    conn.execute("DELETE FROM pending_logins WHERE user_id = ?", (user_id,))
    conn.commit()


def _recovery_code():
    return "-".join(
        "".join(
            secrets.choice(RECOVERY_ALPHABET)
            for _ in range(RECOVERY_GROUP_LEN)
        )
        for _ in range(RECOVERY_GROUPS)
    )


def issue_recovery_codes(conn, user_id):
    """Replace the account's recovery codes and answer the new plaintexts.

    The plaintext is returned to the caller ONCE, for the operator's
    terminal, and never stored: the rows hold generate_password_hash of
    each code, the same primitive as the password.

    The FORMAT is load-bearing, not cosmetic. A code is four hyphenated
    groups of five characters from RECOVERY_ALPHABET — 23 characters
    containing three hyphens — so it can NEVER be six ASCII digits. The
    login route only tries the recovery path when the input does not look
    like a TOTP code, and this format is what makes that test structurally
    safe rather than probabilistically safe. Entropy is 31**20 (about
    2**99), and the codes sit behind the same admit_login_attempt gate as
    everything else on the login routes.
    """
    conn.execute("DELETE FROM recovery_codes WHERE user_id = ?", (user_id,))
    now = _now()
    codes = [_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    for code in codes:
        conn.execute(
            "INSERT INTO recovery_codes (user_id, code_hash, created_at)"
            " VALUES (?, ?, ?)",
            (user_id, generate_password_hash(code), now),
        )
    conn.commit()
    return codes


def consume_recovery_code(conn, user_id, code):
    """Spend one unused recovery code, or answer False.

    Single use: the matching row is stamped with used_at and is never
    accepted again. Codes are compared case-insensitively because
    RECOVERY_ALPHABET is lowercase and a code is typed back by hand.
    """
    candidate = code.strip().lower()
    if not candidate:
        return False
    rows = conn.execute(
        "SELECT id, code_hash FROM recovery_codes"
        " WHERE user_id = ? AND used_at IS NULL",
        (user_id,),
    ).fetchall()
    for row in rows:
        if check_password_hash(row["code_hash"], candidate):
            conn.execute(
                "UPDATE recovery_codes SET used_at = ? WHERE id = ?",
                (_now(), row["id"]),
            )
            conn.commit()
            return True
    return False


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

    # A marker, not a heuristic: the second factor's proof sweeps
    # app.url_map for every gated rule and asserts a half-authenticated
    # token reaches none of them. Reading __wrapped__ would also match any
    # other functools.wraps decorator; this attribute means exactly one
    # thing, so a route added later is covered without anyone remembering.
    wrapped.__admin_gated__ = True
    return wrapped
