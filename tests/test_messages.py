"""LLM-COP-3 — the contact dialog, POST /api/messages, and the admin inbox.

Spec: cp-contact-dialog (fetched from the SpecWeaver server; every
contains-text string below is copied byte-for-byte out of that JSON, never
retyped — the Finnish diacritics are load-bearing).

Three things this file refuses to do, because each of them would let a test
pass while proving nothing:

1. **No whole-document contains-text assertions for the dialog.** The seeded
   public page already renders a contact form (app/seed.py -> the
   ``.contact-form`` block in app/templates/page.html) whose label copy
   includes "Nimi". A bare ``"Nimi" in html`` passes today, with no dialog in
   the document at all.

2. **No assertion scoped only to the dialog root.** conftest's ``element_text``
   concatenates *every* descendant text node, and ``HTMLParser`` hands inline
   ``<script>`` source to ``handle_data`` — so a string that appears anywhere
   in the dialog's own inline script would satisfy a root-scoped check. Every
   contains-text criterion here is therefore scoped to its own uniquely
   classed ``cd-*`` element, and each test fails if that one element is
   deleted.

3. **No document-wide input-name check.** ``input_names`` in test_auth parses
   the whole document, and the seeded form already serves inputs named
   ``name``, ``email`` and ``message``. Only ``phone`` would be new, so a
   document-wide check is three-quarters vacuous. The is-visible criteria use
   ``dialog_scope`` below, which is attribute-aware *and* structural: the
   seeded form's identically named inputs sit outside ``div.contact-dialog``,
   so these assertions genuinely fail without the dialog.

``dialog_scope`` and ``class_count`` are defined here rather than in
tests/conftest.py deliberately: they are this unit's instruments, and
conftest is owned elsewhere.
"""

import logging
import re
import time
from html.parser import HTMLParser
from urllib.parse import urlparse

import pytest

from app import db as database
from app import messages
from tests.conftest import element_text

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
    assert version == 3


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
    assert version == 3


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
    monkeypatch.setenv("MAIL_TO", "anna@esimerkki.fi")

    assert post(client).status_code == 201

    assert len(sends(calls)) == 1, calls
    assert len(stored(app)) == 1


def test_a_failing_send_never_costs_the_visitor_their_message(app, client,
                                                              monkeypatch):
    """The row is stored first and the send failure is swallowed: 201, and
    the message is really in the store — not merely reported as accepted."""
    calls = install_fake_smtp(monkeypatch, raises=True)
    monkeypatch.setenv("SMTP_HOST", "smtp.esimerkki.fi")
    monkeypatch.setenv("MAIL_TO", "anna@esimerkki.fi")

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
    monkeypatch.setenv("MAIL_TO", "anna@esimerkki.fi")
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
        "Isäni sai halvauksen ja etsimme afasiakuntoutusta.",
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
        "Isäni sai halvauksen ja etsimme afasiakuntoutusta.",
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

    Structural on purpose: the seeded ``.contact-form`` inputs live outside
    this element, so nothing it reports can be satisfied by them.
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
    and the seeded .contact-form already serves inputs named name and email.
    Only descendants of div.contact-dialog count here.
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


def test_the_seeded_contact_form_stays_inert(page_html):
    """Cheap regression insurance on the seeded .contact-form: no action, no
    method, and a non-submitting button. The real weight is carried by the
    next test — this one only catches the form being wired up by accident."""
    contact_forms = [
        attrs
        for attrs in forms(page_html)
        if "contact-form" in (attrs.get("class") or "").split()
    ]
    assert len(contact_forms) == 1
    attrs = contact_forms[0]
    assert attrs.get("action") is None
    assert attrs.get("method") is None
    match = re.search(
        r'<form[^>]*class="[^"]*contact-form[^"]*"[^>]*>(.*?)</form>',
        page_html,
        re.DOTALL,
    )
    assert match is not None
    assert "<button type=\"button\"" in match.group(1)


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
    """
    assert class_count(page_html, "cd-thanks") == 1
    scoped = cd_text(page_html, "cd-thanks")
    assert scoped is not None
    assert "Kiitos viestistäsi! Otan yhteyttä lähipäivinä." in scoped

    _, descendants = dialog_scope(page_html)
    thanks = [
        attrs
        for _, attrs in descendants
        if "cd-thanks" in (attrs.get("class") or "").split()
    ]
    assert len(thanks) == 1, "the thanks copy is not inside the dialog"
    assert "hidden" in thanks[0]
