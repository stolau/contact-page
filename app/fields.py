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
        # Site-wide keys (LLM-COP-10's chrome three, LLM-COP-22's style).
        # These are page-wide, not hero content, but they are parked on the
        # hero payload rather than a settings table: the panel form,
        # blank_payload and the bootstrap all derive from FIELDS, so
        # declaring them here is the whole feature.
        #
        # THE NEWEST KEY OF ANY KIND IS APPENDED LAST, IN THE ORDER THE KEYS
        # WERE INTRODUCED. Nothing is ever inserted mid-list, in this dict or
        # in any other kind's. Reason: validate_payload rebuilds a payload in
        # declaration order (app/sanitize.py), so a mid-list key rewrites
        # every stored payload of that kind on its first save and flips every
        # one of its badges to Luonnos.
        #
        # The rule is general, not a property of the site-wide keys that
        # happen to sit here: LLM-COP-25 appended hero.portrait_alt AFTER
        # them, so the tail of this dict is no longer "the chrome keys". The
        # price is paid in the panel — the generated form draws in this order
        # (app/static/section-form.js), so Kuvan tekstivastine renders as the
        # last row of the hero panel, under Alatunniste and far from the
        # Muotokuva row that owns the picture. That is accepted: any other
        # position rewrites every stored hero payload on the owner's first
        # save. A display order is a panel-layout change, never a reorder here.
        #
        # Every such key also owes: a backfill migration (_migration_4, now
        # _migration_7); an entry in tests/test_direct_edit.py's
        # EXCLUDED_SCALARS with a written reason, or a real binding in both
        # public templates; and a line in tests/test_sections.py's
        # site_chrome equality if it is surfaced as chrome. Enforcement:
        # tests/test_seed.py's tail assertion names the WHOLE tail and
        # tests/test_sections.py's dict equality names the WHOLE return
        # value, so the next key must extend both — deliberate edits, never
        # silent passes.
        "brand": {"type": "plain"},
        "page_title": {"type": "plain"},
        "footer": {"type": "plain"},
        # Which public template renders the page (app/styles.py). No
        # FIELD_LABELS entry on purpose — that is what keeps the
        # schema-driven form builder from drawing it, the hero.portrait
        # precedent; its editor is the panel's Ulkoasu tab.
        "style": {"type": "plain"},
        # The portrait's alt text (LLM-COP-25). Hero CONTENT, not site-wide
        # chrome, but appended after the chrome keys because appending is the
        # only safe position — see the ordering rule above.
        "portrait_alt": {"type": "plain"},
    },
    "tietoa": {
        "nostolause": {"type": "plain"},
        "leipäteksti": {"type": "rich"},
        "facts": {"type": "list", "item": {"label": "plain", "value": "plain"}},
        # The section kicker becomes the owner's (LLM-COP-25). Appended last,
        # here and on every other kind that grew one.
        "section_label": {"type": "plain"},
    },
    "palvelut": {
        "services": {"type": "list", "item": "plain"},
        "more_label": {"type": "plain"},
        "section_label": {"type": "plain"},
    },
    "vastaanottoajat": {
        "days": {"type": "list", "item": {"label": "plain", "hours": "plain"}},
        "booking_note": {"type": "plain"},
        "section_label": {"type": "plain"},
    },
    "yhteydenotto": {
        "name_label": {"type": "plain"},
        "email_label": {"type": "plain"},
        "message_label": {"type": "plain"},
        "send_label": {"type": "plain"},
        "thanks": {"type": "plain"},
        # LLM-COP-25: the section kicker, then the contact card's four
        # fields — the first way this product can publish a phone number.
        "section_label": {"type": "plain"},
        "phone": {"type": "plain"},
        "email": {"type": "plain"},
        "body": {"type": "plain"},
        "caveat": {"type": "plain"},
    },
    "sijainti": {
        "address": {"type": "plain"},
        "section_label": {"type": "plain"},
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
        # Unlike hero.portrait and hero.style, this one IS labelled: it
        # renders as the <img>'s alt attribute, so there is nothing on the
        # page for the in-place editor to make contenteditable and the
        # generated form is its only editor.
        "portrait_alt": "Kuvan tekstivastine",
    },
    "tietoa": {
        "nostolause": "Nostolause",
        "leipäteksti": "Leipäteksti",
        "facts": "Faktat",
        "facts.label": "Otsikko",
        "facts.value": "Teksti",
        "section_label": "Osion otsikko",
    },
    "palvelut": {
        "services": "Palvelut",
        "more_label": "Linkkiteksti",
        "section_label": "Osion otsikko",
    },
    "vastaanottoajat": {
        "days": "Vastaanottoajat",
        "days.label": "Päivät",
        "days.hours": "Ajat",
        "booking_note": "Varausohje",
        "section_label": "Osion otsikko",
    },
    "yhteydenotto": {
        "name_label": "Nimikentän otsikko",
        "email_label": "Sähköpostikentän otsikko",
        "message_label": "Viestikentän otsikko",
        "send_label": "Lähetä-painike",
        "thanks": "Kiitosviesti",
        "section_label": "Osion otsikko",
        "phone": "Puhelinnumero",
        "email": "Sähköpostiosoite",
        "body": "Esittelyteksti",
        "caveat": "Huomautus",
    },
    "sijainti": {
        "address": "Osoite",
        "section_label": "Osion otsikko",
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
