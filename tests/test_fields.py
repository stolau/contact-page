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
