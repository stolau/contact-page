"""Every `X.hidden = ...` assignment site in this product, and the CSS
selector that finds the element it writes to (LLM-COP-48).

NOT a test module. This is a table, imported by two files that are:
tests/browser/test_browser_hidden.py drives a real Chrome over it, and
tests/test_hidden_registry.py re-derives the (file, left-hand side) set from
the sources with a regex and fails if the two ever disagree. The name is
deliberately not `test_*.py` — tests/test_browser_marker.py fails a CI run in
which any `test_*.py` under tests/browser/ contributes zero collected items,
and a table contributes none. tests/browser/test_browser_gate.py's ast scan
covers every `*.py` here, this file included, so nothing below imports
playwright.

WHY A TABLE OF ASSIGNMENT SITES AT ALL. An author-origin `display:` beats the
UA stylesheet's `[hidden] { display: none }` at any specificity, so an element
whose class was given a `display` and never a `[hidden]` companion renders
while carrying the attribute. Setting `.hidden = true` on it then changes
nothing on screen, and every server-side test in this repository still passes,
because the element is in the served HTML either way and only a real browser
computes a style. THIS PROJECT HAS SHIPPED THAT DEFECT FIVE TIMES:

  LLM-COP-5   `.button[hidden]`            — Poista drawn for a section with
                                             no picture, clearing a portrait
                                             that was already empty
  LLM-COP-31  `.kuva-row[hidden]`          — the picture row drawn on every
                                             section, so uploads failed with
                                             "tuntematon kenttä"
  LLM-COP-32  `.contact-dialog-form[hidden]` (twice: style.css and
                                             style-v2.css) — a sent contact
                                             form stayed visible and
                                             re-submittable
  LLM-COP-48  `.direct-toolbar[hidden]`    — the direct-edit formatting
                                             toolbar painted while hidden

plus the sixth, `.row-menu-items[hidden]` / `.add-section-menu[hidden]`,
caught before release and fenced at tests/test_sectionlist.py:1820. Four
repeats is a missing guard rather than four unlucky commits, which is what
this table is: the class-level answer.

THE SHAPE OF AN ENTRY. `file` and `lhs` are the assignment site, exactly as
the regex in tests/test_hidden_registry.py reads it out of the source —
that pair is the anti-drift key. `selector` is how a browser finds the same
element. `screens` names the screens the element is rendered on.

THE SOFT SPOT, SAID OUT LOUD. The anti-drift test compares `(file, lhs)` keys
only, so a WRONG-BUT-MATCHING selector would satisfy every guard here: rename
`.kuva-error` in the template and in edit.js and this table would still list
`.kuva-error`, the key set would still agree, and the sweep would quietly stop
probing that element. What limits the blast radius is the browser test's
second non-emptiness guard — EVERY selector in this table must match at least
one real element on its screen, with exactly one disclosed exception below. A
selector that has gone stale therefore turns the sweep red rather than green,
which is the property that makes a stale table visible. It does not close the
hole where a selector matches a DIFFERENT real element; nothing mechanical can,
and that is what a reader of this file has to check by hand.

THE SCREENS, and the route each one means. The browser test derives its case
list from this table, so there is no second list to drift:

  public    /                    the public page, per skin
  direct    /muokkaa/sivu        direct edit mode over the draft, per skin
  edit      /muokkaa             the side-panel editor
  sections  /muokkaa/osiot       the section list
  wizard    /yllapito/alustus    the first-run wizard

/yllapito/viestit is deliberately absent: it renders no `[hidden]` element and
loads no script that sets `.hidden`, so it contributes no entry here and the
browser test does not sweep it. See that module's docstring for why sweeping it
would be worse than not sweeping it.

THE ONE ENTRY NO BROWSER CAN REACH on a seeded install is stated as
`reachable=False` rather than left out: sectionlist.js's `addMenu`,
`.add-section-menu`, which edit_sections.html:40-46 renders only
`{% if offerable %}` — false on a seeded install, where every kind is already
on the page. Its `[hidden]` guard is not an unguarded declaration even so: it
is the SAME declaration as `.row-menu-items`' at sections.css:78-79, which the
sweep does probe, and a deletion of it alone is caught by
tests/test_sectionlist.py:1820, which reads the rule out of the stylesheet.
"""


