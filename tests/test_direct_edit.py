"""Direct edit mode (LLM-COP-6) — GET /muokkaa/sivu, against the real
route, the real template and the app's real DB file.

Governing spec cp-main-direct-edit. One test (or one parametrized case)
per addressed contains-text criterion, each citing its spec address. The
spec states no testids, so nothing here invents a data-testid selector
from a region id — assertions are byte-exact substrings of the one served
document, scoped to the implementation's own element wherever a
document-wide substring could not fail.

Two criteria carry a `when` clause that only a browser can produce
(otsikko-tag's OTSIKKO and direct-counter's "14 / 60"): pytest's purchase
on them is the JSON bootstrap those strings are computed from, asserted
as such below and named as browser-only rather than claimed as covered.

No fixture here plants anything to make a test pass: the two identity
fixtures differ only in the account name, and the pair is what proves the
top bar reads the account row rather than page copy.
"""

import copy
import json
from urllib.parse import urlparse

import pytest

from app import db as database
from app.fields import FIELDS
from app.seed import SEED_SECTIONS
from tests.conftest import (
    ADMIN_PASSWORD,
    create_admin,
    element_text,
    login,
    set_section_state,
)

SEED_BY_KIND = dict(SEED_SECTIONS)
JSON_ACCEPT = {"Accept": "application/json"}
DIRECT_URL = "/muokkaa/sivu"

# The pair below is the whole point of the two identity fixtures: one account
# is named EXACTLY like the page's own h1, the other is a login handle that is
# not. Only the pair can prove the top bar reads the account row rather than
# page copy — with two arbitrary names, a document-wide check could not fail.
#
# Before LLM-COP-10 both were the mockup persona's name and login handle.
# PAGE_NAME_OWNER is now derived from the seeded title so the property is
# preserved BY CONSTRUCTION rather than by two literals that happen to match.
PAGE_NAME_OWNER = SEED_BY_KIND["hero"]["title"]
HANDLE_OWNER = "yllapitaja"


# --- fixtures, all local to this file ---------------------------------------


@pytest.fixture
def direct_admin(app):
    """Signed in as an account named exactly like the page's own h1."""
    create_admin(app, username=PAGE_NAME_OWNER, password=ADMIN_PASSWORD)
    client = app.test_client()
    response = login(client, username=PAGE_NAME_OWNER, password=ADMIN_PASSWORD)
    assert response.status_code == 302
    return client


@pytest.fixture
def handle_admin(app):
    """Signed in as a login handle that is *not* the hero heading on the
    same page — the other half of the identity pair."""
    create_admin(app, username=HANDLE_OWNER, password=ADMIN_PASSWORD)
    client = app.test_client()
    response = login(client, username=HANDLE_OWNER, password=ADMIN_PASSWORD)
    assert response.status_code == 302
    return client


@pytest.fixture
def direct_html(direct_admin):
    response = direct_admin.get(DIRECT_URL)
    assert response.status_code == 200
    return response.get_data(as_text=True)


# --- helpers ----------------------------------------------------------------


def bootstrap_json(html, element_id):
    """The JSON bootstrap parsed out of the served document exactly where
    the controller reads it. Jinja's tojson escapes '<' as \\u003c, so a raw
    substring check over the markup would wrongly fail — parse, as
    tests/test_edit.py already does for the side panel's own bootstrap."""
    marker = f'<script id="{element_id}" type="application/json">'
    start = html.index(marker) + len(marker)
    return json.loads(html[start : html.index("</script>", start)])


def chrome_markup(html):
    """The served document with the JSON bootstrap cut out.

    The bootstrap carries FIELD_LABELS and SECTION_NAMES, so a plain
    document-wide substring check for "Tietoa minusta" or "Linkki" passes
    from the JSON blob alone — it stays green even when the rendered
    element is deleted (observed: deleting the section-name strip did not
    fail the check). Every contains-text criterion below is asserted
    against the *rendered* chrome, which is what the spec addresses."""
    marker = '<script id="direct-bootstrap" type="application/json">'
    start = html.index(marker)
    end = html.index("</script>", start) + len("</script>")
    return html[:start] + html[end:]


