"""The first-run wizard (LLM-COP-7) — /yllapito/alustus, the first-run
predicate, the login offer, and the wizard's write-nothing promise, against
the real routes and the app's real DB file.

Governing spec cp-admin-wizard. One test (or one parametrized case) per
addressed contains-text criterion, each case id citing its spec address
(spec.region.child, with an index when one criterion region asserts several
strings). The spec states no testids, so nothing here invents data-testid
selectors: assertions are byte-exact substrings scoped to the
implementation's own elements, matching tests/test_page.py and
tests/test_edit.py.

Scoping that matters, stated rather than left for a reader to infer:

* All five nav rows, all five progress segments and all five step panels are
  server-rendered into one document, so `.step-title` and `.step-desc` are
  asserted ACROSS the five panels — the wizard opens on step 1 (Perustiedot)
  while the spec's step-title/step-desc criteria are step 2's (Aloitusosio),
  and a first-match assertion would read step 1 and fail on correct code.
* Five spec addresses are NOT covered here and are not faked:
  `otsikko-label`, `otsikko-input`, `otsikko-helper`, `esittely-label` and
  `esittely-textarea` are built by JavaScript from the served bootstrap, and
  a test client executes no JavaScript (the same limitation tests/test_edit.py
  states in its own docstring). This file proves the strings SHIP; the
  run-for-real phase proves they RENDER. Server-rendering duplicate labels to
  turn these green would prove nothing about the form the owner actually sees.
* Likewise the finish panel: pytest proves its markup ships and that the
  publish route its Julkaise posts flips is_first_run — not that it appears
  after step 5.
"""

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest

from app import create_app
from app import db as database
from app.fields import FIELDS
from app.sections import badge
from app.wizard import STEPS, is_first_run, login_target
from tests.conftest import create_admin, login, publish_something

JSON_ACCEPT = {"Accept": "application/json"}
STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


# --- helpers: every element matching a selector, not just the first --------


class _AllElementText(HTMLParser):
    """Raw text content of EVERY <tag> carrying the given class token,
    children included and whitespace unnormalized (the criteria are
    byte-exact). conftest.element_text answers the first match only, which
    is the wrong instrument for a document that server-renders all five
    steps."""

    def __init__(self, tag, cls):
        super().__init__(convert_charrefs=True)
        self._tag = tag
        self._cls = cls
        self._depth = 0
        self._parts = None
        self.texts = []

    def handle_starttag(self, tag, attrs):
        if self._depth:
            if tag == self._tag:
                self._depth += 1
            return
        if tag != self._tag:
            return
        if self._cls is not None and self._cls not in (
            dict(attrs).get("class") or ""
        ).split():
            return
        self._depth = 1
        self._parts = []

    def handle_endtag(self, tag):
        if self._depth and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self.texts.append("".join(self._parts))
                self._parts = None

    def handle_data(self, data):
        if self._depth:
            self._parts.append(data)


def element_texts(html, tag, cls=None):
    parser = _AllElementText(tag, cls)
    parser.feed(html)
    return parser.texts


class _ScriptById(HTMLParser):
    def __init__(self, element_id):
        super().__init__(convert_charrefs=True)
        self._id = element_id
        self._in = False
        self.text = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == self._id:
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.text = data


def bootstrap_json(html):
    """The parsed contents of the served <script id="bootstrap">."""
    parser = _ScriptById("bootstrap")
    parser.feed(html)
    assert parser.text is not None, "no #bootstrap script in the document"
    return json.loads(parser.text)


def user_version(app):
    c = database.connect(app.config["DATABASE"])
    try:
        (version,) = c.execute("PRAGMA user_version").fetchone()
        return version
    finally:
        c.close()


def section_rows(app):
    """Every column of every sections row — the snapshot the write-nothing
    test compares."""
    c = database.connect(app.config["DATABASE"])
    try:
        return [
            tuple(row)
            for row in c.execute(
                "SELECT * FROM sections ORDER BY position"
            ).fetchall()
        ]
    finally:
        c.close()


