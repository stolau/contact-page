/* The one autosave debounce (LLM-COP-7), shared by the edit panel
 * (edit.js) and the first-run wizard (wizard.js).
 *
 * createAutosave(delay, save) owns a single debounce timer and nothing
 * else — the in-flight bookkeeping a host keeps around its own save()
 * stays the host's. The delay is declared here once, as
 * createAutosave.DELAY, so no host ever restates it; a host that did
 * would be a second implementation of this module.
 *
 *   schedule()  reset the timer; save() fires DELAY ms after the last call
 *   cancel()    clear the timer without firing — discard the pending write
 *   flush()     fire now if pending, handing back save()'s own return
 *               value; null when nothing was pending
 *   pending()   is a save queued
 */
(function () {
  "use strict";

  function createAutosave(delay, save) {
    var timer = null;

    function clear() {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
    }

    return {
      schedule: function () {
        clear();
        timer = setTimeout(function () {
          // Cleared before firing, so a save() that cancels or flushes
          // in turn sees an honest idle timer rather than this one.
          timer = null;
          save();
        }, delay);
      },
      cancel: clear,
      flush: function () {
        // The return value is load-bearing: Julkaise chains .then() on
        // it, so a pending save hands back save()'s own promise and an
        // idle one an honest null for the caller's `||` to fall through.
        if (!timer) return null;
        clear();
        return save();
      },
      pending: function () {
        return timer !== null;
      }
    };
  }

  // Two seconds after the last change, per the edit-panel spec. The one
  // declaration of the delay in the codebase.
  createAutosave.DELAY = 2000;

  window.createAutosave = createAutosave;
})();
