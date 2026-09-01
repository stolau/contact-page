"""The shipped placeholder content, written on first run.

This is a generic contact page: every word below is the owner's to replace
from the admin panel. The copy is deliberately unfilled-looking so that an
owner who deploys and does nothing ships a template, not somebody's
identity. It names no person, no place and no register.

The vastaanottoajat and yhteydenotto blocks are generic already and are kept
byte-exact. Mind the trap characters —
they are the spec's own, not ASCII look-alikes; copy, never retype:
en dash – in "45–90 min" and "Ma–To", thin spaces
around the en dash in "9.00 – 16.00".
"""

import json

SEED_SECTIONS = [
    (
        "hero",
        {
            "kicker": "AMMATTINIMIKE · PAIKKAKUNTA · LISÄTIETO",
            "title": "Nimi tähän",
            "subtitle": "Ammattinimike · lisätieto",
            "ingress": (
                "Kerro tässä lyhyesti, kenelle palvelusi on ja mitä teet. "
                "Korvaa tämä teksti omalla esittelylläsi."
            ),
            "ingress_mobile": (
                "Kerro lyhyesti, kenelle palvelusi on ja mitä teet."
            ),
            "facts": [
                {"label": "KOULUTUS", "value": "Täydennä koulutus\nja tutkinnot"},
                {"label": "KOKEMUS", "value": "Täydennä työkokemus"},
                {"label": "OSAAMINEN", "value": "Täydennä osaamisalueet"},
                {"label": "ASIAKKAAT", "value": "Täydennä asiakasryhmät"},
            ],
            "credentials": (
                "Yritysmuoto · Y-tunnus · Rekisteritiedot · Suomi · English"
            ),
            "contact_label": "Ota yhteyttä",
            "services_label": "Lue palveluista",
            "portrait": "",
            "brand": "Yrityksen nimi",
            "page_title": "Yrityksen nimi",
            "footer": "© 2026 Yrityksen nimi",
        },
    ),
    (
        "tietoa",
        {
            "nostolause": (
                "Kirjoita tähän lyhyt esittely: kuka olet, mitä teet ja "
                "miten työskentelet."
            ),
            "leipäteksti": (
                "Kerro tarkemmin palveluistasi ja siitä, miten yhteistyö "
                "etenee. Korvaa tämä esimerkkiteksti omalla sisällölläsi."
            ),
            "facts": [
                "Tapaamiset 45–90 min",
                "Lisätieto tähän",
                "Toinen lisätieto tähän",
            ],
        },
    ),
    (
        "palvelut",
        {
            "services": [
                "Ensimmäinen palvelu",
                "Toinen palvelu",
                "Kolmas palvelu",
            ],
            # Was "Kaikki kuusi palvelua" — a hard-coded count of six against
            # a seed that ships three. Same defect class as LLM-COP-8.
            "more_label": "Kaikki palvelut",
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
            "address": "Lisää käyntiosoite ja saapumisohjeet tähän.",
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
