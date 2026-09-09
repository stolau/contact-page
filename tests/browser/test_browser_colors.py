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
    computed-value time, so outline-style computes to `none` and
    outline-width to 0px — v2's direct-edit page has NO author focus ring,
    and had none before this change either. Measured at 78d5d8e and again
    here.

    So the assertion is what is TRUE, not what ought to be: style `none`,
    width `0px`. It is written to go RED the day somebody gives v2 a ring,
    which is the only honest way to hold a defect open — and the ratio
    assertion that would replace it is one line away. The screenshot is the
    picture of the gap.
    """
    plant(live_app, "v2", accent="#ffe9a8")
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    page.wait_for_selector(DIRECT_FIELD)
    page.focus(DIRECT_FIELD)
    row = measure_edges(page, (DIRECT_ROW,))[DIRECT_FIELD]
    assert row["found"] and row["rendered"]
    assert row["outlineStyle"] == "none" and row["outlineWidth"] == "0px", (
        "v2's direct-edit page now draws an author focus ring. That is the "
        "fix this test was written to notice: replace it with the 3:1 "
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


def test_the_edge_token_never_reaches_the_admin_inbox(page, live_app, skin):
    """style.css:77 now reads --accent-edge, and inbox.html links style.css.

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
    (every .button.primary border, and .direct-changes at
    direct-edit.css:180), which sit on grounds no tuple names, and go red
    for a reason with nothing to do with the fence.

    The NON-EMPTY GUARD: a sweep that finds nothing proves nothing. Measured
    here: 6 hits on V1's `/`, 45 on V1's /muokkaa/sivu, 5 and 21 on V2's.

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
