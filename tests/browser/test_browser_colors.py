"""USR-COP-2 — the owner's two colours, proved in a real browser.

Nothing here is stubbed and nothing is read off a stylesheet. Real Chrome,
the real Flask app on a real loopback port, the panel's own
<input type="color"> and its own Julkaise, and every colour assertion made
against getComputedStyle — the value the browser actually resolved after the
cascade, the var() chain and the <style> block the owner's choice produced.

WHY THIS FILE EXISTS. tests/test_palette.py sweeps the derivation and
tests/test_palette_css.py fences the stylesheets' source text. Neither can
say whether a chosen colour REACHES the screen: a token nothing references,
a rule that sets its own colour and was never retargeted, a <style> block
that loses the cascade, an override that never survives publish — every one
of those passes both of those files and ships a feature that does not work.

THE CONTRAST ASSERTIONS ARE THE POINT, and they are made on the elements
that CARRY THE VISIBLE TEXT, never on an ancestor. An earlier draft of this
plan read `color` off `.site-header` / `.v2-header`. V2's `.brand` sets its
own `color` (app/static/style-v2.css), so a header rule never reaches it —
that draft would have gone green while the brand rendered at 1.07:1 against
a dark chosen header. Every row of TEXT_SITES below is an element that owns
its own `color` declaration or inherits one this change had to retarget, and
the background it is measured against is the nearest ancestor with a
non-transparent backgroundColor, walked in the page.

THE WCAG ARITHMETIC IS DONE HERE, in this file, from the rgb() triples the
browser returned — not by calling app.palette.contrast. Importing the module
under proof would make every ratio below a statement about that module's
own luminance curve; recomputing it independently is what lets these tests
disagree with it.

HOW THE COLOURS GET IN. Two tests drive the REAL PANEL end to end — click
the skin, set both swatches, press Julkaise, read `/` back from a FRESH
ANONYMOUS CONTEXT. The rest write straight into the store with
edit_published_payload, which is not a shortcut round the panel but the only
way to reach the read path with values the panel cannot originate: an
<input type="color"> emits nothing but #rrggbb, and the hostile cases below
are exactly the API-client threat app/palette.py's whitelist is for. The
values the legibility and screenshot tests plant ARE valid #rrggbb, and the
panel path that writes them is proved once, for real, in
test_a_chosen_colour_reaches_the_header_and_the_buttons_and_survives_publish.

SCREENSHOTS land in tmp_path unless COP_COLOR_SHOTS names a directory — the
convention tests/browser/test_browser_contact_submit.py states. Every shot
is taken by a test that also asserts computed colours, so no case here can
pass on a picture alone.
"""

import contextlib
import json
import os
import re

import pytest

from app import db as database
from tests.browser.conftest import V2_STYLESHEET, VIEWPORT, hero_row
from tests.conftest import edit_published_payload

# The two colours the panel-driven tests choose. Neither is any skin's own,
# so "the header is that colour" cannot be true by accident, and both are
# dark enough that on_color picks white for their labels — the derivation
# actually running rather than defaulting.
PANEL_MAIN = "#3355aa"
PANEL_ACCENT = "#cc4400"
# The restore test's second choice, distinct from the first in every channel.
PANEL_MAIN_B = "#aa5533"

# What each skin renders before anything is chosen. Frozen literals, read off
# the shipped :root blocks: V1's header is var(--header-bg) -> var(--card)
# -> #ffffff, V2's is --v2-header -> #d9e8f2. Written out rather than
# imported from app.palette so a wrong ROLE_TOKENS default cannot make the
# fallback assertions agree with themselves.
SKIN_DEFAULT_HEADER = {"v1": (255, 255, 255), "v2": (217, 232, 242)}
SKIN_DEFAULT_ACCENT = {"v1": (31, 111, 92), "v2": (168, 67, 28)}

# A panel whose ground is --card / --v2-card and must NOT move when the
# owner picks a main colour. This is the brief's `--card` error made a test:
# mapping main to --card would repaint eleven surfaces on V1, this one
# included.
UNTOUCHED_PANEL = {"v1": ".fact-card", "v2": ".v2-hero-card"}

# The header element. V2's carries both classes (page_v2.html renders
# `class="site-header v2-header"`), so one selector reaches both skins and
# the background it resolves comes from whichever rule the skin supplies.
HEADER = ".site-header"

# Every element on the public page that renders text in a colour this change
# can move, per skin, with the ground it sits on found by walking the DOM.
#
# `.brand`            V1 inherits the header's ink (it sets none of its own);
#                     V2 sets its own, which is why both are listed and why
#                     an assertion on the header element alone proves nothing
# `.nav-links a`      sets its own colour in both skins; measured at rest and
#                     again after a real page.hover()
# `.header-contact`   the primary button in the header — its label at rest
#                     and its label on hover are DIFFERENT tokens
# `.cta-contact`      the primary button in the hero, on the hero's ground
# `.button.secondary` background: transparent, so the honest ground is the
#                     walked ancestor's
# body link           the accent AS TEXT — the case a header-only override
#                     never touches at all
TEXT_SITES = {
    "v1": (
        ".brand",
        ".nav-links a",
        ".header-contact",
        ".cta-contact",
        ".button.secondary",
        ".portrait-browse",
    ),
    "v2": (
        ".brand",
        ".nav-links a",
        ".header-contact",
        ".cta-contact",
        ".button.secondary",
        ".v2-band-link",
    ),
}

# The two that change colour under the pointer, and are therefore measured
# twice. `.nav-links a:hover` takes the header accent; `.button.primary:hover`
# takes a second, separately derived label ink — one ink cannot serve both
# grounds (3.7680 at #e400f3), which is what the #e400f3 row below tests.
HOVER_SITES = (".nav-links a", ".header-contact")

# The phone width hides .desktop-only, so the header links and the header
# button are not there to measure; V1's .brand-avatar is .phone-only and
# appears instead, carrying --accent-ink on an --accent ground.
PHONE_SITES = {
    "v1": (".brand", ".brand-avatar", ".cta-contact", ".button.secondary",
           ".portrait-browse"),
    "v2": (".brand", ".cta-contact", ".button.secondary", ".v2-band-link"),
}

PHONE_VIEWPORT = {"width": 390, "height": 844}

# The three pairs the legibility test drives, and why each one is here.
LEGIBILITY_CASES = (
    # A pale accent on a dark header: white-on-pale is the defect the brief
    # named, and #ffe9a8 on --paper is 1.1247 without --accent-fg.
    ("#1a1a2e", "#ffe9a8"),
    # The on_color grid's worst case (4.5843) in both roles.
    ("#8855ee", "#8855ee"),
    # The single-ink worst case: on_color(#e400f3) is black and
    # on_color(shade(#e400f3)) is white, so one label token cannot serve the
    # button's rest and hover grounds. With one, the hover row goes red.
    ("#e400f3", "#e400f3"),
)

# Values a colour input cannot produce and an API client can. Each must fall
# back to the skin's own colour and reach the page in NO form.
HOSTILE = (
    "#fff",
    "red",
    "javascript:alert(1)",
    "}",
    "}</style><script>window.__pwned=1</script>",
    "x" * 200,
)

# The three routes that render a public template with the chrome dict, and
# therefore the three that emit the <style> block. edit_published_payload
# writes draft AND published in one UPDATE, so the two owner-only routes —
# which render from the draft — see the planted value too.
ROUTES = ("/", "/muokkaa/sivu", "/muokkaa/esikatselu")


# --- fixtures ---------------------------------------------------------------


@pytest.fixture(params=["v1", "v2"], ids=["v1", "v2"])
def skin(request):
    """Both skins, every test. They do not share a token vocabulary, they do
    not put the header ink on the same element, and V1 needed a --header-bg
    token that V2 did not — so a proof of one is not a proof of the other."""
    return request.param


@pytest.fixture
def shots(tmp_path):
    """Where screenshots land. tmp_path unless COP_COLOR_SHOTS says else."""
    target = os.environ.get("COP_COLOR_SHOTS")
    if not target:
        return str(tmp_path)
    os.makedirs(target, exist_ok=True)
    return target


# --- the measurement helper -------------------------------------------------

# One evaluate, run in the page, returning for each selector the element's
# own computed `color` and the EFFECTIVE background: the nearest ancestor
# whose backgroundColor has an alpha above zero. `.button.secondary` is
# `background: transparent` in both skins, so its own backgroundColor says
# nothing about what its label is read against; the walked ancestor is the
# only honest answer, and it is what a human eye sees.
_MEASURE = """
(selectors) => selectors.map((selector) => {
  const el = document.querySelector(selector);
  if (!el) return { selector, found: false };
  const own = getComputedStyle(el);
  let node = el;
  let background = null;
  while (node) {
    const raw = getComputedStyle(node).backgroundColor;
    const parts = (raw.match(/[\\d.]+/g) || []).map(Number);
    if (parts.length >= 3 && (parts.length < 4 || parts[3] > 0)) {
      background = raw;
      break;
    }
    node = node.parentElement;
  }
  const box = el.getBoundingClientRect();
  return {
    selector,
    found: true,
    color: own.color,
    background,
    backgroundOwn: own.backgroundColor,
    rendered: box.width > 0 && box.height > 0,
  };
});
"""


def measure(page, selectors):
    """{selector: {...}} for every selector, measured in the live page."""
    rows = page.evaluate(_MEASURE, list(selectors))
    return {row["selector"]: row for row in rows}


def _srgb(channel):
    value = channel / 255
    return (
        value / 12.92
        if value <= 0.03928
        else ((value + 0.055) / 1.055) ** 2.4
    )


def _luminance(triple):
    red, green, blue = (_srgb(c) for c in triple)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def rgb(text):
    """The (r, g, b) of a computed `rgb()` / `rgba()` string.

    A translucent value is refused rather than blended: this file's whole
    method is that the ground under a label is a real, opaque colour, and a
    silent blend would be the test quietly inventing one.
    """
    parts = [float(p) for p in re.findall(r"[\d.]+", text or "")]
    assert len(parts) >= 3, f"not a colour: {text!r}"
    assert len(parts) < 4 or parts[3] == 1.0, f"translucent: {text!r}"
    return tuple(round(p) for p in parts[:3])


def ratio(one, other):
    """The WCAG 2.x contrast ratio between two (r, g, b) triples."""
    first, second = _luminance(one), _luminance(other)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def hex_to_rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


@contextlib.contextmanager
def anonymous(browser, live_app, path="/", viewport=None):
    """A visitor with no session at all, in a context of its own.

    A FRESH CONTEXT, not a reload of the signed-in page: the claim these
    tests make is about what the public page serves, and a page that shares
    a context with the panel shares its cookies, its cache and whatever the
    panel last wrote into the document.
    """
    context = browser.new_context(viewport=viewport or VIEWPORT)
    visitor = context.new_page()
    response = visitor.goto(f"{live_app.base_url}{path}")
    try:
        yield visitor, response
    finally:
        context.close()


def assert_skin(page, skin):
    """The served template is the one the case is about.

    resolve_style falls back rather than raising, so a style that failed to
    reach the store would serve V1 and every V2 case would quietly be a
    second V1 run. The stylesheet link is what a browser would fetch, so it
    is the thing asserted.
    """
    expected = 1 if skin == "v2" else 0
    assert page.locator(V2_STYLESHEET).count() == expected, (
        f"the page did not serve the {skin} skin"
    )


def choose_in_panel(page, skin, main=None, accent=None):
    """Drive the REAL Ulkoasu controls: the skin, then either swatch.

    Every write is wrapped in expect_response on the draft PUT, which does
    two things: it serialises the clicks against edit.js's queued/in-flight
    save machinery, and it makes "the panel wrote it" an observed request
    rather than an assumption.

    fill() on an <input type="color"> is Playwright setting the value and
    dispatching the input and change events the UA dispatches — the native
    picker is an OS window no automation can drive. The `change` binding
    (not `input`) is what edit.js listens on, deliberately, so this is the
    exact path a real choice takes.
    """
    page.click('.panel-tab[data-tab="ulkoasu"]')
    with page.expect_response("**/api/sections/*/draft"):
        page.click(f'.tyyli-option[data-style="{skin}"]')
    for role, value in (("main", main), ("accent", accent)):
        if value is None:
            continue
        with page.expect_response("**/api/sections/*/draft"):
            page.fill(f'.vari-input[data-color="{role}"]', value)


def publish(page):
    with page.expect_response("**/api/publish"):
        page.click(".julkaise-button")


def plant(live_app, skin, main="", accent=""):
    """Write the skin and both colours into the hero's draft AND published.

    edit_published_payload writes the two columns in one UPDATE, so /,
    /muokkaa/sivu and /muokkaa/esikatselu all see the same value: the first
    renders published, the other two render draft.

    The skin goes in with the colours rather than through a click, for the
    tests that are not ABOUT the panel. The panel path is driven for real,
    once, in test_a_chosen_colour_reaches_the_header... — planting it under
    that test too would leave nothing proving the control works.
    """
    edit_published_payload(
        live_app,
        "hero",
        lambda p: p.update(style=skin, color_main=main, color_accent=accent),
    )


# --- 1: the colour reaches the page, through the panel, and survives --------


