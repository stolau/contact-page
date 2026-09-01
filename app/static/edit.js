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
  var vaihdaButton = document.querySelector(".vaihda-button");
  var vaihdaInput = document.querySelector(".vaihda-input");
  var poistaButton = document.querySelector(".poista-button");
  var muotokuvaError = document.querySelector(".muotokuva-error");
  var muutOsiotList = document.querySelector(".muut-osiot-list");
  var savedNote = document.querySelector(".draft-saved-note");
  var savedTime = document.querySelector(".saved-time");
  var peruutaNote = document.querySelector(".peruuta-note");
  var previewFrame = document.querySelector(".preview-frame");
  var preview = document.querySelector(".preview");
  var panelTabs = document.querySelectorAll(".panel-tab[data-tab]");
  var panelBodies = document.querySelectorAll(".panel-body[data-panel]");
  var tyyliOptions = document.querySelectorAll(".tyyli-option");

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

  // The whole write path, for ANY section — not only the open one. The
  // Ulkoasu tab writes the hero's drafted style while some other section is
  // open (LLM-COP-22), which is why this takes its section and payload as
  // arguments rather than reading `current` and `draft`.
  //
  // saveInFlight and its settle pair live HERE, not in save(): a background
  // style write must be visible to Julkaise, whose
  // `autosave.flush() || saveInFlight` (below) is what makes it wait for a
  // write it did not start. Leaving them in save() would make style writes
  // invisible to publish and introduce a race.
  function putDraft(section, payload) {
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

  function save() {
    // A save now settles whatever the debounce had queued.
    autosave.cancel();
    return putDraft(sections[current], deepCopy(draft));
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
    refreshMuotokuva();
    // The style mark's SOURCE changes with the open section — `draft` when
    // the hero is open, hero.payload otherwise — so switching sections owes
    // it a refresh even though the stored value did not move.
    refreshStyleOptions();
    clearErrors();
    buildForm();
    buildMuutOsiot();
    highlightPreview();
  }

  /* ---- muotokuva (LLM-COP-21) ---- */

  // hero.portrait is in no form: it is a plain field deliberately absent
  // from FIELD_LABELS, so the schema-driven builder never draws it. These
  // two buttons are its only writers — Vaihda sets a reference, Poista
  // clears it — and both then go through the ordinary save().
  //
  // Errors do NOT go through showErrors: that maps every key through
  // labelFor, and LABELS.hero.portrait is undefined by design, so the owner
  // would read a raw "portrait: ..." key in an otherwise Finnish panel. The
  // server's message is already Finnish and already actionable, so it goes
  // verbatim into the row's own error element.

  function refreshMuotokuva() {
    var gone = !(draft && draft.portrait);
    // Poista only exists for a section that actually has a picture. The
    // attribute alone is enough: `.button[hidden] { display: none }` in
    // edit.css gives it back its meaning against .button's own
    // display: inline-block, the way sections.css and wizard.css do.
    poistaButton.hidden = gone;
    muotokuvaError.hidden = true;
    muotokuvaError.textContent = "";
  }

  function showMuotokuvaError(message) {
    muotokuvaError.textContent = message;
    muotokuvaError.hidden = false;
  }

  function setPortrait(ref) {
    draft.portrait = ref;
    return save().then(refreshMuotokuva);
  }

  vaihdaButton.addEventListener("click", function () {
    vaihdaInput.click();
  });

  vaihdaInput.addEventListener("change", function () {
    var file = vaihdaInput.files && vaihdaInput.files[0];
    // Clearing the value lets the same file be chosen again after a
    // refusal; without it the second pick fires no change event.
    vaihdaInput.value = "";
    if (!file) return;
    refreshMuotokuva();
    var body = new FormData();
    body.append("kuva", file);
    // Accept must be explicit. auth.require_admin compares the quality of
    // application/json against text/html, and a bare fetch sends */*, so an
    // expired session would answer a 302 to /yllapito rather than a 401 —
    // fetch follows it and response.json() then throws on an HTML body.
    // Content-Type is deliberately NOT set: the browser has to write the
    // multipart boundary itself.
    fetch("/api/kuvat", {
      method: "POST",
      headers: { "Accept": "application/json" },
      body: body
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function (data) {
        if (!response.ok) {
          showMuotokuvaError(data.error || "Kuvan lähetys epäonnistui.");
          return;
        }
        return setPortrait(data.ref);
      });
    });
  });

  poistaButton.addEventListener("click", function () {
    // No delete route: this takes the picture off the page, not off disk.
    setPortrait("");
  });

  /* ---- ulkoasu: the site-wide style (LLM-COP-22) ---- */

  // The style is a field on the HERO payload, so it follows draft and
  // publish like any other content — but its control sits outside the
  // section form and is reachable while another section is open. Hence two
  // branches everywhere below: the hero open (the value lives in `draft`)
  // and the hero not open (it lives in that section's `payload`).

  function heroSection() {
    for (var index = 0; index < sections.length; index++) {
      if (sections[index].kind === "hero") return sections[index];
    }
    return undefined;
  }

  function styleNow() {
    var hero = heroSection();
    if (!hero) return "";
    return (sections[current] === hero ? draft : hero.payload).style || "";
  }

  function refreshStyleOptions() {
    var active = styleNow();
    tyyliOptions.forEach(function (option) {
      option.classList.toggle("active", option.dataset.style === active);
    });
  }

  function setStyle(value) {
    var hero = heroSection();
    if (!hero) return;
    // Wait for the queued save if there is one, otherwise for the in-flight
    // one: the hero's payload is refreshed only on a successful PUT, so
    // writing on top of a stale copy would drop the edits that PUT carries.
    //
    // This NARROWS the window, it does not close it. `||` short-circuits, so
    // when a save is queued AND a hero PUT is already in flight, saveInFlight
    // is never awaited and the stale copy is still possible. saveInFlight
    // holds one promise rather than one per section, which is the actual
    // cause; julkaise below ships the same weakness on the same line. Closing
    // it means per-section write tracking, which changes a shipped path, so
    // it is filed rather than fixed here.
    var pending = autosave.flush() || saveInFlight || Promise.resolve();
    return pending.then(function () {
      if (sections[current] === hero) {
        // Hero open: the value goes into `draft` and the mark is set
        // optimistically, exactly as every other field in the panel behaves
        // on a failed save — the value stays, showErrors explains, Peruuta
        // reverts it.
        draft.style = value;
        refreshStyleOptions();
        return save().then(refreshStyleOptions, refreshStyleOptions);
      }
      // Hero not open: nothing is marked on the click. The mark comes from
      // hero.payload, which advances only on a successful PUT, so an
      // aborted fetch or a 400 leaves it exactly where it was.
      var payload = deepCopy(hero.payload);
      payload.style = value;
      return putDraft(hero, payload).then(
        refreshStyleOptions,
        refreshStyleOptions
      );
    });
  }

  tyyliOptions.forEach(function (option) {
    option.addEventListener("click", function () {
      setStyle(option.dataset.style);
    });
  });

  panelTabs.forEach(function (tab) {
    tab.addEventListener("click", function () {
      panelTabs.forEach(function (other) {
        other.classList.toggle("active", other === tab);
      });
      panelBodies.forEach(function (body) {
        body.hidden = body.dataset.panel !== tab.dataset.tab;
      });
    });
  });

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
      // Peruuta is the third writer of draft.portrait, after Vaihda and
      // Poista, so it owes the same refresh. Without it: Poista, then a
      // failed save on some other field, then Peruuta — the picture is
      // back on the page but its Poista button is not, and the only way
      // back is to leave the section and return.
      refreshMuotokuva();
      // Same debt for the style: Peruuta is a writer of draft.style too,
      // through the hero-open branch of setStyle, so an optimistic mark left
      // by a failed style write has to go back with the rest of the draft.
      refreshStyleOptions();
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
