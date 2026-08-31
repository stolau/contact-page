"""LLM-COP-14 — the bridge that makes `pytest` mean the whole gate.

Every other file under tests/ asserts only that the right strings ship to
the browser; none of them executes a line of JavaScript, and six real
defects shipped green because of it. tests/js/ is that JavaScript's test
home, run on Node's own built-in test runner with no third-party
dependency, and this module is what puts it inside the one gate command.

A runner that is optional is a runner that rots, so this never skips: a
missing Node is a red test, not a quiet pass. `node` must be on PATH —
Node 22.x, see README's Develop section.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

JS_DIR = Path(__file__).parent / "js"
# Recursive, so a suite filed in a subdirectory still runs rather than
# sitting there looking covered.
FILES = sorted(JS_DIR.rglob("*.test.js"))
NODE = shutil.which("node")  # resolved once, absolute

# The exact current count per file. The assertion is >=, so adding a test
# never breaks the gate; only deleting one does, which is when a human
# should look. Never lowball one: a floor under the true count is a hole
# nothing else notices.
EXPECTED_MIN = {
    "undo-stack.test.js": 2,
    "autosave.test.js": 7,
    "editor-serialize.test.js": 8,
}

_COUNT = re.compile(
    r"^# (tests|pass|fail|cancelled|skipped|todo) (\d+)$", re.MULTILINE
)


def _tap_counts(stdout: str) -> dict[str, int]:
    """The TAP summary counters. Last match wins.

    Node escapes a leading "#" from a test body (console.log and a raw
    process.stdout.write alike both come out as "# \\# ..."), but an
    unprefixed console.log("pass 0") is rendered as a "# pass 0"
    diagnostic and would match. The real summary is emitted last, so
    last-wins is what makes these counters unforgeable.
    """
    return {k: int(v) for k, v in _COUNT.findall(stdout)}


def test_node_is_installed():
    """A missing runtime fails the gate; it never shrinks it to the Python
    half. pytest.fail, deliberately not skipif — a skip here is the false
    assurance this whole artifact exists to remove."""
    if NODE is None:
        pytest.fail(
            "node is not on PATH, so the JavaScript half of the gate cannot "
            "run. Install Node 22.x (see README, Develop). An nvm install "
            "your login shell can see is not enough for a cron or container "
            "shell."
        )


def test_js_dir_holds_only_named_files():
    """A .js under tests/js/ that is neither a suite nor the harness is a
    file nothing runs and nothing reports."""
    stray = sorted(
        str(p.relative_to(JS_DIR))
        for p in JS_DIR.rglob("*.js")
        # By relative path, not basename: a second tests/js/lib/harness.js
        # must not inherit the exemption.
        if p.relative_to(JS_DIR) != Path("harness.js")
        and not p.name.endswith(".test.js")
    )
    assert not stray, (
        "a .js under tests/js/ that is neither *.test.js nor harness.js is "
        "never run by the gate and nothing else notices. (This suite is "
        "dependency-free by design: a node_modules/ under tests/js/ will "
        f"trip this too.) {stray}"
    )
    assert FILES, "tests/js/ holds no *.test.js — the JavaScript half of the gate is empty"
    assert set(EXPECTED_MIN) == {str(p.relative_to(JS_DIR)) for p in FILES}, (
        "every *.test.js must declare a floor in EXPECTED_MIN; "
        f"declared={sorted(EXPECTED_MIN)} found="
        f"{sorted(str(p.relative_to(JS_DIR)) for p in FILES)}"
    )


_NAMES = [str(p.relative_to(JS_DIR)) for p in FILES]


@pytest.mark.parametrize("name", _NAMES, ids=_NAMES)
def test_js_file(name):
    if NODE is None:
        pytest.fail("node is not on PATH; see test_node_is_installed")
    proc = subprocess.run(
        # --test-reporter=tap pinned: Node >= 23 defaults to the spec
        # reporter, and without the pin the regex below matches nothing and
        # the floor becomes unreachable.
        [NODE, "--test", "--test-reporter=tap", name],
        cwd=JS_DIR,
        capture_output=True,
        text=True,
        # A hung JavaScript test fails the gate rather than freezing it.
        timeout=120,
        # The assertions below report the TAP output; a CalledProcessError
        # would throw it away.
        check=False,
    )
    counts = _tap_counts(proc.stdout)
    report = proc.stdout + proc.stderr
    # -1 sentinels fail closed when the process died before TAP began.
    assert proc.returncode == 0, f"{name} exited {proc.returncode}\n{report}"
    assert counts.get("fail", -1) == 0, f"{name} reported failures\n{report}"
    assert counts.get("cancelled", -1) == 0, f"{name} cancelled a test\n{report}"
    assert counts.get("skipped", -1) == 0, (
        f"{name} skipped a test — a skip in the gate is a hole\n{report}"
    )
    assert counts.get("todo", -1) == 0, (
        f"{name} has a todo test — a todo in the gate is a hole\n{report}"
    )
    # A file that registers ZERO tests is reported by Node as one passing
    # subtest named for the file itself, so pass >= 1 is satisfied by a file
    # that tested nothing. This catches that; the floor below catches the
    # opposite shape (a describe with every it() commented out gives
    # pass 0, tests 0, rc 0). Both are needed.
    assert f"# Subtest: {name}\n" not in proc.stdout, (
        f"{name} registered NO tests; Node passed the file itself\n{report}"
    )
    assert counts.get("pass", 0) >= EXPECTED_MIN[name], f"{name} lost tests\n{report}"
