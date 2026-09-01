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

import pytest

from app.sections import initials
from app.seed import SEED_SECTIONS
from tests.conftest import edit_published_payload, element_text, set_section_state
from tests.test_seed import DAYS, DURATION, HOURS

SEED_BY_KIND = dict(SEED_SECTIONS)

# --- whole-document byte-exact contains-text criteria -----------------------
#
# LLM-COP-10 split the old 55-row table in two.
#
# Byte-exact below: strings the TEMPLATE owns, which no admin can edit, plus
# the brief's explicit chrome carve-out ("Ota yhteyttä", "Lue palveluista") —
# those two are payload fields, but the artifact names them as the product's
# promise rather than the persona, so they stay pinned. That tension is
# recorded in the spec delta, not resolved here.
#
# Everything else moved to SEEDED_RENDERS below: 36 criteria that pinned a
# value the owner can change through the admin panel. Pinning those is the
# defect this artifact was filed against — a data value promoted to a promise.
# They now assert that the STORED value reaches the page, never what it says.

DOCUMENT_CRITERIA = [
    ("cp-main.hero.portrait-placeholder-0", "Muotokuva"),
    ("cp-main.hero.portrait-placeholder-1", "browse files"),
    ("cp-main.hero.cta-row.cta-contact", "Ota yhteyttä"),
    ("cp-main.hero.cta-row.cta-services", "Lue palveluista"),
    ("cp-main.about-section.about-kicker", "NÄIN TYÖSKENTELEN"),
    ("cp-main-phone.phone-hero.phone-portrait-0", "Kuva"),
    ("cp-main-phone.phone-hero.phone-portrait-1", "browse files"),
    ("cp-main-phone.phone-hero.phone-contact-button", "Ota yhteyttä"),
    ("cp-main-phone.phone-palvelut.phone-palvelut-label", "PALVELUT"),
    ("cp-main-phone.phone-vastaanotto.phone-vastaanotto-label", "VASTAANOTTOAJAT"),
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
    # cp-main.about-section.about-facts-0/-1/-2
    for fact in SEED_BY_KIND["tietoa"]["facts"]:
        assert fact in page_html
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
