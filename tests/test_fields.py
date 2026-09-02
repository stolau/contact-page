"""Plan step 3 — app/fields.py: the field-schema module.

Includes the mechanical schema/seed cross-check: every field key every seed
payload writes must be declared, with a type, for that kind, and the seeded
value's shape must match the declared structure. This enforces the brief's
"no field type is restated anywhere else" mechanically.
"""

import pytest

from app.fields import ANCHORS, FIELD_LABELS, FIELDS, NAV_LABELS
from app.seed import SEED_SECTIONS


def test_hero_title_cap_is_exactly_60():
    assert FIELDS["hero"]["title"]["type"] == "plain"
    assert FIELDS["hero"]["title"]["cap"] == 60


def test_rich_and_plain_declarations():
    assert FIELDS["hero"]["ingress"]["type"] == "rich"
    assert FIELDS["tietoa"]["leipäteksti"]["type"] == "rich"
    assert FIELDS["hero"]["title"]["type"] == "plain"
    assert FIELDS["hero"]["kicker"]["type"] == "plain"


def test_hero_facts_is_a_list_of_label_value_pairs():
    fact = FIELDS["hero"]["facts"]
    assert fact["type"] == "list"
    assert fact["item"] == {"label": "plain", "value": "plain"}


def test_tietoa_facts_is_a_list_of_label_value_pairs():
    fact = FIELDS["tietoa"]["facts"]
    assert fact["type"] == "list"
    assert fact["item"] == {"label": "plain", "value": "plain"}


def test_style_carries_no_field_label():
    """hero.style is declared, and deliberately has no FIELD_LABELS entry.

    That absence is the whole mechanism keeping it out of the panel form: the
    form is generated from FIELDS + FIELD_LABELS and section-form.js skips
    every field with no label, the hero.portrait precedent. The style's editor
    is the panel's Ulkoasu tab, not a text input the owner could type "banana"
    into.

    Both halves are asserted. Without the first, deleting the field would pass
    this test; without the second, giving it a label would.
    """
    assert FIELDS["hero"]["style"] == {"type": "plain"}
    assert FIELD_LABELS["hero"].get("style") is None
    # The precedent, named so the shape is recognisable rather than a
    # one-off: portrait is the other declared-but-unlabelled hero field.
    assert FIELD_LABELS["hero"].get("portrait") is None


    # LLM-COP-25 appended a THIRD unlabelled-key candidate and deliberately
    # did not take it: hero.portrait_alt is declared AND labelled, because it
    # renders as an <img> alt attribute — no text node, so no in-place
    # editor — and the generated panel form is therefore its only editor.
    # Asserted here so the two shapes stay distinguishable: portrait and
    # style have bespoke controls, portrait_alt has none.
    assert FIELD_LABELS["hero"]["portrait_alt"] == "Kuvan tekstivastine"


# The tail each kind's FIELDS entry must end with (LLM-COP-25). Named WHOLE
# rather than as "the last key", so a key inserted between them is caught
# too, and stated here rather than derived from FIELDS — a derived expectation
# would agree with the schema whatever the schema said.
#
# ORDER IS THE HAZARD, not a style preference. validate_payload rebuilds a
# payload in declaration order (app/sanitize.py) and the backfill migrations
# append with setdefault, so a key declared anywhere but last makes the
# owner's first save rewrite every stored payload of that kind and flip every
# one of its badges to Luonnos. That is what this table pins.
NEW_FIELD_TAILS = {
    "hero": ["brand", "page_title", "footer", "style", "portrait_alt"],
    "tietoa": ["nostolause", "leipäteksti", "facts", "section_label"],
    "palvelut": ["services", "more_label", "section_label"],
    "vastaanottoajat": ["days", "booking_note", "section_label"],
    "yhteydenotto": [
        "name_label",
        "email_label",
        "message_label",
        "send_label",
        "thanks",
        "section_label",
        "phone",
        "email",
        "body",
        "caveat",
    ],
    "sijainti": ["address", "section_label"],
}


@pytest.mark.parametrize("kind", sorted(NEW_FIELD_TAILS))
def test_the_new_keys_are_declared_last_in_their_kind(kind):
    tail = NEW_FIELD_TAILS[kind]
    assert list(FIELDS[kind])[-len(tail):] == tail


@pytest.mark.parametrize(
    "kind,name",
    [
        ("hero", "portrait_alt"),
        ("tietoa", "section_label"),
        ("palvelut", "section_label"),
        ("vastaanottoajat", "section_label"),
        ("yhteydenotto", "section_label"),
        ("yhteydenotto", "phone"),
        ("yhteydenotto", "email"),
        ("yhteydenotto", "body"),
        ("yhteydenotto", "caveat"),
        ("sijainti", "section_label"),
    ],
)
def test_every_new_key_is_a_labelled_plain_field(kind, name):
    """All ten are plain fields WITH a label, and the label is what makes
    them editable at all: section-form.js draws a field only if
    FIELD_LABELS names it, so a declared-but-unlabelled key is a key the
    owner has no way to set and a migration has to backfill anyway."""
    assert FIELDS[kind][name] == {"type": "plain"}
    assert FIELD_LABELS[kind][name]


def test_nav_label_map():
    assert NAV_LABELS == {
        "hero": None,
        "tietoa": "Tietoa",
        "palvelut": "Palvelut",
        "vastaanottoajat": "Vastaanotto",
        "yhteydenotto": None,
        "sijainti": "Sijainti",
    }


def test_every_kind_has_an_anchor():
    assert set(ANCHORS) == set(FIELDS)
    assert all(isinstance(a, str) and a for a in ANCHORS.values())


@pytest.mark.parametrize(
    "kind,payload", SEED_SECTIONS, ids=[kind for kind, _ in SEED_SECTIONS]
)
def test_every_seeded_key_is_declared_with_matching_shape(kind, payload):
    """The mechanical cross-check (plan step 3, strengthened criterion)."""
    assert kind in FIELDS, f"seed writes undeclared kind {kind!r}"
    schema = FIELDS[kind]
    for key, value in payload.items():
        assert key in schema, f"seed writes undeclared field {kind}.{key}"
        descriptor = schema[key]
        assert "type" in descriptor, f"{kind}.{key} declared without a type"
        kind_of_field = descriptor["type"]
        if kind_of_field in ("plain", "rich"):
            assert isinstance(value, str), (
                f"{kind}.{key} is {kind_of_field} but seed wrote "
                f"{type(value).__name__}"
            )
            if "cap" in descriptor:
                assert len(value) <= descriptor["cap"], (
                    f"{kind}.{key} seed value exceeds its cap of "
                    f"{descriptor['cap']}"
                )
        elif kind_of_field == "list":
            assert isinstance(value, list), (
                f"{kind}.{key} is a list field but seed wrote "
                f"{type(value).__name__}"
            )
            item_shape = descriptor["item"]
            for item in value:
                if item_shape == "plain":
                    assert isinstance(item, str), (
                        f"{kind}.{key} is declared list-of-plain-strings "
                        f"but seed wrote a {type(item).__name__} item"
                    )
                else:
                    assert isinstance(item, dict), (
                        f"{kind}.{key} is declared list-of-pairs but seed "
                        f"wrote a {type(item).__name__} item"
                    )
                    assert set(item) == set(item_shape), (
                        f"{kind}.{key} item keys {sorted(item)} do not "
                        f"match declared keys {sorted(item_shape)}"
                    )
                    for item_key, item_value in item.items():
                        assert item_shape[item_key] == "plain"
                        assert isinstance(item_value, str)
        else:
            pytest.fail(f"{kind}.{key} has unknown type {kind_of_field!r}")
