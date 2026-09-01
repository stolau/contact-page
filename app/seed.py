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

Since LLM-COP-20 reshaped tietoa.facts into {label, value} pairs, the en-dash
anchor lives in tietoa.facts[3]["value"], which is exactly "45–90 min" rather
than embedded in a longer string — the split moved the caption "Tapaamiset"
into the label beside it, so the trap character is now the whole value.
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
            # No style chosen (LLM-COP-22). "" rather than "v1": blank_payload
            # gives "" for every plain field and app/sectionlist.py compares a
            # published payload to blank_payload(kind) BY VALUE, so seeding
            # "v1" would quietly drop the BLANK_PUBLISHED refusal from a blank
            # hero's Näytä osio. app/styles.py resolves "" to the default.
            "style": "",
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
            # LLM-COP-20. The labels are the mockup's three (Koulutus,
            # Kokemus, Osaaminen); the fourth pair is the shipped
            # "Tapaamiset 45–90 min" split at the seam it always had, which
            # is this reshape applied to existing content rather than a
            # fourth fact invented for it.
            # Both these labels and hero.facts' above name the same three
            # things, but they must never collide as STRINGS. Both blocks
            # render on the same page, and test_fact_card_count_follows_the_data
            # drops one hero card and asserts that card's label and value are
            # absent from the WHOLE page — so a tietoa copy of either would
            # make that test FAIL, not merely weaken it. Two separate things
            # keep them apart, and both are load-bearing:
            #   - the VALUES are worded differently from hero's "Täydennä
            #     koulutus…/työkokemus/osaamisalueet" (no substring overlap
            #     in either direction);
            #   - the LABELS differ by case — hero's are uppercase
            #     (KOULUTUS), these are title-case (Koulutus), because the
            #     public fact cards shout and the Tietoa fact line does not.
            # Keep them distinct on both counts.
            "facts": [
                {"label": "Koulutus", "value": "Täydennä tutkintosi"},
                {"label": "Kokemus", "value": "Täydennä työhistoriasi"},
                {"label": "Osaaminen", "value": "Täydennä erityisosaamisesi"},
                {"label": "Tapaamiset", "value": "45–90 min"},
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
