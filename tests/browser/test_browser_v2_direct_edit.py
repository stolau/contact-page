"""In-place editing over the V2 template, driven in a real Chrome
(LLM-COP-23).

THE HAZARD THIS FILE EXISTS FOR, in LLM-COP-18's own words: "the direct
in-place editor binds to `data-section` attributes rendered into the
public template, so V2's template must carry the same bindings or
in-place editing silently stops working on V2 — a defect shape this
project has already shipped once (LLM-COP-6's focus-steal)."

tests/test_page_v2.py fences the markup: the two templates render the
same set of (section id, field name) pairs. That is necessary and it is
not sufficient. An attribute present in the document proves nothing about
whether direct-edit.js bound it, whether the element can be focused,
whether something in V2's stylesheet sits on top of it, or whether the
value reaches the store. Those are browser questions and this is where
they are asked.

WHY THE FIXTURE GUARDS AGAINST A FALLBACK. Until LLM-COP-24 there was no
URL that served V2, so this file registered a test-local route that named
page_v2.html literally. V2 is selectable now and these tests reach the
product's own /muokkaa/sivu instead — which costs something the harness
did not: an unknown style resolves to V1 BY DESIGN (app/styles.py), so a
subtly wrong selection would serve this file V1, every sweep below would
type into V1's bindings, and all of it would pass while proving nothing
about V2. The harness could not fall back; a real URL can. So the fixture
asserts the served document IS V2 before any test runs — the stylesheet
link and a class page.html contains zero times — and that assertion is
what replaces the property the harness provided.

NO SAMPLE COPY IS ASSERTED. Every value typed below is compared against
what the page itself shows, never against a literal: the seven V2
documents assert three strings in total and the rest of that page is the
owner's data.
"""

import json

import pytest

from app import db as database
from tests.browser.conftest import V2_STYLESHEET, set_hero_draft_style

# Only page_v2.html emits this class — measured, eleven times there and
# zero times in page.html — so it is what tells a served V2 apart from a
# fallback to V1 that would otherwise look like a healthy page.
V2_ONLY_CLASS = ".v2-hero"


@pytest.fixture
def v2_page(page, live_app):
    """conftest.py's signed-in page, landed on the REAL /muokkaa/sivu with
    the drafted style set to v2 — and NOT yielded until the document that
    came back is actually V2.

    The guard is the point. /muokkaa/sivu renders whatever the drafted
    style resolves to, and resolve_style turns anything it does not know
    into "v1" rather than raising, because a stored style must never be
    able to 500 a page. That is right for the product and it is a trap for
    this file: a fixture that planted a value the renderer did not know
    would hand every test below a V1 document, and every one of them would
    pass against V1's bindings. Measured: resolve_style("banana") is "v1",
    and page.html contains v2-hero zero times.
    """
    set_hero_draft_style(live_app, "v2")
    page.goto(f"{live_app.base_url}/muokkaa/sivu")
    assert page.locator(V2_STYLESHEET).count() == 1, (
        "/muokkaa/sivu did not serve the V2 skin — the drafted style fell "
        "back to V1, and every test in this file would have passed against "
        "V1's bindings"
    )
    assert page.locator(V2_ONLY_CLASS).count() > 0, (
        f"the served document links style-v2.css but carries no "
        f"{V2_ONLY_CLASS}"
    )
    return page


def drafts(app):
    """Every section's draft payload, straight from the app's own DB file."""
    conn = database.connect(app.config["DATABASE"])
    try:
        return {
            str(row["id"]): json.loads(row["draft"])
            for row in conn.execute("SELECT id, draft FROM sections")
        }
    finally:
        conn.close()


def activate(page, field):
    """Put the caret in one bound field and return its locator.

    focus(), not click(). Direct edit mode's own chrome is two FIXED bars
    plus a toolbar that floats over whichever field is active, so a
    synthetic click at an element's centre is intercepted by the chrome
    for any field that happens to scroll under it — which is a fact about
    the harness, not about the product, and it makes a whole-page sweep
    impossible to write with click().

    Nothing is lost: direct-edit.js activates on the `focus` event
    (:315-317), so focus is the real entry point, and the click path has
    its own test — test_clicking_a_bound_button_on_v2_edits_it_and_leaves
    _the_dialog_shut, which is where the pointer behaviour belongs.
    """
    locator = page.locator(
        f'[data-section="{field["sid"]}"][data-field="{field["name"]}"]'
    )
    locator.focus()
    return locator


