"""Which public template renders the page (LLM-COP-22) — app/styles.py and
the three render_template call sites that ask it.

THE INSTRUMENT, and the two ways it silently proves nothing.

Selection is a template-NAME choice in Python, so the honest question is
"which template did Flask render", and flask.template_rendered answers it.
Two traps, both hit for real in this worktree before these tests existed:

1. blinker holds signal receivers WEAKLY. `template_rendered.connect(lambda
   ...)` records nothing at all — the lambda is collected before the request
   runs, the recorded list stays empty, and an assertion like `"page.html" in
   rendered` fails while `"page_v2.html" not in rendered` passes for the wrong
   reason. captured_templates below keeps a NAMED function in a local and
   holds it for the life of the with-block, which is what makes the signal
   report anything.

2. template_rendered fires ONLY for the top-level render. An {% import %}d or
   {% include %}d template never appears. That killed an earlier criterion
   here: /muokkaa/osiot reaches page.html through {% import "page.html" %} at
   _section_row.html, so the signal reports ['edit_sections.html'] and nothing
   else, and a criterion demanding page.html in that list could never pass
   whatever the code did. The section-list pair below asks a question the
   document can actually answer instead.

NO SAMPLE COPY IS ASSERTED. Every assertion here is about a template name, a
stylesheet link or a class the product's own markup defines — never about a
word of the owner's content. LLM-COP-8 and LLM-COP-10 were spent undoing the
opposite mistake.
"""

import json
import re
from contextlib import contextmanager
from pathlib import Path

import pytest
from flask import render_template, template_rendered

from app import db as database
from app.fields import ANCHORS, FIELD_LABELS, FIELDS, NAV_LABELS, SECTION_NAMES
from app.sections import badge, draft_sections, site_chrome, visible_sections
from app.styles import (
    DEFAULT_STYLE,
    STYLE_CHOICES,
    STYLE_TEMPLATES,
    resolve_style,
    template_for,
)

V1_TEMPLATE = "page.html"
V2_TEMPLATE = "page_v2.html"

# The two attributes the public document is read by below. Both are the
# product's own markup, never a word of the owner's content.
KIND = re.compile(r'data-kind="([^"]+)"')
BINDING = re.compile(r'data-section="(\d+)"\s+data-field="([^"]+)"')

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "app" / "templates"


@contextmanager
def captured_templates(app):
    """Every template Flask renders at the TOP LEVEL inside the block.

    The receiver is a named function bound to a local, deliberately not a
    lambda: blinker's connect() takes a WEAK reference, so a receiver with no
    other reference is collected immediately and the signal quietly delivers
    to nobody. A test built on that records [] and can assert "the other
    template was not rendered" forever, whatever the code does.
    """
    recorded = []

    def record(sender, template, **extra):
        recorded.append(template.name)

    template_rendered.connect(record, app)
    try:
        yield recorded
    finally:
        template_rendered.disconnect(record, app)


