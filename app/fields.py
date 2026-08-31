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
    },
    "tietoa": {
        "nostolause": {"type": "plain"},
        "leipäteksti": {"type": "rich"},
        "facts": {"type": "list", "item": "plain"},
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
