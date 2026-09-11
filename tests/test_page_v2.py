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
from app.sections import contact_dialog_copy, site_chrome, visible_sections
from tests.conftest import (
    PERSONA_PATTERN,
    assert_absent_from_app,
    edit_published_payload,
)

# LLM-COP-32's fences ask the same questions of both skins, so the three
# instruments are imported rather than retyped — a second copy of
# server_cap_literals would be the very duplication it exists to forbid.
# The precedent for importing another test module is tests/test_page.py,
# which takes DURATION out of tests/test_seed.py.
from tests.test_messages import class_attrs, server_cap_literals

V2_TEMPLATE = "page_v2.html"
V1_TEMPLATE = "page.html"

# A 64-hex digest is the only thing app/images.py:image_url will turn into
# a URL, so this is what "an image has been uploaded" looks like to a
# template. No file has to exist for the markup question these tests ask.
DIGEST = "b" * 64
# The second reference (LLM-COP-30). DIFFERENT from DIGEST on purpose: the
# whole claim of the hero-photo test below is that the two pictures are two
# pictures, and one digest in both fields cannot tell a correct build from
# the one this artifact exists to fix.
BACKGROUND_DIGEST = "c" * 64

# LLM-COP-28's four: one per editorial kind, each a DIFFERENT digest, for
# the reason BACKGROUND_DIGEST is different from DIGEST. Every band now
# stores its own picture, so "each band draws its own" is only falsifiable if
# no two bands could be drawing the same one by accident. A single shared
# constant would let a template that fed all four from one payload pass every
# count below.
SECTION_DIGESTS = {
    "tietoa": "d" * 64,
    "palvelut": "e" * 64,
    "vastaanottoajat": "f" * 64,
    "sijainti": "a" * 64,
}

# The band's <section> class, which is where the alternation is visible. It
# is read with a regex over data-kind rather than by splitting the document,
# because the class and the kind are attributes of the same element and
# asserting them apart would let a build put the right classes on the wrong
# bands.
BAND = re.compile(
    r'<section id="[^"]*" class="v2-band ([^"]+)"'
    r' data-section="\d+" data-kind="([^"]+)"'
)


def band_classes(html):
    """The layout class of every rendered band, keyed by kind.

    `v2-band-media-left`, `v2-band-media-right` or `v2-band-prose` — the
    three the template can emit. The hero and the contact card carry their
    own classes and appear here too; the tests below name the kinds they
    care about rather than asserting the whole map, so a band gaining a class
    does not break a test about a different band.
    """
    return {kind: cls for cls, kind in BAND.findall(html)}


BINDING = re.compile(r'data-section="(\d+)"\s+data-field="([^"]+)"')
KIND = re.compile(r'data-kind="([^"]+)"')


