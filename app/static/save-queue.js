/* The one save queue (LLM-COP-12), owned by direct edit mode
 * (app/static/direct-edit.js).
 *
 * A draft write is last-write-wins — PUT /api/sections/<id>/draft is a
 * bare UPDATE with no version column and no If-Match — so two writes to
 * one section in flight at once are decided by arrival order, and the
 * later click can lose to the earlier one while the page reports both as
 * saved. Two ordinary clicks are enough; nothing else on that page
 * guards it. The queue's whole job is that no two runs overlap.
 *
 * createSaveQueue() owns a promise chain and nothing else: no timers, no
 * DOM, no idea what a save is. It is autosave.js's sibling in shape — one
 * mechanism, in one place, so no host grows a second one.
 *
 *   add(work)  start work only once every run queued before it has
 *              settled, and hand back that run's own promise
 *
 * Two properties carry the module, and each is a way to get it wrong.
 *
 * Lazy — the work function is queued, not called. It reads the world when
 * it runs (direct edit's saveDrafts computes its dirty set in its own
 * body), so a run that waited recomputes instead of replaying what was
 * true at the click; that is what lets a queued save with nothing left to
 * send issue no request at all. Calling work here to get a promise to
 * chain would both fire the request immediately and destroy that
 * recompute.
 *
 * A never-rejecting tail — what the next run waits on is a derivative of
 * the run that cannot reject, never the run itself. Chained onto the run
 * itself, the first work function that throws leaves the chain
 * permanently rejected and every later run inherits that rejection
 * without ever starting: one error and the page can never save again.
 * The derivative absorbs the rejection for the chain only. The promise
 * handed back to the caller still rejects, so a host that reports its
 * failures keeps seeing them.
 */
(function () {
  "use strict";

  function createSaveQueue() {
    // Handed to both arms, so the chain records that a run finished and
    // nothing about how it went. The queue has no opinion on the outcome;
    // the caller's promise is where the outcome lives.
    function settled() {}

    var tail = Promise.resolve();

    return {
      add: function (work) {
        // Passed, not called: the chain invokes it when it reaches it.
        var run = tail.then(work);
        // The chain moves on to the rejection-proof derivative, so the
        // next run starts whether this one resolved or threw.
        tail = run.then(settled, settled);
        return run;
      }
    };
  }

  window.createSaveQueue = createSaveQueue;
})();
