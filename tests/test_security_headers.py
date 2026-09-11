"""The security headers on HTML responses (LLM-COP-35 item 2).

WHAT THIS FILE CAN AND CANNOT PROVE, stated first because the distinction
is the whole reason tests/browser/test_browser_csp.py exists beside it.
Everything here reads the BYTES of a response — the header string, the
document body, and whether every inline script in that body is covered by
a hash in that same response's policy. None of it proves a browser accepts
the policy, runs the blessed scripts, or refuses anything. That evidence is
real Chrome's, and it is collected in tests/browser/test_browser_csp.py.

NO TEST HERE PINS A HASH LITERAL, and that is deliberate rather than
convenient. app/security.py derives the three digests from the template
sources precisely so that editing an inline script updates its own hash;
a pinned literal would have to be hand-maintained, which is the design the
module rejected. What IS pinned is the (template, element id) PAIRS and
the COUNT — the set of scripts the policy blesses — so a NEW inline script
turns test_the_blessed_inline_scripts_are_exactly_these_three red while an
EDIT to an existing one stays green, which is exactly the split that makes
the derivation safe.

BOTH SKINS, for steps 4 and 5. app/templates/page.html and
app/templates/page_v2.html are separate documents; a policy proved on one
is not proved on the other, and the coverage guard's entire job — noticing
an inline script nobody blessed — would never have parsed page_v2.html on
a default seed. Only four of the nine routes actually move with the
parameter (see the sweep's docstring); the other five are swept under both
anyway, because the cost is nothing and a route that silently stopped
moving would otherwise be invisible here.
"""

import base64
import hashlib
import io
import json
import os
import struct
import zlib
from html.parser import HTMLParser

import pytest

from app.security import (
    HEADERS_EVERYWHERE,
    content_security_policy,
    inline_script_hashes,
)
from tests.conftest import edit_published_payload, section_rows

# --- what the policy is supposed to bless ----------------------------------

# The three executable inline scripts in app/templates/, as
# (template name, element id). A `None` id is a bare <script> with no id —
# login_dialog.html's password toggle, which lives inside
# {% if not totp_step %} and carries no attributes at all.
#
# THE PAIRS AND THE COUNT, NEVER A DIGEST. See the module docstring.
BLESSED = (
    ("contact_dialog.html", "contact-dialog-script"),
    ("gdpr_dialog.html", "gdpr-dialog-script"),
    ("login_dialog.html", None),
)

# The four type="application/json" bootstraps. A browser never executes
# them, so script-src never checks them and app/security.py deliberately
# leaves them unhashed — which it MUST, because every one of them
# interpolates and a source-derived hash could not match the rendered
# response. Named here so the rendered-coverage guard below can say
# "unhashed BECAUSE it is data", rather than "unhashed, shrug".
DATA_SCRIPT_TYPE = "application/json"

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app",
    "templates",
)

# The link only page_v2.html emits. Asserted rather than trusted wherever a
# skin is planted: resolve_style never raises — it falls back — so a plant
# that did not land would leave every "v2" case a second, silent v1 run.
V2_STYLESHEET = "style-v2.css"

# The nine HTML routes. Seven are @auth.require_admin; `/` and `/yllapito`
# are public and render 200 for an admin too (app/__init__.py's yllapito
# decided to show the dialog to an already-signed-in admin).
#
# "{row}" is filled with a real section id — /muokkaa/osiot/rivi/<id> is an
# HTML FRAGMENT (app/sectionlist.py, injected by sectionlist.js), not a
# whole document, so nothing here may assume a text/html response has a
# <!doctype> or a <head>.
HTML_ROUTES = (
    "/",
    "/yllapito",
    "/yllapito/alustus",
    "/yllapito/viestit",
    "/muokkaa",
    "/muokkaa/esikatselu",
    "/muokkaa/sivu",
    "/muokkaa/osiot",
    "/muokkaa/osiot/rivi/{row}",
)

# The FOUR routes the skin parameter actually moves: each renders the
# public document through app/styles.py's template_for. /yllapito is one of
# them — it is the public page with the login dialog laid over it
# (app/__init__.py's yllapito calls the same render_page). /muokkaa/osiot
# and its row fragment are skin-independent by construction —
# app/templates/_section_row.html hard-imports page.html — and /muokkaa,
# /yllapito/alustus and /yllapito/viestit render templates of their own.
SKINNED_ROUTES = (
    "/",
    "/yllapito",
    "/muokkaa/esikatselu",
    "/muokkaa/sivu",
)