def set_hero_style(app, style, column="draft"):
    """Plant a style in ONE of the hero row's payload columns.

    tests/conftest.py's edit_published_payload writes draft AND published, so
    it cannot express "drafted but not published" — which is exactly what the
    preview-versus-public test is about. Hence a direct UPDATE of one column.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        row = conn.execute(
            "SELECT id, draft, published FROM sections WHERE kind = 'hero'"
        ).fetchone()
        payload = json.loads(row[column])
        payload["style"] = style
        conn.execute(
            f"UPDATE sections SET {column} = ? WHERE id = ?",
            (json.dumps(payload, ensure_ascii=False), row["id"]),
        )
        conn.commit()
    finally:
        conn.close()


def set_hero_style_everywhere(app, style):
    set_hero_style(app, style, "draft")
    set_hero_style(app, style, "published")


# --- app/styles.py itself ---------------------------------------------------


def test_template_for_resolves_every_input():
    """The whole resolution table, including the inputs a store can really
    hold: "" is what the migration and the seed write, and anything else is
    what an API client, a rolled-back build or a typo can leave behind.

    None is in here because site_chrome's .get() default is "" and a caller
    that lost that default would hand None straight through; `None in dict`
    is a lookup, not an error, so the fallback covers it — and this is the
    test that says so out loud.

    THE UNHASHABLE CASES ARE THE POINT. A dict and a list are not merely
    unknown styles, they are wrongly TYPED ones, and they take a different
    path: `in` on a dict hashes its operand, so before resolve_style tested
    isinstance these raised TypeError instead of falling through, and
    GET / answered 500 for every visitor. An unknown string could never
    have caught that — the whole resolution table passed while the public
    page was one stored object away from going down. Drop the isinstance
    guard and the UNHASHABLE lines below are what go red — the number
    stays green, since 7 is hashable and simply misses the mapping.
    """
    assert template_for("v1") == V1_TEMPLATE
    assert template_for("v2") == V2_TEMPLATE
    assert template_for("") == V1_TEMPLATE
    assert template_for("banana") == V1_TEMPLATE
    assert template_for(None) == V1_TEMPLATE
    assert template_for(7) == V1_TEMPLATE
    assert template_for({}) == V1_TEMPLATE
    assert template_for({"v1": True}) == V1_TEMPLATE
    assert template_for(["v2"]) == V1_TEMPLATE

    # The seam the resolution rides on, stated once: the default has to name
    # a template the mapping actually holds, or every unknown style 500s.
    assert DEFAULT_STYLE in STYLE_TEMPLATES
    assert resolve_style("") == DEFAULT_STYLE
    assert resolve_style("v2") == "v2"
    assert set(STYLE_TEMPLATES) == {"v1", "v2"}


def test_every_declared_template_exists_on_disk():
    """A style whose template is missing is a 500 nobody sees until a store
    holds that value. Driven off STYLE_TEMPLATES, so it covers a style added
    later without being edited.
    """
    for style, template in STYLE_TEMPLATES.items():
        assert (TEMPLATES_DIR / template).is_file(), (style, template)


# --- the three call sites ---------------------------------------------------


def test_the_public_page_renders_the_v1_template_when_no_style_is_stored(
    app, client
):
    """A freshly seeded store holds "" and must serve V1 — the property that
    keeps V1's bytes where they were for every install that never touches the
    Ulkoasu tab."""
    with captured_templates(app) as rendered:
        response = client.get("/")

    assert response.status_code == 200
    assert rendered == [V1_TEMPLATE]
    assert "style-v2.css" not in response.get_data(as_text=True)


def test_an_unknown_stored_style_renders_the_default_template_and_still_200s(
    app, client
):
    """A stored style must never be able to take the public page down.

    "banana" is not a hypothetical: PUT /api/sections/<id>/draft accepts any
    string for a plain field with no cap (app/sanitize.py), so an API client
    can store one today, and a build that drops a style leaves every install
    that chose it holding an unknown value.
    """
    set_hero_style_everywhere(app, "banana")

    with captured_templates(app) as rendered:
        response = client.get("/")

    assert response.status_code == 200
    assert rendered == [V1_TEMPLATE]


def test_a_wrongly_typed_stored_style_still_serves_the_public_page(app, client):
    """The hazard at the route, not just at the function.

    A style that is a JSON object or array is not merely unknown, it is
    wrongly TYPED, and it used to take a different path: `in` on a dict
    hashes its operand, so resolve_style raised TypeError before any
    fallback and GET / answered 500 for every visitor. The whole unknown-
    STRING table passed while the page was one stored object away from
    going down, which is why this asserts the response and not the mapping.

    Written straight into the store because validate_payload admits only a
    str for a plain field — that is the point: the app cannot write this,
    and the store is not the app's alone. A hand-edited row, a restored
    backup, or a future writer is enough.
    """
    for stored in ({}, {"v1": True}, ["v2"], 7):
        set_hero_style_everywhere(app, stored)

        with captured_templates(app) as rendered:
            response = client.get("/")

        assert response.status_code == 200, stored
        assert rendered == [V1_TEMPLATE], stored


def test_a_stored_v2_style_selects_the_v2_template_on_the_public_page(
    app, client
):
    """The stored value reaches the renderer. The stylesheet link is asserted
    beside the template name because the name alone is Flask's word for it;
    the link is the served document's."""
    set_hero_style_everywhere(app, "v2")

    with captured_templates(app) as rendered:
        response = client.get("/")

    assert response.status_code == 200
    assert rendered == [V2_TEMPLATE]
    assert "style-v2.css" in response.get_data(as_text=True)


