"""The `browser` marker's extent, guarded.

The marker is applied by path in tests/browser/conftest.py rather than written
per file, so nothing has to be remembered -- and this is what notices if that
stops being true: if the predicate narrows, if someone replaces the hook with
per-file pytestmark and misses one, or if a new file lands somewhere the
predicate does not reach.

The CI branch guards the other, worse failure: a GREEN run in which the browser
layer never ran. Under `-m "not browser"` the set comparison above passes
VACUOUSLY (both sets empty) -- which is precisely the configuration that would
cause it -- so on a CI host every module file that exists under tests/browser/
must additionally have contributed at least one collected item. Derived from
disk, never a hardcoded count: adding or deleting a browser test file needs no
edit here.

Known limit: rglob("test_*.py") does not match `*_test.py`, which pytest also
collects by default. That is an under-catch, never a false red, and no such
file exists in this tree -- recorded here so the next reader does not have to
rediscover it.
"""

import os
from pathlib import Path

BROWSER_DIR = (Path(__file__).parent / "browser").resolve()


def _under_browser(item):
    return BROWSER_DIR in Path(item.path).resolve().parents


def test_the_browser_marker_covers_exactly_tests_browser(request):
    items = request.session.items

    under = {i.nodeid for i in items if _under_browser(i)}
    marked = {i.nodeid for i in items if i.get_closest_marker("browser") is not None}
    assert under == marked, (
        "the `browser` marker and the directory tests/browser/ have drifted. "
        "The marker is applied by path in tests/browser/conftest.py's "
        "pytest_collection_modifyitems; if a test is under that directory it "
        "must carry the marker, and nothing else may."
    )

    if os.environ.get("CI"):
        on_disk = {p.resolve() for p in BROWSER_DIR.rglob("test_*.py")}
        contributed = {Path(i.path).resolve() for i in items if _under_browser(i)}
        root = BROWSER_DIR.parent.parent
        silent = sorted(str(p.relative_to(root)) for p in on_disk - contributed)
        assert not silent, (
            "this CI run collected NOTHING from these files under "
            f"tests/browser/: {silent}. A green run that did not run the "
            "browser layer is the failure this project's browser tests exist "
            "to prevent -- check for `-m \"not browser\"`, `addopts` in "
            "pytest.ini, or an --ignore, or a `test_*.py` under tests/browser/ "
            "that defines no tests (put helpers in `conftest.py`, as this "
            "project already does). If you are seeing this on your own "
            "machine, unset CI for the fast local loop."
        )