def render_public(app, template):
    """One public document, rendered with render_page's own context.

    Built from the same calls app/__init__.py makes — visible_sections,
    NAV_LABELS/ANCHORS, site_chrome and contact_dialog_copy — so a V2 document
    here is the document the public route would serve if it named this
    template.
    """
    with app.test_request_context("/"):
        conn = database.connect(app.config["DATABASE"])
        try:
            context = dict(
                sections=visible_sections(conn),
                nav_labels=NAV_LABELS,
                anchors=ANCHORS,
                **site_chrome(conn),
                **contact_dialog_copy(conn),
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


def test_the_hero_photo_and_the_band_picture_come_from_two_sections(app):
    """The two V2 image sites read two DIFFERENT stored references from two
    DIFFERENT sections — and the second half of that sentence is
    LLM-COP-28's, where the first half was LLM-COP-30's.

    The history is worth keeping, because this one test has now been the
    written-down form of two separate defects.

      * Before LLM-COP-30 there was ONE reference and V2 painted it in both
        places: the owner could not put a photograph behind the hero card
        without also making it their profile picture. This test was called
        ..._reaches_both_the_hero_photo_and_the_portrait and asserted
        `count(one digest) == 2` to say so.
      * LLM-COP-30 split the references and it became
        ..._are_two_different_pictures: hero.background in the hero,
        hero.portrait in the tietoa circle, each digest exactly once. But
        BOTH still came out of the hero row, hoisted across the section
        boundary by a namespace pass at the bottom of the template.
      * LLM-COP-28 deletes that hoist. The band that draws a picture is now
        the section that STORES it, so the circle reads tietoa.image and
        hero.portrait reaches this document nowhere at all.

    So the claim is now three-part: hero.background is in the hero,
    tietoa.image is in the tietoa band, and hero.portrait is NOWHERE. The
    third part is the one that goes red against a build that kept the hoist,
    and it is asserted on a digest that is deliberately set to a valid
    64-hex value — a `not in` over an empty field would hold whatever the
    template did.

    Exactly once matters in both directions. `>= 1` would pass a build that
    fed the hero from the band's picture as well; `== 1` on one digest alone
    would pass a build that dropped the other picture entirely.
    """
    edit_published_payload(
        app,
        "hero",
        lambda p: p.update(portrait=DIGEST, background=BACKGROUND_DIGEST),
    )
    edit_published_payload(
        app, "tietoa", lambda p: p.update(image=SECTION_DIGESTS["tietoa"])
    )
    html = render_public(app, V2_TEMPLATE)

    band = SECTION_DIGESTS["tietoa"]
    assert html.count(f"/kuvat/{band}") == 1, html.count(f"/kuvat/{band}")
    assert html.count(f"/kuvat/{BACKGROUND_DIGEST}") == 1, html.count(
        f"/kuvat/{BACKGROUND_DIGEST}"
    )
    # And each is in ITS OWN site, not merely somewhere on the page: a build
    # that swapped the two would satisfy both counts above.
    assert f'<img class="v2-hero-image" src="/kuvat/{BACKGROUND_DIGEST}"' in html
    assert f'src="/kuvat/{band}"' in html
    assert f'<img class="v2-hero-image" src="/kuvat/{band}"' not in html

    # LLM-COP-28's Decision 3, in the template's own terms: hero.portrait is
    # a V1 field from here. It is SET to a valid digest above, and the hoist
    # that used to carry it here is gone, so this line is the one that fails
    # if it comes back.
    assert f"/kuvat/{DIGEST}" not in html
    assert DIGEST not in html

    assert "has-image" in html
    assert "Muotokuva" not in html
    assert "browse files" not in html


def test_a_non_digest_section_image_falls_back_to_the_placeholder(app):
    """image_url answers None for anything that is not a 64-hex digest, so
    junk in the payload must not become a URL and must not blank the
    placeholder either.

    Re-pointed at tietoa.image by LLM-COP-28, because that is the field the
    circle reads now — and HARDENED at the same time, because in its old
    shape it had quietly become vacuous. Both of its assertions ("etc/passwd
    not in html", "Muotokuva in html") would have held with the image_url
    filter deleted entirely, once V2 stopped reading hero.portrait: an
    unrendered field cannot leak a path and cannot fill a placeholder.

    The third assertion is what fixes that. hero.portrait is planted with a
    VALID digest at the same time, so:

      * a build that still reads hero.portrait for the circle renders a real
        URL and fails on the third line;
      * a build that stopped type-guarding the filter renders the traversal
        path and fails on the first;
      * a build that filled the slot anyway fails on the second.

    Three assertions, three different failures, and no pair of them can be
    satisfied by the same mistake.
    """
    edit_published_payload(
        app, "tietoa", lambda p: p.update(image="../../etc/passwd")
    )
    edit_published_payload(app, "hero", lambda p: p.update(portrait=DIGEST))
    html = render_public(app, V2_TEMPLATE)

    assert "etc/passwd" not in html
    assert "Muotokuva" in html
    assert f"/kuvat/{DIGEST}" not in html


def test_a_non_digest_background_draws_no_hero_image(app):
    """The sibling for LLM-COP-30's second reference: hero.background goes
    through the same image_url filter, so junk there must not become a URL
    either.

    The two fields differ in what is left behind. A refused portrait falls
    back to the placeholder, which has a label and a browse affordance; the
    hero band has no placeholder and needs none — .v2-hero-photo renders
    unconditionally and only the <img> inside it is conditional, so a refused
    background leaves the band exactly as an unset one does. Asserted rather
    than assumed, because "no URL" and "no broken <img>" are two claims.
    """
    edit_published_payload(
        app, "hero", lambda p: p.update(background="../../etc/passwd")
    )
    html = render_public(app, V2_TEMPLATE)

    assert "etc/passwd" not in html
    assert "v2-hero-image" not in html
    assert "has-image" not in html
    assert 'class="v2-hero-photo"' in html


# --- LLM-COP-28: every editorial band draws its own picture -----------------
#
# Four kinds, three new fields each, and the claims divide cleanly: WHICH
# picture a band draws (its own), HOW it is cropped (its own image_shape),
# and WHICH SIDE it sits on (positional, computed down the page). Each has
# its own test below, and the side one has three, because the alternation is
# a property of the SEQUENCE and a single rendering can only ever show one
# point of it.


def set_positions(app, order):
    """Rewrite the page order, the way PUT /api/sections/order does.

    A direct write to the store rather than a route call, and that is on
    purpose here: these are TEMPLATE tests, and the question they ask is what
    page_v2.html renders from a given stored order. The owner's real route to
    that order is proved once, in tests/test_sectionlist.py, where the same
    reordering is driven through PUT /api/sections/order and the resulting
    document's band classes are read — that is the test that makes this one
    more than a fixture.

    `order` is a list of kinds; every kind not named keeps a position after
    them, in its existing relative order, so a caller only has to say what it
    cares about.
    """
    conn = database.connect(app.config["DATABASE"])
    try:
        rows = conn.execute(
            "SELECT id, kind FROM sections ORDER BY position"
        ).fetchall()
        named = [r for kind in order for r in rows if r["kind"] == kind]
        rest = [r for r in rows if r["kind"] not in order]
        for position, row in enumerate(named + rest, start=1):
            conn.execute(
                "UPDATE sections SET position = ? WHERE id = ?",
                (position, row["id"]),
            )
        conn.commit()
    finally:
        conn.close()


def test_each_editorial_band_draws_its_own_stored_picture(app):
    """The heart of the artifact: four kinds, four different digests, and
    each one exactly once and inside its own band.

    Exactly once is what tells "each band reads its own field" apart from
    the arrangement this change replaced, where one hoisted reference was
    handed to whichever band wanted it. A build that fed every band from
    tietoa.image would put one digest on the page four times and the other
    three not at all; a build that kept feeding the circle from
    hero.portrait would leave the tietoa digest at zero.

    IN ITS OWN BAND, not merely somewhere on the page, and that is asserted
    by slicing the document at the <section> boundaries rather than by
    counting. Four counts of one can all be satisfied by four pictures in
    the wrong four bands.

    hero.portrait is planted with a valid digest too, and asserted absent, so
    this test also carries Decision 3 in the state where it is hardest: with
    every band drawing something, a stray hero portrait would be easy to miss
    in a count.
    """
    for kind, digest in SECTION_DIGESTS.items():
        edit_published_payload(app, kind, lambda p, d=digest: p.update(image=d))
    edit_published_payload(app, "hero", lambda p: p.update(portrait=DIGEST))
    html = render_public(app, V2_TEMPLATE)

    for kind, digest in SECTION_DIGESTS.items():
        assert html.count(f"/kuvat/{digest}") == 1, (kind, digest)

    # And each inside the band that stores it. The document is cut at the
    # section that OPENS each band, so "inside" means between this band's
    # opening tag and the next one's — the same read a person does.
    for kind, digest in SECTION_DIGESTS.items():
        assert f"/kuvat/{digest}" in band_markup(html, kind), kind

    assert f"/kuvat/{DIGEST}" not in html
    assert DIGEST not in html


def band_markup(html, kind):
    """The markup of one band: from its <section> tag to the next one.

    Written as a slice over the served document rather than with a parser,
    the way every other structural assertion in this file is: the tests here
    are about the bytes the template emits, and a parser would quietly
    forgive a malformed one.
    """
    start = html.index(f'data-kind="{kind}"')
    start = html.rindex("<section", 0, start)
    following = html.find("<section", start + 1)
    return html[start:] if following == -1 else html[start:following]


@pytest.mark.parametrize(
    "kind", ["tietoa", "palvelut", "vastaanottoajat", "sijainti"]
)
def test_a_square_shape_puts_the_square_class_on_that_bands_picture(app, kind):
    """image_shape "square" reaches the page as one word in the .portrait
    element's class list, and "" does not.

    Asked of every kind, because the shape is passed through a different
    macro path for tietoa (which always renders its slot) than for the three
    prose bands (which render one only when a picture is set), and a build
    that wired the parameter through one path and not the other would pass a
    tietoa-only test.

    BOTH DIRECTIONS IN ONE TEST. The square band is asserted to carry the
    class and the circle band asserted not to, in the same rendering, so the
    assertion cannot be satisfied by a template that puts `square` on every
    picture — which is exactly what an unconditional class would do, and
    exactly what would look right in the one screenshot anyone checks.

    "circle" is the class an unset shape resolves to, and it is asserted
    positively: app/shapes.py answers `circle` for "", so the element carries
    a shape word either way and a MISSING word means the filter did not run.
    """
    other = next(k for k in SECTION_DIGESTS if k != kind)
    edit_published_payload(
        app,
        kind,
        lambda p: p.update(image=SECTION_DIGESTS[kind], image_shape="square"),
    )
    edit_published_payload(
        app,
        other,
        lambda p: p.update(image=SECTION_DIGESTS[other], image_shape=""),
    )
    html = render_public(app, V2_TEMPLATE)

    square = band_markup(html, kind)
    circle = band_markup(html, other)
    assert 'class="portrait square has-image"' in square, kind
    assert "square" not in circle, other
    assert 'class="portrait circle has-image"' in circle, other


def test_an_unknown_shape_draws_the_circle_rather_than_its_own_word(app):
    """The resolver reaches the page, not the stored value.

    A band whose image_shape holds a word app/shapes.py does not know must
    render as a circle — and must not render that word into the class
    attribute, which is what a template writing `{{ p.image_shape }}` raw
    would do. That is not merely untidy: an unrecognised class is a picture
    with no border-radius rule at all, so the page would draw a square that
    nobody chose.
    """
    edit_published_payload(
        app,
        "tietoa",
        lambda p: p.update(
            image=SECTION_DIGESTS["tietoa"], image_shape="pyöreä"
        ),
    )
    html = render_public(app, V2_TEMPLATE)

    band = band_markup(html, "tietoa")
    assert 'class="portrait circle has-image"' in band
    assert "pyöreä" not in html


def test_a_prose_band_with_no_picture_keeps_its_prose_layout(app):
    """v2-cp-section-prose's own note, both halves of it.

    "Each section would have option for image" is the test above; "This
    section is rendered with no image, so the text runs in the left column
    and the right column is empty" is this one. A band with nothing stored
    renders v2-band-prose and emits no media column at all — not an empty
    one, which would take the copy out of the left column and leave a hole.

    tietoa is deliberately excluded from the claim and asserted the other
    way in the same rendering: its design has an asserted placeholder
    criterion (`when: no portrait image has been uploaded`), so it renders
    its slot whether or not a picture exists. That asymmetry is the designs'
    rather than a preference, and stating it here is what stops a later
    reader "fixing" one of the two macros to match the other.
    """
    html = render_public(app, V2_TEMPLATE)  # the seeded store: no pictures

    classes = band_classes(html)
    for kind in ("palvelut", "vastaanottoajat", "sijainti"):
        assert classes[kind] == "v2-band-prose", kind
        assert "v2-band-media" not in band_markup(html, kind), kind

    # tietoa keeps its media column and its placeholder.
    assert classes["tietoa"] == "v2-band-media-left"
    assert 'class="v2-band-media"' in band_markup(html, "tietoa")
    assert "Muotokuva" in band_markup(html, "tietoa")


def test_the_picture_side_alternates_down_the_page_in_stored_order(app):
    """"Starting from left side, then right side" — the design's own words,
    asked of three media bands at once.

    One rendering can only show one point of an alternation, so this test
    sets THREE pictures and reads all three classes: left, right, left. Two
    bands would agree with a template that simply alternated every band, and
    one band would agree with a hardcoded class — which is precisely what
    this template had before, `v2-band-media-left` written into the tietoa
    macro.

    The band WITHOUT a picture is the second half of the claim and it is why
    vastaanottoajat is left empty here: it must not consume a turn. A
    counter that incremented for every band rather than for every band with
    a picture would put sijainti back on the left, and the page would show
    two left-hand pictures in a row — the exact defect the alternation
    exists to prevent.
    """
    for kind in ("tietoa", "palvelut", "sijainti"):
        edit_published_payload(
            app, kind, lambda p, k=kind: p.update(image=SECTION_DIGESTS[k])
        )
    html = render_public(app, V2_TEMPLATE)

    classes = band_classes(html)
    assert classes["tietoa"] == "v2-band-media-left"
    assert classes["palvelut"] == "v2-band-media-right"
    assert classes["vastaanottoajat"] == "v2-band-prose"
    assert classes["sijainti"] == "v2-band-media-left"


def test_a_reordered_store_alternates_by_position_and_not_by_kind(app):
    """The case a hardcoded class could not render, and the reason `side`
    became a parameter of the tietoa macro like every other band's.

    PUT /api/sections/order rewrites `position` for the whole list and
    visible_sections orders by it, so "tietoa is the first band with a
    picture" is an owner-editable fact rather than an invariant. Move a
    palvelut that carries a picture above it and the alternation must follow
    the new order: palvelut left, tietoa right.

    Before this change the tietoa band carried `class="v2-band
    v2-band-media-left"` as a literal, so this rendering would have painted
    two consecutive left-hand pictures — defeating the design note the whole
    feature claims to meet. This is the assertion that says so.

    No spec criterion changes verdict under this order.
    v2-cp-section-portrait's portrait-section has exactly one asserted
    criterion, `is-visible`, which holds on either side; "the section renders
    its image on the left" is a note, in the same sentence that says the
    sections alternate.
    """
    for kind in ("tietoa", "palvelut"):
        edit_published_payload(
            app, kind, lambda p, k=kind: p.update(image=SECTION_DIGESTS[k])
        )
    set_positions(app, ["hero", "palvelut", "tietoa"])
    html = render_public(app, V2_TEMPLATE)

    # The order really moved — asserted before the classes are read, so the
    # test cannot pass by rendering the order it was trying to change.
    kinds = KIND.findall(html)
    assert kinds.index("palvelut") < kinds.index("tietoa")

    classes = band_classes(html)
    assert classes["palvelut"] == "v2-band-media-left"
    assert classes["tietoa"] == "v2-band-media-right"


# --- the section labels and the contact card are the owner's now ------------
#
# Until LLM-COP-25 this template owned five literal strings and its own header
# comment said so. They are stored fields on both skins now, so the rule this
# file has always held to — assert that the STORED value reaches the page,
# never what it says — finally applies to them as well. The values below are
# checked to appear nowhere in app/ first, which is what makes these fail
# against a template that kept its literal.


def test_each_v2_band_renders_its_stored_section_label(app):
    """All five, and the count matters as much as the strings.

    V2 draws these labels through three different constructs: the tietoa
    macro's own <p>, the prose_band macro shared by palvelut, vastaanottoajat
    and sijainti, and the contact card's kicker. A test that checked one band
    would say nothing about the other two constructs, and the prose_band one
    is the one that took a call-site change at three call sites — the shape a
    half-done edit takes.
    """
    labels = {
        "tietoa": "TÄSTÄ ON KYSE",
        "palvelut": "TARJOAMANI PALVELUKOKONAISUUDET",
        "vastaanottoajat": "TAVATTAVISSA NÄINÄ AIKOINA",
        "yhteydenotto": "LAITA VIESTIÄ",
        "sijainti": "LÖYDÄT MINUT TÄÄLTÄ",
    }
    assert_absent_from_app(*labels.values())

    for kind, label in labels.items():
        edit_published_payload(
            app, kind, lambda p, label=label: p.update(section_label=label)
        )

    html = render_public(app, V2_TEMPLATE)
    for kind, label in labels.items():
        assert label in html, kind
    for old in (
        "NÄIN TYÖSKENTELEN",
        "PALVELUT",
        "VASTAANOTTOAJAT",
        "YHTEYDENOTTO",
        "SIJAINTI",
    ):
        assert old not in html, old


def test_the_v2_contact_card_renders_its_four_stored_values(app):
    """v2-cp-section-contact.contact-band.contact-card's body, caveat and two
    action rows, which LLM-COP-23 reported unsatisfied because the kind
    stored none of them.

    Every element is emitted unconditionally, so the second half asserts the
    empty case as well: a conditional element would take the binding the
    in-place editor needs off the page for exactly the install that most
    needs it — a MIGRATED one, where all four are backfilled empty.
    """
    values = {
        "phone": "050 123 4567 iltapäivisin",
        "email": "posti@toinenesimerkki.invalid",
        "body": "Kirjoita muutamalla lauseella, mistä on kyse.",
        "caveat": "Älä liitä viestiin salassa pidettäviä liitteitä.",
    }
    assert_absent_from_app(*values.values())

    edit_published_payload(app, "yhteydenotto", lambda p: p.update(**values))
    html = render_public(app, V2_TEMPLATE)
    for value in values.values():
        assert value in html, value

    edit_published_payload(
        app,
        "yhteydenotto",
        lambda p: p.update(phone="", email="", body="", caveat=""),
    )
    empty = render_public(app, V2_TEMPLATE)
    for cls in (
        "v2-contact-body",
        "v2-contact-caveat",
        "v2-contact-phone",
        "v2-contact-email",
    ):
        assert cls in empty, cls


# --- USR-COP-4: the availability notice, on V2 ------------------------------
#
# The V1 siblings of these live in tests/test_page.py. BOTH sets are needed
# and neither is a copy of the other's claim: app/notice.py decides once, and
# what these say is that each skin obeys that one decision — including the
# "off means absent from the bytes" half, which is the assertion a `hidden`
# element would fail on either skin independently.

V2_NOTICE_TEXT = "Vastaanotto on suljettu heinäkuun ajan"


def test_the_v2_card_shows_the_availability_notice_when_it_is_switched_on(app):
    assert_absent_from_app(V2_NOTICE_TEXT)

    edit_published_payload(
        app,
        "yhteydenotto",
        lambda p: p.update(notice_text=V2_NOTICE_TEXT, notice_on="on"),
    )

    html = render_public(app, V2_TEMPLATE)
    assert V2_NOTICE_TEXT in html
    assert "v2-contact-notice" in html
    # Between the body and the caveat, which is the reading position the
    # notice takes on both skins. Asserted by document order rather than by
    # a line number, so reformatting the template cannot break it and moving
    # the element can.
    assert (
        html.index("v2-contact-body")
        < html.index("v2-contact-notice")
        < html.index("v2-contact-caveat")
    )
    # Neither field is bound for direct edit here either, and the V1 sibling
    # says the same of its own skin. Held on both, deliberately: a one-sided
    # binding is exactly what the V1/V2 fence exists to catch, and that fence
    # cannot see this element — direct edit renders the seeded store, where
    # notice_on is "" and the notice is not emitted at all.
    assert 'data-field="notice_text"' not in html
    assert 'data-field="notice_on"' not in html


def test_switching_the_v2_notice_off_removes_it_from_the_rendered_bytes(app):
    """The same claim tests/test_page.py makes for V1, asked of V2's own
    document: off means the sentence is not in the served HTML at all, not
    that it is in there wearing `hidden`."""
    assert_absent_from_app(V2_NOTICE_TEXT)

    edit_published_payload(
        app,
        "yhteydenotto",
        lambda p: p.update(notice_text=V2_NOTICE_TEXT, notice_on="on"),
    )
    assert V2_NOTICE_TEXT in render_public(app, V2_TEMPLATE)

    edit_published_payload(app, "yhteydenotto", lambda p: p.update(notice_on=""))

    off = render_public(app, V2_TEMPLATE)
    assert V2_NOTICE_TEXT not in off
    assert "v2-contact-notice" not in off


@pytest.mark.parametrize(
    "notice_on,notice_text",
    [
        ("on", ""),
        ("on", "   "),
        ("KYLLÄ", V2_NOTICE_TEXT),
        ("1", V2_NOTICE_TEXT),
        ("", V2_NOTICE_TEXT),
    ],
)
def test_an_empty_or_unrecognised_v2_notice_renders_no_element(
    app, notice_on, notice_text
):
    edit_published_payload(
        app,
        "yhteydenotto",
        lambda p: p.update(notice_text=notice_text, notice_on=notice_on),
    )
    assert "v2-contact-notice" not in render_public(app, V2_TEMPLATE)


@pytest.mark.parametrize(
    "key,value",
    [("notice_on", {}), ("notice_on", []), ("notice_text", {}), ("notice_text", [])],
)
def test_a_wrongly_typed_v2_notice_value_renders_rather_than_raising(
    app, key, value
):
    """app/styles.py's recorded 500, asked of the second skin. Rendering at
    all is the assertion: an unguarded membership test or .strip() raises
    inside the template and the whole document is lost, not just the notice.
    """
    edit_published_payload(
        app, "yhteydenotto", lambda p: p.update({"notice_on": "on", key: value})
    )

    html = render_public(app, V2_TEMPLATE)
    assert "v2-contact-card" in html
    assert "v2-contact-notice" not in html


def test_the_v2_notice_is_not_marked_up_or_painted_as_an_error(app):
    """Not a warning (the author's second example is a promise), and
    specifically not wearing this card's own error ink: #ffb4a2 is
    .v2-contact-copy .contact-error's colour in app/static/style-v2.css, and
    reusing it would make an availability note read as a failure. The rule
    reuses .v2-contact-body's #c3d5e3 instead, which is also why this change
    adds no new colour literal to that stylesheet.
    """
    edit_published_payload(
        app,
        "yhteydenotto",
        lambda p: p.update(notice_text=V2_NOTICE_TEXT, notice_on="on"),
    )

    html = render_public(app, V2_TEMPLATE)
    tag = re.search(
        r'<p\b[^>]*class="[^"]*\bv2-contact-notice\b[^"]*"[^>]*>', html
    )
    assert tag is not None, "no p.v2-contact-notice start tag in the document"
    assert "role=" not in tag.group(0), tag.group(0)
    assert "aria-live" not in tag.group(0), tag.group(0)

    # Read by the same relative path test_no_mockup_persona_in_the_v2_files
    # below uses, so there is one convention in this file for reaching a
    # source file rather than two.
    with open("app/static/style-v2.css", encoding="utf-8") as handle:
        css = handle.read()
    rule = re.search(r"\.v2-contact-notice\s*\{[^}]*\}", css)
    assert rule is not None, "no .v2-contact-notice rule in style-v2.css"
    assert "#ffb4a2" not in rule.group(0), rule.group(0)


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


# --- LLM-COP-32: the card's button sends the card ---------------------------
#
# (It read "Lähetä" then. USR-COP-4 renamed the default to "Ota yhteyttä",
# which is what the button has actually done since USR-COP-1 — it opens the
# dialog — so it is named below by its binding, send_label, and by its class,
# never by its words.)
#
# V2 is the skin the artifact was actually filed against: its contact card
# rendered a real form with three real inputs and a button that carried
# .cta-contact, so filling it in and pressing that button threw the answers away
# and opened a dialog asking the same three questions again. The tests below
# pin the two halves of the fix that a later edit could undo silently —
# the class the button must NOT have, and the association it must have
# instead — plus the consent the second collection path has to carry.
#
# tests/browser/test_browser_contact_submit.py drives all of it in a real
# Chrome. These are the cheap fences that say WHY the browser test would
# start failing.


def tags(html, name):
    """Every <name ...> start tag in the document, as raw source text."""
    return re.findall(rf"<{name}\b[^>]*>", html)


def test_v2s_card_button_opens_the_dialog_and_submits_nothing(v2_html):
    """The card's button is an OPENER again, and this time there is nothing
    left on the card for it to submit.

    LLM-COP-32 made it a submitter because the class had it reopening a
    dialog over the answers the visitor had already typed into the card.
    USR-COP-1 removes the other half of that collision instead: the card's
    form is gone, the product collects a message in one place, so the button
    carries .cta-contact and opens the dialog.

    form= ABSENT is asserted, not merely unchecked. An out-of-form submitter
    is associated by that attribute alone, so one left pointing at a form
    that no longer exists is a button that looks wired and is not.

    data-section and data-field stay ADJACENT and in that order, because
    BINDING at the top of this file reads them as one pattern and the
    in-place editor's whole V1/V2 fence is built on it.
    """
    send = [tag for tag in tags(v2_html, "button") if "v2-contact-primary" in tag]
    assert len(send) == 1, send
    tag = send[0]

    assert "cta-contact" in tag, (
        "the card's button opens nothing — the card has no form left to send,"
        " so a button without the opener class does nothing at all"
    )
    assert 'type="button"' in tag, tag
    assert 'form=' not in tag, (
        "the button still names a form; the card's form is gone, so this "
        "points at nothing"
    )
    assert re.search(r'data-section="\d+"\s+data-field="send_label"', tag), (
        "data-section and data-field must stay adjacent and in that order"
    )
    # Both halves are falsifiable, and the exact strings matter. V2's form
    # carried class="contact-form v2-contact-form", so 'class="contact-form"'
    # WITH the closing quote never appeared in this document even at head —
    # asserting its absence would have passed against every build. The open
    # prefix is what actually catches it. A bare "contact-form" would be
    # wrong in the other direction: contact_dialog.html:130's querySelectorAll
    # names form.contact-form in the script that ships with every page.
    assert "v2-contact-form" not in v2_html
    assert 'class="contact-form' not in v2_html


def test_v2s_hero_button_is_still_the_dialogs_opener(v2_html):
    """The half of the ask that was already right.

    test_v2_carries_the_class_hooks_other_files_bind_to only asks whether
    the string "cta-contact" is anywhere in the document, which stays true
    while the class sits on entirely the wrong control. This says WHICH
    buttons carry it: exactly two since USR-COP-1 — the hero's contact_label
    and the card's send_label — and they are named by field, so "two openers"
    cannot be satisfied by the class landing on some other pair of controls.
    """
    openers = [tag for tag in tags(v2_html, "button") if "cta-contact" in tag]
    assert len(openers) == 2, openers
    fields = sorted(
        re.search(r'data-field="([^"]+)"', tag).group(1)
        for tag in openers
        if re.search(r'data-field="([^"]+)"', tag)
    )
    assert fields == ["contact_label", "send_label"], openers
    # And the top bar, which the artifact says must keep working, is still
    # the other opener contact_dialog.html binds.
    assert "header-contact" in v2_html


def test_v2s_footer_carries_the_privacy_link(v2_html):
    """v2-cp-section-contact.footer.footer-right — "Address, a privacy link
    and the admin link, separated by dots" — was unsatisfied: the footer
    rendered the owner's copyright line and the Ylläpito link and nothing
    else.

    Half of that address is now met. It is asserted here because the card's
    own Tietosuojaseloste link went with the deleted form, and a visitor who
    never opens the contact dialog would otherwise have no way to reach the
    privacy statement at all. Scoped to the <footer>: the dialog's consent row
    carries a .gdpr-open of its own, so a document-wide check would be
    satisfied by that one.

    Still unmet and reported rather than faked: the street address, and the
    dot separators.
    """
    footer = re.search(r"<footer\b.*?</footer>", v2_html, re.DOTALL)
    assert footer is not None, "no <footer> in the V2 document"
    link = re.search(
        r'<a[^>]*class="[^"]*\bgdpr-open\b[^"]*"[^>]*>(.*?)</a>',
        footer.group(0),
        re.DOTALL,
    )
    assert link is not None, "no a.gdpr-open in the V2 footer"
    assert link.group(1).strip() == "Tietosuojaseloste"


def test_v2_serves_the_gdpr_dialog_hidden_and_names_the_endpoint_once(v2_html):
    """The new dialog reaches this skin too, shut, and brings no second
    copy of the endpoint with it.

    The once-and-only-once rule on /api/messages is what keeps the
    submission path a single source of truth; a second inline script is the
    obvious way to break it, and the GDPR dialog is exactly that — a second
    inline script, included on both skins.
    """
    roots = class_attrs(v2_html, "gdpr-dialog")
    assert len(roots) == 1, roots
    assert "hidden" in roots[0][1], roots[0][1]
    assert v2_html.count('id="gdpr-dialog-script"') == 1
    assert v2_html.count("/api/messages") == 1


def test_v2s_client_never_duplicates_the_servers_length_caps(v2_html):
    """The same fence tests/test_messages.py lays over the V1 document.

    Both skins include the one script, so the JavaScript half is the same
    text twice — but the MARKUP half is not: a maxlength copied into this
    template alone would pass over there and fail here, which is the whole
    reason this is asked of the served document rather than of the script.
    """
    assert server_cap_literals(v2_html) == []