def audit_rows(app):
    c = database.connect(app.config["DATABASE"])
    try:
        return [
            tuple(row)
            for row in c.execute(
                "SELECT id, at, event FROM audit_log ORDER BY id"
            ).fetchall()
        ]
    finally:
        c.close()


@pytest.fixture
def wizard_html(logged_in_admin):
    """One served /yllapito/alustus document, so every contains-text
    criterion is proven to hold in the SAME document."""
    response = logged_in_admin.get("/yllapito/alustus")
    assert response.status_code == 200
    return response.get_data(as_text=True)


# --- the gate (auth.require_admin over the wizard route) --------------------


def test_alustus_anonymous_redirects_to_yllapito(client):
    response = client.get("/yllapito/alustus")
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"


def test_alustus_anonymous_preferring_json_gets_401(client):
    response = client.get("/yllapito/alustus", headers=JSON_ACCEPT)
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


# --- byte-exact contains-text criteria over the served document -------------

# (spec address, tag, class token, expected byte-exact text). Each row is one
# `contains-text` criterion of cp-admin-wizard; the assertion is that SOME
# element matching the selector carries the text, because the document
# carries all five steps at once.
CRITERIA = [
    (
        "cp-admin-wizard.wizard.wizard-header.wizard-kicker",
        "p", "wizard-kicker", "SIVUN ALUSTUS",
    ),
    (
        "cp-admin-wizard.wizard.wizard-header.wizard-title",
        "h1", "wizard-title", "Täytetään profiili yhdessä",
    ),
    (
        "cp-admin-wizard.wizard.wizard-header.wizard-autosave",
        "p", "wizard-autosave", "Tallennetaan automaattisesti",
    ),
    ("cp-admin-wizard.wizard.wizard-steps-0", "li", "wizard-step", "Perustiedot"),
    ("cp-admin-wizard.wizard.wizard-steps-1", "li", "wizard-step", "Aloitusosio"),
    ("cp-admin-wizard.wizard.wizard-steps-2", "li", "wizard-step", "Palvelut"),
    (
        "cp-admin-wizard.wizard.wizard-steps-3",
        "li", "wizard-step", "Vastaanottoajat",
    ),
    (
        "cp-admin-wizard.wizard.wizard-steps-4",
        "li", "wizard-step", "Yhteydenotto",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.step-title",
        "h2", "step-title", "Aloitusosio",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.step-desc-0",
        "p", "step-desc", "Muotokuva, otsikko ja esittelyteksti.",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.step-desc-1",
        "p", "step-desc", "Voit muuttaa tekstejä myöhemmin milloin tahansa.",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.muotokuva-row.muotokuva-text-0",
        "span", "wizard-muotokuva-text", "Muotokuva",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.muotokuva-row.muotokuva-text-1",
        "span", "wizard-muotokuva-text", "Pyöreä rajaus",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.muotokuva-row.muotokuva-text-2",
        # × is U+00D7 MULTIPLICATION SIGN, as the spec's bytes are.
        "span", "wizard-muotokuva-text", "vähintään 600 × 600 px",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.muotokuva-row.muotokuva-vaihda",
        "button", "wizard-vaihda", "Vaihda",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.skip-link",
        "button", "wizard-skip", "Ohita toistaiseksi",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.back-button",
        "button", "wizard-back", "Takaisin",
    ),
    (
        "cp-admin-wizard.wizard.step-panel.save-button",
        "button", "wizard-save", "Tallenna ja jatka",
    ),
]


@pytest.mark.parametrize(
    "tag,cls,expected",
    [case[1:] for case in CRITERIA],
    ids=[case[0] for case in CRITERIA],
)
def test_contains_text(wizard_html, tag, cls, expected):
    texts = element_texts(wizard_html, tag, cls)
    assert texts, f"no <{tag} class=…{cls}…> in the served document"
    assert any(expected in text for text in texts), (
        f"{expected!r} in no {cls} element; saw {texts!r}"
    )


