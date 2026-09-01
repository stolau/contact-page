/* First-run wizard controller (LLM-COP-7).
 *
 * Five client-side steps over the server-rendered chrome in wizard.html.
 * Every form is drawn by the shared builder (section-form.js) — the same
 * controls the edit panel draws — and every write goes through the same
 * draft route the panel writes through. The debounce is the shared one
 * (autosave.js): this file owns no timer of its own.
 *
 * One working payload per section id, not per step: steps 1 and 2 both
 * edit hero, and they must not clobber each other's fields.
 */
(function () {
  "use strict";

  var bootstrap = JSON.parse(
    document.getElementById("bootstrap").textContent
  );
  var sections = bootstrap.sections;
  var FIELDS = bootstrap.fields;
  var LABELS = bootstrap.field_labels;
  var STEPS = bootstrap.steps;

  var FINISH = STEPS.length; // `current` when the finish panel is open

  var navRows = document.querySelectorAll(".wizard-step");
  var segments = document.querySelectorAll(".wizard-progress-segment");
  var panels = document.querySelectorAll(".wizard-panel[data-step]");
  var forms = document.querySelectorAll(".wizard-panel[data-step] .wizard-form");
  var muotokuvaRow = document.querySelector(".wizard-muotokuva");
  var finishPanel = document.querySelector(".wizard-finish");
  var summaryList = document.querySelector(".wizard-summary");
  var publishedNote = document.querySelector(".wizard-published-note");
  var skipButton = document.querySelector(".wizard-skip");
  var backButton = document.querySelector(".wizard-back");
  var saveButton = document.querySelector(".wizard-save");
  var julkaiseButton = document.querySelector(".wizard-julkaise");

  var current = 0;
  var savedSteps = {}; // step index -> true, set only by a successful save
  var saveInFlight = null; // the last save()'s PUT, until it settles

  // The working payloads and their last-saved copies, keyed by section
  // id — the Ohita restore reads lastSaved, so it must survive steps.
  var payloads = {};
  var lastSaved = {};
  sections.forEach(function (section) {
    payloads[section.id] = deepCopy(section.payload);
    lastSaved[section.id] = deepCopy(section.payload);
  });

  function deepCopy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function sectionFor(index) {
    var kind = STEPS[index].kind;
    for (var i = 0; i < sections.length; i++) {
      if (sections[i].kind === kind) return sections[i];
    }
    return null;
  }

  /* ---- saving ---- */

  // save is a hoisted declaration, so constructing the shared debounce
  // over it here is safe. This file owns no timer of its own.
  var autosave = window.createAutosave(
    window.createAutosave.DELAY,
    save
  );

  function showErrors(errors) {
    if (current >= FINISH) return;
    var form = forms[current];
    var box = form.querySelector(".form-errors");
    if (!box) {
      box = document.createElement("div");
      box.className = "form-errors";
      form.insertBefore(box, form.firstChild);
    }
    var kind = STEPS[current].kind;
    box.textContent = Object.keys(errors)
      .map(function (name) {
        var label = (LABELS[kind] || {})[name] || name;
        return label + ": " + errors[name];
      })
      .join(" · ");
  }

  function clearErrors() {
    if (current >= FINISH) return;
    var box = forms[current].querySelector(".form-errors");
    if (box) box.remove();
  }

  function save() {
    // A save now settles whatever the debounce had queued.
    autosave.cancel();
    // The step is resolved here, at fire time, and captured: a timer
    // armed on one step must never write another step's payload.
    var step = current;
    if (step >= FINISH) return Promise.resolve(false);
    var section = sectionFor(step);
    var payload = deepCopy(payloads[section.id]);
    var request = fetch("/api/sections/" + section.id + "/draft", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      // Mirrors the edit panel: an expired session goes to the login
      // screen rather than silently swallowing every later autosave.
      if (response.status === 401) {
        window.location = "/yllapito";
        return false;
      }
      return response.json().then(function (data) {
        // The step may have been left while the PUT was in flight; the
        // error box belongs to the open step only, the saved section's
        // own rows always.
        if (!response.ok) {
          if (step === current) showErrors(data.errors || {});
          return false;
        }
        if (step === current) clearErrors();
        lastSaved[section.id] = deepCopy(payload);
        section.payload = deepCopy(payload);
        savedSteps[step] = true;
        renderProgress();
        return true;
      });
    });
    saveInFlight = request;
    request.then(
      function () {
        if (saveInFlight === request) saveInFlight = null;
      },
      function () {
        if (saveInFlight === request) saveInFlight = null;
      }
    );
    return request;
  }

  /* ---- nav and progress, from one source ---- */

  function stepStates() {
    return STEPS.map(function (step, i) {
      if (i === current) return "current";
      return savedSteps[i] ? "done" : "upcoming";
    });
  }

  // The only consumer of stepStates: it paints the nav rows and the
  // segments together, so the two can never disagree. There is no
  // progress counter — `current` is a position, not progress.
  function renderProgress() {
    stepStates().forEach(function (state, i) {
      navRows[i].className = "wizard-step is-" + state;
      segments[i].className =
        "wizard-progress-segment" + (state === "upcoming" ? "" : " is-filled");
    });
  }

  /* ---- steps ---- */

  function buildStepForm() {
    var step = STEPS[current];
    window.createSectionForm(forms[current], {
      kind: step.kind,
      draft: payloads[sectionFor(current).id],
      fields: FIELDS,
      labels: LABELS,
      helpers: step.helpers,
      only: step.only,
      onChange: function () {
        autosave.schedule();
      }
    });
  }

  function buildSummary() {
    summaryList.textContent = "";
    STEPS.forEach(function (step, i) {
      var row = document.createElement("li");
      row.className = "wizard-summary-row";
      var name = document.createElement("span");
      name.textContent = step.label;
      var state = document.createElement("span");
      state.className = "wizard-summary-state";
      state.textContent = savedSteps[i] ? "Täytetty" : "Ohitettu";
      row.appendChild(name);
      row.appendChild(state);
      summaryList.appendChild(row);
    });
  }

  function openStep() {
    var finishing = current === FINISH;
    panels.forEach(function (panel, i) {
      panel.hidden = finishing || i !== current;
    });
    finishPanel.hidden = !finishing;
    skipButton.hidden = finishing;
    saveButton.hidden = finishing;
    julkaiseButton.hidden = !finishing;
    // Re-arming Julkaise retracts the published note with it, so the
    // panel can never both claim to be published and offer to publish.
    publishedNote.hidden = true;
    // Takaisin stays visible on step 1, disabled — the spec asserts it
    // is visible, and the wizard opens on step 1.
    backButton.disabled = current === 0;
    if (muotokuvaRow) {
      muotokuvaRow.hidden = finishing || !STEPS[current].muotokuva;
    }
    if (finishing) {
      buildSummary();
    } else {
      buildStepForm();
    }
    renderProgress();
  }

  function goTo(index) {
    // First statement, and load-bearing: a timer armed on this step
    // resolves its section at fire time, so leaving the step with one
    // pending would write the next step's payload against this step's
    // section — a dropped edit, or a 400 on validate_payload.
    autosave.flush();
    // Clamped so openStep is total: every caller's arithmetic lands on a
    // real step or on the finish panel, never past the roster.
    current = Math.max(0, Math.min(index, FINISH));
    openStep();
  }

  function skip() {
    // Cancel, never flush: skipping is precisely the case where the
    // owner's in-progress edits are meant to be discarded. No fetch is
    // issued at all, so the row is untouched and its badge stays
    // Julkaistu — badge compares raw JSON text, so writing even a
    // semantically identical payload would be a risk not worth taking.
    autosave.cancel();
    var section = sectionFor(current);
    // Without this restore a later save of the other hero step would
    // smuggle these discarded edits back in.
    payloads[section.id] = deepCopy(lastSaved[section.id]);
    goTo(current + 1); // savedSteps[current] deliberately untouched
  }

  /* ---- chrome wiring ---- */

  navRows.forEach(function (row, index) {
    row.addEventListener("click", function () {
      goTo(index);
    });
  });

  skipButton.addEventListener("click", skip);

  backButton.addEventListener("click", function () {
    if (current > 0) goTo(current - 1);
  });

  saveButton.addEventListener("click", function () {
    // The step this click meant, captured now: `current` is read again
    // when the PUT resolves, and two clicks in one frame would otherwise
    // both advance from the step the second one already left — skipping
    // a step, or running off the end of the roster.
    var step = current;
    save().then(function (saved) {
      if (saved && current === step) goTo(step + 1);
    });
  });

  julkaiseButton.addEventListener("click", function () {
    // A pending autosave — still debounced, or already in flight — must
    // land before the publish reads the drafts.
    var pending = autosave.flush() || saveInFlight || Promise.resolve();
    pending.then(publishNow);
  });

  function publishNow() {
    fetch("/api/publish", {
      method: "POST",
      headers: { "Accept": "application/json" }
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function () {
        julkaiseButton.hidden = true;
        publishedNote.hidden = false;
      });
    });
  }

  openStep();
})();