def test_the_preview_pane_follows_the_draft_style_while_the_public_page_follows_the_published_one(
    app, logged_in_admin
):
    """The draft -> preview -> publish cycle, in one test.

    The style is a field on the hero payload, so it inherits draft/published
    semantics with no route plumbing — and this is the test that says the
    inheritance is real rather than plausible. A preview that ignored the
    drafted skin would show the owner a page they are not about to publish,
    which is the "the preview lies" defect LLM-COP-18 names; a public page
    that followed the draft would publish the skin the moment it was picked.

    POST /api/publish is the real route, and it moves the style because
    publish_dirty copies the whole draft text over published for every row
    whose two columns differ.
    """
    set_hero_style(app, "v2", "draft")

    with captured_templates(app) as previewed:
        preview = logged_in_admin.get("/muokkaa/esikatselu")
    assert preview.status_code == 200
    assert previewed == [V2_TEMPLATE]

    with captured_templates(app) as public:
        before = logged_in_admin.get("/")
    assert before.status_code == 200
    assert public == [V1_TEMPLATE]  # not published yet

    published = logged_in_admin.post(
        "/api/publish", headers={"Accept": "application/json"}
    )
    assert published.status_code == 200
    assert published.get_json()["published"], "the publish landed no rows"

    with captured_templates(app) as after_publish:
        after = logged_in_admin.get("/")
    assert after.status_code == 200
    assert after_publish == [V2_TEMPLATE]
    assert "style-v2.css" in after.get_data(as_text=True)


def test_direct_edit_follows_the_draft_style(app, logged_in_admin):
    """/muokkaa/sivu edits the DRAFTED page, skin included.

    The server-side half of the bridge to tests/browser/. The stylesheet link
    is asserted alongside the template name because that is what a browser
    would have to fetch; the browser half
    (test_the_real_direct_edit_route_serves_the_v2_skin_when_the_draft_says_so)
    covers the one thing this cannot show — direct-edit.js actually booting on
    the served skin.
    """
    set_hero_style(app, "v2", "draft")

    with captured_templates(app) as rendered:
        response = logged_in_admin.get("/muokkaa/sivu")

    assert response.status_code == 200
    assert rendered == [V2_TEMPLATE]
    html = response.get_data(as_text=True)
    assert "style-v2.css" in html
    assert "direct-edit.css" in html  # the chrome came with it


def test_the_section_list_never_renders_the_other_style(app, logged_in_admin):
    """The admin section list stays V1 whatever the style says.

    THE CRITERION IS THE DOCUMENT, NOT THE SIGNAL, and that is not a
    convenience: /muokkaa/osiot reaches page.html through {% import %} in
    _section_row.html, and template_rendered never reports an imported module
    — measured, ['edit_sections.html'] and nothing more. So the signal cannot
    distinguish a correct build from a broken one here, and "v2-hero is not in
    the document" can.

    Why V1 and not the stored style: edit_sections.html deliberately links no
    public stylesheet (it says so in its own comment — style.css would restyle
    the admin chrome), so a V2 card there would be unstyled V2 markup inside
    V1-shaped sections.css rules. PROVEN FALSIFIABLE: flipping that import to
    page_v2.html in a throwaway copy put v2-hero into this document while
    style-v2.css stayed absent — the predicted breakage, observed.
    """
    set_hero_style_everywhere(app, "v2")

    response = logged_in_admin.get("/muokkaa/osiot")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "v2-hero" not in html
    # ...and the reason it must stay V1 is still true: no public stylesheet.
    assert "style-v2.css" not in html


