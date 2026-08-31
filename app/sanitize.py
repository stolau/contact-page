"""The one sanitizer and payload validator (LLM-COP-4, LLM-COP-6).

Rich text is reduced to the allowlist strong/em/br/a: b and i normalize
to strong and em (so editor output and pasted content converge — the
round-trip guarantee direct edit needs), script and style are dropped
with their text content, every other tag is stripped with its text kept,
and the result is idempotent under a second pass. Every attribute is
dropped except a[href], and that href must pass _safe_href — an <a> whose
href does not is dropped like any other disallowed tag, its text kept.
Validation walks app.fields.FIELDS — the one schema — and rebuilds the
payload in declaration order so a no-op save stays byte-identical to the
stored draft.
"""

import html
from html.parser import HTMLParser

from .fields import FIELDS

_ALLOWED = {"strong", "em", "a"}
_NORMALIZE = {"b": "strong", "i": "em"}
_DROP_WITH_CONTENT = {"script", "style"}

# The only schemes a link may carry. A bare fragment (#...) is also
# accepted; every path-relative shape is not — see _safe_href.
_SAFE_SCHEMES = {"http", "https", "mailto", "tel"}


def _safe_href(value):
    """The emittable href for one <a>, or None to drop the tag.

    Non-string input is rejected first and before anything else touches
    it: html.parser hands the handler ('href', None) for a bare <a href>
    and omits the attribute entirely for <a>, and a sanitizer that raises
    on hostile input is a bug on the draft-write path and on the render
    path alike.

    ASCII control characters are removed before the scheme is read
    (java&Tab;script: and NUL-embedded variants arrive already decoded),
    then the value is stripped. What is returned is the *normalized*
    value — the string that was checked is the string that gets emitted,
    so the two can never diverge.

    Every path-relative form is rejected: "/x", "//evil", "/\\evil" and
    "\\evil" alike. The site is one page, so no public link needs a path,
    and rejecting the whole shape removes the browser-normalization bug
    class rather than one instance of it. Widening this to same-origin
    paths later must handle the backslash forms.
    """
    if not isinstance(value, str):
        return None
    text = "".join(ch for ch in value if ch > "\x1f" and ch != "\x7f").strip()
    if not text:
        return None
    if text.startswith("#"):
        return text
    scheme, colon, _ = text.partition(":")
    if colon and scheme.isascii() and scheme.lower() in _SAFE_SCHEMES:
        return text
    return None


class _Sanitizer(HTMLParser):
    """Emit only strong/em/br/a and escaped text; see module docstring."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out = []
        self._open = []  # allowed tags emitted and not yet closed
        self._dropping = 0  # nesting depth inside script/style

    def handle_starttag(self, tag, attrs):
        tag = _NORMALIZE.get(tag, tag)
        if tag in _DROP_WITH_CONTENT:
            self._dropping += 1
            return
        if self._dropping:
            return
        if tag == "br":
            self._out.append("<br>")
        elif tag in _ALLOWED:
            if tag == "a":
                # The one tag that keeps an attribute, and href the one
                # attribute it keeps. An unsafe or absent href drops the
                # tag and keeps its text: the tag never reaches _open, so
                # the matching </a> falls through the guard in
                # handle_endtag exactly as any disallowed tag does.
                href = _safe_href(dict(attrs).get("href"))
                if href is None:
                    return
                self._out.append(f'<a href="{html.escape(href, quote=True)}">')
            else:
                self._out.append(f"<{tag}>")
            self._open.append(tag)

    def handle_endtag(self, tag):
        tag = _NORMALIZE.get(tag, tag)
        if tag in _DROP_WITH_CONTENT:
            if self._dropping:
                self._dropping -= 1
            return
        if self._dropping or tag not in self._open:
            return
        # Close intervening tags too, so the output is always balanced.
        while self._open:
            innermost = self._open.pop()
            self._out.append(f"</{innermost}>")
            if innermost == tag:
                break

    def handle_data(self, data):
        if not self._dropping:
            self._out.append(html.escape(data, quote=False))

    def result(self):
        self.close()
        while self._open:
            self._out.append(f"</{self._open.pop()}>")
        return "".join(self._out)


def sanitize_rich(value):
    """Reduce one rich-text string to the allowlist (idempotent)."""
    parser = _Sanitizer()
    parser.feed(value)
    return parser.result()


# Validation messages are data; one string per failure shape.
_ERROR_MISSING = "kenttä puuttuu"
_ERROR_UNKNOWN = "tuntematon kenttä"
_ERROR_TEXT = "arvon on oltava tekstiä"
_ERROR_LIST = "arvon on oltava lista"
_ERROR_ITEM = "listan alkio on väärän muotoinen"


def _over_cap(cap):
    return f"enintään {cap} merkkiä"


def _validate_item(shape, item):
    """One list item against its declared shape; the clean item, or None."""
    if shape == "plain":
        return item if isinstance(item, str) else None
    if not isinstance(item, dict) or set(item) != set(shape):
        return None
    if not all(isinstance(item[key], str) for key in shape):
        return None
    # Rebuild in the declared key order — the serialization convention.
    return {key: item[key] for key in shape}


def validate_payload(kind, payload):
    """Validate payload against FIELDS[kind].

    Returns (clean, errors): errors is a field -> message dict, and clean
    is the payload rebuilt in schema declaration order with rich fields
    sanitized — or None whenever errors is non-empty. Nothing is mutated.
    """
    schema = FIELDS[kind]
    errors = {}
    clean = {}
    if not isinstance(payload, dict):
        return None, {"payload": _ERROR_UNKNOWN}
    for name in payload:
        if name not in schema:
            errors[name] = _ERROR_UNKNOWN
    for name, descriptor in schema.items():
        if name not in payload:
            errors[name] = _ERROR_MISSING
            continue
        value = payload[name]
        if descriptor["type"] == "plain":
            if not isinstance(value, str):
                errors[name] = _ERROR_TEXT
            elif "cap" in descriptor and len(value) > descriptor["cap"]:
                errors[name] = _over_cap(descriptor["cap"])
            else:
                clean[name] = value
        elif descriptor["type"] == "rich":
            if not isinstance(value, str):
                errors[name] = _ERROR_TEXT
            else:
                clean[name] = sanitize_rich(value)
        else:  # list
            if not isinstance(value, list):
                errors[name] = _ERROR_LIST
                continue
            items = [_validate_item(descriptor["item"], item) for item in value]
            if any(item is None for item in items):
                errors[name] = _ERROR_ITEM
            else:
                clean[name] = items
    if errors:
        return None, errors
    return clean, {}
