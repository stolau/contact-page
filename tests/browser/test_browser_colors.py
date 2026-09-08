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