def hero_section_markup(html):
    """The <section id="hero">…</section> slice, whole and byte-exact."""
    start = html.index('<section id="hero"')
    end = html.index("</section>", start) + len("</section>")
    return html[start:end]


def section_ids(html):
    """kind -> section id, read from the document's own bootstrap."""
    sections = bootstrap_json(html, "direct-bootstrap")["sections"]
    return {section["kind"]: section["id"] for section in sections}


def stored_row(app, kind):
    conn = database.connect(app.config["DATABASE"])
    try:
        return conn.execute(
            "SELECT id, draft, published FROM sections WHERE kind = ?", (kind,)
        ).fetchone()
    finally:
        conn.close()


# --- the admin gate (plan step 6) -------------------------------------------


def test_anonymous_browser_request_is_redirected_to_the_login_dialog(client):
    response = client.get(DIRECT_URL)
    assert response.status_code == 302
    assert urlparse(response.headers["Location"]).path == "/yllapito"


def test_anonymous_json_request_is_answered_401(client):
    response = client.get(DIRECT_URL, headers=JSON_ACCEPT)
    assert response.status_code == 401
    assert response.get_json() == {"error": "unauthorized"}


def test_signed_in_admin_gets_the_page(direct_admin):
    response = direct_admin.get(DIRECT_URL)
    assert response.status_code == 200


# --- Decision A: the top-bar identity is the account, not page copy ---------


def test_direct_topbar_shows_the_account_name(direct_html):
    # cp-main-direct-edit.direct-topbar.direct-breadcrumb — scoped to the
    # top bar, because this fixture's account name is also the hero heading,
    # so a document-wide check could not fail.
    topbar = element_text(direct_html, "header", cls="direct-topbar")
    assert topbar is not None
    assert PAGE_NAME_OWNER in topbar
    assert "ylläpitäjä" in topbar


def test_direct_topbar_name_follows_the_account_not_the_page(handle_admin):
    # The other half of the pair: with the account named by a handle, the bar
    # must read the handle and must NOT read the hero heading — which the very
    # same document still renders.
    html = handle_admin.get(DIRECT_URL).get_data(as_text=True)

    topbar = element_text(html, "header", cls="direct-topbar")
    assert topbar is not None
    assert HANDLE_OWNER in topbar
    assert "ylläpitäjä" in topbar
    assert PAGE_NAME_OWNER not in topbar

    breadcrumb = element_text(html, "span", cls="direct-breadcrumb")
    assert breadcrumb == f"{HANDLE_OWNER} · ylläpitäjä"

    # …while the page copy on the same page does say it. Without this the
    # assertion above would pass on a page that renders no heading at all.
    heading = element_text(html, "h1")
    assert heading == PAGE_NAME_OWNER


# --- the server-rendered chrome, byte-exact (Decision C) --------------------

# Strings that exist only as edit chrome. Every one of them is asserted
# present in /muokkaa/sivu below and absent from / and /muokkaa/esikatselu
# in the leak test, so neither assertion is vacuous.
CHROME_CRITERIA = [
    ("cp-main-direct-edit.direct-topbar.direct-mode", "Muokkaustila"),
    ("cp-main-direct-edit.direct-topbar.direct-breadcrumb", "ylläpitäjä"),
    ("cp-main-direct-edit.direct-topbar.direct-esikatsele", "Esikatsele"),
    ("cp-main-direct-edit.direct-topbar.direct-poistu", "Poistu"),
    ("cp-main-direct-edit.direct-canvas.direct-portrait", "Vaihda kuva"),
    ("cp-main-direct-edit.direct-canvas.format-toolbar", "Linkki"),
    ("cp-main-direct-edit.direct-canvas.format-toolbar", "Lista"),
    ("cp-main-direct-edit.direct-canvas.format-toolbar", "Kumoa"),
    ("cp-main-direct-edit.direct-canvas.direct-title.direct-counter", "merkkiä"),
    ("cp-main-direct-edit.tietoa-band.tietoa-heading", "Tietoa minusta"),
    ("cp-main-direct-edit.tietoa-band.edit-hint", "Klikkaa tekstiä muokataksesi"),
    ("cp-main-direct-edit.publish-bar.changes-badge", "muutosta"),
    ("cp-main-direct-edit.publish-bar.autosave-note", "Tallentamattomia muutoksia"),
    ("cp-main-direct-edit.publish-bar.autosave-note", "viimeksi tallennettu"),
    ("cp-main-direct-edit.publish-bar.hylkaa-button", "Hylkää"),
    ("cp-main-direct-edit.publish-bar.tallenna-luonnos-button", "Tallenna luonnos"),
    ("cp-main-direct-edit.publish-bar.julkaise-muutokset-button",
     "Julkaise muutokset"),
]

