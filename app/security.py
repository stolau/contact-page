"""The security headers HTML responses carry, and where they come from.

LLM-COP-35 item 2. Until this module there were none. app/images.py served
GET /kuvat/<digest> with nosniff and a strict "default-src 'none'; sandbox",
and every HTML route sent nothing at all; README.md said so out loud. The
factory registers one after_request (app/__init__.py) that puts the policy
built here on every text/html response, and HEADERS_EVERYWHERE on every
response whatever its type.

**Why this CSP exists at all.** The admin inbox renders visitor-supplied text
(app/templates/inbox.html). Jinja autoescaping is the primary control and the
sanitizer is the second (app/sanitize.py); this is the third, and it is the
one that still holds the day either of the first two has a hole.

**script-src carries HASHES — not a nonce, and never 'unsafe-inline'.**
'unsafe-inline' permits exactly the attack the paragraph above names, so for
scripts it was never on the table. A nonce is the usual answer and costs more
here than it buys: there is no base template ({% extends %} appears nowhere
in app/templates/), six top-level documents each carry their own
<!doctype html>, and every inline <script> and <style> would need hand-edited
markup — markup four tests pin as a full literal (tests/test_edit.py,
tests/test_direct_edit.py, tests/test_sectionlist.py) and a fifth matches by
prefix (tests/test_messages.py). Worse, a FORGOTTEN nonce fails silently: the
page renders, every server-side test stays green, and the feature is dead in a
browser only. Hashes derived from the templates invert that. They edit no
markup, they cannot go stale — editing an inline script changes its own hash —
and a NEW inline script fails loudly in CI, because its hash is missing from
the Content-Security-Policy the very same response carries
(tests/test_security_headers.py).

The three blessed scripts hold no {{ }}, {% %} or {# #} at all, which is what
makes a source-derived hash equal to the rendered one. The four
type="application/json" bootstraps do interpolate, and they are deliberately
NOT hashed: a browser never executes them, so script-src never checks them.

**style-src keeps 'unsafe-inline', deliberately.** Hashing the two inline
<style> blocks (app/templates/page.html, app/templates/page_v2.html) is
impossible by construction: they hold palette_css()'s output, which varies
with the owner's chosen colours, so no fixed hash can ever match. The residual
risk is bounded by facts elsewhere in the tree — app/sanitize.py drops <style>
with its content and every attribute except a[href], so owner content cannot
carry CSS; palette_css's output alphabet is [-a-z0-9:;#{}] by construction
with no < and no quote (app/palette.py), and both templates emit it WITHOUT
|safe; and the classic payoff, background: url(https://evil/?leak), is already
dead under default-src and img-src 'self'. What the grant does not cover is
style-src-attr 'none', which narrows it to <style> ELEMENTS: an injected
style="..." attribute is still refused. That directive is free — there is no
inline style attribute anywhere in app/templates/ — and it is not decorative:
setAttribute('style', ...) really is blocked under it in real Chrome, while
the CSSOM property writes direct edit actually makes
(app/static/direct-edit.js) are not. What is given up is that an attacker who
already has an HTML-injection hole could inject a <style> element and reskin
or reposition the page. Real, much smaller than script execution, and stated
rather than hidden.

**frame-ancestors is 'self', never 'none'.** This product frames itself:
app/templates/edit.html renders the draft preview in a same-origin <iframe>
that app/edit.py serves. 'none' — or X-Frame-Options: DENY — would black out
the editor preview. X-Frame-Options: SAMEORIGIN is emitted alongside as a
legacy echo, because an external scanner looks for that header by name; where
both are present the browser obeys the CSP, and the single place the two could
disagree is SAMEORIGIN's historically inconsistent ancestor semantics
(immediate parent vs. top-level document). This product frames at depth 1,
same-origin — the one case every implementation agrees on — so the echo costs
nothing and cannot contradict frame-ancestors 'self'.

**No upgrade-insecure-requests, and that is a decision rather than an
oversight.** The site may be served over plain HTTP, so the directive would
break every subresource on such a deployment. Rewriting a URL is a claim about
one DOCUMENT's subresources, and nothing here knows they are all reachable
over TLS. Over plain HTTP a man-in-the-middle can strip any of these headers
before the browser sees them, which is the ceiling on this whole module: all
of it is defence in depth BEHIND TLS and never a substitute for it.

**HSTS has arrived, gated (LLM-COP-35 item 1).** https_only() below answers
whether this deployment is served over TLS and strict_transport_security()
answers the header value; app/__init__.py's after_request sends it when the
first says so. Unset — the default — the three set_cookie calls in the login
flow emit exactly the bytes they emitted before this change and no response
carries the header, so plain-HTTP development is untouched.

**Told, never derived.** https_only() reads the HTTPS_ONLY environment
variable and nothing about the request. Three grounds, each checkable in this
tree. First, there is no scheme-trust here to extend: no code anywhere reads
ProxyFix, request.is_secure, wsgi.url_scheme or X-Forwarded-Proto — grep app/
finds those names only in this docstring, and tests/ only in
tests/test_transport.py, which sends them precisely in order to prove they
are ignored. So deriving the scheme would not read
something the app already knows — it would CREATE a trust relationship, in
the very change whose job is to tighten the transport story. Second, derivation would silently never
fire where it is needed: request.is_secure reads wsgi.url_scheme, which is
http on exactly the deployment README.md §4 prescribes, where a reverse proxy
terminates TLS and forwards plain HTTP to 127.0.0.1:8000. The operator does
everything right, the flag never goes on, and nothing anywhere says so — the
same silent shape as the forgotten nonce named above. Third, making derivation
fire means believing X-Forwarded-Proto, and this repository has already
refused that trade in writing: with TRUSTED_PROXY unset, app/auth.py ignores
X-Forwarded-For entirely so a spoofed header cannot mint a fresh window. Same
header family, same forgeability, same remedy — an operator's explicit say-so.

**Read per request, not once at factory time**, for the reasons app/auth.py
already gives for TRUSTED_PROXY: a deployment can be flipped without a
restart, a test can set it around a single call, and both consumers — the five
cookie calls and the after_request — already run per request, so there is
nothing to cache. os.environ.get is a dict lookup.

**Every response, not only text/html.** HSTS is a claim about the CONNECTION
rather than about a document (RFC 6797 §7.1 has the agent process it on any
HTTPS response), so a visitor whose first contact is GET /kuvat/<digest>, a
stylesheet or POST /api/messages must be pinned too. It sits beside
HEADERS_EVERYWHERE and deliberately not inside it: that dict is unconditional
and this value is not.

**max-age is one DAY, and there is no includeSubDomains and no preload.** The
arguments are at HSTS_MAX_AGE and strict_transport_security below, next to the
values they govern.

**Computed ONCE, at factory time.** inline_script_hashes walks the template
directory, and doing that per response would put a directory walk and three
file reads on every request. The price is a dev-mode caveat, stated rather
than hidden: under `flask --app app run --debug` an edit to one of the three
inline scripts needs a server RESTART before its hash matches, or the browser
refuses to run the edited script. The reloader restarts on a .py change, not
on a .html one. What keeps that from reaching a release is the
rendered-coverage guard in tests/test_security_headers.py, which hashes the
scripts in the response BODY and requires each to appear in that same
response's Content-Security-Policy.
"""

