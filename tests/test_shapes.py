"""How a section's own picture is cropped (LLM-COP-28) — app/shapes.py
alone, as a pure function.

Shaped after tests/test_notice.py and tests/test_style_selection.py's
test_template_for_resolves_every_input, because this module guards the same
failure. resolve_shape's answer goes into a class attribute on the public
page, so anything it can raise on is a 500 for every visitor rather than a
missing class.

WHAT THE isinstance GUARD ACTUALLY BUYS HERE, stated accurately, because the
obvious sentence is wrong and this file is where that matters. app/styles.py
says of its own guard that "`in` on a dict HASHES its operand", and there
that is exactly right: STYLE_TEMPLATES is a dict, and `{} in STYLE_TEMPLATES`
raises TypeError. SHAPES is a TUPLE. Membership on a tuple is a linear
equality scan, not a hash lookup, so `{} in SHAPES` and `[] in SHAPES` answer
False politely and raise nothing — MEASURED, not assumed. Dropping the
isinstance from resolve_shape would therefore not change the answer for any
plain JSON value a store can hold.

    (An earlier draft of app/shapes.py's docstring repeated app/styles.py's
    sentence verbatim, tuple and all, and the claim is false of a tuple.
    That docstring now says so itself and names the tuple-vs-dict
    difference; this file measures it rather than restating it, so the two
    cannot drift back apart.)

So the guard is load-bearing for two things, and both are tested:

  * THE REFACTOR. `SHAPES = {"circle", "square"}` — a set, one character's
    difference, and the shape a person reaches for when they want a lookup
    rather than a scan — makes `{} in SHAPES` raise TypeError, which is
    precisely the 500 resolve_style's guard exists to prevent. So does
    keying the vocabulary off a dict, which is how the sibling module one
    file over is written. The wrongly-typed table below is what stands
    between that edit and the public page.
  * A VALUE WHOSE __eq__ RAISES. A linear scan calls == on every candidate,
    so an operand that refuses to be compared takes the whole page down.
    Jinja's StrictUndefined is exactly that object and it is one template
    configuration away, which is why it has a test of its own below.

THE JINJA Undefined CASE IS NOT DECORATIVE either. page_v2.html hands this
filter `p.image_shape` for whichever band it is drawing, and Jinja answers
Undefined for a payload that has no such key — a pre-migration row or a
hand-written one. NOT a kind that declares no picture: the filter lives
inside portrait_slot, and only tietoa and the three prose bands call that
macro, all of which declare the field. The default Undefined compares
False and survives the scan; StrictUndefined does not.
app/images.py's image_url carries the same guard for the same family of
reasons (tests/test_images.py pins it there).

Nothing about the PAGE is asserted here — which element, which class, which
skin, which band. That belongs to tests/test_page_v2.py; this file owns the
decision, not the rendering of it.
"""

import pytest

from app.shapes import DEFAULT_SHAPE, SHAPE_CHOICES, SHAPES, resolve_shape

# --- the two values ---------------------------------------------------------


def test_there_are_exactly_two_shapes_and_the_default_is_one_of_them():
    """The seam the whole resolution rides on, stated once.

    A default that is not in SHAPES would make resolve_shape answer a value
    it does not itself recognise — the page would draw a class no stylesheet
    has a rule for, silently. And SHAPES growing a third member without a CSS
    rule to draw it is the same defect one step earlier, which is why the set
    is written out here rather than derived.
    """
    assert SHAPES == ("circle", "square")
    assert DEFAULT_SHAPE == "circle"
    assert DEFAULT_SHAPE in SHAPES


def test_the_offered_choices_are_the_shapes_that_render():
    """SHAPE_CHOICES is what the panel's Kuvan muoto row draws, and every
    value it offers must be one the renderer can resolve.

    Two constants rather than one, the STYLE_CHOICES arrangement: what the
    renderer accepts and what the owner is offered are two questions, and a
    shape may be offered only once it renders. This test is the join between
    them — an option added to the row without being added to SHAPES would
    store a value resolve_shape then throws away, and the owner would see
    their click undone on reload.

    The labels are asserted because they are the words on the two buttons and
    the designs name both of them: "Should support Square and Circle images".
    """
    assert SHAPE_CHOICES == [("circle", "Pyöreä"), ("square", "Neliö")]
    assert [value for value, _ in SHAPE_CHOICES] == list(SHAPES)


# --- the resolution ---------------------------------------------------------


def test_the_two_known_shapes_resolve_to_themselves():
    assert resolve_shape("circle") == "circle"
    assert resolve_shape("square") == "square"


def test_the_empty_string_is_the_circle():
    """"" is what app/seed.py writes and what _migration_14 backfills, so
    this is the value nearly every stored row actually holds. It resolves to
    the circle because the shipped V2 stylesheet already drew one: an
    upgraded install serves the same picture in the same shape, which is the
    rule every backfill default in app/db.py is chosen by.

    There is deliberately no third state. hero.style has one — "" means
    "unchosen", which the panel must tell apart from "v1" — and the shape has
    not: "" IS the circle and the page draws one.
    """
    assert resolve_shape("") == "circle"
    assert resolve_shape("") == DEFAULT_SHAPE