def test_step_desc_criteria_land_on_one_element(wizard_html):
    """cp-admin-wizard.wizard.step-panel.step-desc states both strings on the
    SAME element, so satisfying them from two different panels would not
    satisfy the spec."""
    both = [
        text
        for text in element_texts(wizard_html, "p", "step-desc")
        if "Muotokuva, otsikko ja esittelyteksti." in text
        and "Voit muuttaa tekstejä myöhemmin milloin tahansa." in text
    ]
    assert len(both) == 1, element_texts(wizard_html, "p", "step-desc")


def test_muotokuva_text_criteria_land_on_one_element(wizard_html):
    """cp-admin-wizard…muotokuva-text states all three strings on one
    element."""
    texts = element_texts(wizard_html, "span", "wizard-muotokuva-text")
    assert len(texts) == 1
    for expected in ("Muotokuva", "Pyöreä rajaus", "vähintään 600 × 600 px"):
        assert expected in texts[0]


def test_one_takaisin_and_one_ohita_in_the_document(wizard_html):
    """The footer is shared by all five steps and its buttons toggle, so
    exactly one of each exists — a per-panel copy would be a second
    implementation of the footer."""
    assert len(element_texts(wizard_html, "button", "wizard-back")) == 1
    assert len(element_texts(wizard_html, "button", "wizard-skip")) == 1
    assert len(element_texts(wizard_html, "button", "wizard-save")) == 1


# --- counts: the five steps, in three places, from one roster ---------------


def test_step_nav_has_five_items(wizard_html):
    """cp-admin-wizard.wizard.wizard-steps: item-count 5."""
    assert element_texts(wizard_html, "ol", "wizard-steps"), "no step nav"
    assert len(element_texts(wizard_html, "li", "wizard-step")) == 5


def test_progress_has_five_segments(wizard_html):
    """cp-admin-wizard.wizard.wizard-header.wizard-progress: five segments
    matching the five steps."""
    assert len(element_texts(wizard_html, "span", "wizard-progress-segment")) == 5


def test_five_step_panels_are_server_rendered(wizard_html):
    """All five panels ship in one document — which is what makes step 2's
    title and description assertable while the wizard opens on step 1. The
    finish panel deliberately uses its own classes, so exactly five
    .step-title elements exist."""
    assert len(element_texts(wizard_html, "h2", "step-title")) == 5
    assert len(element_texts(wizard_html, "p", "step-desc")) == 5
    assert element_texts(wizard_html, "h2", "wizard-finish-title") == [
        "Valmis julkaistavaksi"
    ]


def test_step_titles_ship_in_step_order(wizard_html):
    """The panels are in step order, so the step-title assertion above reads
    step 2's panel and not, say, a duplicate of step 1's."""
    assert element_texts(wizard_html, "h2", "step-title") == [
        "Perustiedot",
        "Aloitusosio",
        "Palvelut",
        "Vastaanottoajat",
        "Yhteydenotto",
    ]


# --- step 2's field strings: they SHIP (they render only in a browser) ------


@pytest.mark.parametrize(
    "expected",
    ["Otsikko", "Esittelyteksti", "Nimi tai nimi + ammattinimike"],
)
def test_step_two_field_strings_ship_in_the_bootstrap(wizard_html, expected):
    """HONEST SCOPE: cp-admin-wizard's otsikko-label, esittely-label and
    otsikko-helper are drawn by section-form.js from this bootstrap, and a
    test client runs no JavaScript. This proves the strings the browser will
    draw are served — not that they are drawn. The run-for-real phase owns
    that half, and no server-rendered duplicate is planted here to fake it."""
    step = bootstrap_json(wizard_html)["steps"][1]
    assert step["label"] == "Aloitusosio"
    shipped = list(step["labels"].values()) + list(step["helpers"].values())
    assert expected in shipped, shipped