def bound_fields(page):
    """Every [data-field] the browser can actually reach: its section id,
    its section's kind, its field name, whether the schema calls it rich,
    and whether it is laid out at this viewport.

    Read out of the live DOM, not out of a list here — a list would be the
    same restatement of app/templates/page_v2.html that would go stale at
    exactly the moment a field stops being bound.
    """
    return page.evaluate(
        """() => {
            const boot = JSON.parse(
                document.getElementById('direct-bootstrap').textContent
            );
            const kinds = {};
            boot.sections.forEach(s => { kinds[s.id] = s.kind; });
            return Array.from(document.querySelectorAll('[data-field]')).map(el => {
                const sid = el.getAttribute('data-section');
                const name = el.getAttribute('data-field');
                const d = (boot.fields[kinds[sid]] || {})[name];
                return {
                    sid: sid,
                    kind: kinds[sid],
                    name: name,
                    rich: !!d && d.type === 'rich',
                    known: !!d,
                    shown: !!el.offsetParent || el.getClientRects().length > 0,
                    editable: el.isContentEditable
                };
            });
        }"""
    )


def test_every_rule_in_the_v2_stylesheet_actually_parses(v2_page, live_app):
    """A real CSS parser, asked whether it kept every rule in the file.

    This caught a shipped defect while this artifact was being built: one
    missing ")" on the second url() of .v2-trees' background-image made
    the parser swallow EVERY rule after it — the hero card, the bands, the
    portrait, the contact card, the footer and the dialogs, ninety rules,
    silently. A stylesheet does not fail loudly; it just stops applying,
    and the page still renders, so nothing else in this suite would have
    said a word.

    Reimplementing a CSS parser here to check for balance would only prove
    that reimplementation right. So the browser's own parser is asked, and
    the assertion is that no selector present in the source text is
    missing from the parsed sheet.
    """
    missing = v2_page.evaluate(
        """async (base) => {
            const css = await (
                await fetch(base + '/static/style-v2.css')
            ).text();
            const norm = s => s.trim()
                               .replace(/\\s*,\\s*/g, ', ')
                               .replace(/\\s+/g, ' ');

            const sheet = new CSSStyleSheet();
            await sheet.replace(css);
            const parsed = new Set();
            const walk = rules => {
                for (const rule of rules) {
                    if (rule.selectorText) parsed.add(norm(rule.selectorText));
                    if (rule.cssRules) walk(rule.cssRules);
                }
            };
            walk(sheet.cssRules);

            // Every selector in the SOURCE, read by scanning to each '{'.
            // Not a per-line regex: a selector list wrapped across lines
            // would report its own continuation as missing, which is a
            // false alarm, and a fence that cries wolf gets deleted.
            const stripped = css.replace(/\\/\\*[\\s\\S]*?\\*\\//g, '');
            const wanted = [];
            let buffer = '';
            for (const ch of stripped) {
                if (ch === '{') {
                    const selector = buffer.trim();
                    if (selector && !selector.startsWith('@')) {
                        wanted.push(norm(selector));
                    }
                    buffer = '';
                } else if (ch === '}') {
                    buffer = '';
                } else {
                    buffer += ch;
                }
            }
            return wanted.filter(sel => !parsed.has(sel));
        }""",
        live_app.base_url,
    )
    assert missing == [], (
        "these rules are in app/static/style-v2.css but the browser's CSS "
        f"parser dropped them: {missing}"
    )


# --- the hazard, asked of the browser ---------------------------------------


