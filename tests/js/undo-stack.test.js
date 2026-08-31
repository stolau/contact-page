/* app/static/editor.js — createUndoStack's burst-coalescing contract
 * (LLM-COP-14, rebuilding the throwaway harness LLM-COP-6 wrote and had
 * nowhere to keep).
 *
 * The contract that matters to a person pressing Kumoa: a burst of typing
 * is ONE undo step, and the value it restores is the value as it stood
 * BEFORE the burst began — not the value part-way through it. That is the
 * whole reason record() pushes `previous` rather than read().
 *
 * Not covered here: mark(), sync(), reset() and the UNDO_LIMIT shift, and
 * nothing about how edit.js or direct-edit.js wire record() to real input
 * events. The clock is node:test's mock timer, so nothing here is timing
 * dependent.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { loadModule } = require("./harness.js");

const COALESCE = 600; // UNDO_COALESCE in editor.js

/* The contract, as a function, so the contrast case can run the very same
 * assertions against a deliberately broken copy of the module. */
function undoBurstContract(createUndoStack, t) {
  let value = "";
  const stack = createUndoStack(
    () => value,
    (v) => {
      value = v;
    }
  );

  assert.strictEqual(stack.undo(), false, "undo on an empty stack is false");

  // Burst one: "" -> "abc" in three record()s inside one quiet window.
  value = "a";
  stack.record();
  t.mock.timers.tick(COALESCE - 100);
  value = "ab";
  stack.record();
  t.mock.timers.tick(COALESCE - 100);
  value = "abc";
  stack.record();
  t.mock.timers.tick(COALESCE); // the burst settles

  // Burst two: "abc" -> "abcde".
  value = "abcd";
  stack.record();
  t.mock.timers.tick(COALESCE - 100);
  value = "abcde";
  stack.record();
  t.mock.timers.tick(COALESCE);

  assert.strictEqual(stack.undo(), true, "the second burst is undoable");
  assert.strictEqual(
    value,
    "abc",
    "the second burst collapses to one entry, holding the value from before it"
  );
  assert.strictEqual(stack.undo(), true, "the first burst is undoable");
  assert.strictEqual(
    value,
    "",
    "the first burst collapses to one entry, holding the value from before it"
  );
  assert.strictEqual(stack.undo(), false, "the stack is empty again");
}

test("a typing burst is one undo step, back to the value before it", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const win = loadModule("editor.js");
  undoBurstContract(win.createUndoStack, t);
});

test("CONTRAST: push(read()) instead of push(previous) breaks the burst contract", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  // loadModule OUTSIDE the assert.throws: a stale anchor must fail this
  // test loudly with AnchorNotFound, not satisfy it.
  const win = loadModule("editor.js", {
    from: "stack.push(previous);",
    to: "stack.push(read());"
  });
  assert.throws(
    () => undoBurstContract(win.createUndoStack, t),
    assert.AssertionError,
    "recording the value DURING the burst must fail the contract"
  );
});