def test_bootstrap_ships_the_schema_and_drafts_the_forms_need(wizard_html):
    bootstrap = bootstrap_json(wizard_html)
    assert bootstrap["fields"] == FIELDS
    assert len(bootstrap["steps"]) == 5
    kinds = {section["kind"] for section in bootstrap["sections"]}
    for step in bootstrap["steps"]:
        assert step["kind"] in kinds


# --- structural guards on the step roster ----------------------------------


@pytest.mark.parametrize("index", range(len(STEPS)))
def test_every_step_field_is_a_real_schema_key(index):
    """No step invents storage: every name in `only` is a key of
    FIELDS[kind]. This is the guard that a new step cannot quietly require a
    schema change (which would need a migration this unit must not add)."""
    step = STEPS[index]
    schema = FIELDS[step["kind"]]
    unknown = [name for name in step["only"] if name not in schema]
    assert unknown == [], f"{step['label']}: {unknown} not in FIELDS[{step['kind']!r}]"


@pytest.mark.parametrize("index", range(len(STEPS)))
def test_step_label_overrides_and_helpers_name_owned_fields(index):
    step = STEPS[index]
    owned = set(step["only"])
    assert set(step["labels"]) <= owned
    assert set(step["helpers"]) <= owned


def test_steps_one_and_two_own_disjoint_hero_fields():
    """Both write the hero section with whole payloads, so overlapping field
    sets would let one step's save clobber the other's."""
    first, second = STEPS[0], STEPS[1]
    assert first["kind"] == second["kind"] == "hero"
    assert set(first["only"]).isdisjoint(second["only"])


def test_the_step_roster_is_the_spec_s_five_labels():
    """cp-admin-wizard.wizard.wizard-steps names all five, and says
    Yhteydenotto where app.fields.SECTION_NAMES says Yhteydenottolomake."""
    assert [step["label"] for step in STEPS] == [
        "Perustiedot",
        "Aloitusosio",
        "Palvelut",
        "Vastaanottoajat",
        "Yhteydenotto",
    ]


# --- the first-run predicate and the login offer ---------------------------


def test_is_first_run_true_on_a_freshly_seeded_database(app):
    c = database.connect(app.config["DATABASE"])
    try:
        assert is_first_run(c) is True
        # login_target builds a URL, so it runs where it is really called:
        # inside a request on this app.
        with app.test_request_context():
            assert login_target(c) == "/yllapito/alustus"
    finally:
        c.close()


def test_is_first_run_false_after_a_real_publish(app, logged_in_admin):
    publish_something(app, logged_in_admin)
    c = database.connect(app.config["DATABASE"])
    try:
        assert is_first_run(c) is False
        with app.test_request_context():
            assert login_target(c) == "/"
    finally:
        c.close()


def test_is_first_run_survives_a_publish_that_publishes_nothing(
    app, logged_in_admin
):
    """A Julkaise with nothing dirty affects zero rows, so the site is still
    unconfigured — and the predicate must still say so. This is also the trap
    conftest.publish_something documents."""
    response = logged_in_admin.post("/api/publish", headers=JSON_ACCEPT)
    assert response.status_code == 200
    assert response.get_json()["published"] == []
    c = database.connect(app.config["DATABASE"])
    try:
        assert is_first_run(c) is True
    finally:
        c.close()


def test_login_on_an_unconfigured_site_lands_on_the_wizard(app):
    create_admin(app)
    response = login(app.test_client())
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito/alustus"


def test_login_on_a_configured_site_lands_on_the_page(app, logged_in_admin):
    """The other branch of the offer — the coverage tests/test_auth.py's
    amended assertion gave up."""
    publish_something(app, logged_in_admin)
    response = login(app.test_client())
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/"


def test_wizard_still_reachable_after_publish(app, logged_in_admin):
    """The wizard is a re-runnable guided edit, not a one-shot gate: it
    renders regardless of is_first_run."""
    publish_something(app, logged_in_admin)
    response = logged_in_admin.get("/yllapito/alustus")
    assert response.status_code == 200
    assert "Täytetään profiili yhdessä" in response.get_data(as_text=True)


