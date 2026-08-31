/* Direct edit mode controller (LLM-COP-6).
 *
 * The page is the editor: every element page.html marked with
 * data-section/data-field becomes an editing host, plain fields as bare
 * contenteditable with the schema's cap enforced, rich fields through
 * the one shared editor (app/static/editor.js) in adopt mode — it takes
 * the element the template already rendered instead of building one.
 *
 * The dashed affordance is a class on <body>, never an inline style, so
 * nothing can leak into the public page or the draft preview. Saving
 * goes through the side panel's own routes: PUT /api/sections/<id>/draft
 * with the whole payload (that route validates the whole payload) and
 * POST /api/publish. No second write path, no second sanitizer.
 *
 * data-field is bound at boot, not per click: a <button> or an <a href>
 * that becomes an editing host only on focus is a different, unmeasured
 * path, and these four labels (Ota yhteyttä, Lue palveluista, the
 * palvelut link and Lähetä) are real fields.
 */
(function () {
  "use strict";

  var bootstrap = JSON.parse(
    document.getElementById("direct-bootstrap").textContent
  );
  var sections = bootstrap.sections;
  var FIELDS = bootstrap.fields;
  var LABELS = bootstrap.field_labels;

  var PLAIN_ONLY_TITLE = "Vain rich-tekstikentissä";

  function deepCopy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function query(selector) {
    return document.querySelector(selector);
  }

  /* ---- chrome ---- */

  var tag = query(".direct-field-tag");
  var counter = query(".direct-counter");
  var counterValue = query(".direct-counter-value");
  var toolbar = query(".direct-toolbar");
  var changes = query(".direct-changes");
  var changesCount = query(".direct-changes-count");
  var autosave = query(".direct-autosave");
  var savedTime = query(".direct-saved-time");
  var errorNote = query(".direct-errors");
  var portraitPill = query(".direct-portrait-pill");

  document.body.classList.add("direct-edit");

  // The section names ship hidden (page.html must not be restructured);
  // each one moves into the band it names.
  document
    .querySelectorAll(".direct-section-names [data-kind]")
    .forEach(function (name) {
      var band = document.querySelector(
        'section[data-kind="' + name.dataset.kind + '"]'
      );
      if (!band) return;
      name.className = "direct-section-name";
      band.insertBefore(name, band.firstChild);
    });

  // The disabled Vaihda kuva pill sits under the portrait circle, as a
  // sibling — the circle itself is a centred flex column of its own.
  var portrait = query(".portrait");
  if (portrait) {
    portrait.parentNode.insertBefore(portraitPill, portrait.nextSibling);
  }

  /* ---- state ---- */

  var working = {}; // section id -> the payload as edited
  var lastSaved = {}; // section id -> the payload as the server has it
  var kinds = {};

  sections.forEach(function (section) {
    working[section.id] = deepCopy(section.payload);
    lastSaved[section.id] = deepCopy(section.payload);
    kinds[section.id] = section.kind;
  });

  var fields = [];
  var active = null;

  function isDirty() {
    return sections.some(function (section) {
      return (
        JSON.stringify(working[section.id]) !==
        JSON.stringify(lastSaved[section.id])
      );
    });
  }

  function changedFieldCount() {
    var count = 0;
    fields.forEach(function (field) {
      if (working[field.sid][field.name] !== lastSaved[field.sid][field.name]) {
        count++;
      }
    });
    return count;
  }

  function updateChanges() {
    var count = changedFieldCount();
    changesCount.textContent = String(count);
    changes.hidden = count === 0;
    autosave.hidden = count === 0;
  }

  /* ---- the floating field chrome ---- */

  function placeChrome(element) {
    var rect = element.getBoundingClientRect();
    var top = rect.top + window.pageYOffset;
    var left = rect.left + window.pageXOffset;
    tag.style.top = top - tag.offsetHeight - 4 + "px";
    tag.style.left = left + "px";
    if (!counter.hidden) {
      counter.style.top = top + rect.height + 4 + "px";
      counter.style.left = left + rect.width - counter.offsetWidth + "px";
    }
    var toolbarTop = top + rect.height + (counter.hidden ? 6 : 28);
    toolbar.style.top = toolbarTop + "px";
    toolbar.style.left = left + "px";
  }

  function commandButtons() {
    return toolbar.querySelectorAll(".direct-command");
  }

  function updateCounter(field) {
    if (!field.descriptor.cap) {
      counter.hidden = true;
      return;
    }
    counter.hidden = false;
    counterValue.textContent =
      field.read().length + " / " + field.descriptor.cap;
  }

  function activate(field) {
    if (active && active !== field) active.element.classList.remove("direct-active");
    active = field;
    field.element.classList.add("direct-active");
    tag.textContent = (LABELS[field.kind][field.name] || field.name).toUpperCase();
    tag.hidden = false;
    updateCounter(field);
    // Rule D: B / I / Linkki are functional on rich fields only, and say
    // so when they are not, rather than quietly doing nothing.
    commandButtons().forEach(function (button) {
      button.disabled = !field.rich;
      button.title = field.rich ? button.dataset.title : PLAIN_ONLY_TITLE;
    });
    toolbar.hidden = false;
    placeChrome(field.element);
  }

  function deactivate(field) {
    if (active !== field) return;
    field.element.classList.remove("direct-active");
    active = null;
    tag.hidden = true;
    counter.hidden = true;
    toolbar.hidden = true;
  }

  function reposition() {
    if (active) placeChrome(active.element);
  }

  window.addEventListener("scroll", reposition, true);
  window.addEventListener("resize", reposition);

  /* ---- binding ---- */

  function placeCaretAtEnd(element) {
    var range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function bindPlain(field) {
    var element = field.element;
    element.contentEditable = "true";

    var undoStack = window.createUndoStack(
      function () {
        return element.textContent;
      },
      function (text) {
        element.textContent = text;
        placeCaretAtEnd(element);
      }
    );

    function commit() {
      var text = element.textContent;
      var cap = field.descriptor.cap;
      if (cap && text.length > cap) {
        // The cap is the schema's (app/fields.py) and the server rejects
        // an over-cap payload outright, so stopping input here is the
        // affordance, not the enforcement.
        text = text.slice(0, cap);
        element.textContent = text;
        placeCaretAtEnd(element);
      }
      working[field.sid][field.name] = text;
      if (active === field) updateCounter(field);
      updateChanges();
    }

    element.addEventListener("input", function () {
      undoStack.record();
      commit();
    });

    // Plain fields are one line: Enter in a contenteditable inserts a
    // div or a br that textContent flattens unpredictably, and one of
    // these lives inside <form class="contact-form">.
    element.addEventListener("keydown", function (event) {
      if (event.key === "Enter") event.preventDefault();
    });

    // Paste is text only, and truncated like typed input.
    element.addEventListener("paste", function (event) {
      var data = event.clipboardData;
      if (!data) return;
      event.preventDefault();
      var text = data.getData("text/plain").replace(/\s*\r?\n\s*/g, " ");
      document.execCommand("insertText", false, text);
      undoStack.record();
      commit();
    });

    field.read = function () {
      return element.textContent;
    };
    field.undo = function () {
      if (undoStack.undo()) commit();
    };
  }

  function bindRich(field) {
    var element = field.element;
    var editor = window.createRichEditor(null, {
      editable: element,
      toolbar: false,
      onInput: function () {
        working[field.sid][field.name] = editor.getHTML();
        if (active === field) updateCounter(field);
        updateChanges();
      }
    });
    field.editor = editor;
    field.read = function () {
      return element.textContent;
    };
    field.undo = function () {
      editor.undo();
    };
  }

  document.querySelectorAll("[data-field]").forEach(function (element) {
    var sid = Number(element.getAttribute("data-section"));
    var name = element.getAttribute("data-field");
    var kind = kinds[sid];
    if (!kind) return;
    var descriptor = (FIELDS[kind] || {})[name];
    if (!descriptor) return;

    var field = {
      element: element,
      sid: sid,
      kind: kind,
      name: name,
      descriptor: descriptor,
      rich: descriptor.type === "rich"
    };

    if (field.rich) {
      bindRich(field);
    } else {
      bindPlain(field);
    }

    var tagName = element.tagName.toLowerCase();
    if (tagName === "a" || tagName === "button") {
      // The element is an editing host now, not a control: say so, or
      // assistive tech announces a button whose content happens to be
      // editable. (Not spec-asserted; cheap and true.)
      element.setAttribute("role", "textbox");
      element.setAttribute("aria-multiline", field.rich ? "true" : "false");
    }
    if (tagName === "a") {
      // Chrome suppresses the in-page jump on a contenteditable anchor,
      // but that is observed behaviour, not a guarantee, and the jump
      // would move the field out from under the caret. Links are also
      // draggable by default, which turns a drag-select into a drag.
      element.draggable = false;
      element.addEventListener("click", function (event) {
        event.preventDefault();
      });
    }

    element.addEventListener("focus", function () {
      activate(field);
    });
    element.addEventListener("blur", function () {
      deactivate(field);
    });

    fields.push(field);
  });

  /* ---- toolbar ---- */

  commandButtons().forEach(function (button) {
    button.dataset.title = button.title;
    button.addEventListener("mousedown", function (event) {
      // mousedown, so the selection inside the field survives the click.
      event.preventDefault();
      var field = active;
      if (!field || !field.rich) return;
      if (button.dataset.command === "link") {
        var url = window.prompt("Linkin osoite", "https://");
        if (!url) return;
        field.editor.exec("createLink", url);
        // Normalize through the editor's own serializer: an href the
        // sanitizer would reject disappears here rather than on save,
        // so what the owner sees is what gets stored.
        field.editor.setHTML(field.editor.getHTML());
        field.editor.focus();
        working[field.sid][field.name] = field.editor.getHTML();
        updateChanges();
      } else {
        field.editor.exec(button.dataset.command);
      }
    });
  });

  query(".direct-undo").addEventListener("mousedown", function (event) {
    event.preventDefault();
    if (active) active.undo();
  });

  /* ---- saving ---- */

  function showSavedTime(savedAt) {
    var when = new Date(savedAt * 1000);
    savedTime.textContent =
      when.getHours() + "." + ("0" + when.getMinutes()).slice(-2);
  }

  function showErrors(kind, errors) {
    errorNote.textContent = Object.keys(errors)
      .map(function (name) {
        return ((LABELS[kind] || {})[name] || name) + ": " + errors[name];
      })
      .join(" · ");
    errorNote.hidden = false;
  }

  function saveDrafts() {
    errorNote.hidden = true;
    var dirty = sections.filter(function (section) {
      return (
        JSON.stringify(working[section.id]) !==
        JSON.stringify(lastSaved[section.id])
      );
    });
    var ok = true;
    return Promise.all(
      dirty.map(function (section) {
        // The whole payload, because the route validates the whole
        // payload — the same contract the side panel saves under.
        return fetch("/api/sections/" + section.id + "/draft", {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
            "Accept": "application/json"
          },
          body: JSON.stringify(working[section.id])
        }).then(function (response) {
          if (response.status === 401) {
            window.location = "/yllapito";
            ok = false;
            return null;
          }
          return response.json().then(function (data) {
            if (!response.ok) {
              showErrors(section.kind, data.errors || {});
              ok = false;
              return null;
            }
            lastSaved[section.id] = deepCopy(working[section.id]);
            return data.saved_at;
          });
        });
      })
    ).then(function (times) {
      var stamps = times.filter(function (value) {
        return typeof value === "number";
      });
      if (stamps.length) showSavedTime(Math.max.apply(null, stamps));
      updateChanges();
      return ok;
    });
  }

  query(".direct-tallenna").addEventListener("click", function () {
    saveDrafts();
  });

  query(".direct-julkaise").addEventListener("click", function () {
    saveDrafts().then(function (ok) {
      if (!ok) return;
      return fetch("/api/publish", {
        method: "POST",
        headers: { "Accept": "application/json" }
      }).then(function (response) {
        if (response.status === 401) {
          window.location = "/yllapito";
          return;
        }
        window.location.reload();
      });
    });
  });

  query(".direct-hylkaa").addEventListener("click", function () {
    if (!window.confirm("Hylätäänkö tallentamattomat muutokset?")) return;
    // The server's drafts are the truth and local edits were never
    // persisted, so a reload is exactly "re-fetch drafts, drop edits".
    unguard();
    window.location.reload();
  });

  query(".direct-poistu").addEventListener("click", function () {
    if (
      isDirty() &&
      !window.confirm("Sinulla on tallentamattomia muutoksia. Poistutaanko?")
    ) {
      return;
    }
    unguard();
    window.location = "/";
  });

  function guard(event) {
    if (!isDirty()) return;
    event.preventDefault();
    event.returnValue = "";
    return "";
  }

  function unguard() {
    window.removeEventListener("beforeunload", guard);
  }

  window.addEventListener("beforeunload", guard);

  updateChanges();
})();
