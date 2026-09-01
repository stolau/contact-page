"""The V2 public template (LLM-COP-23), rendered directly.

Template SELECTION is LLM-COP-22's work, not this artifact's, so nothing
here switches a style: these tests render app/templates/page_v2.html with
exactly the context app/__init__.py:render_page hands page.html and read
the document that comes back. That is deliberate — it keeps this file
true whatever the selector ends up looking like.

WHAT THIS FILE IS REALLY FOR. The direct in-place editor binds by
[data-section][data-field] attributes rendered into the PUBLIC template
(app/static/direct-edit.js:277-323). A second template is a second place
those can go missing, and when one does nothing raises: the field simply
stops being editable. LLM-COP-18 names that as the hazard that decides
the work and LLM-COP-6 is the defect of the same shape this project has
already shipped once. test_v2_binds_exactly_the_fields_v1_binds is the
fence, and tests/browser/test_browser_v2_direct_edit.py types into every
one of them in a real Chrome.

NO SAMPLE COPY IS ASSERTED HERE. The seven V2 documents are deliberately
thin on contains-text — only "Muotokuva", "browse files" and "Ylläpito"
are asserted across all of them — because every other word on that page
is the owner's data, not the product's promise. LLM-COP-8 and LLM-COP-10
were spent undoing the opposite mistake. The list-shaped assertions below
therefore assert that the STORED value reaches the page, never what it
says.
"""

import json
import re

import pytest
from flask import render_template

from app import db as database
from app.fields import ANCHORS, FIELDS, NAV_LABELS
from app.sections import site_chrome, visible_sections
from tests.conftest import PERSONA_PATTERN, edit_published_payload

V2_TEMPLATE = "page_v2.html"
V1_TEMPLATE = "page.html"

# A 64-hex digest is the only thing app/images.py:image_url will turn into
# a URL, so this is what "an image has been uploaded" looks like to a
# template. No file has to exist for the markup question these tests ask.
DIGEST = "b" * 64

BINDING = re.compile(r'data-section="(\d+)"\s+data-field="([^"]+)"')
KIND = re.compile(r'data-kind="([^"]+)"')


def render_public(app, template):
    """One public document, rendered with render_page's own context.

    Built from the same three calls app/__init__.py makes — visible_sections,
    NAV_LABELS/ANCHORS and site_chrome — so a V2 document here is the
    document the public route would serve if it named this template.
    """
    with app.test_request_context("/"):
        conn = database.connect(app.config["DATABASE"])
        try:
            context = dict(
                sections=visible_sections(conn),
                nav_labels=NAV_LABELS,
                anchors=ANCHORS,
                **site_chrome(conn),
            )
        finally:
            conn.close()
        return render_template(template, **context)


@pytest.fixture
def v2_html(app):
    return render_public(app, V2_TEMPLATE)


def bindings(html):
    """Every (section id, field name) the in-place editor would bind."""
    return set(BINDING.findall(html))


# --- the anti-drift fence ---------------------------------------------------


def test_v2_binds_exactly_the_fields_v1_binds(app):
    """The one test this artifact exists to make pass.

    Set EQUALITY, not containment, and against V1's own rendered document
    rather than a list written down here — a list would have to be
    maintained beside app/templates/page.html and would go stale exactly
    when a field is added to one template and not the other, which is the
    drift it is supposed to catch.

    LLM-COP-23 states the falsification condition in as many words: if the
    two templates drift such that a field editable in V1 is not editable
    in V2, the second-template decision was wrong. This is that condition,
    executable.
    """
    v1 = bindings(render_public(app, V1_TEMPLATE))
    v2 = bindings(render_public(app, V2_TEMPLATE))

    assert v1, "no bindings found in V1 at all — the extractor is wrong"
    assert v2 - v1 == set(), f"V2 binds fields V1 does not: {sorted(v2 - v1)}"
    assert v1 - v2 == set(), (
        "in-place editing silently stops working on V2 for these fields: "
        f"{sorted(v1 - v2)}"
    )