# --- the public page is not touched ----------------------------------------


def test_the_public_page_is_untouched_by_the_wizard(app, logged_in_admin):
    """A standing contract, not an observation: GET / answers 200 with no
    redirect for an anonymous visitor AND for the logged-in admin, on the
    unconfigured database where the offer is live. Any future
    before_app_request hook, cookie or banner that reaches the public page
    breaks this loudly."""
    for label, http in (("anonymous", app.test_client()), ("admin", logged_in_admin)):
        response = http.get("/")
        assert response.status_code == 200, f"{label}: {response.status_code}"
        assert "Location" not in response.headers, label
        assert "Anna Virtanen" in response.get_data(as_text=True), label


# --- the wizard writes nothing ---------------------------------------------


def test_loading_the_wizard_writes_no_section_and_no_audit_row(
    app, logged_in_admin
):
    """Scoped deliberately to `sections` + `audit_log`, the two tables the
    wizard could wrongly touch. NOT a whole-database snapshot: require_admin
    slides sessions.last_seen_at on every gated request (app/auth.py), so a
    wider snapshot would be red no matter how correct the wizard is."""
    sections_before = section_rows(app)
    audit_before = audit_rows(app)

    assert logged_in_admin.get("/yllapito/alustus").status_code == 200

    assert section_rows(app) == sections_before  # byte-identical rows
    assert audit_rows(app) == audit_before  # no "draft saved" row


def test_the_wizard_leaves_every_badge_julkaistu(app, logged_in_admin):
    """The hazard the artifact names: a wizard that wrote empty or
    re-serialized drafts would flip badges to Luonnos. badge() compares raw
    JSON text, so the only safe defence is writing nothing."""
    assert logged_in_admin.get("/yllapito/alustus").status_code == 200
    c = database.connect(app.config["DATABASE"])
    try:
        rows = c.execute("SELECT * FROM sections").fetchall()
    finally:
        c.close()
    assert rows
    for row in rows:
        assert badge(row["state"], row["draft"], row["published"]) == "Julkaistu"


# --- the finish panel: what pytest can honestly prove ----------------------


def test_the_finish_panel_markup_ships(wizard_html):
    """HONEST SCOPE (a): the finish panel is in the served document, hidden.
    That it appears AFTER step 5 is a claim only the browser can settle —
    the panels are toggled by wizard.js and a test client runs no
    JavaScript."""
    assert element_texts(wizard_html, "h2", "wizard-finish-title") == [
        "Valmis julkaistavaksi"
    ]
    assert element_texts(wizard_html, "p", "wizard-finish-desc")
    assert element_texts(wizard_html, "button", "wizard-julkaise") == ["Julkaise"]


def test_the_publish_the_finish_panel_posts_flips_is_first_run(
    app, logged_in_admin
):
    """HONEST SCOPE (b): the finish panel's Julkaise posts the existing
    /api/publish — no second publish implementation — so what pytest proves
    is that route's effect: a dirty draft published makes the site
    configured, permanently."""
    c = database.connect(app.config["DATABASE"])
    try:
        assert is_first_run(c) is True
    finally:
        c.close()

    publish_something(app, logged_in_admin)

    c = database.connect(app.config["DATABASE"])
    try:
        assert is_first_run(c) is False
    finally:
        c.close()


# --- always reachable, and loadable ----------------------------------------


def test_the_edit_topbar_links_to_the_wizard(logged_in_admin):
    """The offer fires only at login, which makes the topbar link the whole
    "re-runnable guided edit" half of the design rather than a convenience:
    without it a configured site has no route back to the wizard but a
    hand-typed URL."""
    html = logged_in_admin.get("/muokkaa").get_data(as_text=True)
    assert 'href="/yllapito/alustus"' in html
    assert "Alustus" in html


