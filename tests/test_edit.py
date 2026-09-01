"""Edit mode (LLM-COP-4) — /muokkaa, /muokkaa/esikatselu, the draft PUT and
POST /api/publish, against the real routes and the app's real DB file.

Governing spec cp-main-edit: the shell's contains-text criteria are asserted
byte-exact against the served /muokkaa document, one test per addressed
criterion. The spec states no testids, so nothing here invents data-testid
selectors; is-visible criteria are proven as presence in the served document,
matching tests/test_page.py's convention. The preview-* criteria hold because
/muokkaa/esikatselu renders the same page.html the public page tests already
cover; here the preview is proven to render from *drafts* instead.

Brief reviewer checks covered where the test client can reach them:
editing Pääotsikko changes the preview but not the logged-out public page
until Julkaise; a draft <script> in a rich field is stripped server-side;
the Palvelut payload is a real list (a fourth service round-trips to the
public page). Panel behaviors that exist only in the browser (Peruuta,
the live counter, the generated form) are the run-for-real phase's job —
a test client executes no JavaScript.
"""

import copy
import json
import time
from urllib.parse import urlparse

import pytest

from app import db as database
from app.fields import FIELD_LABELS, FIELDS
from app.sections import badge, draft_sections
from app.seed import SEED_SECTIONS
from tests.conftest import set_section_state

SEED_BY_KIND = dict(SEED_SECTIONS)
JSON_ACCEPT = {"Accept": "application/json"}


def hero_payload():
    return copy.deepcopy(SEED_BY_KIND["hero"])


def section_row(app, kind):
    c = database.connect(app.config["DATABASE"])
    try:
        return c.execute(
            "SELECT * FROM sections WHERE kind = ?", (kind,)
        ).fetchone()
    finally:
        c.close()


def all_rows(app):
    c = database.connect(app.config["DATABASE"])
    try:
        return c.execute("SELECT * FROM sections ORDER BY position").fetchall()
    finally:
        c.close()


def put_draft(admin, app, kind, payload):
    row = section_row(app, kind)
    return admin.put(
        f"/api/sections/{row['id']}/draft", json=payload, headers=JSON_ACCEPT
    )


# --- the gate (auth.require_admin over the edit routes) ----------------------