CHROME_ONLY_STRINGS = sorted({text for _address, text in CHROME_CRITERIA})


@pytest.mark.parametrize(
    "address,expected",
    [pytest.param(a, e, id=f"{a}:{e}") for a, e in CHROME_CRITERIA],
)
def test_direct_chrome_contains_text(direct_html, address, expected):
    rendered = chrome_markup(direct_html)
    assert expected in rendered, (
        f"{address}: {expected!r} not in the rendered {DIRECT_URL} chrome"
    )


def test_tietoa_band_heading_is_a_rendered_element_not_only_bootstrap_data(
    direct_html,
):
    # cp-main-direct-edit.tietoa-band.tietoa-heading — "Tietoa minusta" is
    # SECTION_NAMES["tietoa"], which also rides in the JSON bootstrap, so
    # this pins the *element*. page.html must not be restructured, so the
    # six names ship in a hidden strip and direct-edit.js moves each into
    # its band; that placement is a browser claim, not proven here.
    strip = element_text(direct_html, "div", cls="direct-section-names")
    assert strip is not None
    assert "Tietoa minusta" in strip
    assert '<span data-kind="tietoa">Tietoa minusta</span>' in direct_html


def test_format_toolbar_strings_are_rendered_inside_the_toolbar(direct_html):
    # cp-main-direct-edit.direct-canvas.format-toolbar — the three asserted
    # strings belong to one element, not merely to the document. The
    # criterion's `when` (a text field is being edited) is browser-only:
    # the toolbar ships `hidden` and direct-edit.js unhides it on focus.
    toolbar = element_text(direct_html, "div", cls="direct-toolbar")
    assert toolbar is not None
    for expected in ("Linkki", "Lista", "Kumoa"):
        assert expected in toolbar
    assert 'class="direct-toolbar" role="toolbar"' in direct_html
    assert "Lista</button>" in direct_html


def test_publish_bar_strings_are_rendered_inside_the_publish_bar(direct_html):
    # cp-main-direct-edit.publish-bar.* — scoped to the bar element.
    bar = element_text(direct_html, "footer", cls="direct-publishbar")
    assert bar is not None
    for expected in (
        "muutosta",
        "Tallentamattomia muutoksia",
        "viimeksi tallennettu",
        "Hylkää",
        "Tallenna luonnos",
        "Julkaise muutokset",
    ):
        assert expected in bar


# --- the page copy the spec addresses, each scoped to its own element -------


@pytest.mark.parametrize(
    "address,expected",
    [
        pytest.param(
            "cp-main-direct-edit.direct-canvas.direct-kicker", text,
            id=f"cp-main-direct-edit.direct-canvas.direct-kicker:{index}",
        )
        for index, text in enumerate(
            SEED_BY_KIND["hero"]["kicker"].split(" · ")
        )
    ],
)
def test_direct_kicker(direct_html, address, expected):
    # The criterion is that each stored kicker part renders in the kicker
    # element, not that the parts are any particular words.
    kicker = element_text(direct_html, "p", cls="kicker")
    assert kicker is not None
    assert expected in kicker, f"{address}: {expected!r} not in the kicker"