def test_every_v2_binding_names_a_real_field_in_the_schema(app, v2_html):
    """A data-field naming nothing in app/fields.py binds to nothing:
    direct-edit.js looks the descriptor up and returns early when it is
    missing (:282-283), so a typo is silent there too."""
    sections = {
        str(section["id"]): section["kind"]
        for section in visible_sections(
            database.connect(app.config["DATABASE"])
        )
    }
    unknown = [
        (sid, name)
        for sid, name in bindings(v2_html)
        if name not in FIELDS.get(sections.get(sid, ""), {})
    ]
    assert not unknown, f"data-field names no schema field: {unknown}"


def test_v2_carries_the_section_bindings_the_chrome_moves_names_into(app, v2_html):
    """direct-edit.js finds each band by section[data-kind="..."] and moves
    the section-name chip into it (:62-71). A band without the attribute
    silently keeps no name."""
    v1_kinds = KIND.findall(render_public(app, V1_TEMPLATE))
    assert KIND.findall(v2_html) == v1_kinds


@pytest.mark.parametrize(
    "selector,why",
    [
        ('class="portrait', "direct-edit.js anchors the Vaihda kuva pill on it"),
        ("cta-contact", "contact_dialog.html binds it as a dialog opener"),
        ("header-contact", "contact_dialog.html binds it as a dialog opener"),
    ],
)
def test_v2_carries_the_class_hooks_other_files_bind_to(v2_html, selector, why):
    assert selector in v2_html, why


def test_v2_anchors_every_section_the_nav_links_at(app, v2_html):
    """preview.js highlights by getElementById(anchor) (:22-23) and the nav
    links point at the same ids, so every rendered band needs its id."""
    conn = database.connect(app.config["DATABASE"])
    try:
        kinds = [section["kind"] for section in visible_sections(conn)]
    finally:
        conn.close()
    for kind in kinds:
        assert f'id="{ANCHORS[kind]}"' in v2_html, kind


# --- nothing published disappears when the skin changes ---------------------


def test_v2_renders_every_published_section_kind(app, v2_html):
    """LLM-COP-18 answer 4: the kinds V2's designs do not draw still
    appear, in a neutral V2 default. They are explicitly NOT hidden —
    switching style must never silently remove published content."""
    conn = database.connect(app.config["DATABASE"])
    try:
        kinds = [section["kind"] for section in visible_sections(conn)]
    finally:
        conn.close()
    rendered = KIND.findall(v2_html)
    assert sorted(rendered) == sorted(kinds), (
        f"kinds published but not drawn by V2: {sorted(set(kinds) - set(rendered))}"
    )


def test_v2_hides_no_bound_field_behind_a_viewport_class_v1_leaves_visible(app):
    """The tempting way to make V2's desktop hero match its mockup exactly
    is to mark the rest of the hero payload phone-only. That would take
    those fields out of reach of the in-place editor at the desktop
    viewport, which is the only viewport the browser gate runs at — the
    hazard dressed as a layout decision.

    So: whatever V1 hides behind desktop-only/phone-only, V2 may hide too,
    and nothing else.
    """
    hidden = re.compile(
        r'<[^>]*\b(?:desktop-only|phone-only)\b[^>]*data-field="([^"]+)"'
    )
    v1_hidden = set(hidden.findall(render_public(app, V1_TEMPLATE)))
    v2_hidden = set(hidden.findall(render_public(app, V2_TEMPLATE)))
    assert v2_hidden <= v1_hidden, (
        "V2 hides bound fields behind a viewport class that V1 shows: "
        f"{sorted(v2_hidden - v1_hidden)}"
    )


# --- the three strings the seven documents actually assert ------------------


def test_portrait_placeholder_shows_the_two_asserted_strings(v2_html):
    """v2-cp-section-portrait.portrait-section.portrait.portrait-empty
    .portrait-empty-label / .portrait-browse, and the same pair again in
    v2-cp-phone-scroll-1 and v2-cp-phone-scroll-2. Both criteria are
    `when: no portrait image has been uploaded`, which is the seeded
    state: seed.py ships hero.portrait as "".
    """
    assert "Muotokuva" in v2_html
    assert "browse files" in v2_html


def test_admin_link_says_yllapito(v2_html):
    """v2-cp-section-contact.footer.footer-right.footer-admin-link and
    v2-cp-phone-scroll-2.footer.footer-admin-link. Product chrome rather
    than owner content, which is why it is asserted at all."""
    assert "Ylläpito" in v2_html


