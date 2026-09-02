"""Plan step 6 — GET / rendered from the store, against the governing specs.

One test (or one parametrized case) per addressed contains-text criterion;
each case id cites its spec address (spec.region.child, with an index when a
criterion region asserts several strings). The specs state no testids, so
nothing here invents data-testid selectors — assertions are byte-exact
substrings of the one served document, scoped to the implementation's own
header/nav/section/footer elements where a bare substring would be
ambiguous (short strings like "Pe" or nav labels that recur in the copy).

Trap characters are built from the constants in test_seed (escaped-verified
en dash U+2013 and thin space U+2009 copied from the spec JSON).
"""

import re

import pytest

from app.sections import initials
from app.seed import SEED_SECTIONS
from tests.conftest import (
    PERSONA_PATTERN,
    assert_absent_from_app,
    edit_published_payload,
    element_text,
    set_section_state,
)
from tests.test_seed import DAYS, DURATION, HOURS

SEED_BY_KIND = dict(SEED_SECTIONS)

# --- whole-document byte-exact contains-text criteria -----------------------
#
# LLM-COP-10 split the old 54-row DOCUMENT_CRITERIA table in two, LLM-COP-26
# took two more rows out of what was left, and LLM-COP-25 took three: the
# section kickers became sijainti/tietoa/palvelut/vastaanottoajat/yhteydenotto
# .section_label, a field the panel offers as "Osion otsikko", so the words are
# the owner's. 4 rows stay below; of the rest, 15 became SEEDED_RENDERS, 32 are
# covered by the three list-driven tests (fact cards, about facts, services),
# which assert every stored item rather than a hand-picked few, and 3 became
# CTA_RENDERS further down.
#
# The fourth criterion LLM-COP-25 demoted on the server,
# cp-main-edit.preview-pane.preview-card.preview-palvelut-label, has no row
# anywhere in this suite: the section-list preview card renders the public
# macro (app/templates/_section_row.html), so it follows the stored label with
# no test of its own. That demotion is spec-only.
#
# test_nav_links below is deliberately NOT touched. Its four addresses pin
# NAV_LABELS' words (app/fields.py), which stay hardcoded product chrome after
# LLM-COP-25 — so an owner who renames a kicker still sees the old word in the
# nav link pointing at it. Making nav labels editable is a later unit, and it
# inherits four more demotions on cp-main.header.nav-links.
#
# Byte-exact below: strings the TEMPLATE owns, which no admin can edit.
# "Ota yhteyttä" used to be the one exception, on the ground that the brief
# named it as the product's promise rather than the persona. It is
# hero.contact_label — a stored field the panel offers as "Painike 1"
# (app/fields.py) — so LLM-COP-26 demoted the seven criteria that pinned it
# and hero.services_label, and its rows left this table.
#
# The two labels are deliberately NOT in SEEDED_RENDERS either, for two
# different reasons. A whole-document substring for "Ota yhteyttä" cannot fail
# while the header's button at app/templates/page.html:128 carries those same
# words as a template literal: delete the hero's binding entirely and such a
# row still passes. "Lue palveluista" has no such literal, so a whole-document
# row does catch a deleted binding — but it cannot say which element rendered
# the value: swap the hero's two bindings and both whole-document rows still
# pass while every element-scoped case goes red.
# They live in CTA_RENDERS below, scoped to the hero's own element, plus
# test_cta_labels_are_data_the_owner_can_change, which stores strings that
# appear nowhere in app/. test_header_contact_button is the criterion that
# legitimately owns that header literal.
#
# Everything that moved pinned a value the owner can change from the admin
# panel. Pinning those is the defect this artifact was filed against: a data
# value promoted to a promise. They now assert that the STORED value reaches
# the page, never what it says.

DOCUMENT_CRITERIA = [
    ("cp-main.hero.portrait-placeholder-0", "Muotokuva"),
    ("cp-main.hero.portrait-placeholder-1", "browse files"),
    ("cp-main-phone.phone-hero.phone-portrait-0", "Kuva"),
    ("cp-main-phone.phone-hero.phone-portrait-1", "browse files"),
]