SKINS = ("v1", "v2")


# --- module-local helpers --------------------------------------------------
#
# Module-local rather than in tests/conftest.py, which is this project's own
# stated convention for a helper only one file needs
# (tests/test_sectionlist.py says so in as many words). The parser below is
# also deliberately a SECOND implementation rather than an import of
# app.security's private one: a guard that reuses the code it guards agrees
# with that code's bugs.


class _InlineScriptsInResponse(HTMLParser):
    """Every <script> in a served document that has no src, as
    (type attribute or None, body)."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=False)
        self.scripts = []
        self._type = None
        self._body = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        values = dict(attrs)
        if "src" in values:
            return  # fetched, not inlined: script-src 'self' covers it
        self._type = values.get("type")
        self._body = []

    def handle_data(self, data):
        if self._body is not None:
            self._body.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._body is not None:
            self.scripts.append((self._type, "".join(self._body)))
            self._type = None
            self._body = None


def inline_scripts_in(html):
    parser = _InlineScriptsInResponse()
    parser.feed(html)
    parser.close()
    return parser.scripts


def sha256_b64(body):
    """A script body as CSP spells its hash. Computed here from the
    RESPONSE, never imported from app.security — see the note above."""
    return base64.b64encode(
        hashlib.sha256(body.encode("utf-8")).digest()
    ).decode("ascii")


def directives(policy):
    """The policy string split into {name: [values]}."""
    out = {}
    for chunk in policy.split(";"):
        parts = chunk.split()
        if parts:
            out[parts[0]] = parts[1:]
    return out


def row_id(app):
    """A real section id, for the fragment route."""
    return section_rows(app)[0]["id"]


def plant_skin(app, skin):
    """Write the skin into the hero's published AND draft payload.

    ONE call, edit_published_payload — never a second write to `draft`
    alone. `/` renders the PUBLISHED payload and /muokkaa/esikatselu and
    /muokkaa/sivu render the DRAFT one; this helper writes both columns in
    one UPDATE, so all three see the same skin and no route can quietly
    run the wrong template.
    """
    edit_published_payload(app, "hero", lambda p: p.update(style=skin))


def _png_chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
        ">I", crc
    )


def png_bytes(width=8, height=8):
    """A real, decodable PNG. POST /api/kuvat reads the bytes and refuses
    anything whose header does not say PNG or JPEG, so this has to be one."""
    raw = b"".join(b"\x00" + bytes((0x2E, 0x6F, 0x9E)) * width
                   for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        )
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b"")
    )


# === step 1 — which inline scripts are blessed =============================


def test_the_blessed_inline_scripts_are_exactly_these_three():
    """The SET of scripts the policy trusts, pinned by identity.

    A fourth inline <script> added to any template turns this red, which
    is the whole loud half of the hash design: a new script is a decision
    somebody has to make, an edit to an existing one is not.

    FALSIFIED, not assumed: with `<script>window.x = 1;</script>` added to
    app/templates/page.html this test failed with a four-element list, and
    passed again the moment the template was restored.
    """
    found = inline_script_hashes(TEMPLATE_DIR)

    assert [(name, element) for name, element, _ in found] == list(BLESSED)


def test_every_blessed_hash_is_a_real_distinct_sha256():
    """The digests are what CSP expects and tell the three scripts apart.

    No literal is pinned — what is checked is the SHAPE: 32 bytes of
    base64, one per script, all different. A derivation that returned the
    same digest three times, or a truncated one, would satisfy a test that
    only counted them.
    """
    digests = [digest for _, _, digest in inline_script_hashes(TEMPLATE_DIR)]

    assert len(digests) == len(BLESSED)
    assert len(set(digests)) == len(BLESSED)
    for digest in digests:
        assert len(base64.b64decode(digest, validate=True)) == 32


def test_a_source_derived_hash_is_the_hash_of_the_template_text():
    """The derivation is the plain thing it claims to be.

    Recomputed here from the template file with a second, independent
    read: the body between <script ...> and </script>, UTF-8, SHA-256,
    base64. No strip, no newline normalization — CSP hashes the element's
    text content exactly as served.
    """
    found = {
        (name, element): digest
        for name, element, digest in inline_script_hashes(TEMPLATE_DIR)
    }
    path = os.path.join(TEMPLATE_DIR, "gdpr_dialog.html")
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    bodies = [
        body for kind, body in inline_scripts_in(source) if kind is None
    ]

    assert len(bodies) == 1
    assert found[("gdpr_dialog.html", "gdpr-dialog-script")] == sha256_b64(
        bodies[0]
    )


def test_a_script_with_a_src_is_not_hashed(tmp_path):
    """An external script has no body to hash and is covered by 'self'.

    Fed a directory of its own rather than asserted against the product's
    templates: the claim is about the RULE, and the rule has to hold for a
    template this tree does not happen to contain.
    """
    (tmp_path / "x.html").write_text(
        '<script src="/static/a.js"></script>\n'
        '<script id="inline">var a = 1;</script>\n',
        encoding="utf-8",
    )

    found = inline_script_hashes(str(tmp_path))

    assert [(name, element) for name, element, _ in found] == [
        ("x.html", "inline")
    ]


def test_a_json_data_block_is_not_hashed(tmp_path):
    """type="application/json" is never executed, so script-src never
    checks it — and it MUST stay unhashed, because all four of the
    product's bootstraps interpolate and a source-derived hash could not
    match the rendered response."""
    (tmp_path / "x.html").write_text(
        '<script id="bootstrap" type="application/json">{"a": 1}</script>\n'
        '<script id="real" type="text/javascript">var a = 1;</script>\n',
        encoding="utf-8",
    )

    found = inline_script_hashes(str(tmp_path))

    assert [(name, element) for name, element, _ in found] == [
        ("x.html", "real")
    ]


# === step 2 — the policy string ============================================


def test_the_policy_carries_every_derived_hash_and_nothing_it_was_not_given():
    """script-src is 'self' plus exactly the hashes it was handed.

    Built from a fabricated argument, not from the templates: the question
    is what content_security_policy does with what it is given, and using
    the real digests here would make the test unable to tell a correct
    build from one that ignored its argument and re-derived.
    """
    fake = [("a.html", "one", "AAAA"), ("b.html", None, "BBBB")]

    script_src = directives(content_security_policy(fake))["script-src"]

    assert script_src == ["'self'", "'sha256-AAAA'", "'sha256-BBBB'"]


def test_script_src_has_no_unsafe_inline_and_the_policy_has_no_unsafe_eval():
    """The two allowances that would make the script half decorative.

    'unsafe-inline' in script-src permits exactly the attack this policy
    exists to stop — an injected <script> running in the admin's browser
    on the inbox page. style-src keeps it deliberately (palette_css varies
    with the owner's colours, so no fixed hash can match), so the
    assertion is per-DIRECTIVE and never a bare `not in policy`, which
    would be green for a policy with the allowance in the wrong place.
    """
    policy = content_security_policy(inline_script_hashes(TEMPLATE_DIR))
    parsed = directives(policy)

    assert "'unsafe-inline'" not in parsed["script-src"]
    assert "'unsafe-inline'" in parsed["style-src"]
    assert "'unsafe-eval'" not in policy


def test_frame_ancestors_is_self_because_the_editor_frames_its_own_preview():
    """app/templates/edit.html renders /muokkaa/esikatselu in a same-origin
    <iframe>. 'none' — or X-Frame-Options: DENY — would black that pane
    out, so the weaker-looking value is the correct one and this pins it
    against a future hardening pass that "tightens" it."""
    parsed = directives(
        content_security_policy(inline_script_hashes(TEMPLATE_DIR))
    )

    assert parsed["frame-ancestors"] == ["'self'"]


@pytest.mark.parametrize(
    "name,value",
    [
        ("default-src", ["'self'"]),
        ("base-uri", ["'none'"]),
        ("object-src", ["'none'"]),
        ("form-action", ["'self'"]),
        ("img-src", ["'self'"]),
        ("connect-src", ["'self'"]),
        ("script-src-attr", ["'none'"]),
        ("style-src-attr", ["'none'"]),
    ],
)
def test_the_policy_shuts_each_of_these(name, value):
    """The directives that carry no derived part, each named on its own so
    a failure says which one moved."""
    parsed = directives(
        content_security_policy(inline_script_hashes(TEMPLATE_DIR))
    )

    assert parsed[name] == value


def test_the_policy_does_not_upgrade_insecure_requests():
    """A decision, not an oversight: the site is served over plain HTTP
    (item 1 is the TLS work), so the directive would break every
    subresource on a real deployment. It belongs with TLS, and so does
    HSTS — which is why neither appears here."""
    policy = content_security_policy(inline_script_hashes(TEMPLATE_DIR))

    assert "upgrade-insecure-requests" not in policy
    assert "Strict-Transport-Security" not in policy


def test_the_always_on_headers_are_nosniff_and_no_referrer():
    """HEADERS_EVERYWHERE carries no assumption about the body, which is
    why it goes on JSON, images, fragments and static files alike.

    no-referrer rather than the weaker strict-origin-when-cross-origin:
    nothing in the app reads Referer or document.referrer, and the weaker
    value would hand the admin path /yllapito/viestit to every site the
    owner links to.
    """
    assert HEADERS_EVERYWHERE == {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


# === step 4 — the header sweep, over both skins ============================


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("route", HTML_ROUTES)
def test_every_html_route_carries_all_four_headers(
    app, logged_in_admin, route, skin
):
    """Nine routes x two skins: CSP, X-Frame-Options, nosniff,
    Referrer-Policy.

    THE STATUS ASSERTION IS LOAD-BEARING, not decoration. Seven of these
    nine are @auth.require_admin and a Flask redirect is ALSO text/html —
    so a session that silently stopped working would leave every row here
    green while it measured the headers on a login page. 200 is what says
    the route under test is the route that answered.

    Which routes the skin parameter actually moves — FOUR, not three:
    `/`, `/yllapito`, /muokkaa/esikatselu and /muokkaa/sivu, each
    rendering the public document through app/styles.py's template_for.
    /yllapito is easy to miss: it is that same public page with the login
    dialog laid over it. /muokkaa/osiot and its row fragment are
    skin-independent by construction (_section_row.html hard-imports
    page.html), and /muokkaa, /yllapito/alustus and /yllapito/viestit
    render templates of their own. The other five are swept under both
    skins anyway — it costs nothing, and it is how a route that quietly
    STOPPED being skin-independent would show up.

    /muokkaa/osiot/rivi/<id> is an HTML fragment, not a document; nothing
    below assumes a <!doctype> or a <head>.
    """
    plant_skin(app, skin)
    client = logged_in_admin
    path = route.format(row=row_id(app))

    response = client.get(path)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.mimetype == "text/html"
    assert response.headers["Content-Security-Policy"] == (
        content_security_policy(inline_script_hashes(TEMPLATE_DIR))
    )
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("route", SKINNED_ROUTES)
def test_the_skin_parameter_really_moves_the_four_routes_it_claims_to(
    app, logged_in_admin, route, skin
):
    """The plant is ASSERTED, never trusted.

    app/styles.py's resolve_style never raises — it falls back — so a
    plant that did not land would leave every "v2" row above a second,
    silent v1 run against page.html, and the coverage guard's whole
    purpose (noticing an inline script nobody blessed, in EITHER template)
    would be unmet while looking met. This is the check that says the
    parametrization is real.

    FOUR routes, and /yllapito is the one an earlier draft of this file
    left out: it renders the same public document with the login dialog
    over it, so it moves with the skin exactly as `/` does.
    """
    plant_skin(app, skin)

    body = logged_in_admin.get(route).get_data(as_text=True)

    assert (V2_STYLESHEET in body) is (skin == "v2"), (
        f"{route} did not serve the {skin} skin"
    )


# === step 5 — the rendered-coverage guard, over both skins =================


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize("route", HTML_ROUTES)
def test_every_inline_script_in_the_response_is_covered_by_that_response(
    app, logged_in_admin, route, skin
):
    """Every executable inline script in the BODY has its hash in the CSP
    of the very same response.

    This is the guard that cannot be fooled by the derivation agreeing
    with itself. app/security.py hashes the template SOURCE; this hashes
    what the server actually SENT. The two differ the moment an inline
    script gains a {{ }} or a {% %} — and that mismatch would otherwise
    ship green from every server-side test and be dead in a browser only.

    FALSIFIED, not assumed: with `<script>var x = {{ 1 }};</script>` added
    to app/templates/page.html this test went red on every route that
    renders that template, naming the uncovered digest, and green again
    the moment the template was restored.

    A script with no src and a type the browser will not execute is
    allowed to be uncovered — but only if that type is exactly
    application/json, the four bootstraps. Any other unhashed inline
    script is a failure, so a new type nobody thought about cannot slip
    through as "probably data".
    """
    plant_skin(app, skin)
    client = logged_in_admin
    path = route.format(row=row_id(app))

    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_data(as_text=True)
    policy = response.headers["Content-Security-Policy"]

    uncovered = []
    for kind, script in inline_scripts_in(body):
        if f"'sha256-{sha256_b64(script)}'" in policy:
            continue
        if kind is not None and kind.strip().lower() == DATA_SCRIPT_TYPE:
            continue
        uncovered.append((kind, script[:120]))

    assert uncovered == [], (
        f"{path} ({skin}) served inline script(s) no hash in its own "
        f"Content-Security-Policy covers: {uncovered}"
    )


@pytest.mark.parametrize("skin", SKINS)
def test_the_guard_would_notice_an_unblessed_script(app, logged_in_admin, skin):
    """The guard above is falsifiable — proved here rather than promised.

    The same comparison is run against a document with one extra inline
    script the policy was never given. If this comes back empty the guard
    is broken and every green row above means nothing.
    """
    plant_skin(app, skin)
    response = logged_in_admin.get("/")
    body = response.get_data(as_text=True)
    policy = response.headers["Content-Security-Policy"]
    tampered = body.replace(
        "</body>", "<script>window.__pwned = 1;</script></body>"
    )
    assert tampered != body

    uncovered = [
        kind
        for kind, script in inline_scripts_in(tampered)
        if f"'sha256-{sha256_b64(script)}'" not in policy
        and (kind is None or kind.strip().lower() != DATA_SCRIPT_TYPE)
    ]

    assert uncovered == [None]


@pytest.mark.parametrize("skin", SKINS)
@pytest.mark.parametrize(
    "route,templates",
    [
        ("/", ("contact_dialog.html", "gdpr_dialog.html")),
        (
            "/yllapito",
            ("contact_dialog.html", "gdpr_dialog.html", "login_dialog.html"),
        ),
    ],
)
def test_the_public_documents_really_carry_their_blessed_scripts(
    app, route, templates, skin
):
    """The sweep and the guard are both vacuous on a document with no
    inline scripts at all — so this says they measured something.

    WHICH scripts, per route, because the three are not all on every page:
    `/` includes the contact and GDPR dialogs, and login_dialog.html is
    rendered only by /yllapito (app/__init__.py's render_page takes
    login_dialog=True there). An earlier draft of this test asserted three
    on `/` and failed, which is how that distinction got written down
    instead of assumed.

    page.html and page_v2.html are separate documents that each include
    the same partials, so both skins are checked. A refactor that moved a
    dialog's script to /static/ leaves the coverage guard green and turns
    this red, which is the right way round: that is a decision, not
    something to discover in a browser.

    Still no digest literal. The expected digests are looked up BY
    TEMPLATE NAME out of the derivation.
    """
    plant_skin(app, skin)
    by_template = {
        name: digest for name, _, digest in inline_script_hashes(TEMPLATE_DIR)
    }

    response = app.test_client().get(route)
    body = response.get_data(as_text=True)
    policy = response.headers["Content-Security-Policy"]

    served = [
        sha256_b64(script)
        for kind, script in inline_scripts_in(body)
        if kind is None
    ]
    assert sorted(served) == sorted(by_template[name] for name in templates)
    for digest in served:
        assert f"'sha256-{digest}'" in policy


# === step 6 — the three regression tests that name their hazard ============


def test_the_image_csp_is_not_widened_by_the_html_policy(app, logged_in_admin):
    """GET /kuvat/<digest> keeps its own, far stricter policy.

    app/images.py sets "default-src 'none'; sandbox" on the serving route,
    and an after_request that assigned the HTML policy ungated would
    overwrite it with something enormously looser — every image in the
    store suddenly a same-origin document that may load scripts. The gate
    is response.mimetype == "text/html", and send_from_directory is given
    the stored content type, so an image is image/png and is skipped
    whole. This names that interaction directly rather than leaning on
    tests/test_images.py, which asserts the same header for another
    reason and would not say WHY it broke.
    """
    ref = logged_in_admin.post(
        "/api/kuvat",
        data={"kuva": (io.BytesIO(png_bytes()), "kuva.png")},
        content_type="multipart/form-data",
        headers={"Accept": "application/json"},
    ).get_json()["ref"]

    response = app.test_client().get(f"/kuvat/{ref}")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; sandbox"
    )
    assert "'self'" not in response.headers["Content-Security-Policy"]
    assert "script-src" not in response.headers["Content-Security-Policy"]
    assert "X-Frame-Options" not in response.headers
    # ...and the always-on pair is still there, byte-identical to the value
    # app/images.py sets itself, so the two can never disagree.
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_the_json_api_gets_no_csp(client):
    """POST /api/messages is application/json: nosniff and Referrer-Policy,
    no CSP and no X-Frame-Options.

    Not tidiness. A Content-Security-Policy on a JSON body is a claim
    about a document that does not exist, and X-Frame-Options on it is
    noise; what a JSON response genuinely needs is nosniff, so a browser
    cannot be talked into treating it as HTML. The gate is what makes both
    true at once.
    """
    response = client.post(
        "/api/messages",
        json={
            "name": "Maria Koskinen",
            "email": "maria@esimerkki.fi",
            "message": "Hei.",
            "consent": True,
        },
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 201
    assert response.mimetype == "application/json"
    assert "Content-Security-Policy" not in response.headers
    assert "X-Frame-Options" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_an_inbox_message_containing_a_script_tag_stays_inert(
    app, client, logged_in_admin
):
    """WHAT THIS PROVES, AND WHAT IT DOES NOT — read before trusting it.

    It proves AUTOESCAPING. app/templates/inbox.html renders
    message.body with plain {{ }} and no |safe, so a stored
    "<script>window.__pwned=1</script>" comes back as &lt;script&gt; text.
    Delete the whole after_request from app/__init__.py and the first two
    assertions below still pass, unchanged — they are not header proof and
    must never be read as header proof.

    What makes the rest of it about THIS change is the second half: the
    policy that arrives on this very response is one under which that
    payload could not have run even if the escaping had failed. That is
    checked as a property of the header on the inbox response — script-src
    with no 'unsafe-inline', and the three blessed digests being the only
    inline bodies it trusts — rather than inferred from the module-level
    policy string, because the question is what the ADMIN'S browser was
    told on the page that renders visitor text.

    Whether Chrome actually refuses such a script in that document is not
    a question this layer can answer at all. It is answered for real in
    tests/browser/test_browser_csp.py, which appends an inline <script> to
    the live inbox document and watches the browser refuse it.
    """
    payload = "<script>window.__pwned=1</script>"
    assert client.post(
        "/api/messages",
        json={
            "name": "Maria Koskinen",
            "email": "maria@esimerkki.fi",
            "message": payload,
            "consent": True,
        },
        headers={"Accept": "application/json"},
    ).status_code == 201

    response = logged_in_admin.get("/yllapito/viestit")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    # (1) autoescaping — the primary control, and NOT a claim about headers.
    assert "<script>window.__pwned" not in body
    assert "&lt;script&gt;window.__pwned=1&lt;/script&gt;" in body
    # ...and the store really holds the raw payload, so the escaping above
    # is the template's doing and not the API quietly rewriting the text.
    assert json.loads(
        json.dumps(_stored_bodies(app))
    ) == [payload]
    # (2) the header on THIS response — the second line of defence.
    parsed = directives(response.headers["Content-Security-Policy"])
    assert "'unsafe-inline'" not in parsed["script-src"]
    assert parsed["script-src-attr"] == ["'none'"]
    blessed = {
        f"'sha256-{digest}'"
        for _, _, digest in inline_script_hashes(TEMPLATE_DIR)
    }
    assert set(parsed["script-src"]) == {"'self'"} | blessed


def _stored_bodies(app):
    """Every stored message body, from the app's own database file."""
    from app import db as database

    conn = database.connect(app.config["DATABASE"])
    try:
        return [row["body"] for row in conn.execute(
            "SELECT body FROM messages ORDER BY id"
        )]
    finally:
        conn.close()