import base64
import hashlib
import os
from html.parser import HTMLParser

# The MIME type essences the HTML spec calls a JavaScript type, plus "module"
# and the empty string, which that spec treats as classic script. Quoted in
# full rather than narrowed to the one type this tree actually uses (none —
# all three blessed scripts carry no type at all), and the DIRECTION of the
# error is the reason: classifying a JavaScript type as non-JavaScript drops a
# hash the policy needs and breaks the product in a browser only, where no
# server-side test can see it. The opposite mistake merely folds a
# never-executed blob into script-src. The list is long because getting it
# wrong is not cheap.
_JAVASCRIPT_TYPES = frozenset(
    {
        "",
        "module",
        "application/ecmascript",
        "application/javascript",
        "application/x-ecmascript",
        "application/x-javascript",
        "text/ecmascript",
        "text/javascript",
        "text/javascript1.0",
        "text/javascript1.1",
        "text/javascript1.2",
        "text/javascript1.3",
        "text/javascript1.4",
        "text/javascript1.5",
        "text/jscript",
        "text/livescript",
        "text/x-ecmascript",
        "text/x-javascript",
    }
)

# On EVERY response, document or not. nosniff because a sniffed JSON or
# fragment response is a real hazard and the value is not a document-only
# claim; app/images.py already sets this byte-identically on GET
# /kuvat/<digest>, so the after_request and that line can never disagree and
# neither has to know about the other. no-referrer because nothing in the app
# reads Referer or document.referrer (nothing in app/ mentions either), there
# are no external subresources at all, and the only outbound navigations are
# owner-authored <a href> — while the weaker strict-origin-when-cross-origin
# would hand the admin path /yllapito/viestit to every site the owner links to.
HEADERS_EVERYWHERE = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}

