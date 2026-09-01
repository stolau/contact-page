"""The field schema — the one declaration of every editable field per section kind.

Each kind maps field name -> descriptor:
  {"type": "plain"}                        one line of text, always escaped
  {"type": "plain", "cap": N}              plain with a length cap
  {"type": "rich"}                         limited-HTML text (sanitizer lands with
                                           the first untrusted write path)
  {"type": "list", "item": "plain"}        list of plain strings
  {"type": "list", "item": {k: "plain"}}   list of objects with the given plain keys

No field type is restated anywhere else; the seed and the editors read this.
"""

FIELDS = {
    "hero": {
        "kicker": {"type": "plain"},
        "title": {"type": "plain", "cap": 60},
        "subtitle": {"type": "plain"},
        "ingress": {"type": "rich"},
        "ingress_mobile": {"type": "rich"},
        "facts": {"type": "list", "item": {"label": "plain", "value": "plain"}},
        "credentials": {"type": "plain"},
        "contact_label": {"type": "plain"},
        "services_label": {"type": "plain"},
        "portrait": {"type": "plain"},
        # Site chrome (LLM-COP-10). These three are page-wide, not hero
        # content, but they are parked on the hero payload rather than a
        # settings table: the panel form, blank_payload and the bootstrap all
        # derive from FIELDS, so declaring them here is the whole feature.
        # They are appended LAST on purpose — validate_payload rebuilds a
        # payload in declaration order, so a mid-list key would reorder the
        # stored JSON on the first save and flip every badge to Luonnos.
        "brand": {"type": "plain"},
        "page_title": {"type": "plain"},
        "footer": {"type": "plain"},
    },
    "tietoa": {
        "nostolause": {"type": "plain"},
        "leipäteksti": {"type": "rich"},
        "facts": {"type": "list", "item": {"label": "plain", "value": "plain"}},
    },
    "palvelut": {
        "services": {"type": "list", "item": "plain"},
        "more_label": {"type": "plain"},
    },
    "vastaanottoajat": {
        "days": {"type": "list", "item": {"label": "plain", "hours": "plain"}},
        "booking_note": {"type": "plain"},
    },
    "yhteydenotto": {
        "name_label": {"type": "plain"},
        "email_label": {"type": "plain"},
        "message_label": {"type": "plain"},
        "send_label": {"type": "plain"},
        "thanks": {"type": "plain"},
    },
    "sijainti": {
        "address": {"type": "plain"},
    },
}

# The edit panel's Finnish names (LLM-COP-4). Section names follow the
# cp-main-edit mockup (Aloitusosio, Tietoa minusta, …); field labels the
# spec names are byte-exact (Yläotsikko, Pääotsikko, Ingressi, Painike 1,
# Painike 2), the rest are data. Dotted keys label the parts of a
# list-of-objects row. A field with no label here (hero.portrait) is not
# drawn in the generated form — the mockup's Muotokuva row stands for it —
# but its value still rides along in the whole-payload draft.
SECTION_NAMES = {
    "hero": "Aloitusosio",
    "tietoa": "Tietoa minusta",
    "palvelut": "Palvelut",
    "vastaanottoajat": "Vastaanottoajat",
    "yhteydenotto": "Yhteydenottolomake",
    "sijainti": "Sijainti",
}

FIELD_LABELS = {
    "hero": {
        "kicker": "Yläotsikko",
        "title": "Pääotsikko",
        "subtitle": "Alaotsikko",
        "ingress": "Ingressi",
        "ingress_mobile": "Ingressi (mobiili)",
        "facts": "Faktakortit",
        "facts.label": "Otsikko",
        "facts.value": "Teksti",
        "credentials": "Yritystiedot",
        "contact_label": "Painike 1",
        "services_label": "Painike 2",
        "brand": "Sivuston nimi",
        "page_title": "Selaimen otsikko",
        "footer": "Alatunniste",
    },
    "tietoa": {
        "nostolause": "Nostolause",
        "leipäteksti": "Leipäteksti",
        "facts": "Faktat",
        "facts.label": "Otsikko",
        "facts.value": "Teksti",
    },
    "palvelut": {
        "services": "Palvelut",
        "more_label": "Linkkiteksti",
    },
    "vastaanottoajat": {
        "days": "Vastaanottoajat",
        "days.label": "Päivät",
        "days.hours": "Ajat",
        "booking_note": "Varausohje",
    },
    "yhteydenotto": {
        "name_label": "Nimikentän otsikko",
        "email_label": "Sähköpostikentän otsikko",
        "message_label": "Viestikentän otsikko",
        "send_label": "Lähetä-painike",
        "thanks": "Kiitosviesti",
    },
    "sijainti": {
        "address": "Osoite",
    },
}

# Nav is generated from data: a visible section whose kind maps to a label
# gets a link; None means the section never appears in the nav.
NAV_LABELS = {
    "hero": None,
    "tietoa": "Tietoa",
    "palvelut": "Palvelut",
    "vastaanottoajat": "Vastaanotto",
    "yhteydenotto": None,
    "sijainti": "Sijainti",
}

# Anchor ids the section blocks carry and the nav links point at.
ANCHORS = {
    "hero": "hero",
    "tietoa": "tietoa",
    "palvelut": "palvelut",
    "vastaanottoajat": "vastaanotto",
    "yhteydenotto": "yhteydenotto",
    "sijainti": "sijainti",
}