def test_a_chosen_colour_reaches_the_header_and_the_buttons_and_survives_publish(
    page, live_app, skin
):
    """The whole feature, end to end, with nothing short-cut.

    The skin is chosen with the real .tyyli-option, both colours with the
    real .vari-input, Julkaise is the real button and the real POST
    /api/publish, and the result is read in a FRESH ANONYMOUS CONTEXT — so
    what is measured is what a visitor gets, not what the panel remembers.

    THREE ASSERTIONS, and the third is the one the brief got wrong. The
    header takes the main colour; the primary button takes the accent; and
    the white panel beside them does NOT move. The brief mapped main to
    --card, which is eleven surfaces on V1 — every white panel on the page.
    UNTOUCHED_PANEL is that error turned into a test.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    choose_in_panel(page, skin, main=PANEL_MAIN, accent=PANEL_ACCENT)
    publish(page)

    with anonymous(page.context.browser, live_app) as (visitor, response):
        assert response.status == 200
        assert_skin(visitor, skin)
        seen = measure(
            visitor,
            (HEADER, ".header-contact", UNTOUCHED_PANEL[skin]),
        )
        assert rgb(seen[HEADER]["backgroundOwn"]) == hex_to_rgb(PANEL_MAIN)
        assert rgb(seen[".header-contact"]["backgroundOwn"]) == hex_to_rgb(
            PANEL_ACCENT
        )
        # White before, white after. The --card finding, made falsifiable.
        assert rgb(seen[UNTOUCHED_PANEL[skin]]["backgroundOwn"]) == (
            255,
            255,
            255,
        )


def test_the_previous_colour_comes_back_through_restore(
    page, live_app, skin
):
    """Publish A, publish B, Palauta, publish — and the header is A again.

    POST /api/sections/<id>/restore copies previous_published into the
    DRAFT only (app/sectionlist.py), so the restore still needs a Julkaise
    to reach the public page — which is why the panel is reloaded before
    that click rather than clicked straight through. A panel left open
    holds its own in-memory draft, and publishing over the top of it would
    have proved the opposite of what this test claims.

    The reload also lets the swatch be asserted: after a restore the
    control shows A, because refreshColorInputs reads the stored value and
    not the last thing clicked.
    """
    page.goto(f"{live_app.base_url}/muokkaa")
    choose_in_panel(page, skin, main=PANEL_MAIN, accent=PANEL_ACCENT)
    publish(page)
    choose_in_panel(page, skin, main=PANEL_MAIN_B)
    publish(page)

    with anonymous(page.context.browser, live_app) as (visitor, _):
        seen = measure(visitor, (HEADER,))
        assert rgb(seen[HEADER]["backgroundOwn"]) == hex_to_rgb(PANEL_MAIN_B)

    hero = hero_row(live_app)["id"]
    restored = page.request.post(
        f"{live_app.base_url}/api/sections/{hero}/restore"
    )
    assert restored.status == 200, restored.text()

    page.goto(f"{live_app.base_url}/muokkaa")
    page.click('.panel-tab[data-tab="ulkoasu"]')
    assert (
        page.input_value('.vari-input[data-color="main"]') == PANEL_MAIN
    ), "the swatch did not follow the restored draft"
    publish(page)

    with anonymous(page.context.browser, live_app) as (visitor, _):
        assert_skin(visitor, skin)
        seen = measure(visitor, (HEADER, ".header-contact"))
        assert rgb(seen[HEADER]["backgroundOwn"]) == hex_to_rgb(PANEL_MAIN)
        assert rgb(seen[".header-contact"]["backgroundOwn"]) == hex_to_rgb(
            PANEL_ACCENT
        )


# --- 2: hostile values ------------------------------------------------------

# The direct-edit page's data island. /muokkaa/sivu ships the whole draft
# payload to direct-edit.js through it, so EVERY stored field appears there —
# these two colours no more and no less than hero.title does. It is
# type="application/json", so the browser parses it as data and executes
# nothing in it, and Jinja's |tojson escapes `<` on the way in.
BOOTSTRAP_OPEN = (
    '<script id="direct-bootstrap" type="application/json">'
)
BOOTSTRAP_CLOSE = "</script>"


def rendered_text(document):
    """`document` with the direct-edit JSON bootstrap cut out of it.

    What is left is everything a browser renders or executes. A stored value
    that appears in THAT is a value that reached the page; one that appears
    only in the island is a value that reached direct-edit.js's copy of the
    draft, which is where every field it edits already lives.
    """
    start = document.find(BOOTSTRAP_OPEN)
    if start == -1:
        return document
    end = document.find(BOOTSTRAP_CLOSE, start)
    assert end != -1, "the bootstrap script is not closed"
    return document[:start] + document[end + len(BOOTSTRAP_CLOSE):]


def assert_bootstrap_is_inert_data(page, value):
    """The island parses, and the hostile value comes back out as a STRING.

    Parsed in the page by JSON.parse, so this is Chrome's own reading of the
    bytes it was served rather than Python's — the question being asked is
    whether the browser sees data or markup, and only the browser can answer
    it.
    """
    hero = page.evaluate(
        """() => {
          const el = document.getElementById('direct-bootstrap');
          if (!el) return null;
          const data = JSON.parse(el.textContent);
          const row = data.sections.find((s) => s.kind === 'hero');
          return {
            type: el.getAttribute('type'),
            main: row.payload.color_main,
            accent: row.payload.color_accent,
          };
        }"""
    )
    assert hero is not None
    assert hero["type"] == "application/json"
    assert hero["main"] == value and hero["accent"] == value




@pytest.mark.parametrize("value", HOSTILE, ids=lambda v: repr(v)[:32])
def test_a_hostile_stored_colour_reaches_no_route_in_any_form(
    page, live_app, skin, value
):
    """Six values a colour input cannot emit, on all three rendering routes.

    Written STRAIGHT INTO THE STORE, because that is the threat: the panel's
    control can produce nothing but #rrggbb, so the whitelist has to live on
    the READ path where an API client's write also passes. This is the only
    way to reach that path at all.

    FIVE THINGS ARE ASSERTED PER ROUTE, and each catches a different
    failure:

    * 200 — asserted FIRST, so nothing below can pass on an error page. A
      stored value that 500s the public page is the unrecoverable failure
      resolve_color is shaped to prevent.
    * no `<style` at all — the exact claim, and the strongest one available:
      a rejected colour produces no block, not a block carrying a repaired
      approximation of it.
    * the RENDERED document — everything outside the direct-edit JSON
      bootstrap — contains the value exactly as often as a clean load did.
      A count, not `not in`: "}" and "red" occur in a perfectly innocent
      document, so `not in` would be red on correct code.
    * window.__pwned is undefined in real Chrome, and the document's
      <script> count is what a clean load had — the payload that closes the
      style element and opens a script, executed by a browser rather than
      inspected as text.
    * the header falls back to the skin's own colour.

    WHY THE BOOTSTRAP IS EXCLUDED, and it is a finding rather than a
    convenience. /muokkaa/sivu serves
    `<script id="direct-bootstrap" type="application/json">{{ bootstrap|tojson }}</script>`
    (app/templates/direct_edit_chrome.html), and that bootstrap is the whole
    draft payload — every stored field of every section, these two colours
    among them. So the plan's criterion as written, "the served document does
    not contain the string", is FALSE ON CORRECT CODE for that one route,
    and was measured false here: each value arrives twice, once per key.

    What is asserted instead is what is actually claimed. Jinja's |tojson
    escapes `<` to `\u003c`, which is why the `}</style><script>` payload
    does not appear even inside the bootstrap; the element is
    type="application/json" so nothing in it executes; and
    assert_bootstrap_is_inert_data below parses it in the browser and shows
    the value coming back out as a STRING on the hero payload. Everywhere
    else in the document — and every byte of `/` and /muokkaa/esikatselu —
    the value does not appear at all.
    """
    plant(live_app, skin)
    baseline = {}
    for route in ROUTES:
        response = page.goto(f"{live_app.base_url}{route}")
        assert response.status == 200, route
        baseline[route] = (
            rendered_text(response.text()).count(value),
            page.locator("script").count(),
        )
        assert "<style" not in response.text(), route

    plant(live_app, skin, main=value, accent=value)

    for route in ROUTES:
        response = page.goto(f"{live_app.base_url}{route}")
        assert response.status == 200, (route, value)
        text = response.text()
        occurrences, scripts = baseline[route]
        assert "<style" not in text, (
            f"{route} emitted a <style> block for a rejected value"
        )
        rendered = rendered_text(text)
        assert rendered.count(value) == occurrences, (
            f"{route} served the stored value {value!r} "
            f"{rendered.count(value)} times outside the JSON bootstrap, "
            f"{occurrences} on a clean load"
        )
        assert page.locator("script").count() == scripts, (
            f"{route} grew a <script> element"
        )
        assert page.evaluate("window.__pwned") is None
        seen = measure(page, (HEADER,))
        assert rgb(seen[HEADER]["backgroundOwn"]) == SKIN_DEFAULT_HEADER[
            skin
        ], f"{route} did not fall back to the {skin} header colour"
        if BOOTSTRAP_OPEN in text:
            assert_bootstrap_is_inert_data(page, value)


# --- 3: legibility, measured on the elements that carry the text ------------


@pytest.mark.parametrize(
    "main,accent", LEGIBILITY_CASES, ids=lambda v: v.lstrip("#")
)
def test_every_text_site_clears_four_and_a_half_to_one(
    page, live_app, skin, main, accent
):
    """The assertion that must be able to fail, and does.

    Every row reads BOTH the computed `color` and the effective background
    off the element that carries the visible text, parses the two rgb()
    triples here, computes the WCAG ratio here, and requires 4.5:1. Nothing
    is taken from app/palette.py — not the ratio, not the curve, not the
    expected value — so a wrong luminance, a wrong token name, a losing
    cascade, an override that never reached a rule, and an element whose own
    `color` was never retargeted all fail it, separately and by name.

    Demonstrated red during authoring: with V2's `.brand` left on
    var(--v2-ink), the #1a1a2e header renders the brand at 1.36:1 and this
    test names `.brand` in its failure. That is the miss an ancestor-only
    assertion could not see.

    The hover rows are measured after a real page.hover(), because the
    button's label on hover is a SEPARATE token from its label at rest — one
    ink cannot clear both grounds (3.7680 at #e400f3), and with a single
    token the #e400f3 case fails here rather than in a comment.
    """
    plant(live_app, skin, main=main, accent=accent)
    page.goto(f"{live_app.base_url}/")
    assert_skin(page, skin)

    failures = []
    seen = measure(page, TEXT_SITES[skin])
    for selector in TEXT_SITES[skin]:
        row = seen[selector]
        assert row["found"], f"{selector} is not on the {skin} page at all"
        assert row["rendered"], f"{selector} rendered at zero size"
        measured = ratio(rgb(row["color"]), rgb(row["background"]))
        if measured < 4.5:
            failures.append(
                f"{selector} rest {measured:.4f}:1 "
                f"({row['color']} on {row['background']})"
            )

    for selector in HOVER_SITES:
        page.hover(selector)
        row = measure(page, (selector,))[selector]
        measured = ratio(rgb(row["color"]), rgb(row["background"]))
        if measured < 4.5:
            failures.append(
                f"{selector} hover {measured:.4f}:1 "
                f"({row['color']} on {row['background']})"
            )

    assert not failures, (
        f"{skin} with main={main} accent={accent}: " + "; ".join(failures)
    )


# --- 4: an untouched site ---------------------------------------------------


def test_a_site_that_chose_nothing_emits_no_style_block_anywhere(
    page, live_app, skin
):
    """The "renders as it did before" claim, as far as a test can carry it.

    `/` serves no `<style` SUBSTRING at all — absent, not empty — and every
    element this change retargeted still resolves to the skin's own shipped
    literal. The header and the accent are checked as values, so a token
    left pointing at the wrong default fails here even though nothing was
    ever chosen.

    /yllapito/viestit is the admin inbox, which links style.css and renders
    .site-header, .brand and .button.secondary — and which passes NO chrome,
    so no block can reach it whatever an owner picks. THE 200 IS ASSERTED
    BEFORE THE ABSENCE: /viestit is not a route (app/messages.py serves
    /yllapito/viestit), and a test written against the wrong path would have
    proved the absence of a <style> block in a 404 page.
    """
    plant(live_app, skin)
    response = page.goto(f"{live_app.base_url}/")
    assert response.status == 200
    assert_skin(page, skin)
    assert "<style" not in response.text()

    seen = measure(page, (HEADER, ".header-contact"))
    assert rgb(seen[HEADER]["backgroundOwn"]) == SKIN_DEFAULT_HEADER[skin]
    assert rgb(seen[".header-contact"]["backgroundOwn"]) == (
        SKIN_DEFAULT_ACCENT[skin]
    )

    inbox = page.goto(f"{live_app.base_url}/yllapito/viestit")
    assert inbox.status == 200, "the inbox route moved; the check below is void"
    assert "<style" not in inbox.text()


def test_the_owners_colour_never_repaints_the_admin_inbox(
    page, live_app, skin
):
    """With a colour CHOSEN, the admin surfaces stay the skin's own.

    The inbox links style.css and renders a .site-header, so "the panel is
    untouched" is a claim about a page that shares a stylesheet with the one
    that IS repainted. app/messages.py passes no chrome, so site_colors_css
    is not in that template's context at all — asserted here rather than
    assumed, because the assumption is one template edit away from false.
    """
    plant(live_app, skin, main=PANEL_MAIN, accent=PANEL_ACCENT)
    public = page.goto(f"{live_app.base_url}/")
    assert public.status == 200
    assert "<style" in public.text(), "the colour never reached the public page"

    inbox = page.goto(f"{live_app.base_url}/yllapito/viestit")
    assert inbox.status == 200
    assert "<style" not in inbox.text()
    seen = measure(page, (".site-header",))
    # style.css's own --header-bg -> --card -> #ffffff, untouched.
    assert rgb(seen[".site-header"]["backgroundOwn"]) == (255, 255, 255)


# --- 5: screenshots, taken by a test that also asserts ----------------------


@pytest.mark.parametrize(
    "width,height,label",
    ((1280, 900, "desktop"), (390, 844, "phone")),
    ids=("desktop", "phone"),
)
def test_a_chosen_palette_renders_and_is_photographed(
    browser, live_app, skin, shots, width, height, label
):
    """Both skins at both widths, with a colour set — and the picture is
    taken by a test that measures the pixels' colours first.

    The pale accent is deliberate: #ffe9a8 on a dark header is the case the
    brief calls out and the one a screenshot is actually useful for, because
    "is that readable" is the question a number answers and a human confirms.

    The phone width measures a different set of elements, and that is not a
    convenience: .desktop-only hides the header links and the header button
    below 720, and V1's .brand-avatar — an --accent ground with a derived
    --accent-ink label — appears only there. Asserting the desktop set at
    390 would be asserting against elements the browser is not drawing.
    """
    main, accent = "#1a1a2e", "#ffe9a8"
    edit_published_payload(
        live_app,
        "hero",
        lambda p: p.update(
            style=skin, color_main=main, color_accent=accent
        ),
    )
    context = browser.new_context(viewport={"width": width, "height": height})
    visitor = context.new_page()
    try:
        response = visitor.goto(f"{live_app.base_url}/")
        assert response.status == 200
        assert_skin(visitor, skin)

        seen = measure(visitor, PHONE_SITES[skin] if label == "phone"
                       else TEXT_SITES[skin])
        for selector, row in seen.items():
            assert row["found"] and row["rendered"], (selector, label)
            measured = ratio(rgb(row["color"]), rgb(row["background"]))
            assert measured >= 4.5, (
                f"{skin} {label} {selector}: {measured:.4f}:1 "
                f"({row['color']} on {row['background']})"
            )
        header = measure(visitor, (HEADER,))[HEADER]
        assert rgb(header["backgroundOwn"]) == hex_to_rgb(main)

        path = os.path.join(shots, f"colors-{skin}-{label}-{width}x{height}.png")
        visitor.screenshot(path=path, full_page=True)
        assert os.path.getsize(path) > 0
    finally:
        context.close()


# --- what a stored colour looks like on the wire ----------------------------


# --- 6: LLM-COP-40, the accent as an EDGE -----------------------------------
#
# EVERYTHING BELOW IS ADDITIVE. Not one line of the text-site machinery above
# is edited — measure, TEXT_SITES, HOVER_SITES, PHONE_SITES, LEGIBILITY_CASES
# and every test that reads them are untouched, because "text contrast is
# unchanged" is a claim this file has to be able to make about itself.
#
# THE ANTI-HAZARD, and it is the reason measure_edges exists rather than a
# second call to measure. `border-*-color`'s initial value is `currentColor`,
# and style.css declares `--accent-fg: var(--accent)` — so an element that
# renders accent-coloured TEXT and draws NO border at all computes
# borderTopColor as the shipped accent. Measured in Chrome on this very page:
# `.section-kicker` returns rgb(31, 111, 92) with nothing chosen and
# rgb(133, 111, 46) with #ffe9a8 chosen, painting nothing either time. A pin
# on the VALUE alone passes green on it. So every row below is required to
# prove the edge is PAINTED — a non-zero width and a style that is not
# `none` or `hidden` — BEFORE any ratio is computed from it. That is
# USR-COP-2's "read the colour off an element that does not own it" mistake
# in its border-shaped form, and it is closed here by a precondition rather
# than by choosing selectors carefully.

# The three owner picks every edge row is driven at: a PALE one (the defect
# the ask names — 1.1247:1 raw on --paper), a MID one (2.5620:1 raw, the case
# that catches a NEARLY right derivation, which the pale one alone would not)
# and a DARK one, which the derivation must leave alone.
EDGE_CASES = ("#ffe9a8", "#66aa88", "#1a1a2e")

# (selector, property, pseudo, kind). `kind` decides two things: what counts
# as proof the edge is painted, and which grounds the ratio is taken against.
#
# `:first-child` IS LOAD-BEARING on both card rows. style.css gives cards two
# to four fixed literal border colours by ordinal position, so a row aimed at
# `:nth-child(2)` would measure rgb(182, 137, 74) — a colour that clears 3:1
# on white all by itself and proves nothing about this change. Measured, and
# it is what test 1's value pin catches.
EDGE_SITES = {
    "v1": (
        (".cta-row .button.secondary", "borderTopColor", None, "border"),
        (
            ".fact-cards .fact-card:first-child",
            "borderTopColor",
            None,
            "border",
        ),
        (
            ".service-cards .service-card:first-child",
            "borderTopColor",
            None,
            "border",
        ),
    ),
    "v2": (
        (".v2-hero-card .button.secondary", "borderTopColor", None, "border"),
        (
            ".v2-band-media-left .v2-section-label",
            "backgroundColor",
            "::after",
            "bar",
        ),
    ),
}

# The direct-edit affordance and focus ring, on the one route that both
# receives the override and draws a ring of its own. A text field, because
# direct-edit.js sets contentEditable at bind time and page.focus() then
# reaches it the way a keyboard user's Tab does.
DIRECT_FIELD = "[data-field='title']"
DIRECT_ROW = (DIRECT_FIELD, "outlineColor", None, "outline")

# The primary buttons whose border must stay the owner's RAW pick, per skin,
# with the ground each actually sits on. On v2 neither ground is in the
# surface tuple; on v1 --paper is. What excludes all three is the same
# thing: the border is byte-identical to the fill — see test 3.
PRIMARY_BORDERS = {
    "v1": ((".cta-row .button.primary", "rgb(250, 247, 242)"),),
    "v2": (
        (".v2-contact-card .button.primary", "rgb(20, 50, 74)"),
        (".v2-header .button.primary", "rgb(217, 232, 242)"),
    ),
}

# One evaluate for every edge row. Four things this returns that `measure`
# does not, and each closes a way a contrast assertion can be green and
# meaningless:
#
# * borderTopWidth / borderTopStyle / outlineWidth / outlineStyle — the
#   painted-edge precondition described above;
# * `value` read through getComputedStyle(el, pseudo), so a ::after row
#   measures the generated box and not its owner;
# * `own` AND `under`, separately: a card's top rule is seen against the
#   card's own white on its inner face and the paper outside on its outer
#   one, and only asserting both covers the stripe a reader actually sees;
# * content / width / height, so a pseudo-element the browser never paints
#   cannot pass as one it does.
#
# THE GROUND RULE FOR A PSEUDO ROW, stated once and used in BOTH this helper
# and the whole-document sweep further down: the walk starts at `el` ITSELF,
# not at its parent. A ::after box paints on top of its owner's own
# background, so the owner is the honest first candidate. For an element's
# own border or outline the walk starts at `el.parentElement`, because the
# element's own background is a separate candidate already carried in `own`
# — and for an outline, which sits at outline-offset OUTSIDE the border box,
# the element's own fill is not what it is seen against at all.
_MEASURE_EDGES = """
(rows) => rows.map(([selector, property, pseudo]) => {
  const el = document.querySelector(selector);
  if (!el) return { selector, property, pseudo, found: false };
  const own = getComputedStyle(el);
  const target = getComputedStyle(el, pseudo || null);
  const opaque = (raw) => {
    const parts = (raw.match(/[\\d.]+/g) || []).map(Number);
    return parts.length >= 3 && (parts.length < 4 || parts[3] > 0);
  };
  const walk = (node) => {
    while (node) {
      const raw = getComputedStyle(node).backgroundColor;
      if (opaque(raw)) return raw;
      node = node.parentElement;
    }
    return null;
  };
  const box = el.getBoundingClientRect();
  return {
    selector,
    property,
    pseudo: pseudo || null,
    found: true,
    rendered: box.width > 0 && box.height > 0,
    value: target[property],
    color: own.color,
    borderTopWidth: target.borderTopWidth,
    borderTopStyle: target.borderTopStyle,
    outlineWidth: target.outlineWidth,
    outlineStyle: target.outlineStyle,
    own: own.backgroundColor,
    under: walk(pseudo ? el : el.parentElement),
    content: target.content,
    width: target.width,
    height: target.height,
  };
});
"""


def measure_edges(page, rows):
    """{selector: {...}} for every (selector, property, pseudo, kind) row."""
    measured = page.evaluate(
        _MEASURE_EDGES, [[s, p, pseudo] for s, p, pseudo, _ in rows]
    )
    return {row["selector"]: row for row in measured}


def is_opaque(text):
    """True for a computed colour with no alpha or an alpha of exactly 1."""
    parts = [float(p) for p in re.findall(r"[\d.]+", text or "")]
    return len(parts) >= 3 and (len(parts) < 4 or parts[3] == 1.0)


def assert_painted(row, kind, where):
    """THE PRECONDITION. An edge nobody drew has no contrast to measure.

    Called before every ratio in this section, and it is what stops the
    currentColor hazard: an accent-TEXT element with no border computes
    borderTopColor as the shipped accent, so a value pin passes on it while
    a width of 0px and a style of `none` say plainly that nothing is drawn.
    """
    assert row["found"], f"{where}: {row['selector']} is not on the page"
    assert row["rendered"], f"{where}: {row['selector']} rendered at zero size"
    if kind == "border":
        assert float(row["borderTopWidth"].rstrip("px")) > 0, (
            f"{where}: {row['selector']} draws no top border "
            f"(width {row['borderTopWidth']}), so its borderTopColor "
            f"{row['value']} is currentColor and not an edge"
        )
        assert row["borderTopStyle"] not in ("none", "hidden"), (
            f"{where}: {row['selector']} border-top-style is "
            f"{row['borderTopStyle']}"
        )
    elif kind == "outline":
        assert float(row["outlineWidth"].rstrip("px")) > 0, (
            f"{where}: {row['selector']} draws no outline "
            f"(width {row['outlineWidth']}), so its outlineColor "
            f"{row['value']} is currentColor and not a ring"
        )
        assert row["outlineStyle"] not in ("none", "hidden"), (
            f"{where}: {row['selector']} outline-style is "
            f"{row['outlineStyle']}"
        )
    elif kind == "bar":
        assert row["content"] == '""', (
            f"{where}: {row['selector']}::after content is {row['content']}, "
            "so the browser generates no box at all"
        )
        assert row["height"] == "3px" and row["width"] != "0px", (
            f"{where}: {row['selector']}::after is "
            f"{row['width']} x {row['height']}"
        )
    else:  # pragma: no cover - a typo in a table, not a state to reach
        raise AssertionError(f"unknown edge kind {kind!r}")


def edge_grounds(row, kind):
    """The backgrounds this edge is actually seen against.

    A BORDER takes both faces: the element's own fill where it has one — a
    .fact-card's top stripe is seen against the card's white on the inside —
    and the walked ancestor outside it. A translucent own fill is skipped
    rather than blended, the same rule rgb() holds to.

    AN OUTLINE takes the walked ancestor only. It is painted at
    outline-offset OUTSIDE the border box, so the element's own fill is not
    under it — which is also what keeps `.cta-contact`, a [data-field] whose
    own fill can be the raw accent, from being measured against itself.

    A BAR takes the walk from its owner, which is where its own box sits.
    """
    grounds = []
    if kind == "border" and is_opaque(row["own"]):
        grounds.append(row["own"])
    if row["under"]:
        grounds.append(row["under"])
    assert grounds, f"{row['selector']}: no opaque ground anywhere above it"
    return grounds


def edge_failures(seen, rows, where):
    """Every row's ratio against every ground it has, as failure strings."""
    failures = []
    for selector, _prop, _pseudo, kind in rows:
        row = seen[selector]
        assert_painted(row, kind, where)
        for ground in edge_grounds(row, kind):
            measured = ratio(rgb(row["value"]), rgb(ground))
            if measured < 3.0:
                failures.append(
                    f"{selector} {measured:.4f}:1 "
                    f"({row['value']} on {ground})"
                )
    return failures


def test_the_shipped_edges_are_the_skin_s_own_and_are_actually_painted(
    page, live_app, skin
):
    """NOTHING PLANTED — the byte-identity proof, and the baseline that makes
    every ratio below meaningful.

    Two assertions per row, in this order and not the other. FIRST that the
    edge is painted: a width and a style, or for the ::after bar a generated
    box of the size the stylesheet asks for. THEN that the colour is the
    skin's own shipped literal, exactly. A site that has chosen no colour
    emits no <style> block at all, so every one of these resolves through
    the new token's :root default to the value it rendered at 78d5d8e.

    THIS IS THE TEST THAT CATCHES A ROW AIMED AT THE WRONG THING, which is
    why it pins the value with nothing chosen rather than only checking a
    ratio. Measured while writing it: `.fact-card:nth-child(2)` returns
    rgb(182, 137, 74) — a fixed literal by ordinal position — and
    `.section-kicker`, which draws no border, returns the shipped accent
    with a width of 0px. The first fails the value pin, the second the
    painted precondition, and neither would fail a 3:1 assertion.

    The direct-edit idle affordance is measured here too, on the route that
    draws it, because it is the same token and the same hazard.
    """
    plant(live_app, skin)
    rows = EDGE_SITES[skin]
    with anonymous(page.context.browser, live_app) as (visitor, response):
        assert response.status == 200
        assert_skin(visitor, skin)
        assert "<style" not in response.text(), (
            "a site that chose nothing must serve no block at all"
        )
        seen = measure_edges(visitor, rows)
        for selector, _prop, _pseudo, kind in rows:
            row = seen[selector]
            assert_painted(row, kind, f"{skin} /")
            assert rgb(row["value"]) == SKIN_DEFAULT_ACCENT[skin], (
                f"{skin} {selector} renders {row['value']}, not the shipped "
                "accent — the token's :root default does not resolve to what "
                "this site rendered before the change"
            )

    # V1 only: /muokkaa/sivu draws the dashed affordance from the same token.
    # V2 draws no author outline at all, which the recorded-defect test below
    # pins rather than this one asserting around.
    if skin == "v1":
        page.goto(f"{live_app.base_url}/muokkaa/sivu")
        page.wait_for_selector(DIRECT_FIELD)
        row = measure_edges(page, (DIRECT_ROW,))[DIRECT_FIELD]
        assert_painted(row, "outline", "v1 /muokkaa/sivu idle")
        assert row["outlineStyle"] == "dashed" and row["outlineWidth"] == "1px"
        assert rgb(row["value"]) == SKIN_DEFAULT_ACCENT["v1"]


@pytest.mark.parametrize("accent", EDGE_CASES, ids=lambda v: v.lstrip("#"))
def test_every_edge_reaches_three_to_one_against_its_own_ground(
    page, live_app, skin, accent
):
    """THE CENTRAL CLAIM OF LLM-COP-40, in a real browser.

    Every retargeted site, in both skins, at a pale, a mid and a dark owner
    pick, measured from the colour Chrome resolved after the cascade, the
    var() chain and the <style> block the choice produced — and required to
    reach 3:1 against EVERY ground it is actually seen against, its own fill
    included where it has one.

    The arithmetic is this file's own, from the rgb() triples the browser
    returned. app/palette.py is not imported for it: a ratio computed with
    the curve of the module under proof is a statement about that module.

    THE THREE PICKS EACH CATCH A DIFFERENT FAILURE. Pale is the defect the
    ask names — raw, #ffe9a8 is 1.1247:1 on --paper and 1.1466:1 on
    --v2-page, a border drawn and invisible. Mid is the one that catches a
    NEARLY right derivation: raw #66aa88 is 2.5620:1, under 3 but not
    absurd, and a pale-only test would pass on a walk that stopped short.
    Dark is the identity case — #1a1a2e already clears 3:1 everywhere, so
    the derivation must hand it back untouched and the ratio must be the raw
    colour's own 15.9620:1, not something the walk invented.
    """
    plant(live_app, skin, accent=accent)
    rows = EDGE_SITES[skin]
    with anonymous(page.context.browser, live_app) as (visitor, response):
        assert response.status == 200
        assert_skin(visitor, skin)
        assert "<style" in response.text(), "the colour never reached the page"
        seen = measure_edges(visitor, rows)
        failures = edge_failures(seen, rows, f"{skin} {accent} /")
        assert not failures, (
            f"{skin} with accent={accent}: " + "; ".join(failures)
        )


@pytest.mark.parametrize("accent", ("#ffe9a8", "#66aa88"), ids=("pale", "mid"))
def test_the_primary_button_border_is_still_the_owners_own_colour(
    page, live_app, skin, accent
):
    """THE OTHER HALF OF THE BOUNDARY, and it is a guard rather than a note.

    A primary button's border is byte-identical to its fill, so it is no
    boundary a user perceives and SC 1.4.11 does not reach it — and on v2
    its grounds are outside the surface tuple as well, so the derivation has
    nothing true to say about it there. Widening the retarget from
    `.button.secondary` to the bare `.button` rule would repaint it anyway.

    That is not a hypothetical: app/palette.py's own site list called those
    two rules `.button.secondary` when they are the bare `.button`. Under
    the wide retarget the v2 contact card's border would read
    rgb(156, 134, 69) against a fill of rgb(255, 233, 168), and its ratio
    against --v2-navy #14324a would fall from 11.0249:1 to 3.7287:1 for this
    pale pick and 4.8397:1 to 3.7691:1 for the mid one — a real degradation
    bought in the name of an improvement.

    So the assertion is EQUALITY WITH THE FILL, not a ratio: the claim is
    that these two are the same colour, and a ratio of 1.0 is what being the
    same colour means.
    """
    plant(live_app, skin, accent=accent)
    rows = tuple(
        (selector, "borderTopColor", None, "border")
        for selector, _ground in PRIMARY_BORDERS[skin]
    )
    with anonymous(page.context.browser, live_app) as (visitor, _):
        assert_skin(visitor, skin)
        seen = measure_edges(visitor, rows)
        for selector, ground in PRIMARY_BORDERS[skin]:
            row = seen[selector]
            assert_painted(row, "border", f"{skin} {accent} primary")
            assert rgb(row["value"]) == hex_to_rgb(accent), (
                f"{skin} {selector} border is {row['value']}, not the raw "
                f"{accent} — the retarget has been widened to the bare "
                ".button rule, which paints every primary button too"
            )
            assert rgb(row["value"]) == rgb(row["own"]), (
                f"{skin} {selector}: border {row['value']} no longer equals "
                f"its own fill {row['own']}"
            )
            # And the ground it actually sits on, so the docstring's reason
            # is a measured fact rather than a claim about the stylesheets.
            assert row["under"] == ground, (selector, row["under"])


@pytest.mark.parametrize(
    "skin,selector,edge,text",
    (
        ("v1", ".cta-row .button.secondary", (89, 157, 123), (58, 126, 92)),
        ("v2", ".v2-hero-card .button.secondary", (82, 150, 116),
         (52, 120, 86)),
    ),
    ids=("v1", "v2"),
)
def test_the_edge_token_is_not_the_text_token(
    page, live_app, skin, selector, edge, text
):
    """THE ANTI-FOLD ASSERTION, in the browser this time.

    One element, two derivations, both reaching it: `.button.secondary`
    takes --accent-fg on its label and --accent-edge on its border. With
    #66aa88 chosen they are #599d7b and #3a7e5c on V1 and #529674 and
    #347856 on V2 — different colours, because 3:1 and 4.5:1 are different
    claims and the edge does not have to walk as far.

    Alias the two derivations and this row's border becomes the label's
    colour: the inequality fails, and it fails on the element where both
    tokens are visible at once rather than in a module test. Both floors are
    asserted alongside it, so a fold that happened to keep them apart would
    still have to clear each claim on its own ground.
    """
    plant(live_app, skin, accent="#66aa88")
    rows = ((selector, "borderTopColor", None, "border"),)
    with anonymous(page.context.browser, live_app) as (visitor, _):
        assert_skin(visitor, skin)
        row = measure_edges(visitor, rows)[selector]
        assert_painted(row, "border", f"{skin} anti-fold")
        assert rgb(row["value"]) == edge, row["value"]
        assert rgb(row["color"]) == text, row["color"]
        assert rgb(row["value"]) != rgb(row["color"]), (
            f"{skin} {selector}: the border and the label are the same "
            "colour, so the edge derivation has been folded into the text one"
        )
        ground = rgb(row["under"])
        assert ratio(rgb(row["value"]), ground) >= 3.0
        assert ratio(rgb(row["color"]), ground) >= 4.5


def test_the_v2_section_bar_is_drawn_at_desktop_and_deleted_at_the_phone_width(
    page, live_app
):
    """WITHOUT THIS, THE ::after ROW ABOVE COULD PASS ON A BOX NOBODY PAINTS.

    style-v2.css deletes the bar outright below 720px with `content: none`
    (the phone spec says no rule is drawn beneath the label there). A
    generated box that does not exist still answers getComputedStyle with a
    backgroundColor, so a ratio taken from it would be green and meaningless
    — the pseudo-element form of exactly the hazard the painted-edge
    precondition closes for borders.

    So both widths are asserted, on the same page with the same colour
    chosen: content is '""' and the box is 3px tall at 1280, and content is
    `none` at 390.
    """
    plant(live_app, "v2", accent="#ffe9a8")
    rows = tuple(
        row for row in EDGE_SITES["v2"] if row[2] == "::after"
    )
    selector = rows[0][0]
    browser = page.context.browser
    with anonymous(browser, live_app) as (visitor, _):
        row = measure_edges(visitor, rows)[selector]
        assert_painted(row, "bar", "v2 desktop")
        assert rgb(row["value"]) == (156, 134, 69)
    with anonymous(
        browser, live_app, viewport=PHONE_VIEWPORT
    ) as (visitor, _):
        row = measure_edges(visitor, rows)[selector]
        assert row["found"] and row["rendered"]
        assert row["content"] == "none", (
            "the phone breakpoint no longer deletes the bar, so the desktop "
            "row above may be measuring a box the browser never paints"
        )


def test_the_direct_edit_focus_ring_reaches_three_to_one(
    page, live_app, shots
):
    """THE HIGHEST-VALUE SITE OF THE SIX, and the one the ask names first: a
    focus indicator nobody can see is the same as no focus indicator.

    V1's /muokkaa/sivu is the one route that both receives the override and
    draws its own ring. The field is focused for real — direct-edit.js sets
    contentEditable at bind time, so page.focus() reaches it the way Tab
    does — and the ring is measured against the walked CONTAINER, because
    an outline sits at outline-offset 3px outside the border box and the
    field's own translucent fill is not under it.

    MEASURED BEFORE AND AFTER, in real Chrome, with #ffe9a8 chosen. Before
    this change the ring computed rgb(255, 233, 168): 1.2019:1 on --card
    #ffffff and 1.1247:1 on --paper #faf7f2 — drawn, and invisible. After
    it computes rgb(163, 141, 76) on --paper, which is what this asserts.

    The screenshot is taken by this test rather than a separate one, so no
    picture here can be filed as evidence without a number beside it.
    """
    plant(live_app, "v1", accent="#ffe9a8")
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    page.wait_for_selector(DIRECT_FIELD)
    page.focus(DIRECT_FIELD)
    row = measure_edges(page, (DIRECT_ROW,))[DIRECT_FIELD]
    assert_painted(row, "outline", "v1 focus ring")
    assert row["outlineStyle"] == "solid"
    assert row["outlineWidth"] == "2px"
    ground = rgb(row["under"])
    assert ground == (250, 247, 242), row["under"]
    # The ratio FIRST and the exact value after it, so a revert of
    # direct-edit.css's focus rule reports the number it collapsed to rather
    # than only that a literal moved.
    measured = ratio(rgb(row["value"]), ground)
    assert measured >= 3.0, (
        f"the focus ring is {measured:.4f}:1 "
        f"({row['value']} on {row['under']})"
    )
    assert rgb(row["value"]) == (163, 141, 76), row["value"]
    path = os.path.join(shots, "edge-focus-v1.png")
    page.screenshot(path=path)
    assert os.path.getsize(path) > 0


def test_the_v2_direct_edit_page_draws_no_author_outline_at_all(
    page, live_app, shots
):
    """A RECORDED DEFECT, PINNED HONESTLY — this change does not fix it.

    direct-edit.css is loaded by /muokkaa/sivu on both skins and names
    --accent-edge, which style-v2.css does not declare (it declares
    --v2-rust-edge; the same was true of --accent before this change). An
    undeclared custom property makes the `outline` shorthand invalid at
    computed-value time, so outline-style computes to `none` — v2's
    direct-edit page has NO author focus ring, and had none before this
    change either. Measured at 78d5d8e and again here.

    So the assertion is what is TRUE, not what ought to be. It is written to
    go RED the day somebody gives v2 a ring, which is the only honest way to
    hold a defect open — and the ratio assertion that would replace it is one
    line away. The screenshot is the picture of the gap.

    IT ASSERTS NOT-PAINTED, NOT A WIDTH LITERAL, and that distinction cost a
    red CI run. `outline-width` is a UA-supplied value when the outline is
    off: Chrome 142 collapses it to `0px`, Chrome 152 reports the UA default
    `3px` and lets `outline-style: none` be the thing that suppresses the
    ring. Both draw nothing. So `outlineWidth == "0px"` was a claim about a
    browser VERSION rather than about whether a ring is painted, and it went
    red on a Chrome upgrade with the product unchanged. The predicate here is
    the exact negation of assert_painted's — style not none/hidden AND a
    non-zero width — so it still fires the day v2 gains a real ring, which is
    the whole point of the tripwire.
    """
    plant(live_app, "v2", accent="#ffe9a8")
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    page.wait_for_selector(DIRECT_FIELD)
    page.focus(DIRECT_FIELD)
    row = measure_edges(page, (DIRECT_ROW,))[DIRECT_FIELD]
    assert row["found"] and row["rendered"]
    ring_is_painted = (
        row["outlineStyle"] not in ("none", "hidden")
        and float(row["outlineWidth"].rstrip("px")) > 0
    )
    assert not ring_is_painted, (
        "v2's direct-edit page now draws an author focus ring "
        f"({row['outlineWidth']} {row['outlineStyle']} {row['value']}). That "
        "is the fix this test was written to notice: replace it with the 3:1 "
        "assertion test_the_direct_edit_focus_ring_reaches_three_to_one makes"
    )
    # And the chrome's own secondary buttons DO take the edge token on v2,
    # so the page is not simply missing the override.
    chrome = (".direct-topbar .button.secondary", "borderTopColor", None,
              "border")
    button = measure_edges(page, (chrome,))[chrome[0]]
    assert_painted(button, "border", "v2 direct chrome")
    assert rgb(button["value"]) == (156, 134, 69), button["value"]
    assert ratio(rgb(button["value"]), rgb(button["under"])) >= 3.0
    path = os.path.join(shots, "edge-focus-v2.png")
    page.screenshot(path=path)
    assert os.path.getsize(path) > 0


# --- LLM-COP-42: the five direct-edit chrome sites, driven -----------------

# The heading the chrome is driven from. It is the one h1 carrying a
# data-field on either template (page.html:57, page_v2.html:137) and it is
# `"title": {"type": "plain"}` in app/fields.py:17 — which is why the
# toolbar test below has exactly one enabled button to hover.
DIRECT_HEADING = "h1[data-field]"

# THE GROUND THAT IS NOT FROZEN, the same sentinel idea app/palette.py's
# MAIN is. Two of the three text sites sit on --card, a frozen literal; the
# third sits on the owner's own pick, which has no literal until a case
# names one.
OWN_ACCENT = "<the owner's own pick>"

# The three TEXT sites LLM-COP-42 retargeted, with the ground each is
# actually read against and the TOKEN whose derived value must land there.
#
# THE GROUNDS ARE THE CLAIM, which is why each one is asserted before its
# ratio. --accent-fg is readable_on(accent, V1_SURFACES), so the first two
# are only covered while they really sit on a member of that tuple — both
# are inside a chrome bar whose `background: var(--card)` is the frozen
# #ffffff no owner role can move.
#
# .direct-field-tag is the ODD ONE, and the reason it takes --accent-ink
# rather than --accent-fg: its ground is its OWN `background: var(--accent)`,
# so the surface under it is whatever the owner picked — which is why its
# ground is OWN_ACCENT rather than a literal, and why the ground assertion
# below is a real check rather than a restatement. --accent-fg says nothing
# about legibility there, and the three picks make that concrete rather than
# arguable: on #ffe9a8 it is #856f2e at 4.0536:1 ON THE ACCENT, on #4fb3bf
# it is #197d89 at 1.9679:1, and on #3b1f47 it is the accent ITSELF at
# 1.0000:1 — a fresh SC 1.4.3 failure at every one of the three picks, two
# of them total. --accent-ink is on_color(accent) and is >= 4.5826:1 against
# every admissible colour.
DIRECT_TEXT_SITES = (
    (".direct-esikatsele", (255, 255, 255), "fg"),
    (".direct-changes", (255, 255, 255), "fg"),
    (".direct-field-tag", OWN_ACCENT, "ink"),
)

# THE THREE OWNER PICKS every V1 site below is driven at. Three different
# JOBS for the derivation rather than three colours, and each is stated
# because a pick that leaves the derivation nothing to do proves nothing
# about it.
#
# #ffe9a8 PALE is kept from the single-colour form of these tests. It is the
# defect LLM-COP-42 was filed for — raw, 1.2019:1 against the chrome bars'
# --card — and every measured number in the plan and in app/palette.py's
# site list is this colour's. Changing it would orphan all of them.
#
# #4fb3bf MID is a colour nothing else in this file or in the app depends
# on, and it is the one pick of the three that makes BOTH walks run: raw it
# is 2.4611:1 on --card, which fails SC 1.4.3's 4.5 AND SC 1.4.11's 3.0, so
# --accent-fg has to move it (to #197d89, 4.8432:1) and --accent-edge has to
# move it too, and to a DIFFERENT place (#389ca8, 3.2363:1). The pale pick
# exercises both as well, but from so far out that a derivation overshooting
# wildly would still land somewhere legible. A mid pick is what catches a
# walk that stops one constant short, because 2.4611 is under 3 without
# being absurd.
#
# #3b1f47 DARK is the IDENTITY case, and its value is the opposite claim:
# the derivation must leave a colour that ALREADY reads alone. Raw it is
# 14.2572:1 on --card, so --accent-fg and --accent-edge must both hand back
# #3b1f47 untouched, and any ratio here that is not 14.2572 is this module
# rewriting the owner's own colour. It is also the only pick of the three
# where on_color flips: --accent-ink is #ffffff, not #000000, so
# .direct-field-tag's label is proved at BOTH polarities across the set.
#
# WHAT THE DARK PICK CANNOT DO, stated here rather than left to be found.
# Because the derivation is the identity at #3b1f47, --accent-fg,
# --accent-edge and the raw --accent are one and the same colour there, and
# --accent-ink is the same #ffffff the pre-LLM-COP-42 `color: #fff` literal
# computed to. So reverting any one of the five retargeted declarations
# leaves the dark case GREEN. The dark case is a DOES-NO-HARM proof, not a
# revert guard. The revert guard is the pale and mid cases, where all five
# go red — and a derivation that stopped returning the identity is caught
# here and nowhere else.
DIRECT_CASES = ("#ffe9a8", "#4fb3bf", "#3b1f47")

# What app/palette.py must derive from each pick, for the three tokens these
# five sites read. WRITTEN OUT — not imported, not recomputed — for exactly
# the reason this file's docstring gives about the ratios: a table built by
# calling readable_on / on_color / visible_on would agree with those
# functions whatever they did, and the point of a value pin is that it can
# DISAGREE with the module under proof. Every triple below was read back out
# of Chrome, off the element that owns the declaration.
DIRECT_DERIVED = {
    # the owner's pick: --accent-fg, --accent-ink, --accent-edge
    "#ffe9a8": {"fg": (133, 111, 46), "ink": (0, 0, 0),
                "edge": (163, 141, 76)},
    "#4fb3bf": {"fg": (25, 125, 137), "ink": (0, 0, 0),
                "edge": (56, 156, 168)},
    "#3b1f47": {"fg": (59, 31, 71), "ink": (255, 255, 255),
                "edge": (59, 31, 71)},
}


def direct_ground(where, accent):
    """A text site's ground: the frozen literal, or the owner's own pick."""
    return hex_to_rgb(accent) if where == OWN_ACCENT else where

# The toolbar button the hover test drives, and the un-hovered control it is
# measured against. See that test's docstring for why the control is a
# disabled button and what that does and does not prove.
DIRECT_UNDO = ".direct-toolbar button.direct-undo"
DIRECT_UNHOVERED = ".direct-toolbar button.direct-list"

# The colours a chosen #ffe9a8 can produce, on EITHER skin: the raw pick and
# every value app/palette.py derives from it (--accent / --v2-rust and their
# -dark, -ink, -dark-ink, -fg, -edge, -ring and header variants). Written
# out rather than imported, so the V2 test's "nothing here came from the
# override" is a statement this file makes ABOUT that module rather than one
# it borrows from it.
ACCENT_DERIVED_FFE9A8 = frozenset(
    {
        (255, 233, 168),  # --accent / --v2-rust, the raw pick
        (204, 186, 134),  # -dark
        (0, 0, 0),        # -ink, -dark-ink
        (138, 116, 51),   # --header-accent
        (133, 111, 46),   # --accent-fg
        (163, 141, 76),   # --accent-edge, --accent-ring
        (169, 147, 82),   # --accent-ring-header
        (122, 100, 35),   # --v2-header-accent
        (127, 105, 40),   # --v2-rust-fg
        (156, 134, 69),   # --v2-rust-edge, --v2-rust-ring
        (151, 129, 64),   # --v2-rust-ring-header
    }
)


def open_direct_chrome(page, live_app, skin, accent):
    """Drive the chrome into existence the way a person does.

    NOTHING BELOW IS MEASURED ON A HIDDEN ELEMENT, and that is not a
    precaution — it is the difference between a proof and a vacuous one.
    .direct-field-tag, .direct-toolbar and .direct-changes all ship `hidden`
    (direct_edit_chrome.html:31, :34, :53). getComputedStyle on a
    display:none element still returns a `color`, so a test that skipped the
    click and the keystroke would read three colours off three elements
    nobody can see and go green. That hazard is already recorded for these
    two elements in test_typing_updates_the_change_count_and_the_field_counter.

    The click runs direct-edit.js's activate(), which unhides the tag and
    the toolbar; the keystroke runs updateChanges(), which unhides the badge
    on the first real change. Both are the product's own code doing its own
    job — no fixture sets hidden = false.

    `accent` is a parameter rather than a constant because the five sites
    are derived per colour: one pick proves the wiring, three prove the
    derivation. See DIRECT_CASES for what each of the three is for.
    """
    plant(live_app, skin, accent=accent)
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    assert_skin(page, skin)
    page.wait_for_selector(DIRECT_HEADING)
    page.click(DIRECT_HEADING)
    page.keyboard.type("X")


@pytest.mark.parametrize("accent", DIRECT_CASES, ids=("pale", "mid", "dark"))
def test_the_direct_edit_chrome_text_clears_four_and_a_half_to_one(
    page, expect, live_app, shots, accent
):
    """THE THREE TEXT SITES OF LLM-COP-42, driven and measured on V1, at a
    PALE, a MID and a DARK owner pick.

    Before this change all three rendered the owner's raw pick: with
    #ffe9a8 chosen, .direct-esikatsele and .direct-changes were
    rgb(255,233,168) on the chrome bars' #ffffff and .direct-field-tag was
    rgb(255,255,255) on the accent itself — 1.2019:1 at every one of them,
    three SC 1.4.3 failures on the page an owner spends their editing time
    in. After it, at the three picks in order: 4.8718 / 4.8432 / 14.2572 for
    .direct-esikatsele and .direct-changes, and 17.4730 / 8.5328 / 14.2572
    for .direct-field-tag.

    ONE PICK PROVED THE WIRING; THREE PROVE THE DERIVATION. --accent-fg and
    --accent-ink are computed per colour, so a single colour can only say
    that some value arrived. Whether the walk that produced it actually
    clears 4.5:1 for a colour it had to move a long way (pale), a short way
    (mid) or not at all (dark) is three separate questions, and DIRECT_CASES
    says which one each pick asks.

    EVERY COLOUR IS READ OFF THE ELEMENT THAT OWNS THE DECLARATION, never
    off .direct-topbar or .direct-publishbar. That is USR-COP-2's ancestor
    hazard, stated in this file's own docstring: an earlier draft of that
    plan read `color` off .site-header and would have gone green while the
    brand rendered at 1.07:1. A container's ink is not the ink of a child
    that sets its own.

    THE GROUND IS ASSERTED PER PICK, and for .direct-field-tag it MOVES with
    the pick — its ground is its own `background: var(--accent)`, one of the
    two fills LLM-COP-42 deliberately left raw. So this test also proves,
    three times over, that that fill is still the owner's pick and not a
    derived value: if the background had been retargeted too, --accent-ink
    would be on_color of a colour nobody is looking at, and the ground
    assertion says so before any ratio is taken.

    The visibility expectations come FIRST, before any measurement, for the
    reason open_direct_chrome gives.

    The ratio is asserted BEFORE the exact triple, deliberately: on a revert
    the ratio reports the number the site collapsed to (1.2019 at the pale
    pick, 2.4611 at the mid one) rather than only that a literal moved, and
    the triple after it catches a right-ratio-wrong-token wiring error the
    ratio alone would accept.
    """
    open_direct_chrome(page, live_app, "v1", accent)
    expect(page.locator(".direct-field-tag")).to_be_visible()
    expect(page.locator(".direct-changes")).to_be_visible()

    derived = DIRECT_DERIVED[accent]
    seen = measure(page, [site for site, _, _ in DIRECT_TEXT_SITES])
    for selector, where, token in DIRECT_TEXT_SITES:
        ground = direct_ground(where, accent)
        row = seen[selector]
        assert row["found"], f"{selector} is not on the page"
        assert row["rendered"], f"{selector} rendered at zero size"
        assert rgb(row["background"]) == ground, (
            f"{accent} {selector} is read against {row['background']}, not "
            f"the {ground} the derivation was computed for"
        )
        measured = ratio(rgb(row["color"]), ground)
        assert measured >= 4.5, (
            f"{accent} {selector} is {measured:.4f}:1 "
            f"({row['color']} on {row['background']})"
        )
        assert rgb(row["color"]) == derived[token], (
            f"{accent} {selector}: {row['color']}, not the "
            f"{derived[token]} --accent-{token} must derive to"
        )

    path = os.path.join(
        shots, f"direct-chrome-text-v1-{accent.lstrip('#')}.png"
    )
    page.screenshot(path=path)
    assert os.path.getsize(path) > 0


@pytest.mark.parametrize("accent", DIRECT_CASES, ids=("pale", "mid", "dark"))
def test_the_direct_edit_change_badge_border_reaches_three_to_one(
    page, expect, live_app, accent
):
    """The publish bar's change badge is a pill DRAWN in the accent.

    Its border was `1px solid var(--accent)` — 1.2019:1 against the bar's
    #ffffff, a line nobody can see. It is now var(--accent-edge): 3.2449:1
    at the pale pick, 3.2363:1 at the mid one and 14.2572:1 at the dark one,
    where visible_on returns the identity and there was never a defect.

    THREE PICKS, because --accent-edge is derived per colour and 3:1 is a
    claim about each derived value, not about the token's name. The mid pick
    is the load-bearing one for this site: raw #4fb3bf is 2.4611:1, under
    SC 1.4.11 without being visibly absurd, which is the shape of failure a
    pale-only test passes over. DIRECT_CASES says what each pick is for and
    is explicit that the dark one cannot catch a revert here.

    THE BADGE DOES NOT EXIST UNTIL SOMETHING CHANGES. It ships `hidden` and
    updateChanges() unhides it on the first edit, so the keystroke inside
    open_direct_chrome is what produces the element this measures, and the
    to_be_visible is what proves that worked.

    assert_painted runs before the ratio and IS the CI-safe form of the
    precondition: a predicate (width > 0, style not none/hidden), never a
    width literal. Pinning a UA-supplied width is what took LLM-COP-40 green
    locally and red on CI — the incident is recorded in full in
    test_the_v2_direct_edit_page_draws_no_author_outline_at_all's docstring
    above. Nothing in this test or its sibling pins borderTopWidth.
    """
    open_direct_chrome(page, live_app, "v1", accent)
    expect(page.locator(".direct-changes")).to_be_visible()

    spec = (".direct-changes", "borderTopColor", None, "border")
    row = measure_edges(page, (spec,))[".direct-changes"]
    assert_painted(row, "border", f"v1 {accent} change badge")
    for ground in edge_grounds(row, "border"):
        measured = ratio(rgb(row["value"]), rgb(ground))
        assert measured >= 3.0, (
            f"{accent} .direct-changes border is {measured:.4f}:1 "
            f"({row['value']} on {ground})"
        )
    assert rgb(row["value"]) == DIRECT_DERIVED[accent]["edge"], (
        f"{accent} .direct-changes border is {row['value']}, not the "
        f"{DIRECT_DERIVED[accent]['edge']} --accent-edge must derive to"
    )


@pytest.mark.parametrize("accent", DIRECT_CASES, ids=("pale", "mid", "dark"))
def test_the_direct_edit_toolbar_hover_border_reaches_three_to_one(
    page, expect, live_app, shots, accent
):
    """The format toolbar's hover edge, produced by a REAL page.hover(), at
    a PALE, a MID and a DARK owner pick.

    Same three picks and the same reason as the badge above: --accent-edge
    is derived per colour, so 3:1 is a claim about each derived value.
    3.2449:1, 3.2363:1 and 14.2572:1 in DIRECT_CASES order.

    The rule is `.direct-toolbar button:hover:not(:disabled)`, so two things
    must be true before a measurement means anything, and both are asserted
    rather than assumed. The toolbar has to be unhidden — the click in
    open_direct_chrome runs activate(), which does that — and the button
    under the pointer has to be ENABLED, because :not(:disabled) would
    otherwise void the selector in silence and leave this test measuring the
    base rule while reporting on the hover one.

    THE BUTTON IS .direct-undo AND THE CHOICE IS FORCED. activate() sets
    `button.disabled = !field.rich` on the three .direct-command buttons
    (direct-edit.js:164) and app/fields.py:17 declares "title" as a PLAIN
    field, so B / I / Linkki are all disabled here; .direct-list ships
    disabled in the template (direct_edit_chrome.html:38). .direct-undo is
    the only enabled button on a plain field. Hovering any other one would
    be vacuous.

    THE VACUITY GUARD, and what it does NOT prove. A second, un-hovered
    button is measured in the same evaluate and must still read
    rgb(228,221,211), the --line grey of the base `.direct-toolbar button`
    rule. That proves the base value is DISTINGUISHABLE from the hover
    value, so a test that failed to produce a hover at all would read the
    grey and go red rather than pass on the wrong colour — which is the
    whole job of the guard. It does NOT prove the hover was scoped to one
    button: the control, .direct-list, is a DISABLED sibling, and a disabled
    button keeps the base border whether or not :hover leaked to it
    (`.direct-toolbar button:disabled` sets only opacity and cursor). On a
    plain field there is no enabled un-hovered sibling to use instead —
    .direct-command x3 are disabled by direct-edit.js:164 and .direct-list
    by the template — so the choice of control is forced too, and this says
    so rather than implying the guard is stronger than it is.

    THE CONTROL'S GREY IS NOT DERIVED, so it does not move with the pick:
    --line is #e4ddd3, a frozen literal on V1 that no ROLE_TOKENS row emits.
    That is what lets one hardcoded rgb(228,221,211) serve all three cases,
    and it is also why the guard still works at the dark pick, where the
    hover value is the raw accent — the two are still far apart.

    A SCREENSHOT PER PICK, because this hovered edge is the one of the five
    sites no resting shot can show.
    """
    open_direct_chrome(page, live_app, "v1", accent)
    expect(page.locator(".direct-toolbar")).to_be_visible()
    assert not page.locator(DIRECT_UNDO).is_disabled(), (
        "Kumoa is disabled, so :hover:not(:disabled) can never match and "
        "this test would measure the base border while claiming the hover"
    )

    page.hover(DIRECT_UNDO)
    rows = (
        (DIRECT_UNDO, "borderTopColor", None, "border"),
        (DIRECT_UNHOVERED, "borderTopColor", None, "border"),
    )
    seen = measure_edges(page, rows)
    hovered, control = seen[DIRECT_UNDO], seen[DIRECT_UNHOVERED]

    assert_painted(hovered, "border", f"v1 {accent} toolbar hover")
    for ground in edge_grounds(hovered, "border"):
        measured = ratio(rgb(hovered["value"]), rgb(ground))
        assert measured >= 3.0, (
            f"{accent}: the hovered toolbar border is {measured:.4f}:1 "
            f"({hovered['value']} on {ground})"
        )
    assert rgb(hovered["value"]) == DIRECT_DERIVED[accent]["edge"], (
        f"{accent}: the hovered toolbar border is {hovered['value']}, not "
        f"the {DIRECT_DERIVED[accent]['edge']} --accent-edge must derive to"
    )
    assert rgb(control["value"]) == (228, 221, 211), (
        f"the un-hovered control reads {control['value']}, not the --line "
        "grey — the base and the hover values are no longer distinguishable, "
        "so the assertion above could be satisfied with no hover at all"
    )

    path = os.path.join(
        shots, f"direct-chrome-hover-v1-{accent.lstrip('#')}.png"
    )
    page.screenshot(path=path)
    assert os.path.getsize(path) > 0


def test_the_v2_direct_edit_chrome_takes_no_colour_from_the_override(
    page, expect, live_app, shots
):
    """A RECORDED DEFECT, PINNED HONESTLY — and a live revert guard.

    direct-edit.css speaks V1's token vocabulary. style-v2.css declares none
    of --accent, --accent-fg, --accent-ink, --accent-edge, --card or --line,
    so every rule LLM-COP-42 touched is invalid at computed-value time on V2
    and the owner's pick reaches NONE of these five sites. That is what this
    pins. LLM-COP-42 does not fix it: that is a different bug — "the file
    speaks a vocabulary V2 does not declare" — with its own argument to make,
    and it is filed separately rather than bundled in here.

    READ THE 6.4593:1 BELOW AS AN ACCIDENT, BECAUSE THAT IS WHAT IT IS.
    `color` is an INHERITED property. A declaration whose var() names an
    undeclared custom property is invalid at computed-value time, so it
    becomes `unset` — and `unset` on an inherited property is `inherit`, NOT
    a fall-through to the next declaration in the cascade. .direct-chrome is
    a direct child of body (page_v2.html:387) and style-v2.css:115 is
    `body { color: var(--v2-body) }` = #3d5f77, on --v2-page #f7fafc. So the
    tag lands on 6.4593:1 BY FAILURE MODE. It is NOT a claim app/palette.py
    makes, and no derivation guarantees it. Before LLM-COP-42
    .direct-field-tag's `color: #fff` was a valid literal and computed white
    — 1.0482:1 — so this site became legible on V2 as a SIDE EFFECT of the
    retarget.

    It will change the day V2 gets the token vocabulary. REPLACE THIS TEST
    THEN with the 4.5:1 assertions
    test_the_direct_edit_chrome_text_clears_four_and_a_half_to_one makes.

    Meanwhile the pin is more than a defect record: reverting
    .direct-field-tag's color to #fff turns it RED with rgb(255,255,255)
    printed, so site 2 of the five is guarded here as well as on V1.

    IT STAYS ON ONE COLOUR while its three V1 siblings run at three, and
    that is deliberate rather than an omission. Those three assert a
    DERIVATION, which is a different function of every pick and therefore
    has to be sampled. This one asserts a CASCADE ACCIDENT: the value it
    pins, #3d5f77, is body's --v2-body and is the same whatever the owner
    picks, because not one declaration here resolves. Driving it at three
    picks would produce three identical measurements and read as three
    proofs. The one thing that IS pick-shaped is the stray set below, and
    ACCENT_DERIVED_FFE9A8 is written out for this colour precisely so the
    negative can be made without importing the derivation.

    THE TWO NEGATIVES ARE PREDICATES, NEVER WIDTH LITERALS — the exact
    negation of assert_painted. Border and outline widths are UA-supplied
    when the feature is off: Chrome 142 collapses to 0px, Chrome 152 reports
    the UA default and lets `style: none` be what suppresses the edge.
    Pinning one of those is what went green locally and red on CI in
    LLM-COP-40.
    """
    open_direct_chrome(page, live_app, "v2", "#ffe9a8")
    expect(page.locator(".direct-field-tag")).to_be_visible()
    expect(page.locator(".direct-changes")).to_be_visible()

    values = []
    seen = measure(page, [site for site, _, _ in DIRECT_TEXT_SITES])
    for selector, _v1_ground, _v1_token in DIRECT_TEXT_SITES:
        row = seen[selector]
        assert row["found"] and row["rendered"], selector
        assert rgb(row["color"]) == (61, 95, 119), (
            f"{selector} is {row['color']}, not body's inherited --v2-body "
            "— V2's cascade has moved and this pin is out of date"
        )
        assert rgb(row["background"]) == (247, 250, 252), row["background"]
        measured = ratio(rgb(row["color"]), rgb(row["background"]))
        assert round(measured, 4) == 6.4593, f"{selector}: {measured:.4f}:1"
        values.append(rgb(row["color"]))

    # The tag's `background: var(--accent)` is invalid here too, so it has no
    # fill at all — body-coloured text on the page ground, legible but no
    # longer looking like a tag. Asserted because it is the other half of why
    # the 6.4593:1 above is luck: on V1 this site's ground IS the owner's
    # pick, which is what makes --accent-ink the right token there.
    assert seen[".direct-field-tag"]["backgroundOwn"] == "rgba(0, 0, 0, 0)", (
        seen[".direct-field-tag"]["backgroundOwn"]
    )

    page.hover(DIRECT_UNDO)
    rows = (
        (".direct-changes", "borderTopColor", None, "border"),
        (DIRECT_UNDO, "borderTopColor", None, "border"),
    )
    edges = measure_edges(page, rows)
    for selector, _property, _pseudo, _kind in rows:
        row = edges[selector]
        assert row["found"] and row["rendered"], selector
        painted = (
            row["borderTopStyle"] not in ("none", "hidden")
            and float(row["borderTopWidth"].rstrip("px")) > 0
        )
        assert not painted, (
            f"{selector} now draws a border on V2 "
            f"({row['borderTopWidth']} {row['borderTopStyle']} "
            f"{row['value']}). That is the fix this test was written to "
            "notice: replace it with the 3:1 assertions the V1 edge tests "
            "make"
        )
        values.append(rgb(row["value"]))

    # All five retargeted sites, and not one of them carries a colour the
    # override could have produced on either skin.
    assert len(values) == 5, values
    strays = [value for value in values if value in ACCENT_DERIVED_FFE9A8]
    assert not strays, (
        f"V2's edit chrome now takes colour from the owner's pick: {strays}"
    )

    path = os.path.join(shots, "direct-chrome-text-v2.png")
    page.screenshot(path=path)
    assert os.path.getsize(path) > 0


def test_the_edge_token_never_reaches_the_admin_inbox(page, live_app, skin):
    """style.css:116 now reads --accent-edge, and inbox.html links style.css.

    /yllapito/viestit renders .button.secondary and receives no site_chrome
    spread, so no <style> block reaches it whatever an owner picks — which
    means the new token has to resolve through its :root DEFAULT there. If
    it had been added without one, border-color would be invalid at
    computed-value time and fall back to currentColor: a visible regression
    on a page nobody tests for colour.

    The border is proved PAINTED before its value is read, for that exact
    reason — currentColor is what the failure would look like, and on this
    element it would be the accent-fg green, which is the same value this
    asserts. Nothing about the border tells the two apart — the width and
    style come from the bare `.button` rule, which the invalid declaration
    leaves alone. The custom property itself is read below, because it is
    the only thing that differs.
    """
    plant(live_app, skin, main=PANEL_MAIN, accent="#ffe9a8")
    public = page.goto(f"{live_app.base_url}/")
    assert public.status == 200
    assert "<style" in public.text(), "the colour never reached the page"

    inbox = page.goto(f"{live_app.base_url}/yllapito/viestit")
    assert inbox.status == 200, "the inbox route moved; the check below is void"
    assert "<style" not in inbox.text()
    # THE DISCRIMINATING READ, and it is the only assertion here that can
    # tell the two worlds apart. Delete style.css's `--accent-edge:
    # var(--accent)` and every other assertion in this test stays green:
    # border-color becomes invalid at computed-value time, falls back to
    # currentColor, and this element's color is var(--accent-fg) ->
    # var(--accent) -> the same #1f6f5c the value pin below expects. The
    # custom property is the one thing that differs — "#1f6f5c" with the
    # default present, "" without it. Measured both ways.
    declared = page.evaluate(
        "getComputedStyle(document.documentElement)"
        ".getPropertyValue('--accent-edge').trim()"
    )
    assert declared == "#1f6f5c", (
        "style.css declares no :root default for --accent-edge, so on a page "
        "that receives no override border-color is invalid at "
        "computed-value time and falls back to currentColor — which on this "
        "element is the same green, so the value pin below cannot see it"
    )
    rows = ((".button.secondary", "borderTopColor", None, "border"),)
    row = measure_edges(page, rows)[".button.secondary"]
    assert_painted(row, "border", "inbox")
    assert rgb(row["value"]) == (31, 111, 92), (
        f"the inbox's secondary button border is {row['value']}, not "
        "style.css's own --accent — the edge token has no :root default"
    )


# --- 7: the surface SET, not just its values --------------------------------

# Every element in the document whose PAINTED edge is the derived colour, and
# the ground under each. app/palette.py's own comment says the surface VALUES
# are fenced and the SET is not — a future rule painting the accent on a dark
# band would pass every source-text and arithmetic test there is. This is the
# edge half of that missing fence, and it is not circular: the tuple is the
# claim and the rendered DOM is the evidence.
#
# THE GROUND RULE IS THE ONE measure_edges USES, deliberately and stated in
# both places: a border hit takes its own opaque fill plus the walk from
# el.parentElement, an outline hit takes the walk from el.parentElement
# alone, and a pseudo-background hit walks from `el` ITSELF. One rule, two
# call sites, so a hit found here is measured the way test 2 would measure it.
#
# UNPAINTED EDGES ARE NOT HITS. The same width-and-style precondition runs
# inside the sweep, which is what keeps every accent-TEXT element in the
# document — whose borderTopColor is currentColor — out of the result.
_SWEEP_EDGES = """
(sentinel) => {
  const opaque = (raw) => {
    const parts = (raw.match(/[\\d.]+/g) || []).map(Number);
    return parts.length >= 3 && (parts.length < 4 || parts[3] > 0);
  };
  const walk = (node) => {
    while (node) {
      const raw = getComputedStyle(node).backgroundColor;
      if (opaque(raw)) return raw;
      node = node.parentElement;
    }
    return null;
  };
  const where = (el) => {
    const bits = [el.tagName.toLowerCase()];
    if (el.id) bits.push('#' + el.id);
    if (el.className && typeof el.className === 'string') {
      bits.push('.' + el.className.trim().split(/\\s+/).join('.'));
    }
    return bits.join('');
  };
  const painted = (width, style) =>
    parseFloat(width) > 0 && style !== 'none' && style !== 'hidden';
  const hits = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (cs['border' + side + 'Color'] !== sentinel) continue;
      if (!painted(cs['border' + side + 'Width'],
                   cs['border' + side + 'Style'])) continue;
      const grounds = [];
      if (opaque(cs.backgroundColor)) grounds.push(cs.backgroundColor);
      const up = walk(el.parentElement);
      if (up) grounds.push(up);
      hits.push({ what: where(el), kind: 'border-' + side.toLowerCase(),
                  grounds });
    }
    if (cs.outlineColor === sentinel
        && painted(cs.outlineWidth, cs.outlineStyle)) {
      const up = walk(el.parentElement);
      hits.push({ what: where(el), kind: 'outline', grounds: up ? [up] : [] });
    }
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo);
      if (ps.content === 'none' || ps.content === 'normal') continue;
      if (ps.backgroundColor !== sentinel) continue;
      const up = walk(el);
      hits.push({ what: where(el) + pseudo, kind: 'pseudo-background',
                  grounds: up ? [up] : [] });
    }
  }
  return hits;
};
"""

# Where the sweep runs. `/` on both skins, and /muokkaa/sivu on both — the
# plan scoped the second to v1, where the outlines live, but v2's copy of the
# chrome carries four secondary buttons on a different ground (body
# --v2-page, because .direct-topbar's `background: var(--card)` is invalid on
# a skin that declares no --card) and sweeping it is strictly more fence for
# no more machinery. Both were run; both are green.
SWEEP_ROUTES = ("/", "/muokkaa/sivu")


def edge_token_in(document, skin):
    """The value the page's own <style> block gave the edge token.

    READ OFF THE SERVED DOCUMENT, not computed by calling visible_on. The
    needle this sweep hunts for has to be the colour that actually reached
    the browser; deriving it from the module under proof would make the
    sweep agree with that module by construction, and a wrong derivation
    would simply be hunted for under its own wrong value.
    """
    from app.palette import ROLE_TOKENS

    token = ROLE_TOKENS[skin]["accent_edge"]
    found = re.search(rf"{token}:(#[0-9a-f]{{6}});", document)
    assert found, f"{token} is in no <style> block on this page"
    return found.group(1)


@pytest.mark.parametrize("route", SWEEP_ROUTES, ids=lambda r: r.strip("/"))
def test_no_edge_is_drawn_on_a_surface_the_tuple_does_not_name(
    page, live_app, skin, route
):
    """THE FENCE app/palette.py SAYS IS MISSING, built for edges.

    Plant a colour, walk EVERY element in the rendered document plus its
    ::before and ::after, keep the ones whose PAINTED edge is the derived
    colour, and require each one's ground to be a member of the skin's own
    surface tuple. The tuple is what the derivation was computed against; a
    hit on any other ground is an edge this change guarantees nothing about.

    TWO GUARDS BEFORE THE CLAIM, and neither is decoration.

    The VACUITY GUARD: the planted colour must be one the derivation MOVES.
    #ffe9a8 becomes #a38d4c on V1 and #9c8645 on V2. Without it the sweep
    would pass on a page where nothing was derived at all — and worse, it
    would start matching the sites that deliberately KEEP the raw accent
    (every .button.primary border), which sit on grounds no tuple names,
    and go red for a reason with nothing to do with the fence.

    .direct-changes USED to be named in that list and no longer belongs to
    it: LLM-COP-42 retargeted its border to var(--accent-edge), so it is a
    hit this sweep is supposed to find rather than one it must avoid. Its
    ground is .direct-publishbar's --card, rgb(255,255,255), which IS in
    V1_SURFACES, so the fence is satisfied and this test stays green.

    The NON-EMPTY GUARD: a sweep that finds nothing proves nothing. Measured
    here: 6 hits on V1's `/`, 49 on V1's /muokkaa/sivu, 5 and 21 on V2's.
    The V1 edit route was 45 before LLM-COP-42; the four new hits are
    span.direct-changes' border-top/right/bottom/left, which the walk finds
    without any typing because _SWEEP_EDGES has no visibility check and
    Chrome reports the border on a `hidden` element. V2 gains none — every
    rule in direct-edit.css naming --accent-edge is invalid there, on a skin
    that declares no such token.

    WHAT IT CANNOT DO, said rather than implied: it sees only the
    backgrounds these two routes actually render. The retarget table in the
    plan is what a human re-checks by hand.
    """
    from app.palette import ROLE_TOKENS

    accent = "#ffe9a8"
    plant(live_app, skin, accent=accent)
    surfaces = ROLE_TOKENS[skin]["surfaces"]

    response = page.goto(f"{live_app.base_url}{route}")
    assert response.status == 200, route
    edge = edge_token_in(response.text(), skin)
    assert edge != accent, (
        "the sweep needs a colour the derivation MOVES; this one is the "
        "identity, so the needle is the raw accent and every site that "
        "deliberately keeps it would be a false hit"
    )
    if route != "/":
        page.wait_for_selector(DIRECT_FIELD)
    sentinel = "rgb({}, {}, {})".format(*hex_to_rgb(edge))
    hits = page.evaluate(_SWEEP_EDGES, sentinel)
    assert hits, (
        f"{skin} {route}: not one painted edge resolved to {edge} — either "
        "the override never reached the page or every retarget was reverted"
    )

    allowed = {hex_to_rgb(surface) for surface in surfaces}
    strays = [
        (hit["what"], hit["kind"], ground)
        for hit in hits
        for ground in hit["grounds"]
        if rgb(ground) not in allowed
    ]
    assert not strays, (
        f"{skin} {route}: the edge token is drawn on grounds "
        f"{ROLE_TOKENS[skin]['surfaces']} does not name — " + "; ".join(
            f"{what} ({kind}) on {ground}" for what, kind, ground in strays
        )
    )
    # Every hit had a ground to check at all — a hit whose walk reached the
    # top of the document without finding one would otherwise pass silently.
    assert all(hit["grounds"] for hit in hits), [
        hit["what"] for hit in hits if not hit["grounds"]
    ]


def test_the_style_block_is_last_in_head_and_carries_only_the_closed_alphabet(
    page, live_app, skin
):
    """One block, inside <head>, after the stylesheet link — and nothing in
    it that could open a tag.

    Placement is not cosmetic: the block redeclares :root tokens the
    stylesheet already declares, so equal specificity means SOURCE ORDER
    decides, and a block emitted before the link would lose every one of
    them silently. The browser is asked where the element actually is,
    rather than the template being read.
    """
    plant(live_app, skin, main=PANEL_MAIN, accent=PANEL_ACCENT)
    response = page.goto(f"{live_app.base_url}/")
    assert response.status == 200
    assert_skin(page, skin)
    assert response.text().count("<style") == 1

    where = page.evaluate(
        """() => {
          const styles = document.head.querySelectorAll('style');
          if (styles.length !== 1) return { count: styles.length };
          const el = styles[0];
          const links = [...document.head.querySelectorAll('link[rel=stylesheet]')];
          return {
            count: 1,
            text: el.textContent,
            afterEveryStylesheet: links.every(
              (link) => link.compareDocumentPosition(el)
                        & Node.DOCUMENT_POSITION_FOLLOWING
            ),
          };
        }"""
    )
    assert where["count"] == 1
    assert where["afterEveryStylesheet"]
    assert re.fullmatch(r":root\{[-a-z0-9:;#]+\}", where["text"]), where["text"]
    # And it really is the store's own value that got there.
    assert PANEL_MAIN in where["text"]
    assert PANEL_ACCENT in where["text"]
    hero = json.loads(
        database.connect(live_app.config["DATABASE"])
        .execute("SELECT published FROM sections WHERE kind = 'hero'")
        .fetchone()["published"]
    )
    assert hero["color_main"] == PANEL_MAIN
    assert hero["color_accent"] == PANEL_ACCENT


# --- 8: LLM-COP-44, the primary button's RING -------------------------------
#
# ADDITIVE, like section 6 above: not one line of the text-site or edge
# machinery is edited. `measure`, `measure_edges`, TEXT_SITES, EDGE_SITES and
# every test reading them are untouched, because "text contrast is unchanged"
# and "the edges still hold" are claims this file has to be able to make
# about itself.
#
# WHAT IS BEING PROVED, in one sentence, because a looser one is false. The
# button's outer BOUNDARY reaches 3:1 against its own ground at rest and on
# hover, on every ground either skin puts a primary button on. NOT that the
# fill reaches 3:1 — it never will, the fill is the owner's literal pick and
# no derivation may move it. The boundary is carried by the fill wherever the
# fill already clears, and by a 1px ring drawn just outside the border box
# wherever it does not, and which of the two is carrying it on any given
# button is a thing these tests MEASURE rather than assume.
#
# THREE HAZARDS THIS SECTION IS SHAPED AROUND, all three of which have
# actually bitten this codebase:
#
# 1. READ THE PROPERTY OFF THE ELEMENT THAT OWNS IT. USR-COP-2's earlier
#    draft read `color` off an ancestor that does not own it and would have
#    passed green at 1.07:1. Every row below reads boxShadow off the
#    `.button.primary` itself, and its ground by walking from
#    el.parentElement — the ring sits OUTSIDE the border box, so the button's
#    own fill is not what it is seen against.
#
# 2. NEVER PIN A PROPERTY THE UA SUPPLIES. LLM-COP-40's first push was green
#    locally and red on CI because a test pinned a computed `outline-width`
#    that Chrome 142 reports as 0px and Chrome 152 as 3px. So nothing here
#    pins the computed box-shadow STRING or its px serialisation. One regex
#    takes the colour and its alpha out; the offsets, the blur, the spread
#    and the order of the parts are the UA's business and no assertion
#    touches them. Chrome 142 on this machine serialises the two cases as
#    `rgba(0, 0, 0, 0) 0px 0px 0px 1px` and `rgb(192, 91, 52) 0px 0px 0px
#    1px` — recorded so a future reader knows what was parsed, NOT asserted.
#
# 3. TEST THE ALPHA FIRST. `rgb()` above REFUSES a translucent value by
#    design — a silent blend would be this file inventing a ground. Every
#    transparent ring computes with alpha 0, so a row that routed a ring
#    colour through rgb() or ratio() before testing its alpha would die with
#    `translucent:` instead of saying what was wrong. shadow_colour below
#    returns the alpha ALONGSIDE the triple and never goes through rgb(), and
#    every caller looks at the alpha before it looks at the colour.

# Every .button.primary on the public page, per skin: (selector, the ground
# it walks to when no MAIN colour is chosen, whether that ground IS the
# owner's main role).
#
# THE HERO CTA AND THE CONTACT CTA ARE TWO SITES ON V1, not one. page.html:65
# is the hero's `.cta-row` button and page.html:159 is the yhteydenotto
# section's; both carry .cta-contact, both walk to body's --paper because
# neither .hero nor .contact declares a background, and both are measured.
# V2 has no such pair — its yhteydenotto button is .v2-contact-primary on the
# navy card, which is the live defect and is listed on its own.
#
# THE GROUNDS ARE PINNED AS LITERALS and the browser is asked to agree with
# them. That is the assertion that catches a selector aimed at the wrong
# element: `.contact .button.primary` on a ground of rgb(255, 255, 255) would
# mean the walk found the card and not the paper, and every ratio computed
# from it would be a ratio about the wrong thing.
RING_SITES = {
    "v1": (
        (".cta-row .button.primary", "rgb(250, 247, 242)", False),
        (".contact .button.primary", "rgb(250, 247, 242)", False),
        (".site-header .button.primary", "rgb(255, 255, 255)", True),
    ),
    "v2": (
        (".v2-hero-card .button.primary", "rgb(255, 255, 255)", False),
        (".v2-contact-card .button.primary", "rgb(20, 50, 74)", False),
        (".v2-header .button.primary", "rgb(217, 232, 242)", True),
    ),
}

# The dialog's submit, which is a fourth site on both skins and the one that
# cannot be measured where it stands. contact_dialog.html:6 ships
# `<div class="contact-dialog" hidden>`, so .cd-submit has a zero box until
# an opener is clicked — and a zero-size element measured anyway is exactly
# the silent pass assert_painted exists to stop. It is opened for real, with
# a click on the hero's own .cta-contact, and the `rendered` precondition is
# what catches a row that forgot.
DIALOG_OPENER = ".cta-row .cta-contact"
DIALOG_SITE = (".contact-dialog .cd-submit", "rgb(255, 255, 255)", False)

# The five (main, accent) pairs every site is driven at.
#
# The three accents are EDGE_CASES, the file's own picks from LLM-COP-40, so
# the three failure modes its docstring argues for carry over unchanged: pale
# is the defect the ask names, mid is the one that catches a NEARLY right
# derivation, dark is the identity case the derivation must leave alone.
#
# THE FOURTH IS THE PATHOLOGICAL ONE and it is the only way to reach the
# 1.0000 row. An owner who gives BOTH roles one colour puts the header's
# primary button on its own fill: contrast(x, x) is 1.0 for every colour
# there is, so that button is not a button, it is a rectangle of header. No
# amount of sweeping the accent alone finds it, because the ground has to
# move with the fill.
#
# THE FIFTH IS THE ONLY ONE THAT SEPARATES REST FROM HOVER, and without it
# the hover half of this test proves nothing it does not already prove at
# rest. The derivation takes BOTH fills — (accent, shade(accent)) — and the
# case that holds it to that is an accent whose REST fill clears its ground
# while its HOVER fill does not. Swept the 4096-colour grid for one: 811
# exist and all 811 are on --v2-navy, because shade() darkens and every
# other ring ground in either skin is light. #ee0055 is the sharpest of them
# — 3.0076:1 on the navy card at rest, 2.0651:1 once the pointer lands.
# Drop shade(accent) from the derivation's fills and this is the row that
# goes red, at 2.0651, and only on hover.
#
# On V1 it is a quiet pass and says so: no v1 ground can produce the flip at
# all, so the case is carried for the skin that has it and costs the other a
# page load.
RING_CASES = (
    ("", "#ffe9a8"),
    ("", "#66aa88"),
    ("", "#1a1a2e"),
    ("#ffe9a8", "#ffe9a8"),
    ("", "#ee0055"),
)

# One evaluate per measurement. Three things it returns and why each is here:
# `boxShadow` read off the button ITSELF (hazard 1); `fill`, its own computed
# background, which is the other half of the SC 1.4.11 disjunction; and
# `ground`, the walk from el.parentElement — the ring is painted outside the
# border box, so the button's own fill is not underneath it. `rendered` is
# the precondition: a zero-size element has no boundary to perceive and every
# ratio taken off it is a number about nothing.
_MEASURE_RINGS = """
(selectors) => selectors.map((selector) => {
  const el = document.querySelector(selector);
  if (!el) return { selector, found: false };
  const cs = getComputedStyle(el);
  const opaque = (raw) => {
    const parts = (raw.match(/[\\d.]+/g) || []).map(Number);
    return parts.length >= 3 && (parts.length < 4 || parts[3] > 0);
  };
  const walk = (node) => {
    while (node) {
      const raw = getComputedStyle(node).backgroundColor;
      if (opaque(raw)) return raw;
      node = node.parentElement;
    }
    return null;
  };
  const box = el.getBoundingClientRect();
  return {
    selector,
    found: true,
    rendered: box.width > 0 && box.height > 0,
    boxShadow: cs.boxShadow,
    fill: cs.backgroundColor,
    ground: walk(el.parentElement),
  };
});
"""

# The colour of a box-shadow, and NOTHING ELSE OF IT. Chrome puts the colour
# first and the four lengths after; Firefox has been known to put the lengths
# first. This finds the first rgb()/rgba() wherever it sits and ignores every
# length, which is what keeps hazard 2 closed.
_SHADOW_COLOUR = re.compile(r"rgba?\(([\d.,\s]+)\)")


def shadow_colour(text):
    """((r, g, b), alpha) of a computed box-shadow's colour.

    THE ALPHA COMES BACK ALONGSIDE THE TRIPLE, deliberately, and this is the
    one colour parser in this file that does not go through rgb(). rgb()
    refuses a translucent value — a silent blend would be the test inventing
    a ground — and an unpainted ring is `rgba(0, 0, 0, 0)`, so routing one
    through it would turn "this button has no ring" into `translucent:
    'rgba(0, 0, 0, 0) 0px 0px 0px 1px'`, which names neither the button nor
    the claim. Callers test the alpha first and only then look at the colour.

    NOTHING BUT THE COLOUR IS RETURNED. No caller can pin the spread, the
    offsets or the px serialisation of any of them, because they are not here
    to be pinned.
    """
    found = _SHADOW_COLOUR.search(text or "")
    assert found, f"no colour in box-shadow {text!r}"
    parts = [float(part) for part in found.group(1).split(",")]
    assert len(parts) >= 3, f"not a colour: {text!r}"
    alpha = parts[3] if len(parts) > 3 else 1.0
    return tuple(round(part) for part in parts[:3]), alpha


def measure_rings(page, selectors):
    """{selector: {...}} for every selector, measured in the live page."""
    rows = page.evaluate(_MEASURE_RINGS, list(selectors))
    return {row["selector"]: row for row in rows}


def ring_claim(row, where):
    """SC 1.4.11 for one filled button, COMPUTED rather than matched.

    The claim is a disjunction and it is written out as one: the boundary
    reaches 3:1 if the FILL clears its ground, OR if the ring is opaque AND
    the RING clears its ground. Returns None on a pass and a failure line
    naming both halves otherwise.

    WHY THE DISJUNCTION AND NOT A VALUE PIN. An earlier form of the sweep
    below asked whether a button "carries one of the ring values the block
    wrote". That fences nothing: a fourth primary-button site added later on
    a fourth dark ground inherits the base rule, carries the light-surface
    ring token, and passes — while for every accent that clears the light
    tuple that ring is transparent, so the element is never even seen. The
    scenario the sweep existed for is precisely the one that escaped it. The
    claim form has no such hole: a button on a ground neither its fill nor
    its ring clears fails outright, whatever token it happens to carry.

    THE ALPHA IS TESTED BEFORE THE COLOUR, for the reason shadow_colour
    states. A transparent ring is not a weaker ring, it is no ring — so when
    the fill has already failed, alpha 0 is the failure, and saying so names
    the defect instead of raising `translucent:` out of rgb().

    IT DOES NOT REQUIRE THE BUTTON TO BE RENDERED, and its callers do that
    themselves. A named site measured at a zero box is a silent pass and
    every named-site test below asserts against it; the whole-document sweep,
    by contrast, deliberately holds the HIDDEN buttons to the claim as well —
    a dialog submit behind `hidden` still has resolved computed colours, and
    those are exactly what it will paint with the moment somebody opens it.
    """
    assert row["found"], f"{where}: not on the page"
    assert row["ground"], f"{where}: no opaque ground anywhere above it"
    ground = rgb(row["ground"])
    fill = ratio(rgb(row["fill"]), ground)
    if fill >= 3.0:
        return None
    colour, alpha = shadow_colour(row["boxShadow"])
    if alpha != 1.0:
        return (
            f"{where}: the fill is {fill:.4f}:1 on {row['ground']} and the "
            f"ring is not painted (alpha {alpha}) — nothing carries the "
            "boundary"
        )
    ring = ratio(colour, ground)
    if ring >= 3.0:
        return None
    return (
        f"{where}: the fill is {fill:.4f}:1 and the ring {row['boxShadow']} "
        f"is {ring:.4f}:1, both on {row['ground']}"
    )


def open_contact_dialog(page):
    """Click a real opener and wait for the submit to have a box.

    contact_dialog.html binds `.header-contact, .cta-contact` as openers, and
    the hero's is the one every skin has in the same place. Waiting on
    `visible` rather than sleeping is what makes the `rendered` precondition
    below a real assertion rather than a race.
    """
    page.click(DIALOG_OPENER)
    page.wait_for_selector(DIALOG_SITE[0], state="visible")


def test_the_shipped_default_page_carries_the_boundary_at_rest_and_on_hover(
    page, live_app, skin
):
    """NOTHING PLANTED — the rendering every visitor who chose no colour gets,
    and the one no derivation can influence.

    A site that has chosen nothing serves NO <style> block at all, asserted
    here, so every value below resolves through the ring tokens' `:root`
    defaults. That makes this the test that says the DEFAULTS are right, and
    it is the only test in the suite that can: everything else plants a
    colour and measures what the derivation produced.

    WHAT V2 SHOWS. The contact card's button is the live SC 1.4.11 defect the
    artifact was filed for — the shipped rust is 2.1987:1 on --v2-navy, and
    on hover, where --v2-rust-dark #8b3715 takes over, 1.6753:1. After this
    change its ring is opaque rgb(192, 91, 52) at 3.0206:1 against the same
    ground, at rest AND under the pointer, because neither hover rule
    re-declares box-shadow. The other three v2 buttons keep an UNPAINTED ring
    and are byte-identical to what they rendered before — #a8431c already
    clears their grounds, so the fill carries the boundary and nothing new is
    drawn.

    WHAT V1 SHOWS: nothing is drawn anywhere. Both v1 rings derive to
    transparent at the shipped accent and at the hand-picked hover literal,
    so the shipped V1 page does not change by one pixel — and that is a
    falsifiable claim rather than a hope, asserted here as alpha 0 on all
    four buttons in both states.

    THE V1 ASSERTION IS ALPHA, NOT `boxShadow == "none"`. After this change
    the computed value on v1 is a shadow with alpha 0, not `none`, because
    `0 0 0 1px transparent` IS a shadow. An assertion of "none" would be red
    on a correct build.
    """
    plant(live_app, skin)
    page_rows = RING_SITES[skin]
    with anonymous(page.context.browser, live_app) as (visitor, response):
        assert response.status == 200
        assert_skin(visitor, skin)
        assert "<style" not in response.text(), (
            "a site that chose nothing must serve no block at all"
        )
        rows = page_rows + (DIALOG_SITE,)
        for state in ("rest", "hover"):
            for selector, ground, _is_main in rows:
                if selector == DIALOG_SITE[0]:
                    continue
                if state == "hover":
                    visitor.hover(selector)
                row = measure_rings(visitor, (selector,))[selector]
                _assert_default_ring(row, skin, selector, ground, state)
        # The dialog last, and opened for real: it overlays the page, so a
        # button behind it could not be hovered afterwards.
        open_contact_dialog(visitor)
        selector, ground, _is_main = DIALOG_SITE
        for state in ("rest", "hover"):
            if state == "hover":
                visitor.hover(selector)
            row = measure_rings(visitor, (selector,))[selector]
            _assert_default_ring(row, skin, selector, ground, state)


# What the shipped default must render at each site, per skin. Only one row
# in either skin is painted, and it is the defect this change exists for; the
# other seven are the identity case, which is what keeps the two default
# pages from gaining eight rims nobody asked for.
_DEFAULT_RING = {
    "v2": {".v2-contact-card .button.primary": ((192, 91, 52), 3.0206)},
    "v1": {},
}
# And what the fill measures on the one painted row, at rest and on hover —
# the two numbers the artifact filed and the reason the ring is there.
_DEFAULT_NAVY_FILL = {"rest": ((168, 67, 28), 2.1987),
                      "hover": ((139, 55, 21), 1.6753)}


def _assert_default_ring(row, skin, selector, ground, state):
    """One site of the shipped default page, at rest or under the pointer."""
    where = f"{skin} default {selector} ({state})"
    assert row["found"], f"{where}: not on the page"
    assert row["rendered"], f"{where}: rendered at zero size"
    assert row["ground"] == ground, (
        f"{where}: walks to {row['ground']}, not the expected {ground} — the "
        "selector is aimed at an element in a different container"
    )
    colour, alpha = shadow_colour(row["boxShadow"])
    expected = _DEFAULT_RING[skin].get(selector)
    if expected is None:
        assert alpha == 0, (
            f"{where}: the ring is painted {row['boxShadow']}, but this "
            "button's fill already clears 3:1 on its ground and the shipped "
            "page must render exactly what it rendered before"
        )
        # And it really is the fill carrying the boundary, not nothing.
        assert ratio(rgb(row["fill"]), rgb(ground)) >= 3.0, (
            f"{where}: the ring is unpainted AND the fill is "
            f"{ratio(rgb(row['fill']), rgb(ground)):.4f}:1"
        )
        return
    want, want_ratio = expected
    assert alpha == 1.0, (
        f"{where}: the ring is not painted ({row['boxShadow']}), and the "
        f"fill under it measures "
        f"{ratio(rgb(row['fill']), rgb(ground)):.4f}:1 — this is the site "
        "the whole change exists for"
    )
    assert colour == want, (
        f"{where}: the ring is {colour}, not the {want} the :root default "
        "declares"
    )
    assert round(ratio(colour, rgb(ground)), 4) == want_ratio, (
        f"{where}: the ring measures "
        f"{ratio(colour, rgb(ground)):.4f}:1, not {want_ratio}"
    )
    # The fill it is standing in for, so the improvement is measured and not
    # asserted: 2.1987 at rest and 1.6753 on hover, both under 3:1.
    fill_want, fill_ratio = _DEFAULT_NAVY_FILL[state]
    assert rgb(row["fill"]) == fill_want, (where, row["fill"])
    assert round(ratio(rgb(row["fill"]), rgb(ground)), 4) == fill_ratio
    assert fill_ratio < 3.0


@pytest.mark.parametrize(
    "main,accent", RING_CASES,
    ids=("pale", "mid", "dark", "main-equals-accent", "hover-only"),
)
def test_every_primary_button_carries_the_boundary_at_rest_and_on_hover(
    page, live_app, skin, main, accent
):
    """THE CENTRAL CLAIM, in a real browser, at every site in both skins.

    Five owner choices, four buttons per skin, two pointer states each: for
    every one of them the SC 1.4.11 disjunction is COMPUTED from the rgb()
    triples Chrome returned — the fill clears 3:1 against the walked ground,
    or the ring is opaque and clears it. The arithmetic is this file's own;
    app.palette.contrast is not imported for it, because a ratio computed
    with the curve of the module under proof is a statement about that
    module.

    THE HOVER HALF IS NOT DECORATION, and one of the five cases exists only
    for it. The hover fill is the darker of the two, so a derivation that
    looked at the rest fill alone would go blind exactly where the boundary
    is doing the work. #ee0055 is the case that holds it to both: 3.0076:1 on
    the navy card at rest — compliant, and a rest-only test is satisfied —
    and 2.0651:1 the moment the pointer lands. Here the pointer is really
    moved and the computed style read again, so "the ring survives hover" is
    a measurement and not a reading of the stylesheet.

    THE GROUND IS ASSERTED BEFORE ANY RATIO IS TAKEN, and for the header it
    MOVES WITH THE MAIN COLOUR. --header-bg and --v2-header are the owner's
    own main role, so a pair that plants both roles the same colour puts that
    button on its own fill at 1.0000:1 — the row no sweep over the accent
    alone can reach, and the reason the two header ring tokens exist. If the
    walk found some other ground the ratio below would be about a container
    this button is not in, and it would be green for a reason with nothing to
    do with the claim.

    NOTHING HERE PINS A DERIVED COLOUR. The expected ring values are in the
    plan and in tests/test_palette.py; what this test asserts is the
    PROPERTY, so a better derivation that produced different colours still
    passes and a derivation that produced compliant-looking colours on the
    wrong grounds still fails.
    """
    plant(live_app, skin, main=main, accent=accent)
    rows = RING_SITES[skin] + (DIALOG_SITE,)
    failures = []
    with anonymous(page.context.browser, live_app) as (visitor, response):
        assert response.status == 200
        assert_skin(visitor, skin)
        assert "<style" in response.text(), "the colour never reached the page"
        for state in ("rest", "hover"):
            for selector, ground, is_main in rows:
                if selector == DIALOG_SITE[0]:
                    continue
                if state == "hover":
                    visitor.hover(selector)
                row = measure_rings(visitor, (selector,))[selector]
                assert row["found"] and row["rendered"], (
                    f"{skin} {selector} ({state}) is not on the page or "
                    "rendered at zero size — a named site measured at a zero "
                    "box is a silent pass"
                )
                want = (
                    "rgb({}, {}, {})".format(*hex_to_rgb(main))
                    if is_main and main
                    else ground
                )
                assert row["ground"] == want, (
                    f"{skin} {main or 'default'}/{accent} {selector} "
                    f"({state}) walks to {row['ground']}, not {want}"
                )
                failure = ring_claim(
                    row, f"{skin} main={main or 'default'} accent={accent} "
                         f"{selector} ({state})"
                )
                if failure:
                    failures.append(failure)
        open_contact_dialog(visitor)
        selector = DIALOG_SITE[0]
        for state in ("rest", "hover"):
            if state == "hover":
                visitor.hover(selector)
            row = measure_rings(visitor, (selector,))[selector]
            assert row["found"] and row["rendered"], (
                f"{skin} {selector} ({state}) has a zero box — the dialog "
                "ships `hidden` and must be opened before it is measured"
            )
            assert row["ground"] == DIALOG_SITE[1], (selector, row["ground"])
            failure = ring_claim(
                row, f"{skin} main={main or 'default'} accent={accent} "
                     f"{selector} ({state})"
            )
            if failure:
                failures.append(failure)
    assert not failures, "; ".join(failures)


# --- 9: the claim over the whole document, not over a list of selectors -----

# Every element in the document whose PAINTED box-shadow is one of the ring
# values the page's own <style> block wrote, plus every .button.primary in
# it, whether this file names one or not.
#
# TWO HALVES, AND THE SECOND IS THE ONE THAT FENCES. Half (a) is the surface
# fence in its ring-shaped form: a ring painted on a ground it was not
# derived for is a ring this change guarantees nothing about. Half (b) is the
# CLAIM, computed for every primary button the document contains — including
# one added next year on a ground nobody thought of, which is exactly the
# case half (a) cannot see, because a button on a new dark ground would carry
# the light-surface token and for most accents that token is transparent, so
# it would never be a hit at all.
#
# THE GROUND RULE IS measure_rings', deliberately and stated in both places:
# the walk starts at el.parentElement, because a ring sits outside the border
# box and the element's own fill is not underneath it.
_SWEEP_RINGS = """
(sentinels) => {
  const opaque = (raw) => {
    const parts = (raw.match(/[\\d.]+/g) || []).map(Number);
    return parts.length >= 3 && (parts.length < 4 || parts[3] > 0);
  };
  const walk = (node) => {
    while (node) {
      const raw = getComputedStyle(node).backgroundColor;
      if (opaque(raw)) return raw;
      node = node.parentElement;
    }
    return null;
  };
  const where = (el) => {
    const bits = [el.tagName.toLowerCase()];
    if (el.id) bits.push('#' + el.id);
    if (el.className && typeof el.className === 'string') {
      bits.push('.' + el.className.trim().split(/\\s+/).join('.'));
    }
    return bits.join('');
  };
  const shadowColour = (raw) => {
    const found = /rgba?\\([\\d.,\\s]+\\)/.exec(raw || '');
    return found ? found[0] : null;
  };
  const hits = [];
  for (const el of document.querySelectorAll('*')) {
    const colour = shadowColour(getComputedStyle(el).boxShadow);
    if (colour === null || !opaque(colour)) continue;
    if (!sentinels.includes(colour)) continue;
    hits.push({ what: where(el), colour, ground: walk(el.parentElement) });
  }
  const buttons = [];
  for (const el of document.querySelectorAll('.button.primary')) {
    const cs = getComputedStyle(el);
    const box = el.getBoundingClientRect();
    buttons.push({
      selector: where(el),
      found: true,
      rendered: box.width > 0 && box.height > 0,
      boxShadow: cs.boxShadow,
      fill: cs.backgroundColor,
      ground: walk(el.parentElement),
    });
  }
  return { hits, buttons };
};
"""

# Where the sweep runs. `/` and /muokkaa/sivu are SWEEP_ROUTES', and
# /yllapito is added because it is the ONLY route that renders .login-submit:
# login_dialog=True is set at app/__init__.py:256, :362, :375 and :482, all
# of them /yllapito arms, so the two routes above would find TEN primary
# buttons and miss the eleventh entirely. It renders through the same
# render_page and therefore carries the same <style> block, so the sweep sees
# a derived ring there exactly as it does on the other two.
RING_SWEEP_ROUTES = ("/", "/muokkaa/sivu", "/yllapito")

# How many .button.primary each route actually contains, per skin. A COUNT
# and not a lower bound, because the failure this half exists to catch is a
# button nobody knew about — and a `>= 4` would pass on a sweep that stopped
# finding half of them. Measured, and the numbers say what the routes are:
# `/` carries the hero CTA, the contact CTA, the header's and the dialog's
# submit; /muokkaa/sivu adds direct-edit's Julkaise; /yllapito adds
# .login-submit, the one button the other two routes cannot reach.
#
# THE TWO SKINS MATCH ON EVERY ROUTE, which is not the coincidence it looks
# like: v2's yhteydenotto button is .v2-contact-primary on the navy card, a
# different element on a different ground from v1's, but it carries
# .cta-contact and `.button.primary` all the same (page_v2.html:296), so each
# route puts the SAME number of primary buttons on the page in either skin.
RING_SWEEP_COUNTS = {
    "v1": {"/": 4, "/muokkaa/sivu": 5, "/yllapito": 5},
    "v2": {"/": 4, "/muokkaa/sivu": 5, "/yllapito": 5},
}


def ring_values_in(document, skin):
    """The PAINTED ring colours the page's own <style> block wrote.

    READ OFF THE SERVED DOCUMENT, not derived by calling ring_on — the same
    rule edge_token_in states for the edge token. The needle this sweep hunts
    for has to be the colour that actually reached the browser; deriving it
    from the module under proof would make the sweep agree with that module
    by construction, and a wrong derivation would simply be hunted for under
    its own wrong value.

    A `transparent` ring is not a needle and is not returned. Nothing is
    painted, so no element can be found by it, and half (a) of the sweep has
    nothing to say about a button that draws no ring — which is the hole half
    (b) exists to close.
    """
    from app.palette import ROLE_TOKENS

    found = []
    for token, _grounds in ROLE_TOKENS[skin]["rings"]:
        match = re.search(rf"{token}:(#[0-9a-f]{{6}}|transparent);", document)
        assert match, f"{token} is in no <style> block on this page"
        if match.group(1) != "transparent":
            found.append(match.group(1))
    return tuple(found)


@pytest.mark.parametrize("route", RING_SWEEP_ROUTES, ids=lambda r: r.strip("/"))
def test_every_primary_button_in_the_document_carries_the_boundary(
    page, live_app, skin, route
):
    """THE SWEEP THAT NAMES NO SITE — it walks the rendered document and
    computes the claim, so a button this file never heard of is held to it.

    HALF (a), THE SURFACE FENCE FOR RINGS. Every element whose PAINTED
    box-shadow is one of the ring colours the page's own block wrote must
    have a walked ground that the ring clears 3:1 against. A ring painted on
    a ground it was not derived for is a ring this change guarantees nothing
    about, and no arithmetic test could see it: the derivation would be
    perfectly correct about the ground it was given.

    HALF (b), THE CLAIM. For EVERY .button.primary in the document — named
    here or not, rendered or not — the fill clears 3:1 against its walked
    ground, or the ring is opaque and clears it. This is the half that closes
    the hole a value-membership test leaves open. A fourth primary-button
    site added later on a fourth dark ground inherits the base rule and
    carries the light-surface token; for every accent that clears the light
    tuple that token is transparent, so half (a) never sees the element at
    all, while half (b) fails it outright.

    THE VACUITY GUARDS, and neither is decoration. The planted colour must be
    one the derivation actually PAINTS a ring for — #ffe9a8 is 1.0259 on
    V2_SURFACES and 1.1247 on --paper, so it does — and both halves must find
    something. A sweep that finds nothing proves nothing, and "0 results" on
    a page that certainly has primary buttons is a bug in the sweep, not a
    pass.

    THE ROUTES ARE THREE, and the third is here for one button.
    `.login-submit` renders only where login_dialog=True, which is /yllapito
    and nowhere else, so `/` and /muokkaa/sivu between them reach ten primary
    buttons and would leave the eleventh covered by argument alone. Its
    ground is --card / --v2-card, both members of their skin's surface tuple,
    so the argument was sound — but a covered-by-construction button is not a
    measured one, and this is a file about measuring.
    """
    accent = "#ffe9a8"
    plant(live_app, skin, accent=accent)
    response = page.goto(f"{live_app.base_url}{route}")
    assert response.status == 200, route
    sentinels = ring_values_in(response.text(), skin)
    assert sentinels, (
        f"{skin}: the sweep needs a colour the derivation PAINTS a ring for; "
        f"accent={accent} produced none, so half (a) would have no needle"
    )
    assert all(value != accent for value in sentinels), (
        "a ring equal to the raw accent would also match every primary "
        "button's border-coloured neighbours by coincidence"
    )
    if route == "/muokkaa/sivu":
        page.wait_for_selector(DIRECT_FIELD)

    swept = page.evaluate(
        _SWEEP_RINGS,
        ["rgb({}, {}, {})".format(*hex_to_rgb(value)) for value in sentinels],
    )
    hits, buttons = swept["hits"], swept["buttons"]

    # (a) every painted ring is on a ground it clears.
    assert hits, (
        f"{skin} {route}: not one painted ring resolved to {sentinels} — "
        "either the override never reached the page or the rules were "
        "reverted"
    )
    assert all(hit["ground"] for hit in hits), [
        hit["what"] for hit in hits if not hit["ground"]
    ]
    strays = [
        f"{hit['what']} {ratio(rgb(hit['colour']), rgb(hit['ground'])):.4f}:1 "
        f"({hit['colour']} on {hit['ground']})"
        for hit in hits
        if ratio(rgb(hit["colour"]), rgb(hit["ground"])) < 3.0
    ]
    assert not strays, (
        f"{skin} {route}: a derived ring is painted on a ground it does not "
        "clear — " + "; ".join(strays)
    )

    # (b) every primary button in the document carries the boundary — the
    # hidden ones included, because a dialog submit behind `hidden` has
    # resolved computed colours and those are what it paints when opened.
    assert len(buttons) == RING_SWEEP_COUNTS[skin][route], (
        f"{skin} {route}: {len(buttons)} primary buttons, not "
        f"{RING_SWEEP_COUNTS[skin][route]} — "
        + "; ".join(button["selector"] for button in buttons)
    )
    assert any(button["rendered"] for button in buttons), (
        f"{skin} {route}: every primary button has a zero box"
    )
    failures = [
        failure
        for button in buttons
        for failure in (
            ring_claim(button, f"{skin} {route} {button['selector']}"),
        )
        if failure
    ]
    assert not failures, "; ".join(failures)