# Strict-Transport-Security's max-age, in seconds: one DAY, not the year the
# examples reach for. The failure this number governs is a certificate the
# operator later cannot renew — HSTS is remembered CLIENT-side and there is no
# server-side remedy, so a year-long pin turns a lapsed certificate into a
# year-long outage for every returning visitor. One day still closes the
# sslstrip window for anyone who comes back, which is the whole point of the
# header, and it heals a botched TLS setup within a day. README.md tells the
# operator to raise it once a renewal cycle has survived, which is the only
# honest order to do those two things in.
HSTS_MAX_AGE = 86400


def https_only():
    """Whether this deployment is served over TLS — because it was TOLD so.

    Reads the HTTPS_ONLY environment variable and nothing else: never the
    request, never a header. The argument for that, and for reading it on
    every call rather than once at factory time, is in the module docstring.

    Empty is unset, the same rule _data_path states in app/__init__.py. An
    EnvironmentFile line left as `HTTPS_ONLY=` means the operator has not set
    it, not that they set it to the empty string.
    """
    return bool(os.environ.get("HTTPS_ONLY"))


def strict_transport_security():
    """The Strict-Transport-Security value, whole.

    max-age and nothing else. No includeSubDomains: it would apply to
    *.<this host>, which does not exist, so it protects nothing real; it
    would break a later dev.<this host> served over HTTP; and if this app is
    ever deployed at the apex of a shared parent rather than on a subdomain
    of it, the directive reaches sibling hosts this app does not own and
    cannot un-break. A whole-domain claim belongs at the proxy, where
    whoever owns the whole domain is standing. No preload either: it is a
    one-way public commitment to a browser vendor's list that nobody here
    has asked for, and it requires includeSubDomains plus a max-age of at
    least a year — both of which were just declined.

    A function rather than a constant string so a test can pin the value
    without a literal, and so the two decisions above have somewhere to live.
    """
    return f"max-age={HSTS_MAX_AGE}"


class _InlineScripts(HTMLParser):
    """Collects (element_id, body) for each executable inline <script>.

    convert_charrefs is turned OFF explicitly. It would be inert anyway —
    HTMLParser puts <script> into CDATA mode and guards charref conversion
    with `not self.cdata_elem` — but what gets hashed has to be the text the
    browser hashes, and "inert anyway" is a claim about a dependency's
    internals. Off, it is a claim about nothing.
    """

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.scripts = []
        self._id = None
        self._body = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        values = dict(attrs)
        # A src= script is fetched rather than inlined: script-src 'self'
        # covers it and it has no body to hash. A type the browser will not
        # execute is never checked against script-src at all — which is what
        # keeps the four type="application/json" bootstraps out, and they
        # MUST stay out: every one of them interpolates, so a hash taken
        # from the template source could not match the rendered response.
        if "src" in values:
            return
        kind = values.get("type")
        if kind is not None and kind.strip().lower() not in _JAVASCRIPT_TYPES:
            return
        self._id = values.get("id")
        self._body = []

    def handle_data(self, data):
        # A script body arrives in one piece for a whole-file feed(), but
        # accumulating costs nothing and is true whatever the chunking.
        if self._body is not None:
            self._body.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._body is not None:
            self.scripts.append((self._id, "".join(self._body)))
            self._id = None
            self._body = None


