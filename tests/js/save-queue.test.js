/* app/static/save-queue.js — the one save queue (LLM-COP-12).
 *
 * The module is three lines of promise chaining, and each of them is a way
 * to lose a draft. A direct-edit PUT is last-write-wins, so two runs
 * overlapping means the server keeps whichever reply landed second while
 * the page reports both saved; a chain that waits on the run itself is
 * poisoned by the first work function that throws, and the page can never
 * save again; a queue that calls work() to get something to chain on fires
 * the request at click time and destroys the dirty-set recompute the wait
 * exists for. Three defects, invisible in review, so all three get a
 * contract here and two of them get a contrast case.
 *
 * Not covered here: that direct-edit.js's Tallenna and Julkaise handlers
 * actually route through this queue. Those live behind a `document` the
 * harness deliberately does not provide (harness.js:9-13), so host wiring
 * sits in the same acknowledged gap autosave.test.js:9-11 records. The
 * browser scenarios cover it; this file covers the mechanism.
 *
 * Real promises and real microtasks throughout — no mock timers. There is
 * no clock in this module to mock; what is being observed is ordering.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { loadModule } = require("./harness.js");

/* A promise whose settling this file decides, so a run can be held
 * "in flight" for as long as an assertion needs it there. */
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/* Outcome as a value rather than as control flow. A rejecting run must be
 * OBSERVED, never awaited bare: awaiting it would raise the queue's own
 * error out of a contract function, where a contrast case's
 * assert.rejects(..., assert.AssertionError) would report the wrong
 * failure and prove nothing. */
function settle(promise) {
  return promise.then(
    (value) => ({ status: "fulfilled", value }),
    (reason) => ({ status: "rejected", reason })
  );
}

/* One macrotask, which every pending microtask chain drains ahead of. Used
 * to answer "has anything started yet?" rather than to wait for time. */
function drainMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/* --- the two contracts a contrast case breaks ---------------------------
 *
 * Both are async and assert with plain `assert`, so a failure surfaces as a
 * REJECTION carrying an AssertionError, which is what the contrast cases
 * match on. */

/* The never-rejecting tail. A run that throws must not take the queue with
 * it: the next run still starts. Asserted on whether the next work function
 * RAN — under the poisoning form run 2's promise merely inherits run 1's
 * rejection, so an assertion on run 2's value would fail on the wrong
 * thing. */
async function rejectionDoesNotStopTheQueueContract(createSaveQueue) {
  const queue = createSaveQueue();
  const boom = new Error("boom");

  let secondRan = false;
  const first = queue.add(() => Promise.reject(boom));
  const second = queue.add(() => {
    secondRan = true;
    return "second";
  });

  const firstOutcome = await settle(first);
  const secondOutcome = await settle(second);

  assert.strictEqual(
    secondRan,
    true,
    "the run queued behind a rejecting run must still be invoked"
  );
  assert.deepStrictEqual(
    secondOutcome,
    { status: "fulfilled", value: "second" },
    "and must resolve with its own value, not inherit the failure"
  );
  assert.strictEqual(firstOutcome.status, "rejected");
  assert.strictEqual(firstOutcome.reason, boom, "the failure is still reported");
}

/* Lazy invocation. add() takes the work function; it does not call it.
 * Asserted on WHEN work runs, never on the order the runs finish in: the
 * eager form still finishes them in order, so an ordering assertion would
 * pass under the mutation and the contrast would prove nothing. */
async function lazyInvocationContract(createSaveQueue) {
  const queue = createSaveQueue();
  const held = deferred();
  const invoked = [];

  const first = queue.add(() => {
    invoked.push("first");
    return held.promise;
  });
  const second = queue.add(() => {
    invoked.push("second");
    return "second";
  });

  assert.deepStrictEqual(
    invoked,
    [],
    "add() must queue the work function, not call it"
  );

  held.resolve("first");
  await first;
  await second;
  assert.deepStrictEqual(invoked, ["first", "second"], "both ran, in turn");
}

/* --- the queue as written ---------------------------------------------- */

test("add() queues the work function without calling it", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  await lazyInvocationContract(createSaveQueue);
});

