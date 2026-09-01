"""The site-wide style: which public template renders the page (LLM-COP-22).

The style is a value on the hero payload ("style"), so it follows draft and
publish exactly as section content does — no settings table, no second
publish participant, no second badge story.

STYLE_TEMPLATES and STYLE_CHOICES are deliberately two constants, not one.
STYLE_TEMPLATES is what the RENDERER can resolve; STYLE_CHOICES is what the
owner is OFFERED in the panel's Ulkoasu tab. V2 is renderable here and not
yet offered, which is what makes LLM-COP-24 an append of one tuple rather
than a change to this module.

An unknown value — "", a style dropped from a later build, anything an API
client stored — resolves to the default rather than raising: a stored style
must never be able to 500 the public page.
"""

DEFAULT_STYLE = "v1"

STYLE_TEMPLATES = {
    "v1": "page.html",
    "v2": "page_v2.html",
}

# What the Ulkoasu tab offers, as (value, label) pairs in display order.
STYLE_CHOICES = [
    ("v1", "Perus"),
]


def resolve_style(value):
    """The stored style, or DEFAULT_STYLE when it names no known template.

    isinstance before the membership test, and it is load-bearing: `in` on a
    dict hashes its operand, so a stored style that is a JSON object or array
    raises TypeError before the fallback is ever reached — which is a 500 on
    the public page, the one thing this function exists to prevent. Nothing
    in the app writes such a value (validate_payload admits only str for a
    plain field), but the store is not the app's alone.
    """
    return (
        value
        if isinstance(value, str) and value in STYLE_TEMPLATES
        else DEFAULT_STYLE
    )


def template_for(value):
    """The public template a stored style selects."""
    return STYLE_TEMPLATES[resolve_style(value)]