def _sha256_b64(body):
    """One script body as CSP spells its hash: base64 of the SHA-256.

    UTF-8 because that is the encoding the response is served in and the
    bytes the browser hashes. CSP hashes the element's text content as
    served, so this has to be the body EXACTLY — no strip(), no newline
    normalization. There is no CRLF anywhere in app/templates/ and the app
    sets no Jinja whitespace options (app/__init__.py touches only
    |tojson's key order), so the served bytes are the source bytes.
    """
    return base64.b64encode(
        hashlib.sha256(body.encode("utf-8")).digest()
    ).decode("ascii")


def inline_script_hashes(template_dir):
    """Every executable inline script in the templates, in a stable order.

    Returns (template_name, element_id, digest) triples — the name and the id
    so a test can pin WHICH scripts are blessed without ever pinning a hash
    literal, which is the whole point of deriving them. Sorted by template
    name and then document order within the file, so the policy string this
    feeds is byte-stable across runs and across filesystems.

    Flat, not recursive: app/templates/ has no subdirectories. If it ever
    grows one, what turns the omission red is the rendered-coverage guard in
    tests/test_security_headers.py, which hashes what the RESPONSE actually
    contains rather than what this walk happened to find.
    """
    found = []
    for name in sorted(os.listdir(template_dir)):
        if not name.endswith(".html"):
            continue
        with open(
            os.path.join(template_dir, name), encoding="utf-8"
        ) as handle:
            source = handle.read()
        parser = _InlineScripts()
        parser.feed(source)
        parser.close()
        for element_id, body in parser.scripts:
            found.append((name, element_id, _sha256_b64(body)))
    return found


def content_security_policy(hashes):
    """The one Content-Security-Policy every HTML response carries.

    `hashes` is inline_script_hashes' output; only the digest of each triple
    reaches the string. Directive order is the reading order of the argument
    in this module's docstring rather than alphabetical: the broad default
    first, then what is shut outright, then the two per-type grants that
    carry the interesting decisions.

    What the result buys, stated once so nobody has to re-derive it: an
    attacker who gets HTML into a page cannot execute script — not inline
    (no 'unsafe-inline', and no body they can write hashes to a blessed
    value), not from another origin ('self'), not through an event-handler
    attribute (script-src-attr 'none'), not through eval (no 'unsafe-eval',
    and app/static/*.js contains no eval, no new Function, no Worker and no
    string-setTimeout), and not by hijacking a relative URL (base-uri 'none';
    no template has a <base>). Exfiltration closes with it: img-src and
    connect-src 'self' — every fetch() in app/static/ targets an absolute
    same-origin path — and form-action 'self', which costs nothing because
    the sanitizer's allowlist is {strong, em, a}, so injected markup cannot
    contain a form at all.

    What it does not buy: anything against a network attacker (see the module
    docstring), anything against defacement by injected non-script HTML, and
    nothing about CSRF — SameSite=Lax does that, in app/__init__.py.
    """
    script_src = " ".join(
        ["script-src", "'self'"]
        + [f"'sha256-{digest}'" for _, _, digest in hashes]
    )
    directives = [
        "default-src 'self'",
        "base-uri 'none'",
        "object-src 'none'",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "img-src 'self'",
        "connect-src 'self'",
        script_src,
        "script-src-attr 'none'",
        "style-src 'self' 'unsafe-inline'",
        "style-src-attr 'none'",
    ]
    return "; ".join(directives)