def test_the_section_row_module_names_the_v1_template(app, logged_in_admin):
    """The structural half of the pair above.

    The document check catches the breakage; this names WHERE the decision is
    written, so a future reader who changes the import knows a test is about
    to tell them why. It reads the file rather than the render because the
    import target is not observable any other way — the module's own output is
    discarded (see _section_row.html's comment).
    """
    source = (TEMPLATES_DIR / "_section_row.html").read_text(encoding="utf-8")
    assert '{% import "page.html" as public with context %}' in source
    assert "page_v2" not in source


# --- the chrome contract, asserted by RENDERING -----------------------------


def direct_edit_context(app):
    """The context app/direct_edit.py hands its template, built the same way.

    A copy of the route's own three loader calls, not a hand-written dict: a
    context invented here would let a template pass this test and still raise
    UndefinedError on the real route.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        sections = draft_sections(conn)
        chrome = site_chrome(conn, "draft")
    finally:
        conn.close()
    bootstrap = {
        "sections": sections,
        "fields": FIELDS,
        "field_labels": FIELD_LABELS,
        "section_names": SECTION_NAMES,
        "anchors": ANCHORS,
    }
    return dict(
        sections=sections,
        nav_labels=NAV_LABELS,
        anchors=ANCHORS,
        owner_name="yllapitaja",
        section_names=SECTION_NAMES,
        bootstrap=bootstrap,
        **chrome,
    )


@pytest.mark.parametrize(
    "style,template",
    sorted(STYLE_TEMPLATES.items()),
    ids=sorted(STYLE_TEMPLATES),
)
def test_every_selectable_template_renders_the_admin_chrome_seams(
    app, style, template
):
    """Every template selection can reach must carry the whole admin chrome.

    BY RENDERING, not by grepping another unit's Jinja source. A grep would
    assert that file's TEXT: a reformat would break it and a seam moved into a
    partial would pass it, which is the written-down-restatement pattern this
    repository's tests refuse. Rendering asserts the property selection
    actually depends on — and it discharges the context contract in the same
    test, because a template that needed a name no call site binds would raise
    UndefinedError here rather than in production.

    All three flags are set at once on purpose. No single route sets all
    three, but each seam belongs to a route that does set its flag, and one
    render that lights every branch is the cheapest way to reach all of them.

    Needle hygiene, checked: direct-chrome occurs only in
    direct_edit_chrome.html and zero times in either public template, so its
    presence really means the include ran.
    """
    with app.test_request_context("/"):
        html = render_template(
            template,
            direct_edit=True,
            preview=True,
            login_dialog=True,
            **direct_edit_context(app),
        )

    missing = [
        needle
        for needle in (
            "direct-edit.css",   # {% if direct_edit %} stylesheet
            "login-dialog",      # {% if login_dialog %} include
            "contact-dialog",    # the unconditional include
            "preview.js",        # {% if preview %} script
            "direct-chrome",     # {% if direct_edit %} include
        )
        if needle not in html
    ]
    assert missing == [], (style, template, missing)


# --- the V1 guard (step 8) --------------------------------------------------


def test_the_v1_public_template_names_no_style():
    """app/templates/page.html is not in this change's diff, and this is the
    structural guarantee that it cannot quietly get into a later one.

    Selection is a template-NAME choice in Python, never an {% if %} inside
    the V1 page — which is precisely why V1's served bytes cannot move for an
    install that stores no style, and why the byte-identity claim needs no
    golden HTML file (a golden file would turn every legitimate future markup
    change into a false failure).

    It asserts V1's own file and says nothing whatever about page_v2.html.
    """
    source = (TEMPLATES_DIR / "page.html").read_text(encoding="utf-8")
    assert "site_style" not in source
    assert "style-v2" not in source


# --- the OFFERED set, fenced (LLM-COP-24) -----------------------------------
#
# STYLE_TEMPLATES is fenced above: every declared template exists on disk and
# resolves. The menu is a different promise. Offering a style tells the owner
# that picking it is safe, and LLM-COP-24's ruling is that switching skin must
# never silently remove published content — so what the panel offers has to be
# quantified over, not spot-checked at the one entry that happens to be there.


def public_context(app):
    """The context app/__init__.py:render_page hands the public template.

    A copy of the route's own two loader calls, for the same reason
    direct_edit_context above is one: a context invented here would let a
    template pass this test and still raise UndefinedError on the real route.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        return dict(
            sections=visible_sections(conn),
            nav_labels=NAV_LABELS,
            anchors=ANCHORS,
            **site_chrome(conn),
        )
    finally:
        conn.close()


