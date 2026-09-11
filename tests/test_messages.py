"""LLM-COP-3 — the contact dialog, POST /api/messages, and the admin inbox.

Spec: cp-contact-dialog (fetched from the SpecWeaver server; every
contains-text string below is copied byte-for-byte out of that JSON, never
retyped — the Finnish diacritics are load-bearing).

Three things this file refuses to do, because each of them would let a test
pass while proving nothing:

1. **No whole-document contains-text assertions for the dialog.** The rule
   outlived the form that motivated it: the seeded page used to render a
   ``.contact-form`` whose label copy included "Nimi", so a bare
   ``"Nimi" in html`` passed with no dialog in the document at all. USR-COP-1
   deleted that form, but the seeded hero title is still "Nimi tähän" and the
   header still hardcodes "Ota yhteyttä", so a whole-document check is still
   the wrong instrument. Every criterion below stays scoped to its own
   element.

2. **No assertion scoped only to the dialog root.** conftest's ``element_text``
   concatenates *every* descendant text node, and ``HTMLParser`` hands inline
   ``<script>`` source to ``handle_data`` — so a string that appears anywhere
   in the dialog's own inline script would satisfy a root-scoped check. Every
   contains-text criterion here is therefore scoped to its own uniquely
   classed ``cd-*`` element, and each test fails if that one element is
   deleted.

3. **No document-wide input-name check.** ``input_names`` in test_auth parses
   the whole document, and the login dialog serves inputs of its own. The
   is-visible criteria use ``dialog_scope`` below, which is attribute-aware
   *and* structural, so these assertions genuinely fail without the dialog
   rather than being satisfied by some other form's inputs.

``dialog_scope`` and ``class_count`` are defined here rather than in
tests/conftest.py deliberately: they are this unit's instruments, and
conftest is owned elsewhere.
"""

import base64
import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import pytest

from app import db as database
from app import messages
from app.seed import SEED_SECTIONS
from tests.conftest import (
    assert_absent_from_app,
    edit_published_payload,
    element_text,
    set_section_state,
)

# --- shared isolation --------------------------------------------------------


@pytest.fixture(autouse=True)
def _rate_limiter_isolation():
    """No window state and no injected clock ever leaks between tests.

    Autouse and order-independent: the limiter is a module-level structure in
    app.messages, so without this a rate-limit test would poison every test
    that ran after it (and a clock injection would poison the timestamp
    assertions). Restored on the way out as well as reset on the way in.
    """
    original_now = messages._now
    messages.reset_rate_limiter()
    yield
    messages._now = original_now
    messages.reset_rate_limiter()


class _Clock:
    """An injectable clock, so window expiry is proved without sleeping."""

    def __init__(self, start=1_700_000_000):
        self.t = int(start)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += int(seconds)


@pytest.fixture
def clock():
    c = _Clock()
    messages._now = c
    return c


# --- payload and store helpers ----------------------------------------------

VALID = {
    "name": "Maria Koskinen",
    "message": "Kuusivuotias poikani ei sano R-äännettä.",
    "email": "maria@esimerkki.fi",
    "consent": True,
}


def payload(**overrides):
    body = dict(VALID)
    body.update(overrides)
    return body


def post(client, body=None, **kwargs):
    return client.post("/api/messages", json=payload() if body is None else body,
                       **kwargs)


def stored(app):
    """Every stored message, read back through a real connection to the app's
    own database file — the same store the route writes and the inbox reads."""
    c = database.connect(app.config["DATABASE"])
    try:
        return c.execute("SELECT * FROM messages ORDER BY id").fetchall()
    finally:
        c.close()