class Site:
    """One `X.hidden = ...` assignment site.

    A small class rather than a tuple so the browser test's failure messages
    can name the file and the left-hand side, which is what a reader needs in
    order to find the line the sweep is complaining about.
    """

    __slots__ = ("file", "lhs", "note", "reachable", "screens", "selector")

    def __init__(self, file, lhs, selector, screens, reachable=True, note=""):
        self.file = file
        self.lhs = lhs
        self.selector = selector
        self.screens = tuple(screens)
        self.reachable = reachable
        self.note = note

    @property
    def key(self):
        return (self.file, self.lhs)

    def __repr__(self):
        return f"{self.file}:{self.lhs} -> {self.selector}"


# The routes, keyed by the screen name used in `screens` below.
SCREEN_ROUTES = {
    "public": "/",
    "direct": "/muokkaa/sivu",
    "edit": "/muokkaa",
    "sections": "/muokkaa/osiot",
    "wizard": "/yllapito/alustus",
}

# The screens that render a skin-selectable template (app/styles.py's
# template_for), and therefore have to be swept once per skin.
SKINNED_SCREENS = ("public", "direct")

# Every selector below was resolved by READING the source that assigns to it,
# never guessed from the variable's name — the variable `error` in edit.js is
# `.kuva-error` and the variable `error` in contact_dialog.html is
# `.contact-error`, and a table built from names would have merged them.
SITES = (
    # --- app/static/direct-edit.js -----------------------------------------
    # All six are queried at :48-57 off direct_edit_chrome.html, which
    # page.html/page_v2.html include only when the route passes
    # direct_edit=True — so direct mode, and nowhere else.
    Site("direct-edit.js", "tag", ".direct-field-tag", ("direct",)),
    Site("direct-edit.js", "counter", ".direct-counter", ("direct",)),
    Site("direct-edit.js", "toolbar", ".direct-toolbar", ("direct",)),
    Site("direct-edit.js", "changes", ".direct-changes", ("direct",)),
    Site("direct-edit.js", "autosave", ".direct-autosave", ("direct",)),
    Site("direct-edit.js", "errorNote", ".direct-errors", ("direct",)),

    # --- app/static/edit.js ------------------------------------------------
    # edit.html is the only template that loads it (:230).
    Site("edit.js", "ilmoitusRow", ".ilmoitus-row", ("edit",)),
    Site("edit.js", "muotoRow", ".muoto-row", ("edit",)),
    Site("edit.js", "savedNote", ".draft-saved-note", ("edit",)),
    Site("edit.js", "peruutaNote", ".peruuta-note", ("edit",)),
    # Both queried off a `.kuva-row` inside createImageRow (:309-310), so the
    # selector is the descendant, not a variable of the same name elsewhere.
    Site("edit.js", "poistaButton", ".kuva-row .poista-button", ("edit",)),
    Site("edit.js", "error", ".kuva-row .kuva-error", ("edit",)),
    # `imageRow.element` IS the .kuva-row the factory was handed (:381).
    Site("edit.js", "imageRow.element", ".kuva-row", ("edit",)),
    # The panel tab bodies, :42 `.panel-body[data-panel]`. The attribute is
    # part of the query, so it is part of the selector.
    Site("edit.js", "body", ".panel-body[data-panel]", ("edit",)),

    # --- app/static/section-form.js ----------------------------------------
    # createSectionForm builds the tag per field (:53-56) and hides it, so it
    # exists only once a form has actually been drawn. Of the three templates
    # that load the module (edit.html:229, edit_sections.html:68,
    # wizard.html:87) the wizard and /muokkaa both draw a form at boot, so the
    # tag is at rest on each; /muokkaa/osiot draws one only when a row is
    # expanded, which is why `sections` is not listed — a screen listed here
    # must yield a match.
    Site("section-form.js", "tag", ".muokataan-tag", ("edit", "wizard")),

    # --- app/static/sectionlist.js -----------------------------------------
    # edit_sections.html:69 is the only loader.
    Site("sectionlist.js", "items", ".row-menu-items", ("sections",)),
    # `other` is the same class: toggleMenu closes every OTHER row's menu
    # (:325-327) with the same querySelectorAll literal.
    Site("sectionlist.js", "other", ".row-menu-items", ("sections",)),
    Site(
        "sectionlist.js",
        'row.querySelector(".expanded-editor")',
        ".expanded-editor",
        ("sections",),
    ),
    Site("sectionlist.js", "addReason", ".add-section-reason", ("sections",)),
    # THE ONE UNREACHABLE ENTRY — see the module docstring.
    Site(
        "sectionlist.js",
        "addMenu",
        ".add-section-menu",
        (),
        reachable=False,
        note=(
            "edit_sections.html:40-46 renders .add-section-menu only "
            "{% if offerable %}, and a seeded install has every kind on the "
            "page already, so no browser on this harness can reach it. Its "
            "[hidden] guard is the same declaration as .row-menu-items' "
            "(sections.css:78-79), which this sweep does probe, and "
            "tests/test_sectionlist.py:1820 catches its independent deletion "
            "by reading the stylesheet."
        ),
    ),

    # --- app/static/wizard.js ----------------------------------------------
    # wizard.html:88 is the only loader.
    Site("wizard.js", "panel", ".wizard-panel[data-step]", ("wizard",)),
    Site("wizard.js", "finishPanel", ".wizard-finish", ("wizard",)),
    Site("wizard.js", "muotokuvaRow", ".wizard-muotokuva", ("wizard",)),
    Site("wizard.js", "publishedNote", ".wizard-published-note", ("wizard",)),
    Site("wizard.js", "skipButton", ".wizard-skip", ("wizard",)),
    Site("wizard.js", "saveButton", ".wizard-save", ("wizard",)),
    Site("wizard.js", "julkaiseButton", ".wizard-julkaise", ("wizard",)),

    # --- app/templates/contact_dialog.html ---------------------------------
    # The include lands in page.html:213 and page_v2.html:382, which serve
    # both `/` and /muokkaa/sivu — so all four are on both screens, both
    # skins.
    Site("contact_dialog.html", "dialog", ".contact-dialog",
         ("public", "direct")),
    # `form` is whichever form the submit handler was given; the query at
    # :130 is `form.contact-dialog-form, form.contact-form`, and .contact-form
    # renders in no template since USR-COP-1 deleted the on-page form. The
    # live half is named here.
    Site("contact_dialog.html", "form", ".contact-dialog-form",
         ("public", "direct")),
    # `error` and `result` are the slots the form names by id (:79, :124), not
    # neighbours: data-error="contact-error" and data-result="contact-thanks",
    # whose elements carry .contact-error and .cd-thanks (:42-43).
    Site("contact_dialog.html", "error", ".contact-error",
         ("public", "direct")),
    Site("contact_dialog.html", "result", ".cd-thanks", ("public", "direct")),

    # --- app/templates/gdpr_dialog.html ------------------------------------
    # Included beside the contact dialog (page.html:216, page_v2.html:385).
    Site("gdpr_dialog.html", "dialog", ".gdpr-dialog", ("public", "direct")),
)

# The anti-drift key set: what tests/test_hidden_registry.py re-derives from
# app/static/*.js and app/templates/*.html and compares against.
KEYS = {site.key for site in SITES}


def selectors_for(screen):
    """Every distinct selector this table says is rendered on `screen`.

    Distinct, because two assignment sites legitimately write to the same
    element — sectionlist.js's `items` and `other` are both `.row-menu-items`
    — and probing it twice would say nothing the first probe did not.
    """
    return sorted({site.selector for site in SITES if screen in site.screens})


def screens():
    """The screen names this table actually populates, in route order."""
    named = {screen for site in SITES for screen in site.screens}
    return tuple(name for name in SCREEN_ROUTES if name in named)