@pytest.mark.parametrize(
    "value,label",
    STYLE_CHOICES,
    ids=[value for value, _label in STYLE_CHOICES],
)
def test_every_offered_style_renders_a_whole_page(app, value, label):
    """A style may be OFFERED only when picking it renders the whole page.

    LLM-COP-24's ruling, made executable: an owner who picks a skin and
    loses their opening hours has been harmed by a styling choice, and would
    reasonably not notice until a client did. So the quantifier is over
    STYLE_CHOICES — the menu — and not over STYLE_TEMPLATES, which is only
    what the renderer can resolve.

    THE TEMPLATE IS RESOLVED BY INDEXING STYLE_TEMPLATES, NEVER THROUGH
    template_for(). Measured, and it is the whole difference between a fence
    and a decoration: template_for runs its argument through resolve_style
    first, so an offered style naming no template falls back to page.html,
    which renders all six kinds and V1's own bindings and passes everything
    below. Indexing makes that case a KeyError instead — and the explicit
    membership check on the first line turns the KeyError into a sentence.
    Both are load-bearing; neither is redundant.

    This is not the first line of defence for V2 — tests/test_page_v2.py is,
    and it is where a V2-specific drift is caught. The distinct property here
    is the quantifier: a style cannot be added to the menu while dropping a
    kind, or while naming no template at all.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        published_kinds = [
            section["kind"] for section in visible_sections(conn)
        ]
    finally:
        conn.close()

    problems = []
    with app.test_request_context("/"):
        context = public_context(app)
        v1_bindings = set(
            BINDING.findall(render_template(V1_TEMPLATE, **context))
        )

        if value not in STYLE_TEMPLATES:
            problems.append(f"{value}: offered but names no template")
        else:
            html = render_template(STYLE_TEMPLATES[value], **context)
            rendered_kinds = KIND.findall(html)
            if rendered_kinds != published_kinds:
                problems.append(
                    f"{value}: kinds {rendered_kinds} != {published_kinds}"
                )
            if set(BINDING.findall(html)) != v1_bindings:
                problems.append(f"{value}: bindings differ from V1")

    assert v1_bindings, "no bindings found in V1 at all — the extractor is wrong"
    assert problems == [], (label, problems)


# --- the round trip leaves the store where it found it (LLM-COP-24) ---------


def rows_by_kind(app):
    """Every section row, keyed by kind, straight from the app's own DB
    file — what the store HOLDS, never what a route says it holds."""
    conn = database.connect(app.config["DATABASE"])
    try:
        return {
            row["kind"]: dict(row)
            for row in conn.execute(
                "SELECT id, kind, state, draft, published FROM sections"
            )
        }
    finally:
        conn.close()


def badges(rows):
    return {
        kind: badge(row["state"], row["draft"], row["published"])
        for kind, row in rows.items()
    }


def test_switching_style_and_back_leaves_every_other_row_and_the_hero_bytes_alone(
    app, logged_in_admin
):
    """LLM-COP-24's first-named hazard: badge() compares raw stored JSON, so
    a style change that rewrites a payload flips badges to Luonnos across a
    whole site — and the owner sees a site full of unpublished changes they
    never made.

    v1 -> v2 -> v1 through the PRODUCT'S OWN route, the way app/static/edit.js
    drives it: the whole hero payload with exactly one key changed. Six
    properties, and they do not all catch the same thing.

    D IS AN ASSERTION, NOT AN OVERSIGHT. The seed stores style "" rather than
    "v1" (app/seed.py, and it says why: sectionlist compares a published
    payload to blank_payload BY VALUE), so the FIRST v1 write legitimately
    dirties the hero — Julkaistu becomes Luonnos and the bytes move. That is
    correct behaviour, written down here so the next reader does not "fix" it
    back. It is also why the byte baseline for the round trip is taken after
    that first write and not at the seed.

    F IS WHY THIS TEST EXISTS AT ALL. A and C are already true of the shipped
    suite — tests/test_edit.py asserts every non-hero row is byte-identical
    across a draft PUT through this same route — and key order is guarded by
    tests/test_seed.py and tests/test_edit.py. What none of those see is a
    style write that leaves the draft route: load, set, json.dumps with the
    default ensure_ascii=True, store. Measured, that passes A through E and
    every shipped guard, and reddens F alone — the whole hero payload is
    rewritten in \\uXXXX escapes, byte-different from a payload nobody edited,
    and every hero badge in the country says Luonnos.
    """
    seeded = rows_by_kind(app)
    hero_id = seeded["hero"]["id"]
    seed_payload = json.loads(seeded["hero"]["draft"])
    # The premise D rests on, asserted rather than assumed.
    assert seed_payload["style"] == "", seed_payload["style"]

    def choose(style):
        payload = json.loads(rows_by_kind(app)["hero"]["draft"])
        payload["style"] = style
        response = logged_in_admin.put(
            f"/api/sections/{hero_id}/draft",
            json=payload,
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        return rows_by_kind(app)

    after_first_v1 = choose("v1")
    after_v2 = choose("v2")
    final = choose("v1")
    steps = (after_first_v1, after_v2, final)

    # A. No row but the hero moves, at any step. The style lives on the hero
    #    payload, so every other row is a bystander.
    for index, rows in enumerate(steps, start=1):
        moved = [
            kind
            for kind, row in rows.items()
            if kind != "hero"
            and (row["draft"], row["published"])
            != (seeded[kind]["draft"], seeded[kind]["published"])
        ]
        assert moved == [], (index, moved)

    # B. Back where it started: the round trip is closed on the hero's own
    #    draft text, baselined after the first v1 write (see D).
    assert final["hero"]["draft"] == after_first_v1["hero"]["draft"]

    # C. And no bystander's badge moved either — the symptom the owner would
    #    actually see.
    seeded_badges = badges(seeded)
    for index, rows in enumerate(steps, start=1):
        current = badges(rows)
        for kind in seeded_badges:
            if kind == "hero":
                continue
            assert current[kind] == seeded_badges[kind], (index, kind)

    # D. The hero's own first write DOES dirty it, correctly — seeded "" is
    #    not "v1", so this is a real content change.
    assert seeded_badges["hero"] == "Julkaistu"
    assert badges(after_first_v1)["hero"] == "Luonnos"
    assert after_first_v1["hero"]["draft"] != seeded["hero"]["draft"]

    # E. The hero's key order survived three round trips through
    #    validate_payload, which rebuilds a payload in FIELDS declaration
    #    order (app/fields.py says why a mid-list key is forbidden).
    final_payload = json.loads(final["hero"]["draft"])
    assert list(final_payload) == list(seed_payload)

    # F. The final draft is the SEEDED text with only style's value replaced.
    #    Bytes, not a parsed dict: badge() compares the raw text, so a
    #    re-encoding nothing asked for is exactly the defect.
    assert final["hero"]["draft"] == json.dumps(
        dict(seed_payload, style="v1"), ensure_ascii=False
    )