def test_direct_title(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-title — the hero heading,
    # scoped to the h1 because the stored title can also appear elsewhere.
    assert element_text(direct_html, "h1") == SEED_BY_KIND["hero"]["title"]


def test_direct_portrait(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-portrait — "browse files" is
    # the portrait slot's own copy; "Vaihda kuva" is the Rule D pill, which
    # ships disabled, so this proves presence and nothing more.
    portrait = element_text(direct_html, "div", cls="portrait")
    assert portrait is not None
    assert "browse files" in portrait

    pill = element_text(direct_html, "button", cls="direct-portrait-pill")
    assert pill == "Vaihda kuva"
    assert 'class="button secondary direct-portrait-pill" disabled' in direct_html


@pytest.mark.parametrize(
    "address,expected",
    [
        pytest.param(
            "cp-main-direct-edit.direct-canvas.direct-ingress", text,
            id=f"cp-main-direct-edit.direct-canvas.direct-ingress:{index}",
        )
        for index, text in enumerate(
            SEED_BY_KIND["hero"]["subtitle"].split(" · ")
        )
    ],
)
def test_direct_ingress_subtitle_half(direct_html, address, expected):
    # The direct-ingress region's rect spans the subtitle line as well as
    # the intro; these strings are the parts of the stored hero subtitle.
    subtitle = element_text(direct_html, "p", cls="subtitle")
    assert subtitle is not None
    assert expected in subtitle, f"{address}: {expected!r} not in the subtitle"


# The spec's third direct-ingress string used to be asserted here as a strict
# xfail, on the grounds that no seeded value contained it byte-exact. LLM-COP-10
# DELETED it rather than re-wording the reason: the criterion pins a sentence of
# the mockup persona's copy, and against a neutral seed it can never fail, so a
# strict xfail there carries no information at all. It is reported in the spec
# delta as a criterion to demote to a note, which is where it belongs.


def test_direct_ingress_mobile_is_rendered_and_bound(direct_html):
    # What is actually true, and the only pytest-side purchase on the
    # ingress_mobile binding (its element is display:none above 720px, so
    # its dashed outline is a narrow-viewport browser check).
    seeded = SEED_BY_KIND["hero"]["ingress_mobile"]
    assert seeded.strip()
    mobile = element_text(direct_html, "p", cls="phone-only")
    assert mobile is not None
    assert seeded in mobile
    hero_id = section_ids(direct_html)["hero"]
    assert (
        f'data-section="{hero_id}" data-field="ingress_mobile"' in direct_html
    )


# --- Decision D: the two spec-addressed CTA-shaped fields, SCOPED -----------
#
# "Ota yhteyttä" is hard-coded in the header at page.html, so a
# whole-document contains-text for it cannot fail. element_text matches a
# class *token*, so cls="cta-contact" resolves to the hero CTA and skips
# the header button, whose classes are "button primary header-contact
# desktop-only".


def test_direct_cta_contact_is_the_hero_button_and_is_bound(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-cta-contact
    cta = element_text(direct_html, "button", cls="cta-contact")
    assert cta is not None, "no button.cta-contact in the hero"
    assert "Ota yhteyttä" in cta

    hero_id = section_ids(direct_html)["hero"]
    assert (
        '<button type="button" class="button primary cta-contact"'
        f' data-section="{hero_id}" data-field="contact_label">' in direct_html
    )

    # The header button carries the same words and must NOT be bound —
    # otherwise the scoping above would be decorative.
    header = element_text(direct_html, "button", cls="header-contact")
    assert header is not None
    assert "Ota yhteyttä" in header
    assert (
        '<button type="button" class="button primary header-contact'
        ' desktop-only">' in direct_html
    )


def test_direct_cta_services_is_the_hero_link_and_is_bound(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-cta-services — its spec note
    # says "its label is editable here", so presence is asserted on the
    # element and the binding attribute is asserted on its markup. That the
    # label is *editable* is a browser claim (contenteditable is set by JS).
    cta = element_text(direct_html, "a", cls="cta-services")
    assert cta is not None, "no a.cta-services in the hero"
    assert "Lue palveluista" in cta

    hero_id = section_ids(direct_html)["hero"]
    assert (
        '<a class="button secondary cta-services" href="#palvelut"'
        f' data-section="{hero_id}" data-field="services_label">' in direct_html
    )


# --- the binding table: every scalar field is bound or excluded with a reason


# The exclusion table, with the reason each field is not bound in place.
# A scalar field that is neither here nor in the document fails the test
# below, so a field added to app/fields.py cannot go silently unbound.
EXCLUDED_SCALARS = {
    ("hero", "portrait"): (
        "not text — it names an image slot. Uploading one now exists"
        " (LLM-COP-21: Vaihda/Poista in the side panel), but editing an"
        " image slot in place is still out of scope, so the direct-edit"
        " affordance stays the disabled 'Vaihda kuva' pill (Rule D). It has"
        " no FIELD_LABELS entry either, so it is not a form field anywhere."
    ),
    ("yhteydenotto", "name_label"): (
        "a bare text node directly inside <label> in page.html; binding it"
        " means wrapping it in a span, i.e. restructuring the public"
        " template. Still editable in the side panel (Nimikentän otsikko)."
    ),
    ("yhteydenotto", "email_label"): (
        "same bare-text-node-inside-<label> shape. Still editable in the"
        " side panel (Sähköpostikentän otsikko)."
    ),
    ("yhteydenotto", "message_label"): (
        "same bare-text-node-inside-<label> shape. Still editable in the"
        " side panel (Viestikentän otsikko)."
    ),
    ("yhteydenotto", "thanks"): (
        "not rendered on the page at all, so there is no element to bind."
        " Still editable in the side panel (Kiitosviesti)."
    ),
    # The three site-chrome fields (LLM-COP-10). All three render OUTSIDE any
    # section block, so none of them carries a data-section id; binding them
    # means restructuring the public template's header and footer, which this
    # artifact is explicitly not allowed to do. All three are editable in the
    # side panel, which is what closes LLM-COP-7's deferral.
    ("hero", "brand"): (
        "rendered in <header class=\"site-header\">, outside every section"
        " block, so it carries no data-section id. Still editable in the side"
        " panel (Sivuston nimi)."
    ),
    ("hero", "page_title"): (
        "rendered in <head><title>; there is no visible element to bind."
        " Still editable in the side panel (Selaimen otsikko)."
    ),
    ("hero", "footer"): (
        "rendered in <footer class=\"site-footer\">, the same outside-any-"
        "section shape as brand. Still editable in the side panel"
        " (Alatunniste)."
    ),
}

BOUND_SCALAR_COUNT = 14
EXCLUDED_SCALAR_COUNT = 8


def test_every_scalar_field_is_bound_or_excluded(direct_html):
    ids = section_ids(direct_html)
    bound = []
    excluded = []
    unaccounted = []
    for kind, schema in FIELDS.items():
        for name, descriptor in schema.items():
            if descriptor["type"] == "list":
                continue
            attribute = f'data-section="{ids[kind]}" data-field="{name}"'
            if attribute in direct_html:
                bound.append((kind, name))
            elif EXCLUDED_SCALARS.get((kind, name)):
                excluded.append((kind, name))
            else:
                unaccounted.append((kind, name))

    assert not unaccounted, (
        "scalar fields neither bound in /muokkaa/sivu nor listed in"
        f" EXCLUDED_SCALARS with a reason: {unaccounted}"
    )
    assert len(bound) == BOUND_SCALAR_COUNT, sorted(bound)
    assert len(excluded) == EXCLUDED_SCALAR_COUNT, sorted(excluded)
    assert set(excluded) == set(EXCLUDED_SCALARS)
    assert len(bound) + len(excluded) == sum(
        1
        for schema in FIELDS.values()
        for descriptor in schema.values()
        if descriptor["type"] != "list"
    )


def test_no_list_field_is_bound_in_place(direct_html):
    # Lists are rows, not text nodes; the side panel edits them.
    for kind, schema in FIELDS.items():
        for name, descriptor in schema.items():
            if descriptor["type"] != "list":
                continue
            assert f'data-field="{name}"' not in direct_html, (
                f"list field {kind}.{name} is bound as an in-place text field"
            )


def test_every_rendered_section_carries_its_id_and_kind(direct_html):
    ids = section_ids(direct_html)
    assert set(ids) == set(FIELDS)
    for kind, section_id in ids.items():
        assert f'data-section="{section_id}" data-kind="{kind}"' in direct_html


# --- the public template is not restructured in edit mode -------------------


def test_hero_markup_is_byte_identical_on_the_public_page_and_in_direct_mode(
    direct_admin,
):
    # The artifact's headline hazard, made testable: the data-* attributes
    # are emitted unconditionally, so with draft == published (the seed's
    # own state) the hero section is the same bytes in both documents. The
    # guarded <link> in <head> and the guarded chrome include after </main>
    # are outside the compared slice, so this genuinely constrains the
    # template rather than passing trivially.
    public = direct_admin.get("/").get_data(as_text=True)
    direct = direct_admin.get(DIRECT_URL).get_data(as_text=True)
    assert hero_section_markup(public) == hero_section_markup(direct)
    assert 'data-field="title"' in hero_section_markup(public)


def test_the_public_page_is_byte_identical_for_anonymous_and_signed_in(
    client, direct_admin
):
    # Nothing about being signed in changes GET /, so the leak test's
    # anonymous half and its authenticated half describe the same document.
    assert (
        client.get("/").get_data(as_text=True)
        == direct_admin.get("/").get_data(as_text=True)
    )


# --- direct mode renders the draft; the public page does not ----------------


def test_direct_mode_renders_the_draft_and_the_public_page_does_not(
    direct_admin, app
):
    hero = copy.deepcopy(SEED_BY_KIND["hero"])
    hero["title"] = "Luonnosotsikko"
    hero_id = stored_row(app, "hero")["id"]
    response = direct_admin.put(
        f"/api/sections/{hero_id}/draft", json=hero, headers=JSON_ACCEPT
    )
    assert response.status_code == 200

    direct = direct_admin.get(DIRECT_URL).get_data(as_text=True)
    assert element_text(direct, "h1") == "Luonnosotsikko"

    public = direct_admin.get("/").get_data(as_text=True)
    assert element_text(public, "h1") == SEED_BY_KIND["hero"]["title"]
    assert "Luonnosotsikko" not in public


def test_hidden_section_is_absent_from_direct_mode(direct_admin, app):
    # draft_sections(conn) without include_hidden — direct mode edits what
    # the page shows, exactly as /muokkaa/esikatselu does.
    set_section_state(app, "tietoa", "hidden")
    direct = direct_admin.get(DIRECT_URL).get_data(as_text=True)
    assert SEED_BY_KIND["tietoa"]["nostolause"] not in direct
    assert 'data-kind="tietoa"' not in direct
    assert 'data-field="nostolause"' not in direct
    # …and the sections still shown are still bound.
    assert 'data-field="title"' in direct


# --- the leak test: no editing chrome anywhere but /muokkaa/sivu ------------


@pytest.fixture
def leaky_documents(direct_admin, client):
    """The three documents that must carry no editing chrome: the public
    page signed in, the public page anonymous, and the draft preview.

    Each is asserted to be a real, rendered page first. Without that, an
    unguarded chrome include raises UndefinedError, Flask answers a 265-byte
    500, and every "chrome is absent" assertion below passes vacuously —
    which is exactly what happened before this fixture checked."""
    documents = {}
    for where, response in (
        ("GET / (signed in)", direct_admin.get("/")),
        ("GET / (anonymous)", client.get("/")),
        ("GET /muokkaa/esikatselu", direct_admin.get("/muokkaa/esikatselu")),
    ):
        assert response.status_code == 200, f"{where} answered {response.status}"
        html = response.get_data(as_text=True)
        assert element_text(html, "h1") == SEED_BY_KIND["hero"]["title"], (
            f"{where} is not the rendered page"
        )
        documents[where] = html
    return documents


@pytest.mark.parametrize("chrome", CHROME_ONLY_STRINGS)
def test_chrome_strings_do_not_leak(leaky_documents, chrome):
    for where, html in leaky_documents.items():
        assert chrome not in html, f"{chrome!r} leaked into {where}"


@pytest.mark.parametrize(
    "leak",
    ["direct-edit.css", "direct-edit.js", "direct-bootstrap", "save-queue.js"],
)
def test_direct_mode_assets_do_not_leak(leaky_documents, leak):
    for where, html in leaky_documents.items():
        assert leak not in html, f"{leak} leaked into {where}"


@pytest.mark.parametrize("attribute", ["contenteditable", "draggable"])
def test_editing_attributes_are_never_in_the_template(
    leaky_documents, direct_html, attribute
):
    # The dashed affordance and the editing attributes come from a class
    # and from JS at boot — never from the template — so Esikatsele and
    # the public page cannot show editing chrome. Asserted absent from
    # /muokkaa/sivu too: the template must not emit them there either.
    for where, html in leaky_documents.items():
        assert attribute not in html, f"{attribute} leaked into {where}"
    assert attribute not in direct_html


def test_the_contact_dialog_opener_coexists_with_direct_mode(
    leaky_documents, direct_html
):
    """LLM-COP-3 binds a click handler to .cta-contact, which is also the
    bound field hero.contact_label — so in direct edit mode one click
    used to both focus the field and open the contact dialog, whose
    backdrop then swallowed every further click and stopped editing.

    direct-edit.js answers that with a capture-phase click listener on
    the document, suppressing clicks on bound fields in edit mode only.
    What this test pins is the *precondition*: COP-3's opener really does
    ship into /muokkaa/sivu alongside direct-edit.js (so the suppression
    is load-bearing, not dead code), and it ships into the public page
    and the preview WITHOUT direct-edit.js (so the dialog still opens
    there — test_direct_mode_assets_do_not_leak is the other half).

    pytest executes no JavaScript, so it cannot prove the click
    behaviour itself. That is verified only in the live browser pass,
    where clicking the hero CTA in direct mode leaves the dialog hidden
    and focuses contact_label, while the same click on / opens it.
    """
    for where, html in leaky_documents.items():
        assert "contact-dialog" in html, f"COP-3's dialog is missing from {where}"
    assert "contact-dialog" in direct_html
    assert "direct-edit.js" in direct_html


def test_the_preview_still_renders_the_draft_page(direct_admin):
    # The leak test above would also pass against an empty document; this
    # pins that /muokkaa/esikatselu is the real page.
    preview = direct_admin.get("/muokkaa/esikatselu").get_data(as_text=True)
    assert element_text(preview, "h1") == SEED_BY_KIND["hero"]["title"]
    assert "preview.js" in preview


# --- the bootstrap: the only pytest purchase on the two browser-only strings


def test_bootstrap_carries_the_field_label_the_tag_is_built_from(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-title.otsikko-tag asserts
    # "OTSIKKO" when the heading is being edited. The tag's text is
    # FIELD_LABELS[kind][field].uppercased, produced by JS on focus, so
    # pytest can only prove the input it is produced from.
    bootstrap = bootstrap_json(direct_html, "direct-bootstrap")
    assert bootstrap["field_labels"]["hero"]["title"] == "Pääotsikko"
    assert "OTSIKKO" in "Pääotsikko".upper()


def test_bootstrap_carries_the_cap_the_counter_is_built_from(direct_html):
    # cp-main-direct-edit.direct-canvas.direct-title.direct-counter asserts
    # "14 / 60 merkkiä" when the heading is being edited. " merkkiä" is
    # server-rendered (asserted above); the count itself is JS.
    #
    # The CAP is the product's promise and is asserted. The NUMERATOR is live
    # data — it counts whatever title happens to be stored — so nothing here
    # pins it. It used to read `len(seeded title) == 13`, a constant that was
    # only true of the mockup persona's name: exactly the "data value promoted
    # to a promise" defect this artifact removes, and the same one filed as
    # LLM-COP-8. The spec's "14 / 60" is spec-delta material, not a constant.
    bootstrap = bootstrap_json(direct_html, "direct-bootstrap")
    assert bootstrap["fields"]["hero"]["title"]["cap"] == 60
    assert FIELDS["hero"]["title"]["cap"] == 60
    assert 0 < len(SEED_BY_KIND["hero"]["title"]) <= 60
    assert '<span class="direct-counter-value"></span> merkkiä' in direct_html


def test_bootstrap_carries_the_draft_payloads_and_the_schema(direct_html):
    bootstrap = bootstrap_json(direct_html, "direct-bootstrap")
    assert set(bootstrap) == {
        "sections", "fields", "field_labels", "section_names", "anchors"
    }
    hero = next(s for s in bootstrap["sections"] if s["kind"] == "hero")
    assert hero["payload"] == SEED_BY_KIND["hero"]
    assert bootstrap["section_names"]["tietoa"] == "Tietoa minusta"


# --- the artifact's own reviewer check, through the one write route ---------


HOSTILE_INGRESS = (
    'Palveluita <b>kaikille</b> — '
    '<a href="https://example.fi/" onclick="evil()">lisätietoa</a>'
    "<script>alert(1)</script>"
)
CLEAN_INGRESS = (
    "Palveluita <strong>kaikille</strong> — "
    '<a href="https://example.fi/">lisätietoa</a>'
)


def test_bold_and_link_edit_stores_clean_reads_back_and_publishes_sanitized(
    direct_admin, app
):
    """LLM-COP-6's reviewer check, minus the mouse: a bold+link edit made
    in direct mode reads back correctly in the side panel and renders
    sanitized publicly after publish. Direct mode has no write route of
    its own — it saves through PUT /api/sections/<id>/draft, which is the
    route driven here, so this exercises the seam direct mode uses."""
    hero = copy.deepcopy(SEED_BY_KIND["hero"])
    hero["ingress"] = HOSTILE_INGRESS
    hero_id = stored_row(app, "hero")["id"]

    response = direct_admin.put(
        f"/api/sections/{hero_id}/draft", json=hero, headers=JSON_ACCEPT
    )
    assert response.status_code == 200, response.get_data(as_text=True)

    # 1. What is stored is the sanitized string, exactly.
    stored = json.loads(stored_row(app, "hero")["draft"])
    assert stored["ingress"] == CLEAN_INGRESS

    # 2. It reads back into the side panel byte-identically. Parsed, not
    #    substring-matched: Jinja's tojson escapes '<' as \\u003c.
    shell = direct_admin.get("/muokkaa").get_data(as_text=True)
    panel = bootstrap_json(shell, "bootstrap")
    panel_hero = next(s for s in panel["sections"] if s["kind"] == "hero")
    assert panel_hero["payload"]["ingress"] == CLEAN_INGRESS

    # …and into direct mode's own bootstrap the same way.
    direct = direct_admin.get(DIRECT_URL).get_data(as_text=True)
    direct_hero = next(
        s
        for s in bootstrap_json(direct, "direct-bootstrap")["sections"]
        if s["kind"] == "hero"
    )
    assert direct_hero["payload"]["ingress"] == CLEAN_INGRESS

    # 3. After publish the public page renders it, sanitized.
    assert direct_admin.post("/api/publish").status_code == 200
    public = direct_admin.get("/").get_data(as_text=True)
    intro = element_text(public, "p", cls="intro")
    assert intro is not None
    assert "Palveluita kaikille — lisätietoa" in intro
    assert CLEAN_INGRESS in public
    assert "onclick" not in public
    assert "alert(1)" not in public
    assert "<script>alert" not in public
    assert "<b>" not in public