test("two queued runs are never in flight at the same moment", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  const queue = createSaveQueue();

  const gates = { a: deferred(), b: deferred() };
  const started = [];
  let inFlight = 0;
  let mostAtOnce = 0;

  function work(name) {
    return function () {
      started.push(name);
      inFlight += 1;
      mostAtOnce = Math.max(mostAtOnce, inFlight);
      return gates[name].promise.then(() => {
        inFlight -= 1;
        return name;
      });
    };
  }

  const a = queue.add(work("a"));
  const b = queue.add(work("b"));

  await drainMicrotasks();
  assert.deepStrictEqual(started, ["a"], "b must not start while a is unfinished");

  gates.a.resolve();
  assert.strictEqual(await a, "a");
  await drainMicrotasks();
  assert.deepStrictEqual(started, ["a", "b"], "b starts once a has settled");

  gates.b.resolve();
  assert.strictEqual(await b, "b");
  assert.strictEqual(mostAtOnce, 1, "at most one run in flight, ever");
});

test("the second work function is invoked only after the first settles", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  const queue = createSaveQueue();

  const held = deferred();
  let firstSettled = false;
  let secondSawFirstSettled = null;

  const first = queue.add(() =>
    held.promise.then((value) => {
      firstSettled = true;
      return value;
    })
  );
  const second = queue.add(() => {
    secondSawFirstSettled = firstSettled;
    return "second";
  });

  await drainMicrotasks();
  assert.strictEqual(secondSawFirstSettled, null, "the second has not run yet");

  held.resolve("first");
  assert.strictEqual(await first, "first");
  assert.strictEqual(await second, "second");
  assert.strictEqual(
    secondSawFirstSettled,
    true,
    "the second work function ran after the first had finished"
  );
});

test("a rejecting run rejects to its own caller, with its own error", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  const queue = createSaveQueue();

  // The production route to this: saveDrafts() throws SYNCHRONOUSLY out of
  // its own body (JSON.stringify in the dirty filter, deepCopy of the
  // payload). The caller must still see that, or direct edit's error note
  // goes quiet about a save that never happened.
  const boom = new Error("stringify blew up");
  const outcome = await settle(
    queue.add(() => {
      throw boom;
    })
  );

  assert.deepStrictEqual(outcome, { status: "rejected", reason: boom });
});

test("a rejecting run does not stop the next queued run", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  await rejectionDoesNotStopTheQueueContract(createSaveQueue);
});

test("each caller is handed its own run's value", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  const queue = createSaveQueue();

  const first = queue.add(() => Promise.resolve({ ok: true, which: 1 }));
  const second = queue.add(() => Promise.resolve({ ok: false, which: 2 }));

  // Julkaise chains .then(function (ok) {…}) on exactly this promise, so a
  // queue that answered the tail's value instead would publish on the
  // strength of some earlier save's result.
  assert.deepStrictEqual(await first, { ok: true, which: 1 });
  assert.deepStrictEqual(await second, { ok: false, which: 2 });
});

test("a run added after a failed run has drained still runs", async () => {
  const { createSaveQueue } = loadModule("save-queue.js");
  const queue = createSaveQueue();

  await settle(
    queue.add(() => {
      throw new Error("boom");
    })
  );

  // Not the same case as queueing behind a run still in flight: here the
  // chain is idle and carrying whatever the failure left behind it. The
  // next click, seconds later, must still save.
  assert.strictEqual(await queue.add(() => "later"), "later");
});

/* --- contrast cases -----------------------------------------------------
 *
 * loadModule OUTSIDE the assert.rejects in both, so a stale anchor throws
 * AnchorNotFound and fails the test loudly instead of being counted as the
 * defect firing. assert.throws is not usable here: these contracts await,
 * so their failure arrives as a rejection, and the synchronous form would
 * report "Missing expected exception" for the wrong reason. */

test("CONTRAST: a tail chained on the run itself poisons the queue", async () => {
  const { createSaveQueue } = loadModule("save-queue.js", {
    from: "run.then(settled, settled)",
    to: "run"
  });
  await assert.rejects(
    rejectionDoesNotStopTheQueueContract(createSaveQueue),
    assert.AssertionError,
    "dropping the settle guard must fail the contract: one throw and the " +
      "chain stays rejected, so no later run is ever invoked"
  );
});

test("CONTRAST: calling work() to get a promise to chain breaks laziness", async () => {
  const { createSaveQueue } = loadModule("save-queue.js", {
    from: "tail.then(work)",
    to: "(function (p) { return tail.then(function () { return p; }); })(work())"
  });
  await assert.rejects(
    lazyInvocationContract(createSaveQueue),
    assert.AssertionError,
    "invoking work() at queue time must fail the contract, even though " +
      "this form still settles the runs in order"
  );
});
