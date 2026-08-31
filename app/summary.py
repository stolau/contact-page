"""Row summaries and blank payloads (LLM-COP-5).

The section list draws a one-line summary under every row's title. The
summaries are Finnish prose about what a section holds, so they are
written here once and only here — never in JavaScript, which would put
the same sentence in two places and let the two drift the first time a
field is added. The row fragment route re-renders them after every save,
which is how the client gets a fresh summary without knowing any of it.

Where the summary counts something it counts the payload, not the
schema: "3 palvelukorttia" is three items in the stored list, and the
singular form is the same string with the plural dropped.

Recorded divergences from the mockup's sample summaries, none of which is
an asserted criterion — the spec's own notes call them sample data:
yhteydenotto reads "Kentät ja kiitosviesti", not the sample "Kentät,
vastausaika, kiitosviesti", because no vastausaika field exists
(app/fields.py:40-46); sijainti reads "Osoite", not "Osoite ja kartta",
because the kind holds only an address (app/fields.py:47-49) and
app/templates/page.html:97-102 renders no map.
"""

from .fields import FIELDS


def blank_payload(kind):
    """The empty payload for a kind: every declared field at its zero value.

    Every field in FIELDS[kind] is present, the unlabelled ones included
    (hero.portrait, app/fields.py:25) — a payload missing a key the public
    macros dereference raises UndefinedError when the row's preview card
    renders it, and a new section's card renders before anyone has typed
    a character into it.
    """
    return {
        name: [] if descriptor["type"] == "list" else ""
        for name, descriptor in FIELDS[kind].items()
    }


def _count(count, singular, plural):
    """"3 faktaa" / "1 fakta" — the count and its Finnish noun."""
    return f"{count} {singular if count == 1 else plural}"


def _items(payload, name):
    return payload.get(name) or []


def _hero(payload):
    # The two call-to-action labels are separate fields rather than a
    # list, so the count is how many of them carry text.
    buttons = sum(
        1
        for name in ("contact_label", "services_label")
        if payload.get(name)
    )
    return (
        "Muotokuva, otsikko, ingressi, "
        + _count(buttons, "painike", "painiketta")
    )


def _tietoa(payload):
    return (
        "Nostolause, leipäteksti, "
        + _count(len(_items(payload, "facts")), "fakta", "faktaa")
    )


def _palvelut(payload):
    return _count(
        len(_items(payload, "services")), "palvelukortti", "palvelukorttia"
    )


def _vastaanottoajat(payload):
    return "Aukioloajat ja yhteydenottokehotus"


def _yhteydenotto(payload):
    return "Kentät ja kiitosviesti"


def _sijainti(payload):
    return "Osoite"


_SUMMARIES = {
    "hero": _hero,
    "tietoa": _tietoa,
    "palvelut": _palvelut,
    "vastaanottoajat": _vastaanottoajat,
    "yhteydenotto": _yhteydenotto,
    "sijainti": _sijainti,
}


def summarize(kind, payload):
    """The row summary line for one section's payload."""
    return _SUMMARIES[kind](payload)
