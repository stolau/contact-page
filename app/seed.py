"""The mockup content, byte-exact, written on first run.

Copy is taken character-for-character from the governing specs (cp-main,
cp-main-phone, cp-fact-card, cp-service-card). Mind the trap characters —
they are the spec's own, not ASCII look-alikes; copy, never retype:
en dash – in "45–90 min" and "Ma–To", thin spaces
around the en dash in "9.00 – 16.00".
"""

import json

SEED_SECTIONS = [
    (
        "hero",
        {
            "kicker": "PUHETERAPEUTTI · TURKU · KELA-PALVELUNTUOTTAJA",
            "title": "Anna Virtanen",
            "subtitle": "Puheterapeutti, FM · toiminimi vuodesta 2018",
            "ingress": (
                "Puheterapiaa lapsille, nuorille ja aikuisille: arviointi, "
                "kuntoutus ja ohjaus. Vastaanotto Turun keskustassa, "
                "käynnit myös etäyhteydellä."
            ),
            "ingress_mobile": (
                "Arviointi, kuntoutus ja ohjaus lapsille, nuorille ja "
                "aikuisille. Vastaanotto Turun keskustassa tai etäyhteys."
            ),
            "facts": [
                {"label": "KOULUTUS", "value": "FM, logopedia\nTurun yliopisto"},
                {"label": "KOKEMUS", "value": "15 vuotta kliinistä työtä"},
                {"label": "ERITYISOSAAMINEN", "value": "Änkytys ja afasiakuntoutus"},
                {"label": "ASIAKKAAT", "value": "Lapset, nuoret ja aikuiset"},
            ],
            "credentials": (
                "Toiminimi · Y-tunnus 2938471-2 · "
                "Valvira-rekisteri 1093xxx · Suomi · English"
            ),
            "contact_label": "Ota yhteyttä",
            "services_label": "Lue palveluista",
            "portrait": "",
        },
    ),
    (
        "tietoa",
        {
            "nostolause": (
                "Työskentelin ensin keskussairaalassa ja vuodesta 2018 "
                "omalla toiminimellä. Kuntoutusjakso alkaa aina arvioinnista "
                "ja yhdessä sovituista tavoitteista."
            ),
            "leipäteksti": (
                "Harjoitukset suunnitellaan yhdessä perheen tai asiakkaan "
                "kanssa ja sovitetaan osaksi arkea. Tarvittaessa teen "
                "lausunnon neuvolalle, koululle tai Kelalle."
            ),
            "facts": [
                "Käynnit 45–90 min",
                "Lausunnot neuvolalle, koululle ja Kelalle",
                "Etäkäynnit mahdollisia",
            ],
        },
    ),
    (
        "palvelut",
        {
            "services": [
                "Puheen ja kielen arviointi",
                "Äännevirheiden kuntoutus",
                "Änkytyksen kuntoutus",
            ],
            "more_label": "Kaikki kuusi palvelua",
        },
    ),
    (
        "vastaanottoajat",
        {
            "days": [
                {"label": "Ma–To", "hours": "9.00 – 16.00"},
                {"label": "Pe", "hours": "Etävastaanotto"},
            ],
            "booking_note": (
                "Verkossa ei ole varausjärjestelmää – "
                "kerro lomakkeella, mitä etsit."
            ),
        },
    ),
    (
        "yhteydenotto",
        {
            "name_label": "Nimi",
            "email_label": "Sähköposti tai puhelin",
            "message_label": "Viesti",
            "send_label": "Lähetä",
            "thanks": "Kiitos yhteydenotosta! Palaan asiaan mahdollisimman pian.",
        },
    ),
    (
        "sijainti",
        {
            "address": (
                "Vastaanotto Turun keskustassa. Tarkka osoite ja "
                "saapumisohjeet lähetetään ajanvarauksen yhteydessä."
            ),
        },
    ),
]


def seed_if_empty(conn):
    """If the sections table is empty, insert the six kinds in page order,
    all published, draft == published so every badge reads Julkaistu."""
    (count,) = conn.execute("SELECT COUNT(*) FROM sections").fetchone()
    if count:
        return
    for position, (kind, payload) in enumerate(SEED_SECTIONS, start=1):
        text = json.dumps(payload, ensure_ascii=False)
        conn.execute(
            "INSERT INTO sections (kind, position, state, draft, published,"
            " previous_published) VALUES (?, ?, 'published', ?, ?, NULL)",
            (kind, position, text, text),
        )
    conn.commit()
