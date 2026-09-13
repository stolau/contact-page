"""The contact card's call button: does yhteydenotto.phone dial, and what?

LLM-COP-45. The card's phone row is the spec's contact-call-button, and a
button that does nothing when pressed is the worse guess — so the element
carries a `tel:` href. This module decides, once, what that href may be.

THE RULE IS "THE WHOLE FIELD MUST BE A NUMBER", and the shape of it is the
whole point: nothing is ever selected out of the field, so there is no
selection to get wrong. Either the field IS a dialable number and the href
carries exactly its digits in order, or there is no href at all.

    THE PROPERTY, which is what makes this provable rather than argued:
    every digit of the field appears in the href, in order, and none is
    dropped. The "+" is in the href if and only if the field begins with
    one.

TWO EARLIER RULES SHIPPED WRONG NUMBERS IN REVIEW and both were selection
errors, which is why the property above is worth more than any corpus. The
first concatenated every ASCII digit in the field, so "040 123 4567
(arkisin 9-16)" dialled 040123456716. The second let a word precede the
number and nothing follow it, which sounds safe and is not: the alphabet a
phone number is written in is also the alphabet opening hours, postcodes,
trunk prefixes and second numbers are written in, so "+358 (0)40 123 4567"
— the standard Finnish business-card form — became tel:+3580401234567, the
trunk zero welded into the middle of an E.164 number. A rule that discards
nothing cannot express either failure.

PARENTHESES ARE REJECTED OUTRIGHT and "+358 (0)40 123 4567" is the argument
for it. The (0) convention means "dial this zero domestically, omit it
internationally" — a CONDITIONAL digit. Any rule that accepts parentheses
must decide what it means, and the rule that decided got it wrong on the
single most likely real input this field will ever receive. A miss is
cheap: the number is still on screen to be read and dialled by hand.
Guessing a national dialling convention is not.

WHAT THAT COSTS, stated rather than discovered later. A prefix of any kind
("Soita 040 123 4567" — the design's own sample label), parentheses, a
double space, a space after the "+", a trailing separator, opening hours, a
second number: every one of them renders the owner's text with NO link on
it. That is deliberate, it is reported to the author as a delta, and it is
the trade this module is built around — a visitor tapping a wrong number is
worse than a button that does not dial.

THE HONEST RESIDUAL: a field that really is all digits and separators is
rendered faithfully even when a human would not dial it, so
"20100 040 123 4567" yields tel:201000401234567. Nothing is welded, dropped
or invented there — the product has not chosen a reading, it has rendered
the only one — and the button's visible label shows the owner exactly what
it will dial.

isinstance BEFORE the squash and before .strip(), and app/notice.py's
docstring says why in as many words: a stored value that is not a string
raises out of the first thing done to it — TypeError out of re, or a
Jinja Undefined out of a payload whose column is empty (app/sections.py:33
yields {}) — and that is a 500 on the public page, where {{ p.phone }}
renders "" today. Nothing in the app writes such a value, but the store is
not the app's alone; this project has written that lesson down in
app/notice.py, app/shapes.py and app/styles.py already.
"""

import re

# [0-9] AND NOT \d, DELIBERATELY, in the grammar as well as in the
# extraction below. A str-mode \d matches every Unicode decimal digit —
# Arabic-Indic ٠٤٠, Devanagari ०३० — so a \d grammar would ADMIT a
# mixed-script field that the [^0-9] extraction then silently strips digits
# out of, and the href would be a number the owner never typed. With [0-9]
# on both sides such a field fails the fullmatch and gets no href at all.
#
# An optional leading "+", then digit groups separated by exactly one space,
# dot or hyphen. The "+" is anchored at position 0 by the fullmatch, so a
# "+" anywhere else fails the whole string rather than being read as a
# leading one — which is what keeps "(+358) 40 123 4567" from becoming an
# href that claims an international number it is not.
_NUMBER = re.compile(r"\+?[0-9]+(?:[ .\-][0-9]+)*")

# E.164 allows at most fifteen digits; six is the shortest number worth
# offering to dial. A field outside that is not a phone number.
_MIN_DIGITS = 6
_MAX_DIGITS = 15


def tel_href(value):
    """The `tel:` URL for a stored phone field, or "" — never a raise.

    "" means the element renders with no href at all, which is the honest
    rendering of "no dialable number here": an href="tel:" on a fresh site
    would be a dead link shipped by default.
    """
    if not isinstance(value, str):
        return ""
    # Every Unicode space becomes an ASCII one before the grammar sees it,
    # so an NBSP between the groups — which a word processor inserts and no
    # owner can see — is handled rather than silently refused.
    text = "".join(" " if c.isspace() else c for c in value).strip()
    if not _NUMBER.fullmatch(text):
        return ""
    digits = re.sub(r"[^0-9]", "", text)
    if not _MIN_DIGITS <= len(digits) <= _MAX_DIGITS:
        return ""
    return "tel:" + ("+" if text.startswith("+") else "") + digits
