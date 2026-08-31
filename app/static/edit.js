/* Edit-mode controller (LLM-COP-4).
 *
 * The panel form is generated per section kind from the bootstrapped
 * field schema (app/fields.py) — no per-section form is hand-built here.
 * Drafts autosave two seconds after the last change; Tallenna saves at
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

  var AUTOSAVE_DELAY = 2000;

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
  var saveTimer = null;
  var peruutaTimer = null;

  function deepCopy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function labelFor(kind, name) {
    return (LABELS[kind] || {})[name];
  }

  /* ---- saving ---- */

  function scheduleSave() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(save, AUTOSAVE_DELAY);
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
    if (saveTimer) {
      clearTimeout(saveTimer);
      saveTimer = null;
    }
    var section = sections[current];
    var payload = deepCopy(draft);
    return fetch("/api/sections/" + section.id + "/draft", {
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
        clearErrors();
        lastSaved = payload;
        section.payload = deepCopy(payload);
        section.badge = data.badge;
        showSavedNote(data.saved_at);
        reloadPreview();
        buildMuutOsiot();
      });
    });
  }

  function saveIfPending() {
    if (saveTimer) save();
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

  function fieldHead(label) {
    var head = document.createElement("div");
    head.className = "field-head";
    var span = document.createElement("span");
    span.className = "field-label";
    span.textContent = label;
    var tag = document.createElement("span");
    tag.className = "muokataan-tag";
    tag.textContent = "Muokataan";
    tag.hidden = true;
    head.appendChild(span);
    head.appendChild(tag);
    return head;
  }

  function wireMuokataan(field) {
    var tag = field.querySelector(".muokataan-tag");
    field.addEventListener("focusin", function () {
      tag.hidden = false;
    });
    field.addEventListener("focusout", function () {
      tag.hidden = true;
    });
  }

  function plainField(kind, name, descriptor) {
    var field = document.createElement("div");
    field.className = "field";
    field.appendChild(fieldHead(labelFor(kind, name)));
    var input = document.createElement("input");
    input.type = "text";
    input.value = draft[name];
    var counter = null;
    if (descriptor.cap) {
      input.maxLength = descriptor.cap;
      counter = document.createElement("div");
      counter.className = "field-counter";
    }
    function updateCounter() {
      if (counter) {
        counter.textContent =
          input.value.length + " / " + descriptor.cap + " merkkiä";
      }
    }
    input.addEventListener("input", function () {
      draft[name] = input.value;
      updateCounter();
      scheduleSave();
    });
    updateCounter();
    field.appendChild(input);
    if (counter) field.appendChild(counter);
    wireMuokataan(field);
    return field;
  }

  function richField(kind, name) {
    var field = document.createElement("div");
    field.className = "field";
    field.appendChild(fieldHead(labelFor(kind, name)));
    var editor = window.createRichEditor(field, {
      onInput: function () {
        draft[name] = editor.getHTML();
        scheduleSave();
      }
    });
    editor.setHTML(draft[name]);
    wireMuokataan(field);
    return field;
  }

  function listRowInputs(kind, name, itemShape, index) {
    var inputs = [];
    if (itemShape === "plain") {
      var input = document.createElement("input");
      input.type = "text";
      input.value = draft[name][index];
      input.addEventListener("input", function () {
        draft[name][index] = input.value;
        scheduleSave();
      });
      inputs.push(input);
    } else {
      Object.keys(itemShape).forEach(function (key) {
        var part = document.createElement("input");
        part.type = "text";
        part.placeholder = labelFor(kind, name + "." + key) || key;
        part.value = draft[name][index][key];
        part.addEventListener("input", function () {
          draft[name][index][key] = part.value;
          scheduleSave();
        });
        inputs.push(part);
      });
    }
    return inputs;
  }

  function listField(kind, name, descriptor) {
    var field = document.createElement("div");
    field.className = "field";
    field.appendChild(fieldHead(labelFor(kind, name)));
    var rows = document.createElement("div");
    field.appendChild(rows);

    function buildRows() {
      rows.textContent = "";
      draft[name].forEach(function (item, index) {
        var row = document.createElement("div");
        row.className = "list-row";
        listRowInputs(kind, name, descriptor.item, index).forEach(
          function (input) {
            row.appendChild(input);
          }
        );
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "list-remove";
        remove.textContent = "×";
        remove.title = "Poista";
        remove.addEventListener("click", function () {
          draft[name].splice(index, 1);
          buildRows();
          scheduleSave();
        });
        row.appendChild(remove);
        rows.appendChild(row);
      });
    }

    var add = document.createElement("button");
    add.type = "button";
    add.className = "list-add";
    add.textContent = "+ Lisää";
    add.addEventListener("click", function () {
      if (descriptor.item === "plain") {
        draft[name].push("");
      } else {
        var item = {};
        Object.keys(descriptor.item).forEach(function (key) {
          item[key] = "";
        });
        draft[name].push(item);
      }
      buildRows();
      scheduleSave();
    });

    buildRows();
    field.appendChild(add);
    wireMuokataan(field);
    return field;
  }

  function buildForm() {
    var kind = sections[current].kind;
    form.textContent = "";
    Object.keys(FIELDS[kind]).forEach(function (name) {
      // A field with no label is not drawn (hero.portrait — the
      // Muotokuva row stands for it); its value rides in the payload.
      if (!labelFor(kind, name)) return;
      var descriptor = FIELDS[kind][name];
      if (descriptor.type === "plain") {
        form.appendChild(plainField(kind, name, descriptor));
      } else if (descriptor.type === "rich") {
        form.appendChild(richField(kind, name));
      } else {
        form.appendChild(listField(kind, name, descriptor));
      }
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
    saveIfPending();
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
      if (saveTimer) {
        clearTimeout(saveTimer);
        saveTimer = null;
      }
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
      // A pending autosave must land before the publish reads the drafts.
      var pending = saveTimer ? save() : Promise.resolve();
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
