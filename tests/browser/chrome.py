"""Where the browser comes from (LLM-COP-15) — one resolution, one module.

The conftest launches Chrome and test_browser_gate.py asserts Chrome is
findable; both must agree on what "findable" means, so the order lives
here once. A plain module, not the conftest: pytest registers a conftest
under its own plugin name and a `from tests.browser.conftest import ...`
elsewhere builds a SECOND module object for the same file, with its own
copy of every constant. A plain module imports to one object however it
is reached, which is what makes the gate test and the fixture provably
the same rule.

The resolution is deliberately short and has NO hardcoded /usr/bin or
/opt fallback. A fallback would make the missing-browser demo unfalsifi-
able: scrubbing PATH would prove nothing, because the fallback would
still be there. Playwright's own channel= resolution is never used for
the same reason — the conftest passes executable_path and nothing else,
so this function is the only thing standing between the suite and a
browser.
"""

import os
import shutil

CHROME_ENV = "CONTACT_PAGE_CHROME"

# Named in full so a failing gate tells a reader every place it looked,
# in order, rather than "not found".
NO_CHROME = (
    "Google Chrome was not found. The browser half of the gate needs a real "
    "Chrome.\n"
    f"Resolution order: ${CHROME_ENV} (authoritative if set), then "
    "`google-chrome` on PATH, then `google-chrome-stable` on PATH.\n"
    "Playwright's bundled Chromium is deliberately not used and "
    "`playwright install` is deliberately not part of setup; see README, "
    "Develop."
)


def chrome_path():
    """The Chrome to launch, or None when there is none.

    $CONTACT_PAGE_CHROME is authoritative and SHORT-CIRCUITING: set but
    not executable answers None rather than falling through to PATH. An
    override that silently resolved to some other browser would make the
    variable a suggestion, and the one person who sets it is the person
    who most needs to be told it is wrong.
    """
    override = os.environ.get(CHROME_ENV)
    if override:
        return override if os.access(override, os.X_OK) else None
    return shutil.which("google-chrome") or shutil.which("google-chrome-stable")