# (address, kind, field) — the served page must carry the stored string.
SEEDED_RENDERS = [
    ("cp-main.hero.kicker", "hero", "kicker"),
    ("cp-main.hero.main-heading", "hero", "title"),
    ("cp-main.hero.subtitle", "hero", "subtitle"),
    ("cp-main.hero.intro", "hero", "ingress"),
    ("cp-main-phone.phone-hero.phone-intro", "hero", "ingress_mobile"),
    ("cp-main.hero.credentials-row", "hero", "credentials"),
    ("cp-main.about-section.about-lead", "tietoa", "nostolause"),
    ("cp-main.about-section.about-body", "tietoa", "leipäteksti"),
    ("cp-main-phone.phone-palvelut.phone-all-services", "palvelut", "more_label"),
    (
        "cp-main-phone.phone-vastaanotto.phone-booking-note",
        "vastaanottoajat",
        "booking_note",
    ),
    ("cp-main.header.brand", "hero", "brand"),
    ("cp-main-phone.phone-footer.phone-copyright", "hero", "footer"),
    # The three demoted kickers (LLM-COP-25). They now assert that the STORED
    # label reaches the page, never what it says.
    ("cp-main.about-section.about-kicker", "tietoa", "section_label"),
    (
        "cp-main-phone.phone-palvelut.phone-palvelut-label",
        "palvelut",
        "section_label",
    ),
    (
        "cp-main-phone.phone-vastaanotto.phone-vastaanotto-label",
        "vastaanottoajat",
        "section_label",
    ),
]


