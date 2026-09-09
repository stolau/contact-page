"""How a section's own picture is cropped: a circle or a square.

LLM-COP-28. Every editorial band — tietoa, palvelut, vastaanottoajat,
sijainti — carries its own image, its alt text and this: image_shape, the
owner's choice between the two crops the design names. v2-cp-section-portrait
> portrait-section > portrait says it in as many words, "Should support Square
and Circle images", and v2-cp-section-prose says the same for the bands that
grew a picture in this artifact: "Image could be Circle or Square."

TWO VALUES AND NOTHING ELSE, and the vocabulary lives here rather than in a
template's {% if %}: the shape reaches a class attribute on the public page,
so an unrecognised value must resolve rather than render. It is a `plain`
field because there is no enum in the schema (app/fields.py declares plain,
rich and list and nothing else), and it follows the precedent hero.style
(app/styles.py), hero.color_main (app/palette.py) and yhteydenotto.notice_on
(app/notice.py) already set: a plain value with a constrained vocabulary,
resolved in Python and never trusted raw.

"" IS THE CIRCLE, deliberately, and there is no non-empty default stored
anywhere. Three separate reasons this codebase has already written down:

  - _migration_14's default stays a CONSTANT, which is what keeps it
    injective and every badge where it was (app/db.py);
  - app/seed.py keeps "", so app/sectionlist.py's `json.loads(published) ==
    blank_payload(kind)` comparison is untouched — blank_payload gives "" for
    a plain field, and a real literal in the seed would quietly drop the
    BLANK_PUBLISHED refusal from a blank section's Näytä osio;
  - "" reproduces the page the install rendered a moment before the upgrade,
    because the shipped V2 circle IS border-radius: 50%
    (app/static/style-v2.css) — _migration_8's rule.

The field carries no FIELD_LABELS entry, the hero.style and
yhteydenotto.notice_on precedent, so the schema-driven form builder never
draws it: a text box an owner can type "pyöreä" into is exactly the value
resolve_shape would then have to refuse. Its editor is the panel's own Kuvan
muoto row.
"""

DEFAULT_SHAPE = "circle"

# Every shape the renderer can resolve. Anything else — "", a value some
# later build stopped writing, a JSON object an API client stored — falls
# back to DEFAULT_SHAPE; it never raises and never invents a third crop.
SHAPES = ("circle", "square")

# What the panel's Kuvan muoto row offers, as (value, label) pairs in display
# order — STYLE_CHOICES' shape (app/styles.py), and two constants for the
# same reason: what the renderer can resolve and what the owner is offered
# are two questions, and a shape may be offered only once it renders.
SHAPE_CHOICES = [
    ("circle", "Pyöreä"),
    ("square", "Neliö"),
]


def resolve_shape(value):
    """The stored shape, or DEFAULT_SHAPE when it names no known crop.

    isinstance before the membership test — but NOT for the reason
    resolve_style (app/styles.py) gives, and the difference is worth stating
    rather than copying. resolve_style tests against STYLE_TEMPLATES, a
    DICT, so `in` hashes its operand and a stored JSON object raises
    TypeError before any fallback. SHAPES is a TUPLE, so membership is a
    linear `==` scan: `{} in SHAPES` and `[] in SHAPES` answer False and
    raise nothing. Copying that sentence here would have been a true-sounding
    reason for a real guard, which is worse than no reason at all.

    The guard earns its place on two other grounds, both tested
    (tests/test_shapes.py):

      - it survives a refactor. The day SHAPES becomes a set, or gains a
        per-shape dict of CSS the way STYLE_TEMPLATES did, the membership
        test starts hashing and the TypeError resolve_style guards against
        becomes real here too. The guard is what makes that refactor safe
        rather than a 500 on the public page.
      - it survives an operand whose __eq__ raises. A linear scan CALLS
        __eq__ on the stored value, and Jinja's StrictUndefined raises from
        every operator it defines. This filter really does meet an
        Undefined: a band whose kind declares no image_shape passes one
        straight in, and page_v2.html hands section.payload.image to
        image_url on hero and yhteydenotto for the same reason.

    Nothing the app itself writes reaches either case — validate_payload
    admits only str for a plain field — but the store is not the app's
    alone, and a public page that 500s on a value it could have resolved is
    the one outcome this function exists to prevent.
    """
    return (
        value
        if isinstance(value, str) and value in SHAPES
        else DEFAULT_SHAPE
    )
