"""Shared fixtures and a small HTML text extractor (stdlib only).

The page tests assert the spec's contains-text criteria byte-exact, so the
extractor concatenates raw text nodes without normalizing whitespace.
"""

import json
from html.parser import HTMLParser

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app import db as database

ADMIN_USERNAME = "yllapitaja"
ADMIN_PASSWORD = "oikea salasana 123"

# The one place in the suite that names the mockup persona, on purpose.
#
# LLM-COP-10 removed a speech therapist's identity from a product that is a
# GENERIC contact page. The guards in test_seed.py and test_db.py assert that
# identity is ABSENT, and a guard has to name what it forbids — so this
# constant exists once, here, and the release grep is run with
# `--exclude=conftest.py`. Any other occurrence anywhere in app/ or tests/ is
# a regression, which is exactly what that grep is looking for.
#
# It is deliberately wider than the artifact's own stated gate, which missed
# "anna.virtanen": that has a dot where the stated pattern had a space.
PERSONA_PATTERN = (
    r"anna|puheterap|2938471|valvira|virtanen|logopedia|afasia"
)


@pytest.fixture
def conn(tmp_path):
    """A migrated, empty connection to a real temp-file DB (not :memory:)."""
    c = database.connect(str(tmp_path / "test.sqlite3"))
    database.migrate(c)
    yield c
    c.close()


@pytest.fixture
def app(tmp_path):
    """A freshly created app with its own seeded temp DB (function-scoped,
    so mutation tests never leak into each other)."""
    return create_app(instance_path=str(tmp_path / "instance"))


@pytest.fixture
def client(app):
    return app.test_client()


def create_admin(app, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    """Insert the admin row with a real werkzeug hash — the same primitive
    the CLI uses, which the CLI tests in test_auth prove independently."""
    c = database.connect(app.config["DATABASE"])
    try:
        c.execute(
            "INSERT INTO admin_user (username, password_hash) VALUES (?, ?)",
            (username, generate_password_hash(password)),
        )
        c.commit()
    finally:
        c.close()


def login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD,
          remember=False):
    data = {"kayttajatunnus": username, "salasana": password}
    if remember:
        data["pysy"] = "1"
    return client.post("/yllapito/kirjaudu", data=data)


@pytest.fixture
def logged_in_admin(app):
    """A test client holding a real admin session: create_admin run against
    the app's DB and login() posted and asserted — an admin *session*, not
    just an admin account."""
    create_admin(app)
    admin = app.test_client()
    response = login(admin)
    assert response.status_code == 302
    return admin


@pytest.fixture(scope="session")
def page_html(tmp_path_factory):
    """One rendered document, fetched once, shared by every read-only
    contains-text check — proving all criteria hold in the same document."""
    app = create_app(
        instance_path=str(tmp_path_factory.mktemp("readonly") / "instance")
    )
    response = app.test_client().get("/")
    assert response.status_code == 200
    return response.get_data(as_text=True)


class _ElementText(HTMLParser):
    """Collects the raw text content of the first element matching
    tag (and optionally a class token), children included."""

    def __init__(self, tag, cls):
        super().__init__(convert_charrefs=True)
        self._tag = tag
        self._cls = cls
        self._depth = 0
        self.found = False
        self.done = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self._depth:
            if tag == self._tag:
                self._depth += 1
            return
        if tag != self._tag:
            return
        if self._cls is not None:
            classes = (dict(attrs).get("class") or "").split()
            if self._cls not in classes:
                return
        self.found = True
        self._depth = 1

    def handle_endtag(self, tag):
        if self._depth and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self.done = True

    def handle_data(self, data):
        if self._depth and not self.done:
            self.parts.append(data)


def element_text(html, tag, cls=None):
    """Text content of the first <tag> (optionally with class token cls),
    or None if no such element exists in the document."""
    parser = _ElementText(tag, cls)
    parser.feed(html)
    if not parser.found:
        return None
    return "".join(parser.parts)


def edit_published_payload(app, kind, edit):
    """Rewrite one section's published (and draft) payload through a real
    connection to the app's own DB file — the same store the route reads."""
    c = database.connect(app.config["DATABASE"])
    try:
        row = c.execute(
            "SELECT id, published FROM sections WHERE kind = ?", (kind,)
        ).fetchone()
        payload = json.loads(row["published"])
        edit(payload)
        text = json.dumps(payload, ensure_ascii=False)
        c.execute(
            "UPDATE sections SET draft = ?, published = ? WHERE id = ?",
            (text, text, row["id"]),
        )
        c.commit()
    finally:
        c.close()


def set_section_state(app, kind, state):
    c = database.connect(app.config["DATABASE"])
    try:
        c.execute("UPDATE sections SET state = ? WHERE kind = ?", (state, kind))
        c.commit()
    finally:
        c.close()


def publish_something(app, admin):
    """Turn the app's database into a *configured* one — a publish that
    really lands — through the real routes, with `admin` an already
    logged-in client.

    THE TRAP this helper exists for: POST /api/publish on a freshly seeded
    database publishes nothing at all. seed_if_empty writes draft ==
    published on every row, and publish_dirty updates only the rows whose
    draft text differs from their published text, so a bare publish
    affects ZERO rows, leaves previous_published NULL everywhere, and
    leaves wizard.is_first_run True. A "configured database" test built on
    a bare publish would therefore pass for the wrong reason (or fail
    surprisingly). So this dirties a draft first and publishes after, and
    asserts the publish reported the row it dirtied.

    Returns the list of published section ids.
    """
    c = database.connect(app.config["DATABASE"])
    try:
        row = c.execute(
            "SELECT id, draft FROM sections WHERE kind = 'hero'"
        ).fetchone()
        section_id = row["id"]
        payload = json.loads(row["draft"])
    finally:
        c.close()

    # A whole-payload write, as PUT /api/sections/<id>/draft requires:
    # the stored draft with exactly one field changed.
    payload["title"] = "Muokattu otsikko"
    json_accept = {"Accept": "application/json"}
    response = admin.put(
        f"/api/sections/{section_id}/draft", json=payload, headers=json_accept
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["badge"] == "Luonnos"  # the draft really is dirty

    response = admin.post("/api/publish", headers=json_accept)
    assert response.status_code == 200
    published = response.get_json()["published"]
    assert published == [section_id], published  # the publish really landed
    return published


def section_rows(app):
    """Every section row straight from the app's own DB file, in page
    order — what the store holds, not what a route says it holds."""
    c = database.connect(app.config["DATABASE"])
    try:
        return [
            dict(row)
            for row in c.execute(
                "SELECT id, kind, position, state, draft, published,"
                " previous_published FROM sections ORDER BY position"
            ).fetchall()
        ]
    finally:
        c.close()


def delete_section(app, kind):
    """Remove one seeded section, so a kind is genuinely absent.

    seed_if_empty inserts all six kinds, so on a seeded database there is
    no kind left to add; a test of the add path has to make one missing
    first, and it makes it missing in the real store.
    """
    c = database.connect(app.config["DATABASE"])
    try:
        c.execute("DELETE FROM sections WHERE kind = ?", (kind,))
        c.commit()
    finally:
        c.close()