def insert_message(app, name, body, email, phone, created_at):
    c = database.connect(app.config["DATABASE"])
    try:
        cur = c.execute(
            "INSERT INTO messages"
            " (name, body, email, phone, consented_at, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (name, body, email, phone, created_at, created_at),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def table_rows(app, table):
    c = database.connect(app.config["DATABASE"])
    try:
        return c.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    finally:
        c.close()


# --- migration 3 -------------------------------------------------------------


def test_migration_3_creates_the_messages_table(conn):
    """A fresh migrated database carries messages with exactly its columns."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    assert columns == {
        "id",
        "name",
        "body",
        "email",
        "phone",
        "consented_at",
        "created_at",
    }
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    # Not a literal: migration 4 (LLM-COP-10) would turn a hard-coded 3
    # red on correct code. The contract is that migrate() stamps the
    # LAST migration, whatever the list currently holds.
    assert version == len(database.MIGRATIONS)


def test_migrate_is_still_idempotent_with_migration_3(conn):
    """Re-running migrate() must not re-issue CREATE TABLE messages (which
    would raise), and must not move user_version."""
    before = conn.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()

    database.migrate(conn)

    after = conn.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
    ).fetchall()
    assert after == before
    (version,) = conn.execute("PRAGMA user_version").fetchone()
    # Not a literal: migration 4 (LLM-COP-10) would turn a hard-coded 3
    # red on correct code. The contract is that migrate() stamps the
    # LAST migration, whatever the list currently holds.
    assert version == len(database.MIGRATIONS)


# --- POST /api/messages: the happy path --------------------------------------


def test_valid_post_stores_exactly_one_row_and_answers_201(app, client):
    response = post(client)

    assert response.status_code == 201
    assert response.get_json() == {"ok": True}

    rows = stored(app)
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == VALID["name"]
    assert row["body"] == VALID["message"]
    assert row["email"] == VALID["email"]

    # Plausible epoch seconds, not milliseconds and not a placeholder: the
    # real clock is in force here (the autouse fixture restored it).
    now = time.time()
    for column in ("consented_at", "created_at"):
        stamp = row[column]
        assert isinstance(stamp, int), column
        assert 1_700_000_000 < stamp <= now + 5, (column, stamp)
        assert now - stamp < 60, (column, stamp)


def test_optional_phone_is_stored_when_given(app, client):
    assert post(client, payload(phone="040 123 4567")).status_code == 201
    assert stored(app)[0]["phone"] == "040 123 4567"


# --- POST /api/messages: refusals --------------------------------------------


@pytest.mark.parametrize(
    "case, body",
    [
        ("consent false", payload(consent=False)),
        ("consent absent", {k: v for k, v in VALID.items() if k != "consent"}),
        # Consent must be the boolean True, not merely something truthy: a
        # checkbox serialized as "on" or 1 is a client that never sent the
        # boolean the contract asks for, and consent is the one field where
        # "close enough" is not good enough.
        ("consent is the string on", payload(consent="on")),
        ("consent is 1", payload(consent=1)),
        ("consent is null", payload(consent=None)),
    ],
)
def test_without_consent_nothing_is_stored(app, client, case, body):
    response = post(client, body)
    assert response.status_code == 400, case
    assert stored(app) == [], case


def test_form_encoded_body_is_refused(app, client):
    response = client.post("/api/messages", data=payload(consent="on"))
    assert response.status_code == 400
    assert stored(app) == []


@pytest.mark.parametrize("body", [["a"], "a string", 7, None])
def test_non_dict_json_body_is_refused(app, client, body):
    response = client.post("/api/messages", json=body)
    assert response.status_code == 400
    assert stored(app) == []


@pytest.mark.parametrize(
    "case, body",
    [
        ("name over 200", payload(name="a" * 201)),
        ("email over 200", payload(email="a" * 190 + "@" + "b" * 20)),
        ("phone over 50", payload(phone="0" * 51)),
        ("message over 5000", payload(message="a" * 5001)),
        ("email without @", payload(email="maria.esimerkki.fi")),
        ("name empty", payload(name="")),
        ("message empty", payload(message="")),
        ("email empty", payload(email="")),
    ],
)
def test_field_validation_refuses_and_stores_nothing(app, client, case, body):
    response = post(client, body)
    assert response.status_code == 400, case
    assert stored(app) == [], case


def test_oversized_request_is_refused_before_anything_else(app, client):
    """A body over 64 KB is refused on content_length alone."""
    response = client.post(
        "/api/messages",
        data=b"x" * (64 * 1024 + 1),
        content_type="application/json",
    )
    assert response.status_code == 413
    assert stored(app) == []


# --- POST /api/messages: the rate limiter ------------------------------------


def test_sixth_arrival_in_the_window_is_refused_even_when_valid(app, client):
    """The count refused it, not the validation: the sixth body is the same
    fully valid body the first five were."""
    for i in range(messages.RATE_LIMIT):
        assert post(client).status_code != 429, i

    sixth = post(client)

    assert sixth.status_code == 429
    # Refused before storing: still exactly RATE_LIMIT rows.
    assert len(stored(app)) == messages.RATE_LIMIT


def test_rejected_arrivals_consume_slots_too(app, client):
    """Five consent-less posts are all refused 400 — and still burn the
    window, so a sixth, perfectly valid post is refused 429. A limiter that
    only counted successes would answer 201 here."""
    for i in range(messages.RATE_LIMIT):
        assert post(client, payload(consent=False)).status_code == 400, i

    response = post(client)

    assert response.status_code == 429
    assert stored(app) == []


def test_window_expiry_lets_the_next_arrival_through(app, client, clock):
    for _ in range(messages.RATE_LIMIT):
        post(client)
    assert post(client).status_code == 429

    clock.advance(messages.RATE_WINDOW + 1)

    assert post(client).status_code == 201
    assert len(stored(app)) == messages.RATE_LIMIT + 1


def test_each_client_address_gets_its_own_window(app, client, monkeypatch):
    """The default deployment keys on remote_addr, and that is the whole
    point of the limiter: one visitor's five messages must not lock the
    contact form for everyone else. A limiter keyed on a constant satisfies
    every other rate-limit test in this file — including the expiry and both
    proxy tests — and would shut the form for the entire internet after five
    messages an hour."""
    monkeypatch.delenv("TRUSTED_PROXY", raising=False)
    first = {"REMOTE_ADDR": "203.0.113.1"}
    second = {"REMOTE_ADDR": "198.51.100.9"}

    for i in range(messages.RATE_LIMIT):
        assert post(client, environ_base=first).status_code == 201, i
    assert post(client, environ_base=first).status_code == 429

    assert post(client, environ_base=second).status_code == 201


def test_forwarded_for_is_ignored_when_no_proxy_is_trusted(app, client,
                                                           monkeypatch):
    """Without TRUSTED_PROXY the header is worthless: six arrivals with six
    different X-Forwarded-For values share the one remote_addr window."""
    monkeypatch.delenv("TRUSTED_PROXY", raising=False)

    statuses = [
        post(client, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(messages.RATE_LIMIT + 1)
    ]

    assert statuses[-1] == 429, statuses


def test_trusted_proxy_keys_on_the_rightmost_forwarded_for(app, client,
                                                           monkeypatch):
    """With TRUSTED_PROXY set, the rightmost entry is the client. The
    leftmost entry is held constant across all six arrivals, so a limiter
    keying on the leftmost (the spoofable one) would refuse the sixth."""
    monkeypatch.setenv("TRUSTED_PROXY", "1")

    statuses = [
        post(
            client,
            headers={"X-Forwarded-For": f"198.51.100.7, 203.0.113.{i}"},
        ).status_code
        for i in range(messages.RATE_LIMIT + 1)
    ]

    assert statuses == [201] * (messages.RATE_LIMIT + 1), statuses


def test_trusted_proxy_ignores_the_spoofable_leftmost_entry(app, client,
                                                            monkeypatch):
    """The converse of the test above: vary the leftmost, hold the rightmost
    constant. All six are the same client, so the sixth is refused."""
    monkeypatch.setenv("TRUSTED_PROXY", "1")

    statuses = [
        post(
            client,
            headers={"X-Forwarded-For": f"203.0.113.{i}, 198.51.100.7"},
        ).status_code
        for i in range(messages.RATE_LIMIT + 1)
    ]

    assert statuses[-1] == 429, statuses


# --- mail ---------------------------------------------------------------------


class _FakeSMTP:
    """A stand-in for smtplib.SMTP that records what a send produced.

    It stands in for the transport only — the route, the validation, the
    store and the response are all the real thing in every test that uses it.
    """

    calls = None
    raises = False

    def __init__(self, *args, **kwargs):
        type(self).calls.append(("connect", args, kwargs))
        if type(self).raises:
            raise OSError("connection refused")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _noop(self, *args, **kwargs):
        return None

    ehlo = helo = starttls = login = quit = close = set_debuglevel = _noop

    def send_message(self, message, *args, **kwargs):
        type(self).calls.append(("send", message))

    def sendmail(self, sender, to, body, *args, **kwargs):
        type(self).calls.append(("send", body))


def install_fake_smtp(monkeypatch, raises=False):
    """Point app.messages' SMTP seam at _FakeSMTP and return its call log."""
    calls = []
    fake = type("_FakeSMTP", (_FakeSMTP,), {"calls": calls, "raises": raises})
    if hasattr(messages, "smtplib"):
        monkeypatch.setattr(messages.smtplib, "SMTP", fake)
        if hasattr(messages.smtplib, "SMTP_SSL"):
            monkeypatch.setattr(messages.smtplib, "SMTP_SSL", fake)
    elif hasattr(messages, "SMTP"):
        monkeypatch.setattr(messages, "SMTP", fake)
    else:
        pytest.fail("app.messages exposes no smtplib.SMTP seam to inject")
    return calls


def sends(calls):
    return [c for c in calls if c[0] == "send"]


def test_mail_is_sent_when_both_smtp_host_and_mail_to_are_set(app, client,
                                                              monkeypatch):
    calls = install_fake_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.setenv("MAIL_TO", "yllapito@esimerkki.fi")

    assert post(client).status_code == 201

    assert len(sends(calls)) == 1, calls
    assert len(stored(app)) == 1


def test_a_failing_send_never_costs_the_visitor_their_message(app, client,
                                                              monkeypatch):
    """The row is stored first and the send failure is swallowed: 201, and
    the message is really in the store — not merely reported as accepted."""
    calls = install_fake_smtp(monkeypatch, raises=True)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.setenv("MAIL_TO", "yllapito@esimerkki.fi")

    response = post(client)

    assert response.status_code == 201
    assert calls, "the failing transport was never reached"
    rows = stored(app)
    assert len(rows) == 1
    assert rows[0]["body"] == VALID["message"]


def test_smtp_host_without_a_recipient_sends_nothing(app, client, monkeypatch):
    calls = install_fake_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.delenv("MAIL_TO", raising=False)

    assert post(client).status_code == 201

    assert calls == []
    assert len(stored(app)) == 1


def test_no_mail_configuration_sends_nothing(app, client, monkeypatch):
    calls = install_fake_smtp(monkeypatch)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("MAIL_TO", raising=False)

    assert post(client).status_code == 201

    assert calls == []
    assert len(stored(app)) == 1


# --- the Reply-To header, and the boundary that guards it --------------------
#
# Three measured facts shape every assertion below. Each of them turns an
# obvious-looking assertion into one that cannot fail, so they are recorded
# here rather than rediscovered:
#
# 1. **A header reads back decoded.** mail["Reply-To"] answers
#    'märia@esimerkki.fi' for a value the wire carries as
#    '=?utf-8?q?m=C3=A4ria?=@esimerkki.fi'. An in-memory equality assertion
#    therefore passes over a mangled wire. The serialised form is the only
#    witness, which is what header_block exists for.
# 2. **The body is base64.** The template contains "Sähköposti", so
#    set_content picks Content-Transfer-Encoding: base64 and the string
#    "Bcc:" appears verbatim NOWHERE in mail.as_string() — not in the
#    headers and not in the body. So `"Bcc:" not in mail.as_string()` is a
#    vacuous pass. Assertions here are scoped to the header block, or made
#    against a decoded body.
# 3. **A refused assignment leaves the message clean.** After the stdlib
#    raises, no partial Reply-To survives — so "no header" really is the
#    observable outcome, not a half-written one.


def configure_mail(monkeypatch):
    """The two settings _notify needs before it builds a mail at all.

    Without both of them _notify returns before the Reply-To boundary is
    ever reached, so a test of that boundary written without these would
    pass whatever the boundary did.
    """
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.setenv("MAIL_TO", "yllapito@esimerkki.fi")


def sent_mail(calls):
    """The one live EmailMessage the fake transport recorded.

    send_message hands over the real object the route built, so these tests
    assert against the notification itself rather than a reconstruction.
    """
    recorded = sends(calls)
    assert len(recorded) == 1, recorded
    return recorded[0][1]


def header_block(mail):
    """Everything a receiving server reads before the first blank line.

    Serialised, because a header object reads back decoded (fact 1 above)
    and because the body legitimately carries the visitor's address
    verbatim — so a whole-serialisation assertion would either be vacuous
    or fail for an honest reason.
    """
    return mail.as_string().split("\n\n", 1)[0]


def header_lines(mail):
    """The header block as whole lines, so a membership test is exact.

    `"Reply-To: a@b" in header_block(...)` would also be satisfied by
    `Reply-To: a@b.evil.fi`; line membership cannot be.
    """
    return header_block(mail).split("\n")


def body_text(mail):
    """The notification's body as its reader would see it, decoded.

    Fact 2 above: the serialised body is base64, so any assertion about the
    body's text over as_string() passes without proving anything. The
    Content-Transfer-Encoding is asserted rather than assumed, so a future
    change that makes the body 7bit fails here loudly instead of silently
    handing back garbage.

    The assertion is about as_string() and nothing else. smtplib does its
    own serialisation on the way out, and against a real server that
    advertises 8BITMIME the wire body is Content-Transfer-Encoding: 8bit
    rather than base64 — measured, not assumed. The header block is
    identical either way, which is why every load-bearing assertion in this
    section reads the headers and not the body.
    """
    headers, _, encoded = mail.as_string().partition("\n\n")
    assert "Content-Transfer-Encoding: base64" in headers, headers
    return base64.b64decode(encoded).decode("utf-8")


def assert_refusal_warning(caplog, message_id, body):
    """The refusal tells the operator which row, and nothing else.

    A refused address is a visitor's personal data exactly like the name,
    the phone and the message, so the warning keeps the discipline the rest
    of this module already keeps: the id, and not one field value.
    """
    assert_warning_captured(caplog)
    assert f"id={message_id}" in caplog.text, caplog.text
    for field in ("name", "email", "message", "phone"):
        value = body.get(field)
        if value:
            assert value not in caplog.text, (field, caplog.text)


# A CRLF spliced mid-value, so _text's strip cannot quietly remove it and
# leave the test proving nothing. This is the payload the whole boundary
# exists for: on the wire it would end one header and begin another.
CRLF_INJECTION = "maria@esimerkki.fi\r\nBcc: hyokkaaja@esimerkki.fi"


def test_the_notification_replies_to_the_visitor_not_to_mail_from(
    app, client, monkeypatch
):
    """The point of the change: the owner hits reply in their mail client
    and reaches the person who wrote, instead of the address the site sends
    from.

    MAIL_FROM is set to something deliberately unanswerable so the
    assertion has somewhere wrong to land — with no Reply-To a reply goes
    to ei-vastauksia@esimerkki.fi, which is the behaviour this replaces.
    Asserted on the serialised header line, because that is the byte a mail
    client actually parses.
    """
    calls = install_fake_smtp(monkeypatch)
    configure_mail(monkeypatch)
    monkeypatch.setenv("MAIL_FROM", "ei-vastauksia@esimerkki.fi")

    assert post(client).status_code == 201

    mail = sent_mail(calls)
    lines = header_lines(mail)
    assert f"Reply-To: {VALID['email']}" in lines, lines
    assert "From: ei-vastauksia@esimerkki.fi" in lines, lines
    assert "To: yllapito@esimerkki.fi" in lines, lines


@pytest.mark.parametrize(
    "address",
    [
        "maria@esimerkki.fi",
        # Case is the visitor's to choose; nothing here may normalise it.
        "marIa@esimerkki.fi",
        # Accepted on purpose, and pinned so it stays accepted. The
        # boundary is a question about encoding, not about address
        # grammar: a comma cannot add a recipient, because smtplib derives
        # RCPT TO from To/Cc/Bcc and never from Reply-To. If a later edit
        # grows this predicate into RFC 5322 validation, this case is what
        # goes red.
        "a@b, c@d",
        "c@d",
    ],
)
def test_an_ascii_printable_address_reaches_the_header_verbatim(
    app, client, monkeypatch, address
):
    """Whatever the visitor typed is what the owner replies to — no
    encoding, no rewriting, and no header the visitor did not pay for."""
    calls = install_fake_smtp(monkeypatch)
    configure_mail(monkeypatch)

    assert post(client, payload(email=address)).status_code == 201

    mail = sent_mail(calls)
    lines = header_lines(mail)
    assert f"Reply-To: {address}" in lines, lines
    assert "=?" not in header_block(mail), header_block(mail)
    assert mail.get_all("Bcc") is None
    assert mail.get_all("Cc") is None
    assert mail.get_all("To") == ["yllapito@esimerkki.fi"]


def test_a_crlf_in_the_address_adds_no_header_and_still_notifies(
    app, client, monkeypatch
):
    """The header-injection case, whole: the owner is still notified, no
    second header appears, and the attacker's text is not destroyed — it
    stays on the body side of the boundary, where every other visitor value
    already lives.

    This fails against the naive one-liner in two independent ways: that
    version lets the stdlib's ValueError escape _notify and post_message
    altogether, so the POST answers 500 instead of 201 — measured, not
    assumed, because the assignment happens before _notify's own try opens
    — and were the send restored, a Bcc line would stand in the header
    block.
    """
    calls = install_fake_smtp(monkeypatch)
    configure_mail(monkeypatch)

    assert post(client, payload(email=CRLF_INJECTION)).status_code == 201

    mail = sent_mail(calls)
    assert mail["Reply-To"] is None
    assert mail.get_all("Bcc") is None
    # Scoped to the header block: "Bcc" in the whole serialisation would be
    # a vacuous test (fact 2 above), and the keys check below makes the
    # absence exhaustive rather than a spot check.
    assert "Bcc" not in header_block(mail), header_block(mail)
    assert set(mail.keys()) == {
        "Subject",
        "From",
        "To",
        "Content-Type",
        "Content-Transfer-Encoding",
        "MIME-Version",
    }
    assert "Bcc: hyokkaaja@esimerkki.fi" in body_text(mail)
    rows = stored(app)
    assert len(rows) == 1
    assert rows[0]["email"] == CRLF_INJECTION


# Every value here must cost the Reply-To and nothing else. Named, because
# a bare list of escapes in the failure output says nothing about which
# wrong implementation the case is aimed at.
SUPPRESSED_ADDRESSES = {
    # The stdlib raises IndexError on this printable ASCII address, and
    # _validate accepts it (it contains "@"). Fails against any version
    # that does not guard the assignment itself.
    "a plain typo the stdlib crashes on": "a@",
    "a crlf that would begin a header": CRLF_INJECTION,
    "a bare newline": "maria@esimerkki.fi\nBcc: hyokkaaja@esimerkki.fi",
    "a bare carriage return": "maria@esimerkki.fi\rBcc: hyokkaaja@esimerkki.fi",
    # The stdlib accepts NUL and DEL and serialises them into the header
    # line verbatim, so these two fail against a CR/LF-only guard.
    "a nul byte": "mar\x00ia@esimerkki.fi",
    "a del byte": "mar\x7fia@esimerkki.fi",
    # Non-ASCII: the header would serialise to an RFC 2047 encoded word
    # that looks like an address and cannot be replied to. These two fail
    # against an isprintable()-only predicate.
    "non-ascii in the local part": "märia@esimerkki.fi",
    # .fi has permitted ä and ö since 2005, so this is an ordinary Finnish
    # address, not an exotic input.
    "non-ascii in the domain": "maria@esimerkkí.fi",
}


@pytest.mark.parametrize(
    "address",
    list(SUPPRESSED_ADDRESSES.values()),
    ids=list(SUPPRESSED_ADDRESSES),
)
def test_an_unheaderable_address_costs_the_header_and_nothing_else(
    app, client, monkeypatch, caplog, address
):
    """A value that cannot become a header the site trusts loses the
    Reply-To — and only the Reply-To.

    The owner is still notified, the visitor still gets their 201, the row
    is still stored with the address exactly as typed, and the operator
    gets a warning naming the row and no field value. Dropping the mail
    instead would hand any sender a mute button for their own notification;
    rejecting the submission would cost the visitor their message, which is
    the one thing this module is built not to do.

    For the two non-ASCII cases the absence of "=?" from the serialised
    header block is asserted FIRST, and the order is deliberate. A header
    reads back decoded, so an *equality* assertion would pass over an
    encoded word on the wire; `is None` does discriminate, but it would
    also fire first and leave the "=?" check never evaluated, which is a
    backstop that can never bite. Asserted first, an implementation that
    encodes rather than suppresses fails here with the encoded word itself
    in the failure output, which names the bug rather than merely denying
    the header.
    """
    calls = install_fake_smtp(monkeypatch)
    configure_mail(monkeypatch)
    caplog.set_level(logging.DEBUG)
    body = payload(email=address)

    assert post(client, body).status_code == 201

    mail = sent_mail(calls)
    # First on purpose — see the docstring. Ordered after the `is None`
    # below it could never bite, because `is None` already discriminates.
    assert "=?" not in header_block(mail), header_block(mail)
    assert mail["Reply-To"] is None
    assert "Reply-To" not in header_block(mail), header_block(mail)
    assert mail.get_all("Bcc") is None
    rows = stored(app)
    assert len(rows) == 1
    assert rows[0]["email"] == address
    assert_refusal_warning(caplog, rows[0]["id"], body)


# --- never log a visitor's words ---------------------------------------------

SENTINEL_BODY = "kanarialintu-9f3a2b poikani anankytys huolettaa minua"
SENTINEL_NAME = "Kanarialintu-7c1d Testinen"
SENTINEL_EMAIL = "kanarialintu-4e9f@esimerkki.fi"
SENTINEL_PHONE = "040-kanarialintu-2b6c"

SENTINELS = (SENTINEL_BODY, SENTINEL_NAME, SENTINEL_EMAIL, SENTINEL_PHONE)


def sentinel_payload():
    return payload(
        name=SENTINEL_NAME,
        message=SENTINEL_BODY,
        email=SENTINEL_EMAIL,
        phone=SENTINEL_PHONE,
    )


def assert_no_sentinel_logged(caplog):
    """A visitor's words are health information. Nothing they typed may reach
    the log — not through the format string, not through the args."""
    for record in caplog.records:
        rendered = " ".join(
            [record.getMessage(), str(record.msg), str(record.args)]
        )
        for sentinel in SENTINELS:
            assert sentinel not in rendered, (record.name, record.getMessage())
    for sentinel in SENTINELS:
        assert sentinel not in caplog.text


def assert_warning_captured(caplog):
    """Guard against a vacuous pass: on the two paths that are supposed to
    warn, caplog must actually be seeing the app's logger. Without this, a
    caplog that captured nothing at all would satisfy every assertion in
    assert_no_sentinel_logged."""
    # create_app now warns at startup, but it runs in the `app` fixture's SETUP
    # phase and caplog.records holds only the call phase — so that record does
    # not reach here. A test that builds an app inside the call phase would get
    # a free WARNING and satisfy this vacuously.
    assert any(
        record.levelno >= logging.WARNING for record in caplog.records
    ), "no warning was captured — the never-log assertions would prove nothing"


def test_the_success_path_logs_no_field_values(app, client, caplog):
    caplog.set_level(logging.DEBUG)

    assert post(client, sentinel_payload()).status_code == 201

    assert stored(app)[0]["body"] == SENTINEL_BODY
    assert_no_sentinel_logged(caplog)


def test_the_send_failure_path_logs_no_field_values(app, client, caplog,
                                                    monkeypatch):
    """The path that definitely logs — a swallowed send failure warns — is
    the one most likely to spill the payload into the warning."""
    install_fake_smtp(monkeypatch, raises=True)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.setenv("MAIL_TO", "yllapito@esimerkki.fi")
    caplog.set_level(logging.DEBUG)

    assert post(client, sentinel_payload()).status_code == 201

    assert stored(app)[0]["body"] == SENTINEL_BODY
    assert_warning_captured(caplog)
    assert_no_sentinel_logged(caplog)


def test_the_missing_recipient_warning_is_field_free(app, client, caplog,
                                                     monkeypatch):
    install_fake_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.delenv("MAIL_TO", raising=False)
    caplog.set_level(logging.DEBUG)

    assert post(client, sentinel_payload()).status_code == 201

    assert_warning_captured(caplog)
    assert_no_sentinel_logged(caplog)


def test_the_refused_reply_address_path_logs_no_field_values(
    app, client, caplog, monkeypatch
):
    """The newest warning is the one most tempting to spill: an operator
    debugging a refused address wants to see the address, and the address
    is the visitor's personal data exactly like the message is.

    **The payload's shape is the whole point of this test and must not be
    tidied.** assert_no_sentinel_logged searches for SENTINEL_EMAIL as a
    plain substring, so the CRLF is appended AFTER an intact sentinel
    rather than spliced into the middle of one. Written the other way the
    sentinel no longer occurs in the offending address, and an implementer
    who logged the whole address "to help the operator debug it" would pass
    this test. Appending keeps the sentinel a prefix, so logging the
    address logs the sentinel and goes red. If a later edit does want the
    spliced form, the spliced string must join SENTINELS in the same
    commit.

    SMTP_HOST, MAIL_TO and the fake transport are all required rather than
    incidental: without them _notify returns before the boundary is
    reached, nothing warns, and every assertion below is vacuous. That is
    what assert_warning_captured is here to catch — and the send and the
    missing Reply-To pin the warning to this path rather than to a
    swallowed transport failure.
    """
    calls = install_fake_smtp(monkeypatch)
    configure_mail(monkeypatch)
    caplog.set_level(logging.DEBUG)
    body = sentinel_payload()
    body["email"] = SENTINEL_EMAIL + "\r\nBcc: hyokkaaja@esimerkki.fi"

    assert post(client, body).status_code == 201

    assert stored(app)[0]["body"] == SENTINEL_BODY
    mail = sent_mail(calls)
    assert mail["Reply-To"] is None
    assert_warning_captured(caplog)
    assert_no_sentinel_logged(caplog)


# --- the admin inbox ----------------------------------------------------------

INBOX = "/yllapito/viestit"


def test_inbox_is_refused_to_anonymous_visitors(client):
    response = client.get(INBOX)
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"


def test_inbox_renders_both_messages_newest_first_with_every_field(
    app, logged_in_admin
):
    older = insert_message(
        app,
        "Maria Koskinen",
        "Kuusivuotias poikani ei sano R-äännettä.",
        "maria@esimerkki.fi",
        "040 123 4567",
        1_700_000_000,
    )
    newer = insert_message(
        app,
        "Jussi Nieminen",
        "Isäni tarvitsee apua ja etsimme sopivaa palvelua.",
        "jussi@esimerkki.fi",
        "050 765 4321",
        1_700_086_400,
    )
    assert newer > older

    html = logged_in_admin.get(INBOX).get_data(as_text=True)

    for value in (
        "Maria Koskinen",
        "Kuusivuotias poikani ei sano R-äännettä.",
        "maria@esimerkki.fi",
        "040 123 4567",
        "Jussi Nieminen",
        "Isäni tarvitsee apua ja etsimme sopivaa palvelua.",
        "jussi@esimerkki.fi",
        "050 765 4321",
    ):
        assert value in html, value

    # ORDER BY id DESC — the newer message is rendered first.
    assert html.index("Jussi Nieminen") < html.index("Maria Koskinen")

    # The arrival time, formatted for a Finnish reader. Test and app share
    # one process, so the server-local rendering is deterministic here.
    for stamp in (1_700_000_000, 1_700_086_400):
        expected = time.strftime("%d.%m.%Y %H.%M", time.localtime(stamp))
        assert expected in html, expected
    # ...and never the raw epoch.
    assert "1700000000" not in html


def test_inbox_escapes_a_script_payload_in_every_field(app, logged_in_admin):
    attack = "<script>alert(1)</script>"
    insert_message(app, attack, attack, attack, attack, 1_700_000_000)

    html = logged_in_admin.get(INBOX).get_data(as_text=True)

    assert attack not in html
    assert "&lt;script&gt;" in html


def test_inbox_renders_message_text_literally(app, logged_in_admin):
    """Escaping, pinned past the <script> case.

    A body rendered through the rich-text filter instead of plain
    interpolation would survive the test above (sanitize_rich strips script
    tags), but would turn a visitor's typed <b> into markup and silently eat
    their angle brackets and ampersands. The inbox shows what was written.
    """
    insert_message(
        app, "Maria", "5 < 6 & <b>bold</b>", "maria@esimerkki.fi", None,
        1_700_000_000,
    )

    html = logged_in_admin.get(INBOX).get_data(as_text=True)

    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "<b>bold</b>" not in html
    assert "5 &lt; 6 &amp;" in html


def test_delete_removes_exactly_that_message_and_returns_to_the_inbox(
    app, logged_in_admin
):
    doomed = insert_message(
        app, "Maria", "poistettava", "maria@esimerkki.fi", None, 1_700_000_000
    )
    survivor = insert_message(
        app, "Jussi", "säilyy", "jussi@esimerkki.fi", None, 1_700_086_400
    )
    sections_before = table_rows(app, "sections")
    assert sections_before

    response = logged_in_admin.post(f"{INBOX}/{doomed}/poista")

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == INBOX
    assert [row["id"] for row in stored(app)] == [survivor]
    assert table_rows(app, "sections") == sections_before


def test_delete_is_refused_to_anonymous_visitors(app, client):
    message_id = insert_message(
        app, "Maria", "poistettava", "maria@esimerkki.fi", None, 1_700_000_000
    )

    response = client.post(f"{INBOX}/{message_id}/poista")

    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"
    assert [row["id"] for row in stored(app)] == [message_id]


def test_delete_of_an_unknown_id_is_a_404(app, logged_in_admin):
    response = logged_in_admin.post(f"{INBOX}/999999/poista")
    assert response.status_code == 404


def test_the_delete_audit_row_names_the_id_and_not_the_message(
    app, logged_in_admin
):
    message_id = insert_message(
        app, SENTINEL_NAME, SENTINEL_BODY, SENTINEL_EMAIL, SENTINEL_PHONE,
        1_700_000_000,
    )

    assert logged_in_admin.post(f"{INBOX}/{message_id}/poista").status_code == 302

    events = [row["event"] for row in table_rows(app, "audit_log")]
    for sentinel in SENTINELS:
        assert not any(sentinel in event for event in events), events
    assert any(str(message_id) in event for event in events), events


# --- the dialog: local, attribute-aware instruments --------------------------


class _DialogScope(HTMLParser):
    """Finds div.contact-dialog and records the start tags inside it.

    Structural on purpose: the login dialog's inputs and the header's own
    controls live outside this element, so nothing it reports can be
    satisfied by them. Until USR-COP-1 the on-page ``.contact-form``'s inputs
    were the example that mattered here; that form is gone, and the reason
    for scoping is not.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root_attrs = None
        self.descendants = []
        self._depth = 0
        self._done = False

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        if self._depth:
            self.descendants.append((tag, dict(attrs)))
            if tag == "div":
                self._depth += 1
            return
        if tag != "div":
            return
        found = dict(attrs)
        if "contact-dialog" not in (found.get("class") or "").split():
            return
        self.root_attrs = found
        self._depth = 1

    def handle_endtag(self, tag):
        if self._depth and tag == "div":
            self._depth -= 1
            if self._depth == 0:
                self._done = True


def dialog_scope(html):
    """(root_attrs, descendants) for div.contact-dialog, (None, []) if absent."""
    parser = _DialogScope()
    parser.feed(html)
    return parser.root_attrs, parser.descendants


class _ClassIndex(HTMLParser):
    """Every element carrying a given class token, in document order."""

    def __init__(self, cls):
        super().__init__(convert_charrefs=True)
        self._cls = cls
        self.tags = []

    def handle_starttag(self, tag, attrs):
        if self._cls in (dict(attrs).get("class") or "").split():
            self.tags.append(tag)


def class_count(html, cls):
    parser = _ClassIndex(cls)
    parser.feed(html)
    return len(parser.tags)


def class_tag(html, cls):
    """The tag name of the first element carrying `cls`, or None."""
    parser = _ClassIndex(cls)
    parser.feed(html)
    return parser.tags[0] if parser.tags else None


def cd_text(html, cls):
    """conftest's element_text, scoped to the one element carrying `cls`.

    element_text needs a tag name; the class is the address the plan pins, so
    the tag is resolved from the document first. Returns None — and so fails
    the test — exactly when no element carries the class, which is the
    falsification property each criterion test below depends on: delete that
    element and its test goes red.
    """
    tag = class_tag(html, cls)
    if tag is None:
        return None
    return element_text(html, tag, cls=cls)


# --- the dialog: contains-text criteria, one test per address ----------------

# (spec address, the class the plan pins for it, the byte-exact spec string)
CONTAINS_TEXT = [
    ("cp-contact-dialog.dialog-header.dialog-title", "cd-title",
     "Kerro, mitä etsit"),
    ("cp-contact-dialog.dialog-header.dialog-subtitle", "cd-subtitle",
     "Vastaan kahden arkipäivän kuluessa"),
    ("cp-contact-dialog.name-label", "cd-name-label", "Nimi"),
    ("cp-contact-dialog.message-label", "cd-message-label", "Mitä etsit?"),
    ("cp-contact-dialog.message-hint", "cd-message-hint", "Vapaa kuvaus"),
    ("cp-contact-dialog.message-helper", "cd-message-helper",
     "Kerro kenelle terapiaa haetaan ja mikä huolettaa."),
    ("cp-contact-dialog.contact-label", "cd-contact-label", "Yhteystiedot"),
    ("cp-contact-dialog.consent-row-0", "cd-consent",
     "Hyväksyn, että viestini käsitellään tietosuojaselosteen mukaisesti."),
    ("cp-contact-dialog.consent-row-1", "cd-consent",
     "En lähetä arkaluonteisia terveystietoja."),
    ("cp-contact-dialog.cancel-link", "cd-cancel", "Peruuta"),
    ("cp-contact-dialog.submit-button", "cd-submit", "Lähetä viesti"),
]


@pytest.mark.parametrize(
    "cls, text",
    [(cls, text) for _, cls, text in CONTAINS_TEXT],
    ids=[address for address, _, _ in CONTAINS_TEXT],
)
def test_dialog_contains_text_criterion(page_html, cls, text):
    """Each criterion's own element must exist, and must itself carry the
    string. "Nimi" already appears in the seeded page and every one of these
    strings could be hidden in the dialog's inline script, so neither a
    whole-document nor a root-scoped check would prove anything."""
    scoped = cd_text(page_html, cls)
    assert scoped is not None, f"no element carries class {cls}"
    assert text in scoped


# --- the dialog: is-visible criteria, structural -----------------------------


def test_dialog_root_is_present_and_starts_hidden(page_html):
    root_attrs, _ = dialog_scope(page_html)
    assert root_attrs is not None, "no div.contact-dialog in the document"
    assert "hidden" in root_attrs


def test_close_control_is_inside_the_dialog(page_html):
    """cp-contact-dialog.dialog-header.dialog-close — is-visible."""
    _, descendants = dialog_scope(page_html)
    classes = {
        token
        for _, attrs in descendants
        for token in (attrs.get("class") or "").split()
    }
    assert "cd-close" in classes


@pytest.mark.parametrize(
    "address, name",
    [
        ("cp-contact-dialog.name-input", "name"),
        ("cp-contact-dialog.email-input", "email"),
        ("cp-contact-dialog.phone-input", "phone"),
    ],
)
def test_dialog_input_is_inside_the_dialog(page_html, address, name):
    """is-visible for the three text inputs.

    Deliberately not test_auth's input_names: that parses the whole document,
    which also carries the login dialog's inputs, so a document-wide check
    could be satisfied by an element outside the dialog entirely. Only
    descendants of div.contact-dialog count here. (Until USR-COP-1 the
    on-page .contact-form served inputs named name and email and was the
    nearer hazard; it is gone, the scoping is not.)
    """
    _, descendants = dialog_scope(page_html)
    names = {
        attrs.get("name") for tag, attrs in descendants if tag == "input"
    }
    assert name in names, sorted(n for n in names if n)


def test_message_textarea_is_inside_the_dialog(page_html):
    """cp-contact-dialog.message-textarea — is-visible."""
    _, descendants = dialog_scope(page_html)
    names = {
        attrs.get("name") for tag, attrs in descendants if tag == "textarea"
    }
    assert "message" in names, sorted(n for n in names if n)


@pytest.mark.parametrize(
    "cls",
    [
        "cd-title",
        "cd-subtitle",
        "cd-name-label",
        "cd-message-label",
        "cd-message-hint",
        "cd-message-helper",
        "cd-contact-label",
        "cd-consent",
        "cd-cancel",
        "cd-submit",
        "cd-close",
    ],
)
def test_each_criterion_class_addresses_exactly_one_element(page_html, cls):
    """Each cd-* class is an address, and an address must resolve to one
    element — otherwise the scoped assertions above are ambiguous."""
    assert class_count(page_html, cls) == 1


# --- submission goes through the dialog, and nowhere else --------------------


class _Forms(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []

    def handle_starttag(self, tag, attrs):
        if tag == "form":
            self.forms.append(dict(attrs))


def forms(html):
    parser = _Forms()
    parser.feed(html)
    return parser.forms


def test_no_form_submits_to_the_api(page_html):
    """The endpoint is called by the dialog's script, never by a browser form
    post — a form action would navigate away from the page and lose the JSON
    contract entirely."""
    for attrs in forms(page_html):
        assert "/api/messages" not in (attrs.get("action") or "")


def test_the_page_draws_no_contact_form_and_the_dialogs_form_posts_none(
    page_html,
):
    """The page collects a message in ONE place, and that place posts JSON.

    USR-COP-1 deleted the on-page .contact-form from both skins: a second
    collection path is a second place the consent gate, the pre-validation and
    the failure reporting can drift, and it was the path that made pressing
    Lähetä throw the visitor's answers away. So the first half asserts the
    class is gone from the served document altogether.

    The second half is the fence LLM-COP-3 put up and LLM-COP-32 carried
    through its own reversal, carried forward again and WIDENED: no form in
    this document has an action and none has a method. The submission is JSON
    from contact_dialog.html's script, and an action attribute would navigate
    the page away and lose that contract entirely. Quantified over every form
    rather than over the dialog's, so a form added back later is caught by
    this test rather than by nothing. test_no_form_submits_to_the_api is the
    weaker claim — it only forbids an action naming the endpoint.
    """
    assert 'class="contact-form"' not in page_html
    assert class_count(page_html, "contact-form") == 0

    all_forms = forms(page_html)
    assert all_forms, "no <form> at all in the served document"
    for attrs in all_forms:
        assert attrs.get("action") is None, attrs
        assert attrs.get("method") is None, attrs

    # The dialog's own form is still the one that sends, and it still names
    # both outcome slots by id rather than by DOM adjacency: an id that names
    # nothing is a send reporting neither success nor failure.
    dialog_forms = [
        attrs
        for attrs in all_forms
        if "contact-dialog-form" in (attrs.get("class") or "").split()
    ]
    assert len(dialog_forms) == 1
    for attribute in ("data-result", "data-error"):
        target = dialog_forms[0].get(attribute)
        assert target, attribute
        assert f'id="{target}"' in page_html, target


def test_the_endpoint_is_named_once_and_only_inside_the_dialog_script(
    page_html,
):
    """The literal /api/messages occurs exactly once in the served document,
    and that one occurrence lies between the start and end of
    <script id="contact-dialog-script">. Anything else — a second copy, a
    form action, an occurrence outside the script — fails here."""
    assert page_html.count("/api/messages") == 1

    opening = re.search(
        r'<script[^>]*id="contact-dialog-script"[^>]*>', page_html
    )
    assert opening is not None, "no <script id=\"contact-dialog-script\">"
    start = opening.end()
    end = page_html.index("</script>", start)

    assert start < page_html.index("/api/messages") < end


# --- the Ota yhteyttä buttons actually open the dialog -----------------------


class _Buttons(HTMLParser):
    """(attrs, text) for every <button> in the document."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.buttons = []
        self._attrs = None
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "button":
            self._attrs = dict(attrs)
            self._parts = []

    def handle_endtag(self, tag):
        if tag == "button" and self._attrs is not None:
            self.buttons.append((self._attrs, "".join(self._parts)))
            self._attrs = None

    def handle_data(self, data):
        if self._attrs is not None:
            self._parts.append(data)


def buttons(html):
    parser = _Buttons()
    parser.feed(html)
    return parser.buttons


def dialog_script(html):
    """The source inside <script id="contact-dialog-script">."""
    opening = re.search(r'<script[^>]*id="contact-dialog-script"[^>]*>', html)
    assert opening is not None, 'no <script id="contact-dialog-script">'
    return html[opening.end():html.index("</script>", opening.end())]


def opener_classes(html):
    """The class tokens the dialog script binds its open handler to.

    Read out of the script rather than assumed, so a selector that no longer
    names anything real is caught rather than quietly believed.
    """
    match = re.search(
        r'querySelectorAll\(\s*"([^"]+)"\s*\)', dialog_script(html)
    )
    assert match is not None, "the dialog script names no opener selector"
    tokens = [part.strip() for part in match.group(1).split(",")]
    assert tokens and all(tokens), match.group(1)
    for token in tokens:
        # Simple class selectors only: past that this test cannot honestly
        # claim to know what the selector matches.
        assert re.fullmatch(r"\.[A-Za-z][\w-]*", token), token
    return [token.lstrip(".") for token in tokens]


def test_every_opener_selector_matches_a_real_element(page_html):
    """The ASK's first step: pressing Ota yhteyttä opens the dialog.

    A selector naming a class no element carries binds no handler and throws
    no error — the dialog simply never opens. Nothing else in this suite
    notices, because the markup and the script are each fine on their own.
    """
    tokens = opener_classes(page_html)
    for token in tokens:
        assert class_count(page_html, token) >= 1, token


def test_every_ota_yhteytta_button_opens_the_dialog(page_html):
    """The converse: it is not enough that the selector matches *something*.
    Every button whose label is the contact call to action must be among what
    it matches, or one of the two entry points is dead."""
    openers = set(opener_classes(page_html))
    labelled = [
        (attrs, text)
        for attrs, text in buttons(page_html)
        if text.strip() == "Ota yhteyttä"
    ]
    assert len(labelled) >= 2, [text for _, text in buttons(page_html)]
    for attrs, _ in labelled:
        classes = set((attrs.get("class") or "").split())
        assert classes & openers, sorted(classes)


def test_the_dialog_script_sits_outside_the_dialog_element(page_html):
    """conftest's element_text hands <script> source to handle_data, so a
    script inside div.contact-dialog would make every root-scoped text check
    satisfiable by the script body. The plan puts it outside; this proves it."""
    _, descendants = dialog_scope(page_html)
    ids = {attrs.get("id") for tag, attrs in descendants if tag == "script"}
    assert "contact-dialog-script" not in ids


def test_the_thanks_copy_is_served_hidden_in_its_own_element(page_html):
    """The confirmation the visitor sees after a successful send.

    Scoped like every other string here rather than checked against the whole
    document, and required to start hidden — copy that ships visible would
    thank a visitor who has not sent anything.

    The string is READ FROM THE SEED since USR-COP-1, not typed here: the
    copy is yhteydenotto.thanks, the owner's, and a literal written down in
    this file would go stale the moment the owner changed it. Both structural
    halves are unchanged — exactly one .cd-thanks, inside the dialog, shipping
    hidden — and they are what this test is really for.
    """
    seeded = dict(SEED_SECTIONS)["yhteydenotto"]["thanks"]
    assert seeded.strip(), "the seed has no thanks copy to serve"
    assert class_count(page_html, "cd-thanks") == 1
    scoped = cd_text(page_html, "cd-thanks")
    assert scoped is not None
    assert seeded in scoped

    _, descendants = dialog_scope(page_html)
    thanks = [
        attrs
        for _, attrs in descendants
        if "cd-thanks" in (attrs.get("class") or "").split()
    ]
    assert len(thanks) == 1, "the thanks copy is not inside the dialog"
    assert "hidden" in thanks[0]


# --- the ONE collection path, and the consent it carries --------------------
#
# LLM-COP-32 wired a second submission path into the page and these tests
# guarded it: a second way to collect personal data needs the same consent
# gate as the first, and the gate is the product's only record that the
# sender was told how their message is handled. USR-COP-1 removed the second
# path instead — one form, so nothing can drift — and the two tests comparing
# the page form's consent with the dialog's went with it. What remains is the
# claim that survives either arrangement: the dialog's own spec criteria hold
# with the privacy link threaded through its consent row.


class _ClassAttrs(HTMLParser):
    """The tag and attribute dict of every element carrying a class token."""

    def __init__(self, cls):
        super().__init__(convert_charrefs=True)
        self._cls = cls
        self.found = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if self._cls in (attributes.get("class") or "").split():
            self.found.append((tag, attributes))


def class_attrs(html, cls):
    parser = _ClassAttrs(cls)
    parser.feed(html)
    return parser.found


# The four caps app/messages.py enforces, as the literals a client would
# copy. Read off the module rather than typed here, so moving a cap moves
# this fence with it — a hardcoded 200 would go on passing against a client
# that had copied the NEW value.
SERVER_CAPS = (
    messages.NAME_MAX,
    messages.EMAIL_MAX,
    messages.PHONE_MAX,
    messages.MESSAGE_MAX,
)


def server_cap_literals(html):
    r"""Every server cap that appears as a WHOLE NUMBER in `html`.

    Word boundaries, and they are load-bearing: PHONE_MAX is 50, and a bare
    substring search finds it inside 500, 250, 1500 and most hex digests.
    `\b50\b` finds the number and nothing else.

    Shared with tests/test_page_v2.py, which asks this of the other skin.
    """
    return [cap for cap in SERVER_CAPS if re.search(rf"\b{cap}\b", html)]


def test_the_client_never_duplicates_the_servers_length_caps(page_html):
    """NAME_MAX, EMAIL_MAX, PHONE_MAX and MESSAGE_MAX stay the server's.

    The browser deliberately mirrors only the server's four PRESENCE
    refusals — empty name, empty message, empty email, unticked consent —
    because those are the everyday misses, and every arrival at the endpoint
    costs one of five hourly slots whether it is accepted or refused. The
    LENGTH caps are not mirrored: 200/200/50/5000 characters is not a limit
    anyone reaches by accident, and a copy of a Python constant inside a
    Jinja string literal is a duplicate with nothing to go red when the
    original moves.

    SCOPE: the WHOLE SERVED DOCUMENT, not only the dialog's script — a
    deliberate widening of what the plan asked for, stated here because the
    two are not the same fence. A maxlength="200" in the markup is exactly
    as much of a duplicate as a 200 in the JavaScript, and a script-only
    check cannot see it. Measured on the seeded store: none of the four
    numbers occurs anywhere in either served document today, so the widening
    costs nothing now. What it risks is an owner's own copy one day
    containing the bare word "200" — accepted, because a red test naming a
    cap literal is a one-line thing to look at and a silent duplicate is
    not.
    """
    assert server_cap_literals(page_html) == []


def test_the_dialogs_consent_row_gained_a_link_and_lost_no_words(page_html):
    """The link went into the dialog's consent row, and it did no damage.

    The row's sentence already promised a tietosuojaseloste and had nothing
    to open; wrapping that one word makes the promise keepable. The hazard
    is that the row is a spec address carrying two byte-exact contains-text
    criteria, and it is a <label>, so the anchor sits inside the very
    element those criteria are scoped to.

    Both halves are asserted rather than the first alone: that the anchor is
    there, AND that the two spec strings still read verbatim out of the row
    with it there. The second is what proves the first did no harm, and it
    is asserted here rather than left to test_dialog_contains_text_criterion
    — that test would pass just as happily if the row had been split into
    two elements, because it never looks at how many there are.
    """
    row = class_attrs(page_html, "cd-consent")
    assert len(row) == 1, f"cd-consent is an address; it resolves to {len(row)}"
    assert row[0][0] == "label", row[0]

    scoped = cd_text(page_html, "cd-consent")
    for _, cls, text in CONTAINS_TEXT:
        if cls == "cd-consent":
            assert text in scoped, text

    links = [
        attrs for tag, attrs in class_attrs(page_html, "gdpr-open") if tag == "a"
    ]
    assert len(links) == 2, (
        "expected exactly two privacy links in the V1 document — one in the "
        "site footer and one in the dialog's consent row, got "
        f"{links}"
    )
    # The row's link is NESTED, unlike the page's, which sits beside its
    # label. Inside a <label> that is safe: a label's activation behaviour
    # skips events targeted at interactive content and an <a href> is
    # interactive content — and the opener cancels the default action
    # anyway, for the href="#" jump.
    assert '<a class="gdpr-open" href="#">tietosuojaselosteen</a>' in page_html


# --- USR-COP-1: the dialog's four labels are the owner's words --------------

# Four strings absent from app/, so a template that kept its own literal fails
# here rather than passing by looking right.
DIALOG_VALUES = {
    "name_label": "Kutsumanimesi",
    "email_label": "Postiosoitteesi verkossa",
    "message_label": "Kerro asiasi lyhyesti",
    "thanks": "Kiitos! Palaan asiaan torstaihin mennessä.",
}

# The strings contact_dialog.html owned before USR-COP-1 moved these four
# fields into it from the deleted on-page form. None of them may survive in
# the dialog's markup once the store carries different words — an edit that
# APPENDS the stored value beside the literal, or leaves the literal on a
# second element, passes an equality check on one element and fails here.
DIALOG_LITERALS = {
    "name_label": "Nimi",
    "email_label": "Sähköposti",
    "message_label": "Mitä etsit?",
    "thanks": "Kiitos viestistäsi! Otan yhteyttä lähipäivinä.",
}


def dialog_markup(html):
    """The dialog element's own markup, attributes included.

    Attributes, because email_label is drawn as a placeholder and an
    aria-label rather than as a text node — cd_text cannot see either. The
    slice ends at the dialog's script, which sits outside the element
    (test_the_dialog_script_sits_outside_the_dialog_element) and would
    otherwise satisfy any string check with its own source.
    """
    start = html.index('<div class="contact-dialog"')
    end = html.index('<script id="contact-dialog-script"', start)
    return html[start:end]


@pytest.mark.parametrize(
    "field, cls",
    [
        ("name_label", "cd-name-label"),
        ("message_label", "cd-message-label"),
        ("thanks", "cd-thanks"),
        ("email_label", None),
    ],
    ids=["name_label", "message_label", "thanks", "email_label"],
)
def test_the_dialog_draws_the_owners_words(app, client, field, cls):
    """The four fields USR-COP-1 rehomed are read from the store, not typed
    into contact_dialog.html.

    They were yhteydenotto.name_label, .email_label, .message_label and
    .thanks all along — owner-editable in the side panel — but the elements
    that drew them were in the on-page form this change deletes. Rehoming them
    into the dialog is what keeps them rendering anywhere at all; this is the
    test that says they actually arrive there.

    The reader is app/sections.py:contact_dialog_copy. THIS TEST COVERS THE
    PUBLIC ROUTE ONLY. The other two routes that build their own context are
    covered by test_every_route_that_serves_the_dialog_serves_the_owners_words
    below, which exists precisely because a missed spread renders the label
    blank instead of raising — dropping it from app/edit.py or
    app/direct_edit.py was measured to leave this test, and the whole suite,
    green.

    cls=None is email_label, which has no element of its own: it draws the
    email input's placeholder AND its accessible name, and the two are
    asserted equal to each other — one string in two roles, so the input
    cannot end up announced as one thing and captioned as another.
    """
    assert_absent_from_app(*DIALOG_VALUES.values())

    edit_published_payload(
        app, "yhteydenotto", lambda payload: payload.update(**DIALOG_VALUES)
    )
    after = client.get("/").get_data(as_text=True)
    expected = DIALOG_VALUES[field]

    if cls is None:
        email_input = re.search(
            r'<input[^>]*name="email"[^>]*>', dialog_markup(after)
        )
        assert email_input is not None, "no email input in the dialog"
        attrs = dict(
            re.findall(r'(\w[\w-]*)="([^"]*)"', email_input.group(0))
        )
        # Both attributes are checked against the OWNER'S value, which also
        # settles that they equal each other — a third assertion comparing
        # them could not fail once both have been pinned to `expected`.
        assert attrs.get("placeholder") == expected, email_input.group(0)
        assert attrs.get("aria-label") == expected, email_input.group(0)
    else:
        scoped = cd_text(after, cls)
        assert scoped is not None, f"no element carries class {cls}"
        assert scoped.strip() == expected, scoped

    # ...and the word the template used to own is gone from the dialog with
    # it. Without this half, a build that rendered the literal AND the stored
    # value would pass the assertion above.
    assert DIALOG_LITERALS[field] not in dialog_markup(after), field


# Every route that serves contact_dialog.html, and there are three: the public
# page, the draft preview and direct edit mode. Each builds its own context and
# each has to spread contact_dialog_copy into it — three chances to miss one,
# and a missed one renders the labels BLANK rather than raising, because a bare
# undefined name in Jinja is the empty string.
DIALOG_ROUTES = ["/", "/muokkaa/esikatselu", "/muokkaa/sivu"]
DIALOG_ROUTE_IDS = ["public", "preview", "direct-edit"]


@pytest.mark.parametrize("path", DIALOG_ROUTES, ids=DIALOG_ROUTE_IDS)
def test_every_route_that_serves_the_dialog_serves_the_owners_words(
    app, logged_in_admin, path
):
    """The four rehomed fields arrive on EVERY route the dialog is served on,
    not only the public one.

    test_the_dialog_draws_the_owners_words above asks this of `/` and pins
    which element draws which field. It cannot see the other two routes, and
    dropping the spread from either of them was measured to leave the whole
    suite green: app/edit.py's /muokkaa/esikatselu and app/direct_edit.py's
    /muokkaa/sivu build their own contexts, so an owner previewing the site or
    editing it in place would open the contact dialog and find every label
    blank, with nothing red anywhere.

    Containment in the dialog's markup rather than a per-element check,
    deliberately: WHICH element draws each field is already pinned on `/`, and
    what this test is for is the wiring — whose failure mode is a label that is
    not in the document at all. The literal half is asserted too, so a route
    that fell back to contact_dialog.html's old hardcoded words is red here
    rather than green on a string that merely looks right.
    """
    assert_absent_from_app(*DIALOG_VALUES.values())
    edit_published_payload(
        app, "yhteydenotto", lambda payload: payload.update(**DIALOG_VALUES)
    )

    response = logged_in_admin.get(path)
    assert response.status_code == 200, (path, response.status_code)
    markup = dialog_markup(response.get_data(as_text=True))

    for field, value in DIALOG_VALUES.items():
        assert value in markup, (path, field, markup)
        assert DIALOG_LITERALS[field] not in markup, (path, field)


@pytest.mark.parametrize("path", DIALOG_ROUTES, ids=DIALOG_ROUTE_IDS)
def test_hiding_the_contact_section_leaves_the_dialogs_labels_alone(
    app, logged_in_admin, path
):
    """Hiding Yhteydenotto removes the SECTION and must not touch the DIALOG.

    This is the reason app/sections.py:contact_dialog_copy reads the row by
    kind and ignores state, exactly as site_chrome does. Every other section
    loader filters: visible_sections takes state = 'published' and
    draft_sections drops the hidden rows, so a reader built the obvious way
    would blank all four labels the moment the owner hid the section — while
    the header button and both hero CTAs went on opening the dialog, which is
    included unconditionally.

    tests/test_sections.py asks this of the function. This asks it of the three
    ROUTES, which is where the property is actually consumed, and it is asked
    of all three because the two admin routes read the DRAFT column through a
    second call site.

    The section's absence is asserted first, so the test cannot pass by the
    section never having been hidden — which would make every assertion below
    it a statement about the ordinary page.
    """
    edit_published_payload(
        app, "yhteydenotto", lambda payload: payload.update(**DIALOG_VALUES)
    )
    set_section_state(app, "yhteydenotto", "hidden")

    response = logged_in_admin.get(path)
    assert response.status_code == 200, (path, response.status_code)
    html = response.get_data(as_text=True)
    assert 'data-kind="yhteydenotto"' not in html, (
        f"{path} still renders the contact section, so hiding it proved nothing"
    )

    markup = dialog_markup(html)
    for field, value in DIALOG_VALUES.items():
        assert value in markup, (path, field, markup)


def test_the_gdpr_dialog_ships_hidden_with_exactly_one_script(page_html):
    """The new dialog is present, shut, and scripted once.

    Shut matters: a privacy statement that ships visible is a modal over the
    page for every visitor who never asked for one. Once matters because the
    script binds every .gdpr-open in the document — included twice, every
    link would open the dialog twice and the second open would overwrite the
    stored focus with the close button, so closing would never return the
    visitor to where they were.
    """
    roots = class_attrs(page_html, "gdpr-dialog")
    assert len(roots) == 1, roots
    assert "hidden" in roots[0][1], roots[0][1]
    assert page_html.count('id="gdpr-dialog-script"') == 1


def test_the_gdpr_script_names_no_endpoint_of_its_own(page_html):
    """A second inline script is a second place a URL could appear.

    test_the_endpoint_is_named_once_and_only_inside_the_dialog_script says
    /api/messages occurs exactly once document-wide; this says the same
    thing from the other end, so a reader of the new file can see the
    constraint it is under without having to find that test first.
    """
    opening = re.search(r'<script[^>]*id="gdpr-dialog-script"[^>]*>', page_html)
    assert opening is not None
    end = page_html.index("</script>", opening.end())
    assert "/api/" not in page_html[opening.end():end]


@pytest.mark.parametrize(
    "case, body",
    [
        ("consent absent", {k: v for k, v in VALID.items() if k != "consent"}),
        ("consent false", payload(consent=False)),
        # The STRING "true". A client that serialized its checkbox as text
        # would satisfy any truthiness test written in a hurry, and this is
        # the one field where "close enough" is not good enough. Not covered
        # by test_without_consent_nothing_is_stored, which tries "on", 1 and
        # null — none of which LOOKS like consent the way this one does.
        ("consent is the string true", payload(consent="true")),
    ],
)
def test_a_consentless_post_is_refused_by_name_whichever_form_sent_it(
    app, client, case, body
):
    """The rule the artifact forbade weakening, asserted in its own words.

    The endpoint cannot tell the dialog's submission from the on-page
    form's — both are the same JSON at the same URL — so proving the rule
    once proves it for both paths, and there is no inline-only relaxation
    that could hide anywhere. The ERROR STRING is asserted, not just the
    400: a 400 could be any of nine refusals in _validate, and "consent is
    required" is the only one that says the gate itself held.
    """
    response = post(client, body)
    assert response.status_code == 400, case
    assert response.get_json()["error"] == "consent is required", case
    assert stored(app) == [], case
