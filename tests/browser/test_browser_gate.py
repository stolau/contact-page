"""The gate's own preconditions (LLM-COP-15).

Three tests that are about the harness rather than the product, and they
exist because a browser layer that quietly stops running is worse than no
browser layer at all: it reports green for a checkout that never launched
a browser. So a missing package and a missing browser are RED, never
skipped — the same discipline test_node_is_installed holds to for Node
(tests/test_js_suite.py) — and the third test fences the property that
makes the first one reachable at all.
"""

import ast
import importlib.util
from pathlib import Path

import pytest

from tests.browser.chrome import CHROME_ENV, NO_CHROME, chrome_path

BROWSER_DIR = Path(__file__).parent

# Function bodies are the ONLY place an import is deferred. A class body,
# an `if`, a `with`, a `try` — all of them run while the module is being
# imported, however deeply they are indented.
_DEFERRED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def import_time_nodes(node):
    """Every node reached while the module is being imported.

    Deliberately NOT a col_offset test. `col_offset == 0` reads as
    "module level" and is not: `if True:\\n    import playwright` sits at
    column 4, runs at import time all the same, and takes collection down
    on a checkout without the package — which is the one thing this test
    exists to prevent. Measured: the column version passed with exactly
    that text in conftest.py.

    Skipping the whole function node is safe for imports specifically —
    decorators and default arguments run at import time but cannot
    contain an import STATEMENT, so nothing findable is lost.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _DEFERRED):
            continue
        yield child
        yield from import_time_nodes(child)


def test_playwright_is_installed():
    """pytest.fail, deliberately not skipif.

    find_spec rather than an import, so this reports the remedy instead
    of raising ImportError out of collection.
    """
    if importlib.util.find_spec("playwright") is None:
        pytest.fail(
            "playwright is not installed, so the browser half of the gate "
            "cannot run. Install it with:\n"
            "    pip install -r requirements-dev.txt"
        )


def test_chrome_is_resolvable():
    """A missing browser fails the gate; it never shrinks it.

    The message names the whole resolution order, because the person
    reading it is the person who has to fix it — and the commonest fix is
    setting $CONTACT_PAGE_CHROME.
    """
    if chrome_path() is None:
        pytest.fail(NO_CHROME)
    assert CHROME_ENV == "CONTACT_PAGE_CHROME"  # the name README promises


def test_no_browser_module_imports_playwright_at_module_level():
    """Collection must survive a checkout with no playwright installed.

    It survives only while every playwright import in this directory sits
    inside a FUNCTION BODY — which is a narrower thing than "not at
    column 0", and the difference is the whole test. An import at column
    4 inside `if`, `with`, `try` or a class body still raises at
    collection, and then test_playwright_is_installed — the test whose
    whole job is to say `pip install -r requirements-dev.txt` — never
    runs to say it. conftest.py is scanned too; it is the file most
    likely to drift.
    """
    offenders = []
    for path in sorted(BROWSER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in import_time_nodes(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                modules = [alias.name for alias in node.names]
            for module in modules:
                if module == "playwright" or module.startswith("playwright."):
                    offenders.append(f"{path.name}:{node.lineno} imports {module}")

    assert not offenders, (
        "a module-level playwright import in tests/browser/ breaks collection "
        "on a checkout without the package, and takes "
        "test_playwright_is_installed down with it — defer it into the "
        f"function that needs it. {offenders}"
    )
