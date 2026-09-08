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
from tests.conftest import (
    PERSONA_PATTERN,
    assert_absent_from_app,
    edit_published_payload,
)

# LLM-COP-32's fences ask the same questions of both skins, so the three
# instruments are imported rather than retyped — a second copy of
# server_cap_literals would be the very duplication it exists to forbid.
# The precedent for importing another test module is tests/test_page.py,
# which takes DAYS/DURATION/HOURS out of tests/test_seed.py.
from tests.test_messages import cd_text, class_attrs, server_cap_literals

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


def test_the_hero_photo_and_the_portrait_are_two_different_pictures(app):
    """The two V2 image sites read two DIFFERENT stored references
    (LLM-COP-30): the full-bleed hero photograph (v2-cp-hero.hero-photo)
    from hero.background, the portrait circle
    (v2-cp-section-portrait.portrait-section.portrait) from hero.portrait.

    This test is the defect written down and then the fix written down. It
    used to be called ..._reaches_both_the_hero_photo_and_the_portrait and
    asserted `count(one digest) == 2`, because there was one reference and
    V2 painted it in both places — the owner could not put a photograph
    behind the hero card without also making it their profile picture. Two
    digests each appearing EXACTLY ONCE is the same question with the
    answer the product now gives.

    Exactly once matters in both directions. `>= 1` would pass a build that
    still fed the hero from portrait as well; `== 1` on one digest alone
    would pass a build that dropped the other picture entirely.
    """
    edit_published_payload(
        app,
        "hero",
        lambda p: p.update(portrait=DIGEST, background=BACKGROUND_DIGEST),
    )
    html = render_public(app, V2_TEMPLATE)

    assert html.count(f"/kuvat/{DIGEST}") == 1, html.count(f"/kuvat/{DIGEST}")
    assert html.count(f"/kuvat/{BACKGROUND_DIGEST}") == 1, html.count(
        f"/kuvat/{BACKGROUND_DIGEST}"
    )
    # And each is in ITS OWN site, not merely somewhere on the page: a build
    # that swapped the two would satisfy both counts above.
    assert f'<img class="v2-hero-image" src="/kuvat/{BACKGROUND_DIGEST}"' in html
    assert f'src="/kuvat/{DIGEST}"' in html
    assert f'<img class="v2-hero-image" src="/kuvat/{DIGEST}"' not in html

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


# --- LLM-COP-32: the card's Lähetä sends the card ---------------------------
#
# V2 is the skin the artifact was actually filed against: its contact card
# rendered a real form with three real inputs and a button that carried
# .cta-contact, so filling it in and pressing Lähetä threw the answers away
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


def test_v2s_send_button_submits_the_card_and_no_longer_opens_the_dialog(
    v2_html,
):
    """The defect, executable, and the fix's own two halves.

    .cta-contact ABSENT is half of it: contact_dialog.html binds that class
    as a dialog opener, and while the button carried it no amount of
    submitting would have helped — the dialog opened over the answers.

    form= PRESENT and naming a real form is the other half, and it is not
    cosmetic: the design puts this button in the actions column, OUTSIDE
    the copy column that holds the form, so containment cannot associate
    them. That attribute is also what makes this the form's DEFAULT button,
    which is why Enter in a text field submits the card at all.

    data-section and data-field stay ADJACENT and in that order, because
    BINDING at the top of this file reads them as one pattern and the
    in-place editor's whole V1/V2 fence is built on it.
    """
    send = [tag for tag in tags(v2_html, "button") if "v2-contact-primary" in tag]
    assert len(send) == 1, send
    tag = send[0]

    assert "cta-contact" not in tag, (
        "the card's Lähetä is a dialog opener again — pressing it discards "
        "what the visitor typed and asks for it a second time"
    )
    assert 'type="submit"' in tag, tag
    assert 'data-field="send_label"' in tag, tag
    assert re.search(r'data-section="\d+"\s+data-field="send_label"', tag), (
        "data-section and data-field must stay adjacent and in that order"
    )

    named = re.search(r'form="([^"]+)"', tag)
    assert named is not None, "the button is outside the form and names none"
    assert f'id="{named.group(1)}"' in v2_html, (
        f"form={named.group(1)!r} names no form in the document, so the "
        "button submits nothing and Enter submits nothing"
    )


def test_v2s_hero_button_is_still_the_dialogs_opener(v2_html):
    """The half of the ask that was already right.

    test_v2_carries_the_class_hooks_other_files_bind_to only asks whether
    the string "cta-contact" is anywhere in the document, which stays true
    while the class sits on entirely the wrong control. This says WHICH
    button carries it: exactly one, and it is the hero's contact_label.
    """
    openers = [tag for tag in tags(v2_html, "button") if "cta-contact" in tag]
    assert len(openers) == 1, openers
    assert 'data-field="contact_label"' in openers[0], openers[0]
    # And the top bar, which the artifact says must keep working, is still
    # the other opener contact_dialog.html binds.
    assert "header-contact" in v2_html


def test_v2s_contact_form_carries_consent_a_link_and_two_named_slots(v2_html):
    """The same four claims tests/test_messages.py makes of V1's form.

    Asked again here rather than inherited, because a second template is a
    second place each of them can go missing and nothing raises when one
    does: the form simply stops being able to send, or sends without the
    consent the server demands and is refused every time.
    """
    match = re.search(
        r'<form[^>]*class="[^"]*contact-form[^"]*"[^>]*>(.*?)</form>',
        v2_html,
        re.DOTALL,
    )
    assert match is not None, "no .contact-form in the V2 document"
    opening, body = match.group(0)[: match.group(0).index(">") + 1], match.group(1)

    # No browser form post: the submission is JSON from the dialog's script,
    # and an action would navigate the page away and lose that contract.
    assert "action=" not in opening, opening
    assert "method=" not in opening, opening

    consent = re.search(r'<input[^>]*name="consent"[^>]*>', body)
    assert consent is not None, "V2's inline form collects no consent"
    assert 'type="checkbox"' in consent.group(0), consent.group(0)
    assert 'class="gdpr-open"' in body, "V2's form opens no privacy statement"

    for attribute in ("data-result", "data-error"):
        named = re.search(rf'{attribute}="([^"]+)"', opening)
        assert named is not None, attribute
        assert f'id="{named.group(1)}"' in v2_html, (
            f"{attribute} names an id nothing in the document answers to, so "
            "a send reports neither success nor failure"
        )


def test_v2s_consent_sentence_is_the_dialogs_consent_sentence(v2_html):
    """One promise, one string, on this skin too — and the same string the
    V1 document carries, since both include the same dialog."""
    inline = cd_text(v2_html, "contact-consent")
    dialog = cd_text(v2_html, "cd-consent")
    assert inline is not None, "no .contact-consent in the V2 document"
    assert dialog is not None, "no .cd-consent in the V2 document"
    assert inline.strip() == dialog.strip(), (inline, dialog)


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