@pytest.mark.parametrize("path", ["/muokkaa", "/muokkaa/esikatselu"])
def test_anonymous_get_redirects_to_yllapito(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"


def test_anonymous_put_preferring_json_gets_401(client):
    response = client.put(
        "/api/sections/1/draft", json=hero_payload(), headers=JSON_ACCEPT
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_anonymous_publish_preferring_json_gets_401(client):
    response = client.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


# --- draft PUT, preview, and Julkaise ----------------------------------------


def test_draft_put_stores_the_draft_without_touching_published(
    logged_in_admin, app
):
    payload = hero_payload()
    payload["title"] = "Muokattu otsikko"
    before = section_row(app, "hero")

    response = put_draft(logged_in_admin, app, "hero", payload)
    assert response.status_code == 200

    after = section_row(app, "hero")
    assert json.loads(after["draft"])["title"] == "Muokattu otsikko"
    assert after["published"] == before["published"]  # byte-identical

    # The logged-out public page still shows the published title
    # (brief reviewer check: only publishes after Julkaise).
    html = app.test_client().get("/").get_data(as_text=True)
    assert "Muokattu otsikko" not in html
    assert SEED_BY_KIND["hero"]["title"] in html


def test_preview_renders_from_the_draft(logged_in_admin, app):
    payload = hero_payload()
    payload["title"] = "Muokattu otsikko"
    assert put_draft(logged_in_admin, app, "hero", payload).status_code == 200

    html = logged_in_admin.get("/muokkaa/esikatselu").get_data(as_text=True)
    assert "Muokattu otsikko" in html  # the draft, not the published payload


def test_publish_flips_the_public_page(logged_in_admin, app):
    payload = hero_payload()
    payload["title"] = "Muokattu otsikko"
    assert put_draft(logged_in_admin, app, "hero", payload).status_code == 200

    response = logged_in_admin.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 200
    assert response.get_json()["published"] == [section_row(app, "hero")["id"]]

    html = app.test_client().get("/").get_data(as_text=True)
    assert "Muokattu otsikko" in html


def test_publish_touches_exactly_the_dirty_rows(logged_in_admin, app):
    payload = hero_payload()
    payload["title"] = "Muokattu otsikko"
    before = {row["kind"]: tuple(row) for row in all_rows(app)}
    old_published = section_row(app, "hero")["published"]
    assert put_draft(logged_in_admin, app, "hero", payload).status_code == 200

    ids = logged_in_admin.post(
        "/api/publish", headers=JSON_ACCEPT
    ).get_json()["published"]

    hero = section_row(app, "hero")
    assert ids == [hero["id"]]
    assert hero["published"] == hero["draft"]
    assert hero["previous_published"] == old_published
    for row in all_rows(app):
        if row["kind"] == "hero":
            continue
        # Clean rows byte-identical, previous_published untouched.
        assert tuple(row) == before[row["kind"]]
        assert row["previous_published"] is None


def test_noop_put_of_the_seeded_hero_payload_stays_julkaistu(
    logged_in_admin, app
):
    # The serialization-convention trap: the seeded payload contains "ä"
    # (and "·"), so this fails if the PUT serializes with ensure_ascii=True
    # or in a different key order than the seed's.
    payload = hero_payload()
    assert "ä" in payload["ingress"]
    before = section_row(app, "hero")
    assert before["draft"] == before["published"]

    response = put_draft(logged_in_admin, app, "hero", payload)
    assert response.status_code == 200
    assert response.get_json()["badge"] == "Julkaistu"

    after = section_row(app, "hero")
    assert after["draft"] == before["draft"]  # byte-identical no-op

    # And Julkaise publishes nothing.
    ids = logged_in_admin.post(
        "/api/publish", headers=JSON_ACCEPT
    ).get_json()["published"]
    assert ids == []


def test_put_response_carries_saved_at_and_the_sections_badge(
    logged_in_admin, app
):
    payload = hero_payload()
    payload["title"] = "Muokattu otsikko"
    body = put_draft(logged_in_admin, app, "hero", payload).get_json()

    assert abs(body["saved_at"] - int(time.time())) < 5
    row = section_row(app, "hero")
    # The badge follows app.sections.badge over the real stored row.
    assert body["badge"] == badge(
        row["state"], row["draft"], row["published"]
    )
    assert body["badge"] == "Luonnos"


def test_put_badge_for_a_hidden_section_is_piilotettu(logged_in_admin, app):
    set_section_state(app, "tietoa", "hidden")
    body = put_draft(
        logged_in_admin, app, "tietoa", copy.deepcopy(SEED_BY_KIND["tietoa"])
    ).get_json()
    assert body["badge"] == "Piilotettu"


# --- validation and sanitization at the seam ---------------------------------


def test_oversized_title_answers_400_and_writes_nothing(logged_in_admin, app):
    payload = hero_payload()
    payload["title"] = "x" * 61
    before = section_row(app, "hero")

    response = put_draft(logged_in_admin, app, "hero", payload)

    assert response.status_code == 400
    assert "title" in response.get_json()["errors"]
    after = section_row(app, "hero")
    assert tuple(after) == tuple(before)  # nothing written


def test_put_script_in_rich_field_is_stripped_from_draft_and_preview(
    logged_in_admin, app
):
    # Brief hazard: sanitize on write, so the preview never renders
    # unsanitized HTML into the admin's own session.
    payload = hero_payload()
    payload["ingress"] = "Eheä<script>alert(1)</script> <b>sisältö</b>"
    assert put_draft(logged_in_admin, app, "hero", payload).status_code == 200

    stored = json.loads(section_row(app, "hero")["draft"])
    assert stored["ingress"] == "Eheä <strong>sisältö</strong>"

    html = logged_in_admin.get("/muokkaa/esikatselu").get_data(as_text=True)
    assert "alert(1)" not in html
    assert "Eheä <strong>sisältö</strong>" in html


def test_render_rich_sanitizes_a_script_already_published(app):
    # Defense in depth: a <script> forced straight into the published
    # payload (bypassing the write path) still never reaches the page.
    from tests.conftest import edit_published_payload

    def poison(payload):
        payload["ingress"] = "Eheä<script>alert(9)</script> sisältö"

    edit_published_payload(app, "hero", poison)
    html = app.test_client().get("/").get_data(as_text=True)
    assert "alert(9)" not in html
    assert "Eheä sisältö" in html


def test_palvelut_edits_a_real_list_not_a_fixed_three(logged_in_admin, app):
    # Brief reviewer check: the Palvelut payload is a list — a fourth
    # service round-trips through draft and Julkaise to the public page.
    payload = copy.deepcopy(SEED_BY_KIND["palvelut"])
    payload["services"].append("Neljäs palvelu")
    assert len(payload["services"]) == 4
    assert (
        put_draft(logged_in_admin, app, "palvelut", payload).status_code
        == 200
    )
    assert (
        logged_in_admin.post("/api/publish", headers=JSON_ACCEPT).status_code
        == 200
    )

    html = app.test_client().get("/").get_data(as_text=True)
    assert "Neljäs palvelu" in html
    # cp-service-card.service-title: each use states its own contents.
    assert SEED_BY_KIND["palvelut"]["services"][0] in html


def test_unknown_section_id_is_404(logged_in_admin):
    response = logged_in_admin.put(
        "/api/sections/999/draft", json=hero_payload(), headers=JSON_ACCEPT
    )
    assert response.status_code == 404


# --- draft_sections and hidden rows ------------------------------------------


def test_draft_sections_excludes_hidden_rows_by_default(app):
    set_section_state(app, "tietoa", "hidden")
    c = database.connect(app.config["DATABASE"])
    try:
        kinds = [s["kind"] for s in draft_sections(c)]
        assert "tietoa" not in kinds
        with_hidden = draft_sections(c, include_hidden=True)
        assert "tietoa" in [s["kind"] for s in with_hidden]
        hidden = next(s for s in with_hidden if s["kind"] == "tietoa")
        assert hidden["badge"] == "Piilotettu"
    finally:
        c.close()


def test_publish_dirty_publishes_only_the_dirty_row(conn):
    # Step 2 criterion (a), on hand-planted rows: of three rows only the
    # dirty one changes; its previous_published holds the old text; the
    # clean rows' published is byte-identical before and after.
    from app.sections import publish_dirty

    rows = [
        ("hero", 1, '{"title": "a"}', '{"title": "a"}'),
        ("tietoa", 2, '{"nostolause": "uusi"}', '{"nostolause": "vanha"}'),
        ("sijainti", 3, '{"address": "x"}', '{"address": "x"}'),
    ]
    for kind, position, draft, published in rows:
        conn.execute(
            "INSERT INTO sections (kind, position, state, draft, published,"
            " previous_published) VALUES (?, ?, 'published', ?, ?, NULL)",
            (kind, position, draft, published),
        )
    conn.commit()

    dirty_id = conn.execute(
        "SELECT id FROM sections WHERE kind = 'tietoa'"
    ).fetchone()["id"]
    assert publish_dirty(conn) == [dirty_id]

    stored = {
        row["kind"]: row
        for row in conn.execute("SELECT * FROM sections").fetchall()
    }
    assert stored["tietoa"]["published"] == '{"nostolause": "uusi"}'
    assert stored["tietoa"]["previous_published"] == '{"nostolause": "vanha"}'
    for kind, _position, _draft, published in rows:
        if kind == "tietoa":
            continue
        assert stored[kind]["published"] == published
        assert stored[kind]["previous_published"] is None

    # Publishing again is a no-op: nothing is dirty any more.
    assert publish_dirty(conn) == []


def bootstrap_json(html):
    """The panel controller's JSON bootstrap, parsed out of the /muokkaa
    document exactly where edit.js reads it (script#bootstrap)."""
    marker = '<script id="bootstrap" type="application/json">'
    start = html.index(marker) + len(marker)
    return json.loads(html[start : html.index("</script>", start)])


def test_hidden_section_is_absent_from_preview_but_editable(
    logged_in_admin, app
):
    set_section_state(app, "tietoa", "hidden")
    preview = logged_in_admin.get("/muokkaa/esikatselu").get_data(as_text=True)
    assert SEED_BY_KIND["tietoa"]["nostolause"] not in preview

    # ... while the panel bootstrap still carries it, badge Piilotettu.
    shell = logged_in_admin.get("/muokkaa").get_data(as_text=True)
    sections = bootstrap_json(shell)["sections"]
    tietoa = next(s for s in sections if s["kind"] == "tietoa")
    assert tietoa["payload"]["nostolause"] == SEED_BY_KIND["tietoa"][
        "nostolause"
    ]
    assert tietoa["badge"] == "Piilotettu"


# --- field order end to end (LLM-COP-9) --------------------------------------


def test_bootstrap_fields_keep_declaration_order(logged_in_admin):
    """The served bootstrap lists every kind's fields in app/fields.py
    declaration order, not alphabetically.

    This pins the *input* to section-form.js:233, which draws
    `(only || Object.keys(fields[kind]))` — edit.js passes no `only`, so
    the panel's draw order IS the shipped JSON's key order, and an
    alphabetised bootstrap silently reorders the form (the owner met
    Painike 1 before Yläotsikko, Pääotsikko last). Jinja's |tojson passes
    the environment's json.dumps_kwargs policy explicitly, so only that
    policy — never app.json.sort_keys, which DefaultJSONProvider merely
    setdefaults — decides this order; create_app sets it.

    pytest cannot see the *rendered* order: this suite executes no
    JavaScript. The browser check is what pins the output; this pins what
    the browser is handed.
    """
    html = logged_in_admin.get("/muokkaa").get_data(as_text=True)
    boot = bootstrap_json(html)
    assert list(boot["fields"]) == list(FIELDS)  # the kinds, too
    for kind in FIELDS:
        assert list(boot["fields"][kind]) == list(FIELDS[kind]), kind


def test_panel_draw_order_for_hero_matches_the_mockup(logged_in_admin):
    """The hero panel's fields, in the order the browser draws them.

    This encodes section-form.js's draw rule in Python — Object.keys of
    the bootstrapped schema (:233), minus every field with no
    FIELD_LABELS entry, which `if (!labelFor(name)) return;` (:236) skips
    (hero.portrait: the Muotokuva row stands for it). It therefore
    CANNOT notice that JS file changing its rule; the live browser check
    covers that. What it does prove is that the served data, run through
    today's rule, yields the reading order cp-main-edit's panel shows.
    """
    boot = bootstrap_json(logged_in_admin.get("/muokkaa").get_data(as_text=True))
    labels = boot["field_labels"]["hero"]
    drawn = [labels[name] for name in boot["fields"]["hero"] if labels.get(name)]
    assert drawn == [
        "Yläotsikko",
        "Pääotsikko",
        "Alaotsikko",
        "Ingressi",
        "Ingressi (mobiili)",
        "Faktakortit",
        "Yritystiedot",
        "Painike 1",
        "Painike 2",
        # The three site-chrome rows (LLM-COP-10), drawn last because the
        # keys are appended last in FIELDS["hero"]. Their presence here IS
        # the "the admin can set the brand, page title and footer" proof at
        # the panel: the form is generated from FIELDS + FIELD_LABELS, so a
        # labelled key is a drawn input.
        "Sivuston nimi",
        "Selaimen otsikko",
        "Alatunniste",
    ]
    assert FIELD_LABELS["hero"].get("portrait") is None  # why it is absent


def test_draft_put_of_a_reordered_payload_is_byte_identical(
    logged_in_admin, app
):
    """A whole-payload save whose keys arrive in a different order stores
    byte-identical text and keeps the badge Julkaistu.

    The panel writes the payload whole, and nothing guarantees a client's
    key order; validate_payload rebuilds `clean` by iterating
    FIELDS[kind] (app/sanitize.py:168), so edit.py:90's json.dumps output
    is stable. Without that, a save that changed nothing would rewrite
    the stored text in a new key order, and badge() in app/sections.py —
    a raw *text* comparison of draft against published — would flip
    Julkaistu to Luonnos and mark an untouched section dirty for publish.

    WHY EXPLICIT BYTES, NOT json=: Flask's test client serialises `json=`
    through the app's own JSON provider, whose sort_keys is still True
    (deliberately: it is a different path from Jinja's |tojson policy).
    So `json=` would put an ALPHABETICAL body on the wire whatever order
    the dict literal has, the reordering this test exists to exercise
    would never reach the route, and the test would pass without proving
    anything. Do not "simplify" this back to json= or put_draft.
    """
    before = section_row(app, "hero")
    stored = json.loads(before["draft"])
    assert list(stored) == list(FIELDS["hero"])  # the seed's own convention

    reversed_payload = dict(reversed(list(stored.items())))
    body = json.dumps(reversed_payload, ensure_ascii=False)
    assert list(json.loads(body)) == list(reversed(list(FIELDS["hero"])))

    response = logged_in_admin.put(
        f"/api/sections/{before['id']}/draft",
        data=body.encode("utf-8"),
        content_type="application/json",
        headers=JSON_ACCEPT,
    )
    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["badge"] == "Julkaistu"

    after = section_row(app, "hero")
    assert after["draft"] == before["draft"]  # byte-identical
    assert after["draft"] == after["published"]


# --- the /muokkaa shell (spec cp-main-edit, contains-text byte-exact) --------


@pytest.fixture
def muokkaa_html(logged_in_admin):
    response = logged_in_admin.get("/muokkaa")
    assert response.status_code == 200
    return response.get_data(as_text=True)


SHELL_TEXT_CRITERIA = [
    ("cp-main-edit.edit-topbar.topbar-mode", "Muokkaustila"),
    ("cp-main-edit.edit-topbar.topbar-page", "Etusivu"),
    ("cp-main-edit.edit-topbar.viewport-toggle", "Työpöytä"),
    ("cp-main-edit.edit-topbar.viewport-toggle", "Mobiili"),
    ("cp-main-edit.edit-topbar.esikatsele-button", "Esikatsele"),
    ("cp-main-edit.edit-topbar.julkaise-button", "Julkaise"),
    ("cp-main-edit.editor-panel.panel-tabs", "Sisältö"),
    ("cp-main-edit.editor-panel.panel-tabs", "Ulkoasu"),
    ("cp-main-edit.editor-panel.panel-tabs", "SEO"),
    ("cp-main-edit.editor-panel.panel-section-title.section-name",
     "Aloitusosio"),
    ("cp-main-edit.editor-panel.panel-muotokuva.panel-muotokuva-text",
     "Muotokuva"),
    ("cp-main-edit.editor-panel.panel-muotokuva.panel-muotokuva-text",
     "Pyöreä rajaus"),
    ("cp-main-edit.editor-panel.panel-muotokuva.panel-vaihda", "Vaihda"),
    ("cp-main-edit.editor-panel.muut-osiot", "Muut osiot"),
    ("cp-main-edit.editor-panel.panel-footer.draft-saved-note",
     "Luonnos tallennettu"),
    ("cp-main-edit.editor-panel.panel-footer.panel-peruuta", "Peruuta"),
    ("cp-main-edit.editor-panel.panel-footer.panel-tallenna", "Tallenna"),
]


@pytest.mark.parametrize(
    "address,expected",
    [pytest.param(a, e, id=f"{a}:{e}") for a, e in SHELL_TEXT_CRITERIA],
)
def test_muokkaa_shell_contains_text(muokkaa_html, address, expected):
    assert expected in muokkaa_html, f"{address}: {expected!r} not in /muokkaa"


def test_muokkaa_shows_the_section_position_over_the_real_count(muokkaa_html):
    # cp-main-edit...section-position: the spec's own note calls the count
    # data; six sections are seeded, so the truthful text is "Osio 1 / 6".
    assert "Osio 1 / 6" in muokkaa_html