def test_direct_edit_binds_every_bound_field_on_v2(v2_page):
    """Attributes in the document are not bindings. direct-edit.js makes
    each one contenteditable at boot (:277-323, via bindPlain/bindRich),
    and an element it skipped — an unknown field name, a kind it has no
    descriptor for — stays a plain, silent, uneditable node.

    So this asks the DOM: is every field the V2 template marked actually
    contenteditable now? That is the question "does in-place editing work
    on V2" reduces to a single assertion.
    """
    fields = bound_fields(v2_page)
    assert fields, "no [data-field] elements in the V2 direct edit document"

    unknown = [f for f in fields if not f["known"]]
    assert not unknown, f"data-field names nothing in the schema: {unknown}"

    unbound = [(f["sid"], f["name"]) for f in fields if not f["editable"]]
    assert not unbound, (
        "in-place editing is dead on V2 for these fields — they carry the "
        f"attributes but direct-edit.js did not bind them: {unbound}"
    )


def test_the_section_name_chips_reach_their_bands_on_v2(v2_page, expect):
    """direct-edit.js finds each band by section[data-kind="..."] and moves
    the chip into it (:62-71). A band missing the attribute keeps no name
    and nothing raises."""
    chips = v2_page.locator(".direct-section-name")
    sections = v2_page.locator("main section[data-kind]")
    assert chips.count() == sections.count() > 0


def test_the_portrait_pill_is_anchored_to_the_portrait_on_v2(v2_page, expect):
    """direct-edit.js anchors the disabled "Vaihda kuva" pill as the
    portrait's next sibling (:75-78) — guarded by `if (portrait)`, so a
    template without .portrait loses the control in silence. V2 moves the
    portrait out of the hero and into the editorial band; the pill has to
    follow it there."""
    anchored = v2_page.evaluate(
        """() => {
            const portrait = document.querySelector('.portrait');
            if (!portrait) return 'no .portrait in the V2 document';
            const next = portrait.nextElementSibling;
            return next && next.classList.contains('direct-portrait-pill')
                ? 'ok' : 'pill not anchored to the portrait';
        }"""
    )
    assert anchored == "ok", anchored


def test_typing_into_every_visible_bound_field_registers_a_change(
    v2_page, expect
):
    """One keystroke into each field the viewport actually shows, and the
    publish bar's change count after each one.

    The count is derived per FIELD (direct-edit.js:104-112), so it rising
    by exactly one each time is the proof that the field just typed into
    was a distinct, correctly-attributed binding — not that some other
    element absorbed the text. A field bound to the wrong section id would
    still take a character and would still show a count; it would not
    count up in step.

    THE THREE NEUTRAL KINDS ARE NAMED (LLM-COP-24). palvelut,
    vastaanottoajat and sijainti are the kinds V2 has no design for and
    renders in the neutral prose band, and this sweep is derived from the
    live DOM — so if a band stopped being LAID OUT the sweep would simply
    get shorter and still pass. Nothing else catches that. A missing
    BINDING is caught (tests/test_page_v2.py compares the two templates'
    binding sets), but a band hidden by CSS keeps every attribute in the
    markup: `shown` filters on offsetParent/getClientRects above, and
    test_no_bound_field_on_v2_is_covered_by_something_else early-returns on
    the same condition, so display:none is invisible to both. Naming the
    kinds is what makes "V2 renders all six, explicitly not hidden" a claim
    this file can fail.

    Satisfiable by measurement, not by hope: each of the three binds
    exactly one field on V2 — palvelut.more_label, vastaanottoajat's
    booking_note and sijainti.address — and none of them sits behind a
    viewport class, so all three are laid out at this layer's fixed
    1280x900.
    """
    fields = [f for f in bound_fields(v2_page) if f["shown"]]
    assert len(fields) > 1, fields

    swept = {f["kind"] for f in fields}
    unreached = [
        kind
        for kind in ("palvelut", "vastaanottoajat", "sijainti")
        if kind not in swept
    ]
    assert unreached == [], (
        "V2's neutral bands are published and bound, but this sweep never "
        f"reached them — nothing laid out for: {unreached}"
    )

    for index, field in enumerate(fields, start=1):
        activate(v2_page, field)
        v2_page.keyboard.type("x")
        assert v2_page.locator(".direct-changes-count").text_content() == str(
            index
        ), (
            f"after typing into {field['sid']}.{field['name']} the publish "
            "bar did not count it as its own change"
        )


