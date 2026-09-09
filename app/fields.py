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
        # them, and LLM-COP-30 appended hero.background and
        # hero.background_alt after THAT, so the tail of this dict is no
        # longer "the chrome keys". The price is paid in the panel — the
        # generated form draws in this order (app/static/section-form.js), so
        # Muotokuvan tekstivastine and Taustakuvan tekstivastine render as the
        # last rows of the hero panel, under Alatunniste and far from the
        # picture rows that own the pictures. That is accepted: any other
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
        # The V2 skin's full-bleed hero photograph and its alt text
        # (LLM-COP-30). A SECOND image reference: hero.portrait stays the
        # person and this one is the picture behind the hero card.
        #
        # WHICH SKIN DRAWS THE PERSON CHANGED IN LLM-COP-28, and this
        # comment used to say the tietoa band drew hero.portrait "on both
        # skins". It no longer does. V2's editorial bands each carry their
        # own picture now, so that band draws tietoa.image and hero.portrait
        # renders on V1's hero card alone — see the image/image_alt/
        # image_shape block on tietoa below, and _migration_14, which copied
        # the one into the other without clearing this one. The panel keeps
        # showing BOTH hero picture rows on both skins, deliberately: a
        # digest sitting in hero.portrait is a live reference either way
        # (app/images.py counts raw text), and that row is the only control
        # that can clear it. The V1 template
        # renders neither key, and _migration_9 backfills both from portrait
        # anyway, so an owner who switches skins finds their photograph
        # already there. background carries no FIELD_LABELS entry, the
        # hero.portrait precedent: the panel's Taustakuva row is its editor.
        "background": {"type": "plain"},
        "background_alt": {"type": "plain"},
        # The owner's two colours (USR-COP-2): the main colour paints the
        # header, the secondary one the buttons and the accent text.
        # app/palette.py holds the one table mapping the two roles onto each
        # skin's tokens, and everything derived from them.
        #
        # Each is an owner-chosen "#rrggbb" or "" meaning "skin default" —
        # never sanitised into something else, because the value reaches a
        # <style> block on the public page (app/palette.py's resolve_color).
        # Neither carries a FIELD_LABELS entry, the hero.style and
        # hero.portrait precedent: that absence is what keeps the
        # schema-driven form from drawing a text box an owner could type
        # "red" into. Their editor is the panel's Ulkoasu tab, beneath the
        # style list, where the control is an <input type="color"> that can
        # emit nothing but a valid colour.
        #
        # Appended, like every key above them, and the ordering rule's price
        # is paid again: these two read as though they belong beside style,
        # and they are last instead.
        "color_main": {"type": "plain"},
        "color_accent": {"type": "plain"},
    },
    "tietoa": {
        "nostolause": {"type": "plain"},
        "leipäteksti": {"type": "rich"},
        "facts": {"type": "list", "item": {"label": "plain", "value": "plain"}},
        # The section kicker becomes the owner's (LLM-COP-25). Appended last,
        # here and on every other kind that grew one.
        "section_label": {"type": "plain"},
        # Every editorial band gets its own picture (LLM-COP-28): the
        # reference, its alt text and how it is cropped. The same three keys,
        # in the same order, on tietoa, palvelut, vastaanottoajat and
        # sijainti — one row in the panel and one macro parameter serve all
        # four because the names are uniform.
        #
        # tietoa.image is the one the V2 portrait band draws, and since this
        # artifact it draws THIS key rather than hero.portrait: the band that
        # draws a picture is the section that stores it, the principle
        # hero.background already established. _migration_14 copies
        # hero.portrait into it once, so an upgraded V2 install keeps the
        # picture it was showing; hero.portrait is not cleared, because V1's
        # hero card still draws it.
        #
        # Appended, by the ordering rule the hero states above — a mid-dict
        # key rewrites every stored tietoa payload on the owner's first save
        # and flips its badge. The price is paid in the panel again: the
        # generated form draws in this order, so Kuvan tekstivastine renders
        # as the LAST row of each of these four panels, under Osion otsikko
        # and away from the picture row that owns the picture.
        #
        # image and image_shape carry no FIELD_LABELS entry, the hero.portrait
        # and hero.style precedent: image names an image slot rather than
        # text, and image_shape is a constrained vocabulary app/shapes.py
        # resolves — a text box an owner can type "pyöreä" into is exactly the
        # value that resolver would then have to refuse. Their editors are the
        # panel's own Kuva and Kuvan muoto rows. image_alt IS labelled, the
        # hero.portrait_alt precedent: it renders as an <img>'s alt attribute,
        # so there is nothing on the page for the in-place editor to make
        # contenteditable and the generated form is its only editor.
        "image": {"type": "plain"},
        "image_alt": {"type": "plain"},
        "image_shape": {"type": "plain"},
    },
    "palvelut": {
        "services": {"type": "list", "item": "plain"},
        "more_label": {"type": "plain"},
        "section_label": {"type": "plain"},
        # The band's own picture (LLM-COP-28) — see tietoa above for the
        # whole reasoning; these three are that kind's three, appended by the
        # same rule. Backfilled with "" rather than a copy: this band drew no
        # picture before the upgrade, so "" is the value that reproduces it.
        "image": {"type": "plain"},
        "image_alt": {"type": "plain"},
        "image_shape": {"type": "plain"},
    },
    "vastaanottoajat": {
        "days": {"type": "list", "item": {"label": "plain", "hours": "plain"}},
        "booking_note": {"type": "plain"},
        "section_label": {"type": "plain"},
        # The band's own picture (LLM-COP-28) — see tietoa.
        "image": {"type": "plain"},
        "image_alt": {"type": "plain"},
        "image_shape": {"type": "plain"},
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
        # USR-COP-4: the availability notice — a line the owner writes and
        # can switch OFF WITHOUT LOSING IT. Appended last, by the rule the
        # hero states above: validate_payload rebuilds a payload in
        # declaration order, so a mid-list key would rewrite every stored
        # yhteydenotto payload on the owner's first save and flip its badge.
        #
        # notice_on is a FLAG, not content: "on" means shown and anything
        # else means not (app/notice.py resolves it, and never raises on a
        # value it does not know). It is deliberately absent from
        # FIELD_LABELS below — the first unlabelled key outside the hero —
        # so the schema-driven builder cannot draw it. A text box an owner
        # can type "kyllä" into is exactly the value the resolver would then
        # have to refuse; its editor is the panel's own Ilmoitus row.
        "notice_text": {"type": "plain"},
        "notice_on": {"type": "plain"},
    },
    "sijainti": {
        "address": {"type": "plain"},
        "section_label": {"type": "plain"},
        # The band's own picture (LLM-COP-28) — see tietoa.
        "image": {"type": "plain"},
        "image_alt": {"type": "plain"},
        "image_shape": {"type": "plain"},
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
        # Unlike hero.portrait, hero.background and hero.style, these two ARE
        # labelled: each renders as an <img>'s alt attribute, so there is
        # nothing on the page for the in-place editor to make contenteditable
        # and the generated form is their only editor. "Muotokuvan", not
        # "Kuvan" (LLM-COP-30): there are two pictures now, and a row called
        # "the image's alt text" beside "Taustakuvan tekstivastine" would
        # leave the owner guessing which image the first one meant.
        "portrait_alt": "Muotokuvan tekstivastine",
        "background_alt": "Taustakuvan tekstivastine",
    },
    "tietoa": {
        "nostolause": "Nostolause",
        "leipäteksti": "Leipäteksti",
        "facts": "Faktat",
        "facts.label": "Otsikko",
        "facts.value": "Teksti",
        "section_label": "Osion otsikko",
        # The section picture's alt text (LLM-COP-28). Labelled, unlike the
        # image and image_shape declared beside it in FIELDS, for
        # hero.portrait_alt's reason: it renders as an <img>'s alt attribute,
        # so there is nothing on the page for the in-place editor to make
        # contenteditable and the generated form is its only editor.
        # "Kuvan", not "Muotokuvan": each of these four kinds has exactly one
        # picture, so there is nothing to tell apart the way the hero's two
        # rows have to be. The same entry, with the same reason, on all four
        # kinds that grew a picture.
        "image_alt": "Kuvan tekstivastine",
    },
    "palvelut": {
        "services": "Palvelut",
        "more_label": "Linkkiteksti",
        "section_label": "Osion otsikko",
        "image_alt": "Kuvan tekstivastine",
    },
    "vastaanottoajat": {
        "days": "Vastaanottoajat",
        "days.label": "Päivät",
        "days.hours": "Ajat",
        "booking_note": "Varausohje",
        "section_label": "Osion otsikko",
        "image_alt": "Kuvan tekstivastine",
    },
    "yhteydenotto": {
        "name_label": "Nimikentän otsikko",
        "email_label": "Sähköpostikentän otsikko",
        "message_label": "Viestikentän otsikko",
        # "Painike", not "Lähetä-painike" (USR-COP-4): USR-COP-1 deleted the
        # on-page form and this button now OPENS THE DIALOG, so a panel row
        # calling it a send button tells the owner they are editing
        # behaviour it no longer has. Named the way hero.contact_label and
        # hero.services_label are named — by what it is, a button.
        "send_label": "Painike",
        "thanks": "Kiitosviesti",
        "section_label": "Osion otsikko",
        "phone": "Puhelinnumero",
        "email": "Sähköpostiosoite",
        "body": "Esittelyteksti",
        "caveat": "Huomautus",
        # Labelled, so the generated form draws it — last, because it is
        # declared last. Its flag, notice_on, is NOT labelled: see FIELDS.
        "notice_text": "Ilmoitusteksti",
    },
    "sijainti": {
        "address": "Osoite",
        "section_label": "Osion otsikko",
        "image_alt": "Kuvan tekstivastine",
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
