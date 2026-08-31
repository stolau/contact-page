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

from tests.conftest import edit_published_payload, element_text, set_section_state
from tests.test_seed import DAYS, DURATION, HOURS

# --- whole-document byte-exact contains-text criteria -----------------------

DOCUMENT_CRITERIA = [
    ("cp-main.hero.portrait-placeholder-0", "Muotokuva"),
    ("cp-main.hero.portrait-placeholder-1", "browse files"),
    ("cp-main.hero.kicker-0", "PUHETERAPEUTTI"),
    ("cp-main.hero.kicker-1", "TURKU"),
    ("cp-main.hero.kicker-2", "KELA-PALVELUNTUOTTAJA"),
    ("cp-main.hero.main-heading", "Anna Virtanen"),
    ("cp-main.hero.subtitle-0", "Puheterapeutti, FM"),
    ("cp-main.hero.subtitle-1", "toiminimi vuodesta 2018"),
    (
        "cp-main.hero.intro-0",
        (
            "Puheterapiaa lapsille, nuorille ja aikuisille: arviointi,"
            " kuntoutus ja ohjaus."
        ),
    ),
    (
        "cp-main.hero.intro-1",
        "Vastaanotto Turun keskustassa, käynnit myös etäyhteydellä.",
    ),
    ("cp-main.hero.fact-cards.fact-card-koulutus.fact-label", "KOULUTUS"),
    ("cp-main.hero.fact-cards.fact-card-koulutus.fact-value-0", "FM, logopedia"),
    ("cp-main.hero.fact-cards.fact-card-koulutus.fact-value-1", "Turun yliopisto"),
    # The remaining seeded cards (cp-main.hero.fact-cards notes' sample data).
    ("cp-main.hero.fact-cards.kokemus-label", "KOKEMUS"),
    ("cp-main.hero.fact-cards.kokemus-value", "15 vuotta kliinistä työtä"),
    ("cp-main.hero.fact-cards.erityisosaaminen-label", "ERITYISOSAAMINEN"),
    ("cp-main.hero.fact-cards.erityisosaaminen-value", "Änkytys ja afasiakuntoutus"),
    ("cp-main.hero.fact-cards.asiakkaat-label", "ASIAKKAAT"),
    ("cp-main.hero.fact-cards.asiakkaat-value", "Lapset, nuoret ja aikuiset"),
    ("cp-main.hero.cta-row.cta-contact", "Ota yhteyttä"),
    ("cp-main.hero.cta-row.cta-services", "Lue palveluista"),
    ("cp-main.hero.credentials-row-0", "Toiminimi"),
    ("cp-main.hero.credentials-row-1", "Y-tunnus 2938471-2"),
    ("cp-main.hero.credentials-row-2", "Valvira-rekisteri 1093xxx"),
    ("cp-main.hero.credentials-row-3", "Suomi"),
    ("cp-main.hero.credentials-row-4", "English"),
    ("cp-main.about-section.about-kicker", "NÄIN TYÖSKENTELEN"),
    (
        "cp-main.about-section.about-lead-0",
        (
            "Työskentelin ensin keskussairaalassa ja vuodesta 2018 omalla"
            " toiminimellä."
        ),
    ),
    ("cp-main.about-section.about-lead-1", "jakso alkaa aina arvioinnista"),
    (
        "cp-main.about-section.about-body-0",
        "Harjoitukset suunnitellaan yhdessä perheen tai asiakkaan kanssa",
    ),
    (
        "cp-main.about-section.about-body-1",
        "Tarvittaessa teen lausunnon neuvolalle, koululle tai Kelalle.",
    ),
    ("cp-main.about-section.about-facts-0", f"Käynnit {DURATION}"),
    (
        "cp-main.about-section.about-facts-1",
        "Lausunnot neuvolalle, koululle ja Kelalle",
    ),
    ("cp-main.about-section.about-facts-2", "Etäkäynnit mahdollisia"),
    ("cp-main-phone.phone-hero.phone-portrait-0", "Kuva"),
    ("cp-main-phone.phone-hero.phone-portrait-1", "browse files"),
    ("cp-main-phone.phone-hero.phone-kicker-0", "PUHETERAPEUTTI"),
    ("cp-main-phone.phone-hero.phone-kicker-1", "TURKU"),
    ("cp-main-phone.phone-hero.phone-title", "Anna Virtanen"),
    ("cp-main-phone.phone-hero.phone-subtitle-0", "Puheterapeutti, FM"),
    ("cp-main-phone.phone-hero.phone-subtitle-1", "toiminimi"),
    (
        "cp-main-phone.phone-hero.phone-intro-0",
        "Arviointi, kuntoutus ja ohjaus lapsille, nuorille ja aikuisille.",
    ),
    (
        "cp-main-phone.phone-hero.phone-intro-1",
        "Vastaanotto Turun keskustassa tai etäyhteys.",
    ),
    ("cp-main-phone.phone-hero.phone-fact-grid.phone-fact-kokemus.fact-label", "KOKEMUS"),
    ("cp-main-phone.phone-hero.phone-fact-grid.phone-fact-kokemus.fact-value", "15 vuotta"),
    ("cp-main-phone.phone-hero.phone-contact-button", "Ota yhteyttä"),
    ("cp-main-phone.phone-palvelut.phone-palvelut-label", "PALVELUT"),
    (
        "cp-main-phone.phone-palvelut.phone-services.phone-service-1.service-title",
        "Puheen ja kielen arviointi",
    ),
    # The other two seeded services (cp-main-phone.phone-services notes).
    ("cp-main-phone.phone-palvelut.phone-services.aanne", "Äännevirheiden kuntoutus"),
    ("cp-main-phone.phone-palvelut.phone-services.ankytys", "Änkytyksen kuntoutus"),
    ("cp-main-phone.phone-palvelut.phone-all-services", "Kaikki kuusi palvelua"),
    ("cp-main-phone.phone-vastaanotto.phone-vastaanotto-label", "VASTAANOTTOAJAT"),
    (
        "cp-main-phone.phone-vastaanotto.phone-booking-note-0",
        "Verkossa ei ole varausjärjestelmää",
    ),
    (
        "cp-main-phone.phone-vastaanotto.phone-booking-note-1",
        "kerro lomakkeella, mitä etsit.",
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


# --- criteria scoped to the implementation's own elements -------------------


def test_header_brand(page_html):
    # cp-main.header.brand — "Puheterapia Anna Virtanen" as the header
    # brand element's own text, not merely the <title>.
    brand = element_text(page_html, "span", cls="brand")
    assert brand is not None
    assert "Puheterapia Anna Virtanen" in brand
    # cp-main-phone.phone-header.phone-brand
    assert "Anna Virtanen" in brand


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
        pytest.param("cp-main-phone.phone-footer.phone-copyright-0", "© 2026", id="cp-main-phone.phone-footer.phone-copyright-0"),
        pytest.param("cp-main-phone.phone-footer.phone-copyright-1", "toiminimi", id="cp-main-phone.phone-footer.phone-copyright-1"),
        pytest.param("cp-main-phone.phone-footer.phone-yllapito", "Ylläpito", id="cp-main-phone.phone-footer.phone-yllapito"),
    ],
)
def test_footer(page_html, address, expected):
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
    removed = "Äännevirheiden kuntoutus"
    before = client.get("/").get_data(as_text=True)
    assert removed in before

    edit_published_payload(
        app, "palvelut", lambda p: p["services"].remove(removed)
    )

    after = client.get("/").get_data(as_text=True)
    assert removed not in after
    assert "Puheen ja kielen arviointi" in after
    assert "Änkytyksen kuntoutus" in after


def test_fact_card_count_follows_the_data(app, client):
    def drop_erityisosaaminen(payload):
        payload["facts"] = [
            fact
            for fact in payload["facts"]
            if fact["label"] != "ERITYISOSAAMINEN"
        ]

    before = client.get("/").get_data(as_text=True)
    assert "Änkytys ja afasiakuntoutus" in before

    edit_published_payload(app, "hero", drop_erityisosaaminen)

    after = client.get("/").get_data(as_text=True)
    assert "ERITYISOSAAMINEN" not in after
    assert "Änkytys ja afasiakuntoutus" not in after
    for remaining in ("KOULUTUS", "KOKEMUS", "ASIAKKAAT"):
        assert remaining in after
    for remaining_value in (
        "FM, logopedia",
        "15 vuotta kliinistä työtä",
        "Lapset, nuoret ja aikuiset",
    ):
        assert remaining_value in after