@pytest.mark.parametrize(
    "value",
    [
        "pyöreä",
        "neliö",
        "Circle",
        "SQUARE",
        "square ",
        " square",
        "round",
        "rectangle",
        "banana",
    ],
)
def test_an_unknown_string_falls_back_to_the_circle(value):
    """The near-misses are deliberate. "Circle" and "SQUARE" are what a
    case-insensitive implementation would accept; "square " and " square" are
    what a trimming one would; "pyöreä" and "neliö" are what an owner would
    type if the field were ever drawn as a text box — which is exactly why
    image_shape carries no FIELD_LABELS entry (tests/test_fields.py) and the
    panel offers two buttons instead.

    A stored value the resolver does not know is not an error state. It is
    what a rolled-back build, an API client or a later vocabulary change
    leaves behind, and the page it is on must still render.
    """
    assert resolve_shape(value) == DEFAULT_SHAPE


@pytest.mark.parametrize(
    "value",
    [None, 0, 1, 7, True, False, 1.5, b"square", {}, [], {"a": 1}, [1]],
)
def test_a_wrongly_typed_shape_resolves_and_does_not_raise(value):
    """The wrongly-typed table, and it is honest about what it catches.

    {"a": 1} and [1] are not merely unknown shapes, they are wrongly TYPED
    ones. Against SHAPES as it is written today — a tuple — they fall through
    the membership scan without raising, so these lines stay green with the
    isinstance removed. That is measured and it is stated rather than
    implied; the file docstring says why the guard is nonetheless right.

    What these lines DO catch is the vocabulary changing shape.
    test_the_guard_survives_a_set_backed_vocabulary below makes that
    concrete: turn SHAPES into a set and the dict and the list raise
    TypeError, which is a 500 on the public page. Nothing in the app writes
    such a value — validate_payload admits only str for a plain field — but
    the store is not the app's alone.

    b"square" is in here for a quieter reason: it is the one value a
    membership test answers False for while LOOKING like the right answer, so
    an implementation that decoded bytes "to be helpful" would be caught by
    the assertion rather than by a reviewer.
    """
    assert resolve_shape(value) == DEFAULT_SHAPE


def test_the_guard_survives_a_set_backed_vocabulary(monkeypatch):
    """The refactor this module's isinstance is actually insurance against.

    `SHAPES = {"circle", "square"}` is one character's difference and the
    natural edit for anyone who wants a lookup rather than a scan — and it is
    how the sibling app/styles.py is written, with a dict. Under it, `{} in
    SHAPES` raises TypeError, which reaches the visitor as a 500 on the
    public page rather than as a circle.

    Patching the module constant is not a mock standing in for behaviour: it
    is the real resolve_shape, running its real body, over the real
    alternative spelling of its own vocabulary. Delete the isinstance and
    this test goes red while every other test in the file stays green, which
    is the whole reason it is here.
    """
    from app import shapes

    monkeypatch.setattr(shapes, "SHAPES", {"circle", "square"})
    assert shapes.resolve_shape({}) == DEFAULT_SHAPE
    assert shapes.resolve_shape([]) == DEFAULT_SHAPE
    assert shapes.resolve_shape({"a": 1}) == DEFAULT_SHAPE
    assert shapes.resolve_shape([1]) == DEFAULT_SHAPE
    # And the vocabulary still works, so the test is about the guard rather
    # than about the patch.
    assert shapes.resolve_shape("square") == "square"
    assert shapes.resolve_shape("circle") == "circle"


def test_a_value_that_refuses_comparison_resolves_rather_than_raising():
    """The second thing the guard buys, and the one a tuple cannot dodge.

    A linear membership scan calls == on every candidate, so an operand whose
    __eq__ raises takes the page down whatever the container is. Jinja's
    StrictUndefined is exactly such an object — it fails every operation with
    UndefinedError by design — and it is one template configuration away from
    being what page_v2.html hands this filter for a payload missing the key.

    The hand-written class beside it is the general case: any stored value
    whose comparison misbehaves. Neither reaches resolve_shape's membership
    test at all, because isinstance rejects them first.
    """
    from jinja2 import StrictUndefined

    assert resolve_shape(StrictUndefined(name="image_shape")) == DEFAULT_SHAPE

    class Hostile:
        def __eq__(self, other):
            raise RuntimeError("this value refuses to be compared")

        __hash__ = None

    assert resolve_shape(Hostile()) == DEFAULT_SHAPE


def test_a_jinja_undefined_resolves_to_the_circle_rather_than_raising():
    """The likeliest non-string of all: a key that is simply not there.

    `p.image_shape` on a payload without the key is an Undefined, and
    Undefined is not a str — so this is the exact value that would have
    raised. Every band in page_v2.html passes its own payload's key through
    this filter, and a store between the deploy and the migration has none of
    them; so does any row a person wrote by hand. NOT blank_payload, which
    is the one caller that cannot produce an Undefined: it emits every
    declared field at "" precisely so a preview card cannot raise
    UndefinedError (app/summary.py).

    The default Undefined compares False rather than raising, so this one
    would pass without the guard; its stricter sibling would not, and that is
    asserted separately below. Both are asserted because both are reachable:
    which one a template hands over is a Jinja environment setting, not a
    property of this module.
    """
    from jinja2 import Undefined

    assert resolve_shape(Undefined(name="image_shape")) == DEFAULT_SHAPE


def test_the_answer_is_never_anything_but_one_of_the_two():
    """The contract in one line, over every input in this file at once.

    A resolver that returned its argument unchanged for some path — the
    natural shape of a bug introduced while adding a third shape later —
    passes each table above only as far as that table's own value, and fails
    this one. It is written as a sweep rather than a summary because that is
    the only way it can catch a value no individual test above thought to
    name.
    """
    values = [
        "",
        "circle",
        "square",
        "pyöreä",
        "SQUARE",
        None,
        7,
        True,
        b"square",
        {},
        [],
        {"a": 1},
        [1],
    ]
    for value in values:
        assert resolve_shape(value) in SHAPES, value