def test_response_is_200_html_utf8(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.content_type == "text/html; charset=utf-8"


@pytest.mark.parametrize(
    "address,expected",
    [pytest.param(a, e, id=a) for a, e in DOCUMENT_CRITERIA],
)
def test_document_contains_text(page_html, address, expected):
    assert expected in page_html, f"{address}: {expected!r} not in document"


@pytest.mark.parametrize(
    "address,kind,field",
    [pytest.param(a, k, f, id=a) for a, k, f in SEEDED_RENDERS],
)
def test_seeded_value_reaches_the_page(page_html, address, kind, field):
    """The criterion is that the element renders the STORED value — not that
    the value is any particular words. This still exercises seed -> database ->
    visible_sections -> template; it fails whenever that pipeline drops a
    field, and it keeps passing when the owner rewrites their copy."""
    value = SEED_BY_KIND[kind][field]
    assert value.strip(), f"{address}: seeded {kind}.{field} is empty"
    assert value in page_html, f"{address}: stored {kind}.{field} not rendered"


def test_hero_fact_cards_render_their_stored_labels_and_values(page_html):
    # cp-main.hero.fact-cards — four cards, each label and value from the
    # store. The labels were byte-exact criteria until LLM-COP-10; they are
    # payload data the owner can rename, so they are read from the seed.
    for fact in SEED_BY_KIND["hero"]["facts"]:
        assert fact["label"] in page_html
        for line in fact["value"].split("\n"):
            assert line in page_html


def test_about_facts_render_their_stored_strings(page_html):
    # cp-main.about-section.about-facts. Since LLM-COP-20 a tietoa fact is a
    # {label, value} pair, so this reads one level deeper — it still asserts
    # that every stored item reaches the page, now both halves of it.
    for fact in SEED_BY_KIND["tietoa"]["facts"]:
        assert fact["label"] in page_html
        assert fact["value"] in page_html
    assert DURATION in page_html  # the en-dash guarantee, on the served page


def test_services_render_their_stored_strings(page_html):
    # cp-main-phone.phone-palvelut.phone-services.*
    for service in SEED_BY_KIND["palvelut"]["services"]:
        assert service in page_html


# --- criteria scoped to the implementation's own elements -------------------


def test_header_brand(page_html):
    # cp-main.header.brand / cp-main-phone.phone-header.phone-brand — the
    # brand element carries the STORED site name, not a template literal, and
    # the phone avatar carries initials derived from it. Before LLM-COP-10
    # both were hard-coded in page.html and no admin could change them.
    seeded = SEED_BY_KIND["hero"]["brand"]
    brand = element_text(page_html, "span", cls="brand")
    assert brand is not None
    assert seeded in brand
    assert initials(seeded) in brand


@pytest.mark.parametrize(
    "address,label",
    [
        pytest.param("cp-main.header.nav-links-0", "Tietoa", id="cp-main.header.nav-links-0"),
        pytest.param("cp-main.header.nav-links-1", "Palvelut", id="cp-main.header.nav-links-1"),
        pytest.param("cp-main.header.nav-links-2", "Vastaanotto", id="cp-main.header.nav-links-2"),
        pytest.param("cp-main.header.nav-links-3", "Sijainti", id="cp-main.header.nav-links-3"),
    ],
)
def test_nav_links(page_html, address, label):
    nav = element_text(page_html, "nav")
    assert nav is not None
    assert label in nav, f"{address}: {label!r} not in the nav element"


def test_header_contact_button(page_html):
    # cp-main.header.header-contact-button
    header = element_text(page_html, "header")
    assert header is not None
    assert "Ota yhteyttä" in header


# (address, tag, class token, hero field) — the CTA labels are stored fields
# (app/fields.py; the panel offers them as "Painike 1"/"Painike 2"), so the
# criterion is that the element renders the STORED value. Scoped to the
# element, never the document — see the comment above DOCUMENT_CRITERIA.
#
# The first two rows resolve to THE SAME ELEMENT and are not independent phone
# coverage: the hero's contact button carries no phone-only/desktop-only class,
# so it is the contact button in both views, while the header's copy at
# app/templates/page.html:128 is desktop-only and is not the phone view's
# contact button at all. Two rows because two spec addresses land on it, per
# this file's case-id-cites-its-address convention; the assertion is one and
# the same.
CTA_RENDERS = [
    ("cp-main.hero.cta-row.cta-contact", "button", "cta-contact", "contact_label"),
    ("cp-main-phone.phone-hero.phone-contact-button", "button", "cta-contact", "contact_label"),
    ("cp-main.hero.cta-row.cta-services", "a", "cta-services", "services_label"),
]


@pytest.mark.parametrize(
    "address,tag,cls,field",
    [pytest.param(a, t, c, f, id=a) for a, t, c, f in CTA_RENDERS],
)
def test_hero_cta_carries_the_stored_label(page_html, address, tag, cls, field):
    """The hero's own element renders the stored label.

    Element-scoped on purpose, for two different reasons. For "Ota yhteyttä"
    a whole-document check cannot fail at all: the header's template literal
    at app/templates/page.html:128 satisfies it even with the hero binding
    deleted. "Lue palveluista" has no such literal, so a whole-document check
    does catch a deleted binding — but it cannot say which element rendered
    the value: swap the two bindings and both whole-document rows still pass
    while all three of these go red.
    """
    value = SEED_BY_KIND["hero"][field]
    assert value.strip(), f"{address}: seeded hero.{field} is empty"
    text = element_text(page_html, tag, cls=cls)
    assert text is not None, f"{address}: no {tag}.{cls} in the served page"
    assert value in text, f"{address}: stored hero.{field} not in {tag}.{cls}"


def test_phone_menu_glyph_present(page_html):
    # cp-main-phone.phone-header.phone-menu asserts only is-visible; a test
    # client cannot prove CSS visibility, so this proves the element exists
    # in the served document (true visibility needs a browser check).
    assert element_text(page_html, "button", cls="menu-toggle") is not None


@pytest.mark.parametrize(
    "address,expected",
    [
        pytest.param("cp-main-phone.phone-vastaanotto.phone-hours-0", DAYS, id="cp-main-phone.phone-vastaanotto.phone-hours-0"),
        pytest.param("cp-main-phone.phone-vastaanotto.phone-hours-1", HOURS, id="cp-main-phone.phone-vastaanotto.phone-hours-1"),
        pytest.param("cp-main-phone.phone-vastaanotto.phone-hours-2", "Pe", id="cp-main-phone.phone-vastaanotto.phone-hours-2"),
        pytest.param("cp-main-phone.phone-vastaanotto.phone-hours-3", "Etävastaanotto", id="cp-main-phone.phone-vastaanotto.phone-hours-3"),
    ],
)
def test_phone_hours(page_html, address, expected):
    hours = element_text(page_html, "section", cls="hours-section")
    assert hours is not None
    assert expected in hours, f"{address}: {expected!r} not in the hours section"


@pytest.mark.parametrize(
    "address,expected",
    [
        pytest.param(
            "cp-main-phone.phone-footer.phone-copyright",
            SEED_BY_KIND["hero"]["footer"],
            id="cp-main-phone.phone-footer.phone-copyright",
        ),
        pytest.param(
            "cp-main-phone.phone-footer.phone-yllapito",
            "Ylläpito",
            id="cp-main-phone.phone-footer.phone-yllapito",
        ),
    ],
)
def test_footer(page_html, address, expected):
    # The copyright line was two byte-exact criteria ("© 2026", "toiminimi")
    # against a template literal. It is now one stored field, so the case
    # asserts the WHOLE seeded footer reaches the page — strictly stronger
    # than the 6-character substring it replaces. "Ylläpito" is the admin link
    # the template owns and stays byte-exact.
    footer = element_text(page_html, "footer")
    assert footer is not None
    assert expected in footer, f"{address}: {expected!r} not in the footer"


# --- data-driven behaviour: nav and card counts follow the store ------------


def test_hiding_sijainti_removes_it_from_nav_and_body(app, client):
    before = client.get("/").get_data(as_text=True)
    assert "Sijainti" in element_text(before, "nav")
    assert 'id="sijainti"' in before

    set_section_state(app, "sijainti", "hidden")

    after = client.get("/").get_data(as_text=True)
    nav = element_text(after, "nav")
    assert "Sijainti" not in nav
    assert "Tietoa" in nav
    assert "Palvelut" in nav
    assert "Vastaanotto" in nav
    assert 'id="sijainti"' not in after


def test_service_card_count_follows_the_data(app, client):
    seeded = SEED_BY_KIND["palvelut"]["services"]
    removed, kept = seeded[1], [seeded[0], seeded[2]]
    before = client.get("/").get_data(as_text=True)
    assert removed in before

    edit_published_payload(
        app, "palvelut", lambda p: p["services"].remove(removed)
    )

    after = client.get("/").get_data(as_text=True)
    assert removed not in after
    for service in kept:
        assert service in after


@pytest.mark.parametrize(
    "url",
    [
        "/",
        "/muokkaa",
        "/muokkaa/esikatselu",
        "/muokkaa/sivu",
        "/muokkaa/osiot",
        "/yllapito/viestit",
        "/yllapito/alustus",
    ],
)
def test_no_identity_string_reaches_any_served_document(logged_in_admin, url):
    """The real standing guard for LLM-COP-10.

    The artifact's first layer is identity HARD-CODED IN TEMPLATES, unreachable
    by the admin. A guard that reads only the stored payloads cannot see that
    layer at all: put the persona back into page.html's footer and a
    seed-only check stays green. This one reads the SERVED DOCUMENT, so it
    fails on a template literal, and it covers the four admin <title>s as well
    — nothing else in the suite asserts those.
    """
    response = logged_in_admin.get(url)
    assert response.status_code == 200, f"{url} answered {response.status}"
    html = response.get_data(as_text=True)
    found = re.findall(PERSONA_PATTERN, html, re.IGNORECASE)
    assert found == [], f"{url} serves identity string(s): {sorted(set(found))}"


def test_site_chrome_is_data_the_owner_can_change(app, client):
    """LLM-COP-10's central claim, asserted without reference to the seed.

    The site name, the browser title and the footer are stored fields, so
    changing them changes the served page. This is the one case the seed
    cannot satisfy by equalling itself: the expected strings appear nowhere
    in app/, so it fails against any implementation that keeps a template
    literal. It also closes LLM-COP-7's deferral, which reported that its
    wizard could not offer these three.
    """
    def rewrite(payload):
        payload["brand"] = "Testi Yritys"
        payload["page_title"] = "Testiselaimen otsikko"
        payload["footer"] = "© 2030 Testi Yritys ja kumppanit"

    edit_published_payload(app, "hero", rewrite)

    after = client.get("/").get_data(as_text=True)
    assert "<title>Testiselaimen otsikko</title>" in after
    brand = element_text(after, "span", cls="brand")
    assert "Testi Yritys" in brand
    assert "TY" in brand  # initials recomputed from the new brand
    assert "© 2030 Testi Yritys ja kumppanit" in element_text(after, "footer")


def test_cta_labels_are_data_the_owner_can_change(app, client):
    """LLM-COP-26's central claim, asserted without reference to the seed.

    Both hero call-to-action labels are stored fields, so changing them
    changes the served page. As in the site-chrome case above, the expected
    strings appear nowhere in app/, so this fails against any implementation
    that keeps a template literal in the hero.

    The third assertion is the header's own Ota yhteyttä (page.html:128,
    criterion cp-main.header.header-contact-button), which is a TEMPLATE
    literal and must not follow the field. It is not decoration: bind that
    button to hero.contact_label and the header silently starts tracking a
    field the spec says it does not, while test_header_contact_button stays
    green because it runs on the seeded page where the field still holds the
    same words. This assertion is the only one that catches that ALONE.
    """
    def rewrite(payload):
        payload["contact_label"] = "Soita minulle heti"
        payload["services_label"] = "Katso mitä teen"

    edit_published_payload(app, "hero", rewrite)
    after = client.get("/").get_data(as_text=True)

    contact = element_text(after, "button", cls="cta-contact")
    assert contact is not None, "no button.cta-contact in the served page"
    assert "Soita minulle heti" in contact

    services = element_text(after, "a", cls="cta-services")
    assert services is not None, "no a.cta-services in the served page"
    assert "Katso mitä teen" in services

    header_cta = element_text(after, "button", cls="header-contact")
    assert header_cta is not None, "no button.header-contact in the served page"
    assert "Ota yhteyttä" in header_cta


# The five renamed kickers and the four contact values, as strings that
# appear NOWHERE in app/ — asserted, not assumed, by assert_absent_from_app.
# That is what makes the two tests below fail against an implementation that
# kept its template literal: a rename to words the template could itself have
# produced proves nothing at all.
RENAMED_LABELS = {
    "tietoa": "TYÖTAPANI PÄHKINÄNKUORESSA",
    "palvelut": "MITÄ TARJOAN ASIAKKAILLE",
    "vastaanottoajat": "MILLOIN OLEN TAVATTAVISSA",
    "yhteydenotto": "OTA ROHKEASTI YHTEYTTÄ",
    "sijainti": "MISTÄ MINUT LÖYTÄÄ",
}

CONTACT_VALUES = {
    "phone": "040 000 0000 arkisin",
    "email": "yhteys@esimerkkidomain.invalid",
    "body": "Vastaan viesteihin yleensä kahden arkipäivän kuluessa.",
    "caveat": "Kiireellisissä asioissa soita, älä kirjoita.",
}


def test_section_labels_are_data_the_owner_can_change(app, client):
    """LLM-COP-25's central claim for group 3, asserted without reference to
    the seed: all five section kickers are stored fields.

    Until this change they were template literals at page.html:61, 77, 87,
    102 and 114 with no data-field, and LLM-COP-19 proved no owner could
    rename them. So the test rewrites all five published labels to strings
    that exist nowhere in app/ and looks for them on the served page. It
    fails against any implementation that still renders a literal — including
    one that binds four of the five, which is the likelier mistake.

    ALL FIVE, not the three that had spec criteria. Nothing in the suite
    covered the yhteydenotto or sijainti kickers before, so trimming this to
    the demoted three would leave the two nobody was watching still unwatched.

    The last block is the one that must NOT follow the field, and it is not
    decoration. NAV_LABELS (app/fields.py) stays hardcoded product chrome
    after this change: an owner who renames the sijainti kicker still sees
    "Sijainti" in the nav link pointing at it. That divergence is a known,
    named consequence — and if a later unit wires the nav to section_label,
    this assertion is what says so out loud instead of letting four spec
    criteria on cp-main.header.nav-links quietly become false.
    """
    assert_absent_from_app(*RENAMED_LABELS.values())

    for kind, label in RENAMED_LABELS.items():
        edit_published_payload(
            app, kind, lambda payload, label=label: payload.update(
                section_label=label
            )
        )

    after = client.get("/").get_data(as_text=True)
    for kind, label in RENAMED_LABELS.items():
        assert label in after, kind
    # ...and every word the template used to own is gone with them. Both
    # halves are needed: without this one a build that rendered the literal
    # AND the stored value — a half-done binding that appended rather than
    # replaced — would pass on the first loop alone.
    for old in (
        "NÄIN TYÖSKENTELEN",
        "PALVELUT",
        "VASTAANOTTOAJAT",
        "YHTEYDENOTTO",
        "SIJAINTI",
    ):
        assert old not in after, old

    nav = element_text(after, "nav")
    assert nav is not None, "no <nav> in the served page"
    assert "Sijainti" in nav
    assert RENAMED_LABELS["sijainti"] not in nav


def test_the_contact_cards_four_fields_are_data_the_owner_can_change(
    app, client
):
    """LLM-COP-25's central claim for group 2: the contact card's phone,
    email, body and caveat are stored fields on yhteydenotto.

    Before this change the kind stored none of them — LLM-COP-23 reported the
    V2 addresses unsatisfied rather than faking them — so there was no way to
    publish a phone number at all. Each value is a string absent from app/,
    so a hardcoded element would fail here rather than pass by looking right.

    Each is read out of its OWN element rather than as a bare substring of
    the document, because the claim is that four separate bindings exist: a
    single element carrying all four values concatenated would satisfy a
    substring check and leave three fields uneditable in place.
    """
    assert_absent_from_app(*CONTACT_VALUES.values())

    edit_published_payload(
        app, "yhteydenotto", lambda payload: payload.update(**CONTACT_VALUES)
    )

    after = client.get("/").get_data(as_text=True)
    for field, cls in (
        ("body", "contact-body"),
        ("phone", "contact-phone"),
        ("email", "contact-email"),
        ("caveat", "contact-caveat"),
    ):
        text = element_text(after, "p", cls=cls)
        assert text is not None, f"no p.{cls} in the served page"
        assert text.strip() == CONTACT_VALUES[field], cls


def test_fact_card_count_follows_the_data(app, client):
    seeded = SEED_BY_KIND["hero"]["facts"]
    dropped, kept = seeded[2], [seeded[0], seeded[1], seeded[3]]

    def drop_third_card(payload):
        payload["facts"] = [
            fact for fact in payload["facts"] if fact["label"] != dropped["label"]
        ]

    before = client.get("/").get_data(as_text=True)
    assert dropped["value"] in before

    edit_published_payload(app, "hero", drop_third_card)

    after = client.get("/").get_data(as_text=True)
    assert dropped["label"] not in after
    assert dropped["value"] not in after
    for fact in kept:
        assert fact["label"] in after
        for line in fact["value"].split("\n"):
            assert line in after
