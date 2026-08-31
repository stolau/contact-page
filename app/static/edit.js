/* Edit-mode controller (LLM-COP-4).
 *
 * The panel form is drawn by the shared schema-driven form builder
 * (section-form.js) from the bootstrapped field schema (app/fields.py)
 * — no per-section form is hand-built here. Drafts autosave through the
 * shared debounce (autosave.js) after the last change; Tallenna saves at
 * once; Peruuta restores the last-saved draft; Julkaise publishes every
 * dirty section. The preview iframe renders /muokkaa/esikatselu (the
 * real page from drafts) and reloads after each successful save.
 */
(function () {
  "use strict";

  var bootstrap = JSON.parse(
    document.getElementById("bootstrap").textContent
  );
  var sections = bootstrap.sections;
  var FIELDS = bootstrap.fields;
  var LABELS = bootstrap.field_labels;
  var NAMES = bootstrap.section_names;
  var ANCHORS = bootstrap.anchors;

  var form = document.querySelector(".section-form");
  var sectionName = document.querySelector(".section-name");
  var sectionPosition = document.querySelector(".section-position");
  var muotokuvaRow = document.querySelector(".muotokuva-row");
  var muutOsiotList = document.querySelector(".muut-osiot-list");
  var savedNote = document.querySelector(".draft-saved-note");
  var savedTime = document.querySelector(".saved-time");
  var peruutaNote = document.querySelector(".peruuta-note");
  var previewFrame = document.querySelector(".preview-frame");
  var preview = document.querySelector(".preview");

  var current = 0;
  var draft = null; // the working payload
  var lastSaved = null; // the payload as last saved (or loaded)
  var saveInFlight = null; // the last save()'s PUT, until it settles
  var peruutaTimer = null;

  function deepCopy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function labelFor(kind, name) {
    return (LABELS[kind] || {})[name];
  }

  /* ---- saving ---- */

  // The debounce is the shared module's; only the in-flight PUT above is
  // this panel's own. save is a hoisted declaration, so it is safe here.
  var autosave = window.createAutosave(
    window.createAutosave.DELAY,
    save
  );

  function scheduleAutosave() {
    autosave.schedule();
  }

  function showErrors(errors) {
    var box = form.querySelector(".form-errors");
    if (!box) {
      box = document.createElement("div");
      box.className = "form-errors";
      form.insertBefore(box, form.firstChild);
    }
    var kind = sections[current].kind;
    box.textContent = Object.keys(errors)
      .map(function (name) {
        return (labelFor(kind, name) || name) + ": " + errors[name];
      })
      .join(" · ");
  }

  function clearErrors() {
    var box = form.querySelector(".form-errors");
    if (box) box.remove();
  }

  function showSavedNote(savedAt) {
    var when = new Date(savedAt * 1000);
    savedTime.textContent =
      when.getHours() + "." + ("0" + when.getMinutes()).slice(-2);
    peruutaNote.hidden = true;
    savedNote.hidden = false;
  }

  function save() {
    // A save now settles whatever the debounce had queued.
    autosave.cancel();
    var section = sections[current];
    var payload = deepCopy(draft);
    var request = fetch("/api/sections/" + section.id + "/draft", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "Accept": "application/json"
      },
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function (data) {
        if (!response.ok) {
          showErrors(data.errors || {});
          return;
        }
        // The section may have been switched while the PUT was in
        // flight; the panel state (lastSaved, notes) belongs to the
        // open section only, the saved section's own rows always.
        if (section === sections[current]) {
          clearErrors();
          lastSaved = payload;
          showSavedNote(data.saved_at);
        }
        section.payload = deepCopy(payload);
        section.badge = data.badge;
        reloadPreview();
        buildMuutOsiot();
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

  /* ---- preview ---- */

  function reloadPreview() {
    try {
      preview.contentWindow.location.reload();
    } catch (error) {
      preview.src = preview.src;
    }
  }

  function highlightPreview() {
    var anchor = ANCHORS[sections[current].kind];
    try {
      preview.contentWindow.postMessage({ anchor: anchor }, "*");
    } catch (error) {
      /* the frame is still loading; the load handler resends */
    }
  }

  preview.addEventListener("load", highlightPreview);

  /* ---- form generation (schema-driven) ---- */

  // The controls themselves live in the shared builder (section-form.js),
  // which the wizard draws the same fields with; the panel supplies the
  // open section's schema slice and routes every edit into the debounce.
  function buildForm() {
    window.createSectionForm(form, {
      kind: sections[current].kind,
      draft: draft,
      fields: FIELDS,
      labels: LABELS,
      onChange: scheduleAutosave
    });
  }

  /* ---- section switching ---- */

  function buildMuutOsiot() {
    muutOsiotList.textContent = "";
    sections.forEach(function (section, index) {
      if (index === current) return;
      var row = document.createElement("li");
      var name = document.createElement("span");
      name.className = "muut-osiot-name";
      name.textContent = NAMES[section.kind];
      var badge = document.createElement("span");
      badge.className = "muut-osiot-badge";
      badge.textContent = section.badge;
      var chevron = document.createElement("span");
      chevron.className = "muut-osiot-chevron";
      chevron.textContent = "›";
      row.appendChild(name);
      row.appendChild(badge);
      row.appendChild(chevron);
      row.addEventListener("click", function () {
        openSection(index);
      });
      muutOsiotList.appendChild(row);
    });
  }

  function openSection(index) {
    autosave.flush();
    current = index;
    var section = sections[index];
    draft = deepCopy(section.payload);
    lastSaved = deepCopy(section.payload);
    sectionName.textContent = NAMES[section.kind];
    sectionPosition.textContent =
      "Osio " + (index + 1) + " / " + sections.length;
    muotokuvaRow.hidden = section.kind !== "hero";
    clearErrors();
    buildForm();
    buildMuutOsiot();
    highlightPreview();
  }

  /* ---- chrome wiring ---- */

  document.querySelectorAll(".viewport-button").forEach(function (button) {
    button.addEventListener("click", function () {
      document
        .querySelectorAll(".viewport-button")
        .forEach(function (other) {
          other.classList.remove("active");
        });
      button.classList.add("active");
      previewFrame.classList.toggle(
        "mobile",
        button.dataset.viewport === "mobile"
      );
      previewFrame.classList.toggle(
        "desktop",
        button.dataset.viewport === "desktop"
      );
    });
  });

  document
    .querySelector(".tallenna-button")
    .addEventListener("click", save);

  document
    .querySelector(".peruuta-button")
    .addEventListener("click", function () {
      autosave.cancel();
      draft = deepCopy(lastSaved);
      clearErrors();
      buildForm();
      reloadPreview();
      savedNote.hidden = true;
      peruutaNote.hidden = false;
      if (peruutaTimer) clearTimeout(peruutaTimer);
      peruutaTimer = setTimeout(function () {
        peruutaNote.hidden = true;
      }, 3000);
    });

  document
    .querySelector(".julkaise-button")
    .addEventListener("click", function () {
      // A pending autosave — still debounced, or already in flight —
      // must land before the publish reads the drafts.
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
          sections.forEach(function (section) {
            section.badge =
              section.state === "hidden" ? "Piilotettu" : "Julkaistu";
          });
          buildMuutOsiot();
        });
      });
  }

  openSection(0);
})();
