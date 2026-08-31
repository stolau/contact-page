/* app/static/autosave.js — the one debounce (LLM-COP-14 covering LLM-COP-7).
 *
 * Two save-chain defects shipped green here before anything ran this file:
 * a race that lost a keystroke while the badge said saved, and a publish
 * that no-opped because flush()'s return value was not what the caller
 * chained on. Both live in the four lines below, so those four lines get
 * the contract spelled out.
 *
 * Not covered here: how edit.js and wizard.js call schedule(), what they do
 * with the promise flush() hands back, or any in-flight bookkeeping — that
 * is the host's, deliberately, and it has no test home yet. The clock is
 * node:test's mock timer; nothing here waits on real time.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { loadModule } = require("./harness.js");

/* The contract the contrast case breaks: an idle flush() must be a no-op
 * that answers null, because Julkaise falls through it with `||`. A flush()
 * that saved unasked would write on every publish. */
function idleFlushContract(createAutosave) {
  let saves = 0;
  const autosave = createAutosave(createAutosave.DELAY, () => {
    saves += 1;
    return "saved";
  });

  assert.strictEqual(autosave.pending(), false, "nothing is queued yet");
  assert.strictEqual(autosave.flush(), null, "an idle flush answers null");
  assert.strictEqual(saves, 0, "an idle flush does not call save");
}

test("save fires once, DELAY ms after schedule()", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");

  let saves = 0;
  const autosave = createAutosave(createAutosave.DELAY, () => {
    saves += 1;
  });

  autosave.schedule();
  assert.strictEqual(autosave.pending(), true);
  t.mock.timers.tick(createAutosave.DELAY - 1);
  assert.strictEqual(saves, 0, "nothing fires before the delay is up");
  t.mock.timers.tick(1);
  assert.strictEqual(saves, 1, "the save fires exactly on the delay");
  assert.strictEqual(autosave.pending(), false, "the timer clears itself");
  t.mock.timers.tick(createAutosave.DELAY * 3);
  assert.strictEqual(saves, 1, "and never fires a second time");
});

test("a second schedule() inside the window restarts the timer, saving once", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");

  let saves = 0;
  const autosave = createAutosave(createAutosave.DELAY, () => {
    saves += 1;
  });

  autosave.schedule();
  t.mock.timers.tick(createAutosave.DELAY - 1);
  autosave.schedule(); // one keystroke short of firing
  t.mock.timers.tick(createAutosave.DELAY - 1);
  assert.strictEqual(saves, 0, "the second schedule() restarted the clock");
  t.mock.timers.tick(1);
  assert.strictEqual(saves, 1, "two schedules inside one window are one save");
});

test("cancel() discards the pending write without firing it", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");

  let saves = 0;
  const autosave = createAutosave(createAutosave.DELAY, () => {
    saves += 1;
  });

  autosave.schedule();
  autosave.cancel();
  assert.strictEqual(autosave.pending(), false, "cancel() clears pending()");
  t.mock.timers.tick(createAutosave.DELAY * 2);
  assert.strictEqual(saves, 0, "a cancelled write never fires");
});

test("flush() while pending fires now and hands back save()'s own return value", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");

  let saves = 0;
  const token = { promise: "the caller chains .then() on this" };
  const autosave = createAutosave(createAutosave.DELAY, () => {
    saves += 1;
    return token;
  });

  autosave.schedule();
  t.mock.timers.tick(1);
  assert.strictEqual(autosave.pending(), true);
  assert.strictEqual(autosave.flush(), token, "flush() returns save()'s value");
  assert.strictEqual(saves, 1, "and fired it exactly once");
  assert.strictEqual(autosave.pending(), false, "flush() clears the timer");
  t.mock.timers.tick(createAutosave.DELAY * 2);
  assert.strictEqual(saves, 1, "the flushed timer does not fire again");
});

test("flush() while idle answers null and does not call save", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");
  idleFlushContract(createAutosave);
});

test("createAutosave.DELAY is the codebase's one declaration of 2000ms", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { createAutosave } = loadModule("autosave.js");
  // A host that restated the delay would be a second implementation of
  // this module; the edit-panel spec's two seconds lives here alone.
  assert.strictEqual(createAutosave.DELAY, 2000);
});

test("CONTRAST: an idle flush() that returns save() breaks the publish path", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  // loadModule OUTSIDE the assert.throws: a stale anchor must fail this
  // test loudly with AnchorNotFound, not satisfy it.
  const { createAutosave } = loadModule("autosave.js", {
    from: "if (!timer) return null;",
    to: "if (!timer) return save();"
  });
  assert.throws(
    () => idleFlushContract(createAutosave),
    assert.AssertionError,
    "saving on an idle flush must fail the contract"
  );
});