def test_editing_v2_round_trips_through_the_real_store(
    v2_page, expect, live_app
):
    """Every plain field typed into, saved through the product's own PUT
    /api/sections/<id>/draft, and then read back out of the database file.

    The store is compared against the ELEMENT'S OWN TEXT, never a literal:
    click() drops the caret wherever it lands, so any literal here would be
    asserting the browser's caret behaviour by accident — and, more to the
    point, every one of these values is the owner's copy, which this suite
    does not pin. What must hold is that the page and the store agree.

    Rich fields are excluded from the equality only because their stored
    value is HTML and textContent is not; that they changed at all is
    asserted separately below.
    """
    before = drafts(live_app)
    fields = [f for f in bound_fields(v2_page) if f["shown"]]

    for field in fields:
        activate(v2_page, field)
        v2_page.keyboard.type("X")

    v2_page.click(".direct-tallenna")
    # State, not time: a landed save rebaselines lastSaved and the badge
    # goes hidden (direct-edit.js:114-119).
    expect(v2_page.locator(".direct-changes")).to_be_hidden()

    after = drafts(live_app)
    for field in fields:
        sid, name = field["sid"], field["name"]
        stored = after[sid][name]
        assert stored != before[sid][name], f"{sid}.{name} never reached the store"
        if not field["rich"]:
            shown = v2_page.locator(
                f'[data-section="{sid}"][data-field="{name}"]'
            ).text_content()
            assert stored == shown, f"{sid}.{name}: store {stored!r} page {shown!r}"


def test_clicking_a_bound_button_on_v2_edits_it_and_leaves_the_dialog_shut(
    v2_page, expect
):
    """LLM-COP-6's defect, asked again of the other skin.

    V2 renders TWO .cta-contact openers — the hero's contact_label and the
    contact card's send_label — where V1 renders one, so V2 has two ways
    to reproduce it and this asserts on the one V1 never had. The rule is
    a single capture-phase listener on the document
    (direct-edit.js:346-355); with the dialog open its backdrop swallows
    pointer events and editing stops dead.

    .contact-panel carries the visibility assertion, not .contact-dialog:
    the wrapper has no layout rule of its own and reports itself hidden
    with the dialog wide open.
    """
    send = v2_page.locator(".v2-contact-primary")
    expect(send).to_be_visible()
    send.click()

    expect(v2_page.locator(".direct-field-tag")).to_be_visible()
    expect(v2_page.locator(".contact-panel")).to_be_hidden()
    expect(v2_page.locator(".contact-dialog")).to_have_attribute("hidden", "")


def test_no_bound_field_on_v2_is_covered_by_something_else(v2_page):
    """The occlusion class of defect LLM-COP-11 fixed once in V1, asked of
    V2's stylesheet — a second stylesheet is a second place for it.

    For every visible bound field the centre of its own box must hit-test
    to that field, or to something inside it. A sticky header, the fixed
    edit bars, the hero card's clip-path or a z-index that lost can each
    put a field under something the owner cannot click through, and none
    of that is visible in the markup.
    """
    covered = v2_page.evaluate(
        """() => {
            const bad = [];
            document.querySelectorAll('[data-field]').forEach(el => {
                if (!el.offsetParent && !el.getClientRects().length) return;
                const box = el.getBoundingClientRect();
                if (box.width === 0 || box.height === 0) {
                    bad.push(el.getAttribute('data-field') + ': zero box');
                    return;
                }
                const y = box.top + box.height / 2;
                if (y < 0 || y > window.innerHeight) return;  // off-screen
                const hit = document.elementFromPoint(box.left + box.width / 2, y);
                if (!hit || !(el === hit || el.contains(hit))) {
                    bad.push(
                        el.getAttribute('data-field') + ': hit ' +
                        (hit ? hit.tagName + '.' + (hit.className || '') : 'null')
                    );
                }
            });
            return bad;
        }"""
    )
    assert covered == [], covered