def script_order(html):
    """The src attributes of the document's <script src=…>, in order."""

    class _Scripts(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.srcs = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                src = dict(attrs).get("src")
                if src:
                    self.srcs.append(src.rsplit("/", 1)[-1])

    parser = _Scripts()
    parser.feed(html)
    return parser.srcs


def test_the_wizard_loads_its_scripts_in_the_order_that_works(wizard_html):
    """Mandatory, not stylistic: FIELDS['hero']['ingress'] is a rich field,
    so the shared form builder calls window.createRichEditor from editor.js,
    and wizard.js constructs its debounce from window.createAutosave. Any
    other order throws on load and step 2 never draws."""
    srcs = script_order(wizard_html)
    assert srcs == [
        "editor.js",
        "autosave.js",
        "section-form.js",
        "wizard.js",
    ], srcs


def test_the_edit_panel_still_loads_the_shared_modules_before_edit_js(
    logged_in_admin,
):
    """The regression this unit's extraction could cause: edit.js calls the
    shared builder at parse time, so appending the new scripts after it
    would kill /muokkaa outright with `createSectionForm is not defined`.
    Worth a standing guard because three siblings are rebasing this file."""
    srcs = script_order(logged_in_admin.get("/muokkaa").get_data(as_text=True))
    for module in ("autosave.js", "section-form.js"):
        assert module in srcs, srcs
        assert srcs.index(module) < srcs.index("edit.js"), srcs


# --- structural: one debounce, one delay -----------------------------------


def test_the_autosave_delay_is_declared_in_exactly_one_file():
    """The artifact's reuse constraint, made falsifiable: an inlined
    `setTimeout(save, 2000)` copy in a host is the actual hazard, so the
    literal may live in app/static/autosave.js and nowhere else."""
    carriers = sorted(
        path.name
        for path in STATIC.glob("*.js")
        if "2000" in path.read_text(encoding="utf-8")
        or "AUTOSAVE_DELAY" in path.read_text(encoding="utf-8")
    )
    assert carriers == ["autosave.js"], carriers


def test_the_hosts_consume_the_shared_delay():
    """Not merely 'the literal is elsewhere absent' — both hosts must
    actually read the shared constant, or one could quietly pass its own
    number computed some other way."""
    for name in ("edit.js", "wizard.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "window.createAutosave(" in source, name
        assert "window.createAutosave.DELAY" in source, name


def test_wizard_js_owns_no_timer_of_its_own():
    """The honest half of the setTimeout guard. Deliberately NOT asserted for
    edit.js, which legitimately keeps its own setTimeout for peruutaTimer's
    undo window — a bare grep there would be red on correct code."""
    assert "setTimeout" not in (STATIC / "wizard.js").read_text(encoding="utf-8")


# --- schema version ---------------------------------------------------------


def test_the_wizard_app_stamps_the_version_migrate_declares(app):
    """The app the wizard runs in stamps exactly the version migrate() declares.

    Named for what it actually holds, which is NARROWER than "the wizard adds
    no migration". It would stay green if this unit appended a _migration_4,
    because migrate() would then stamp 4 too. It catches a user_version that
    migrate() did not declare, and nothing more.

    Asserted against len(MIGRATIONS) rather than a literal on purpose: a
    literal pins the number a *sibling* is entitled to raise — LLM-COP-3's
    migration 3 landed and turned an earlier `== 2` red on correct code, which
    is exactly the false failure that invites someone to weaken a guard.

    What actually holds "this unit adds no migration" is that app/db.py is
    untouched by this unit's diff, which is a review property, not a test one.
    Naming this test for that stronger claim would be the false assurance this
    unit refuses everywhere else.
    """
    assert user_version(app) == len(database.MIGRATIONS)


def test_a_second_app_on_a_fresh_instance_stamps_the_same_version(tmp_path):
    app = create_app(instance_path=str(tmp_path / "instance2"))
    assert user_version(app) == len(database.MIGRATIONS)