# --- the uploaded image, and the fallback when there is none ----------------


def test_an_uploaded_image_reaches_both_the_hero_photo_and_the_portrait(app):
    """hero.portrait is the product's one stored image reference
    (LLM-COP-21) and V2 needs a picture in two places: the full-bleed hero
    photograph (v2-cp-hero.hero-photo) and the portrait circle
    (v2-cp-section-portrait.portrait-section.portrait). Both read the same
    reference, so both fill from one upload."""
    edit_published_payload(app, "hero", lambda p: p.update(portrait=DIGEST))
    html = render_public(app, V2_TEMPLATE)

    assert html.count(f"/kuvat/{DIGEST}") == 2, html.count(f"/kuvat/{DIGEST}")
    assert "has-image" in html
    assert "Muotokuva" not in html
    assert "browse files" not in html


def test_a_non_digest_portrait_falls_back_to_the_placeholder(app):
    """image_url answers None for anything that is not a 64-hex digest, so
    junk in the payload must not become a URL and must not blank the
    placeholder either."""
    edit_published_payload(
        app, "hero", lambda p: p.update(portrait="../../etc/passwd")
    )
    html = render_public(app, V2_TEMPLATE)

    assert "etc/passwd" not in html
    assert "Muotokuva" in html


# --- the lists are the owner's, so only their arity is asserted -------------


def test_one_fact_card_per_stored_hero_fact(app):
    """cp-fact-card, reused rather than redrawn
    (v2-cp-phone-hero.hero.hero-card.card-facts.card-fact-1 states
    `uses: cp-fact-card`). The document asserts no count and no text — "the
    set, the labels and the values are data" — so this asserts the stored
    set reaches the page, and nothing about what it says."""
    edit_published_payload(
        app,
        "hero",
        lambda p: p.update(facts=[{"label": "A", "value": "1"}]),
    )
    html = render_public(app, V2_TEMPLATE)
    assert html.count('class="fact-card"') == 1
    assert 'class="fact-label"' in html
    assert 'class="fact-value"' in html


def test_one_fact_line_per_stored_tietoa_fact(app):
    """v2-cp-section-prose.prose-section.prose-facts and
    v2-cp-section-portrait.portrait-section.bio-facts, both `matches`:
    "one entry per fact line the owner has filled in ... no count is
    asserted"."""
    conn = database.connect(app.config["DATABASE"])
    try:
        stored = json.loads(
            conn.execute(
                "SELECT published FROM sections WHERE kind = 'tietoa'"
            ).fetchone()["published"]
        )
    finally:
        conn.close()
    # Scoped to the band that owns them: the vastaanottoajat band draws a
    # row of its own, and a whole-document count would add the two together.
    band = re.search(
        r'<section[^>]*data-kind="tietoa".*?</section>',
        render_public(app, V2_TEMPLATE),
        flags=re.DOTALL,
    )
    assert band is not None, "no tietoa band in the V2 document"
    assert band.group(0).count('class="v2-fact-line"') == len(stored["facts"])


# --- V1 is untouched, and no mockup persona rode in --------------------------


def test_v1_still_links_its_own_stylesheet_and_not_v2s(client):
    """V2 is a second file, never an edit of the first: the public route
    still serves V1 and V1 still loads style.css alone. The rest of the
    suite pins V1's bytes in detail; this is the one-line guard that the
    second stylesheet did not leak into the first document."""
    html = client.get("/").get_data(as_text=True)
    assert "style.css" in html
    assert "style-v2.css" not in html


@pytest.mark.parametrize("path", ["app/templates/page_v2.html", "app/static/style-v2.css"])
def test_no_mockup_persona_in_the_v2_files(path):
    """The V2 mockups are one speech therapist's page. LLM-COP-10 took that
    identity out of a product that is a GENERIC contact page, and a second
    template is the obvious place for it to walk back in — every V2 design
    note quotes her copy as "sample data from the mockup, not the
    product's promise"."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    hits = re.findall(PERSONA_PATTERN, text, flags=re.IGNORECASE)
    assert not hits, f"{path} carries mockup persona text: {sorted(set(hits))}"
