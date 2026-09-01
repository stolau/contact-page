"""LLM-COP-12 — /muokkaa/sivu must load save-queue.js before direct-edit.js.

Mandatory, not stylistic, in the same sense test_wizard.py's script-order
test is: direct-edit.js constructs its queue by calling
window.createSaveQueue() at boot, so a missing tag or a tag placed after it
leaves that name undefined, the IIFE throws before it binds a single
handler, and /muokkaa/sivu renders as a page whose editing chrome does
nothing at all. Every other test in tests/ would still be green — they
assert what strings ship, and all of these strings ship in either order.

This is also the file that carries what the withdrawn grep pin was
standing in for on the loading side. tests/js/save-queue.test.js proves the
queue behaves; this proves direct mode is actually handed it.
"""

from html.parser import HTMLParser

DIRECT_URL = "/muokkaa/sivu"


def script_order(html):
    """The src attributes of the document's <script src=…>, in order."""

    class _Scripts(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.srcs = []

        def handle_starttag(self, tag, attrs):
            if tag == "script":
                src = dict(attrs).get("src")
                if src:
                    self.srcs.append(src.rsplit("/", 1)[-1])

    parser = _Scripts()
    parser.feed(html)
    return parser.srcs


def test_direct_mode_loads_save_queue_before_direct_edit(logged_in_admin):
    response = logged_in_admin.get(DIRECT_URL)
    # Asserted first: an unrendered page (a 500 from an unguarded include)
    # would make every "the script is there" check below pass vacuously.
    assert response.status_code == 200, response.status
    srcs = script_order(response.get_data(as_text=True))

    assert "save-queue.js" in srcs, srcs
    assert "direct-edit.js" in srcs, srcs
    assert srcs.index("save-queue.js") < srcs.index("direct-edit.js"), srcs
