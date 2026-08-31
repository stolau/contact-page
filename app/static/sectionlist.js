/* Section-list controller (LLM-COP-5) — the /muokkaa/osiot screen.
 *
 * The inline row editor is the same form component the /muokkaa panel
 * uses: window.createSectionForm (section-form.js), given the row's
 * .section-form container. This file forks the container, never the form.
 * The debounce is the shared one too (autosave.js), one per open row, so
 * the delay is never restated here.
 *
 * The builder mutates the draft it is handed in place and renders no
 * errors; both are the host's, as they are in edit.js. This file keeps a
 * draft and a lastSaved per open row and draws .form-errors into that
 * row's own form — never document-wide, because six rows can be open.
 *
 * Nothing here renders a summary, a badge or a section's markup. After
 * every mutation the row is re-fetched from GET /muokkaa/osiot/rivi/<id>
 * and its .row-head and .esikatselu-card are swapped in, so the summary
 * strings stay in app/summary.py and the section markup in page.html —
 * one renderer each, and this file knows neither. Three server-derived
 * things fall outside those two subtrees and are carried across rather
 * than computed here: .exp-restore's disabled flag, copied off the fresh
 * fragment; the topbar's count, taken as a finished string off the add
 * response so the Finnish plural rule stays in app/sectionlist.py; and
 * the add control's reason, rendered hidden by the template and only
 * unhidden here. Every one of them is still the server's answer.
 *
 * The row buttons are wired by one delegated click listener on the list
 * rather than per row: swapping .row-head out from under per-row
 * listeners would quietly unwire every refreshed row.
 */
(function () {
  "use strict";

  var bootstrap = JSON.parse(
    document.getElementById("bootstrap").textContent
  );
  var FIELDS = bootstrap.fields;
  var LABELS = bootstrap.field_labels;

  var list = document.querySelector(".sections-list");
  var jarjesta = document.querySelector(".jarjesta-link");
  var julkaiseButton = document.querySelector(".julkaise-button");
  var addButton = document.querySelector(".add-section-button");
  var addMenu = document.querySelector(".add-section-menu");
  var addReason = document.querySelector(".add-section-reason");
  var topbarPage = document.querySelector(".topbar-page");

  // The payload a row's form starts from, by section id. The server
  // sends it with the page and again with a newly added section, so no
  // blank payload is ever built here — that shape is the schema's.
  var payloads = {};
  bootstrap.rows.forEach(function (row) {
    payloads[row.id] = row.payload;
  });

  // Open rows only: id -> { row, draft, lastSaved, autosave, saveInFlight }
  var editors = {};

  var JSON_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json"
  };

  function deepCopy(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function labelFor(kind, name) {
    return (LABELS[kind] || {})[name];
  }

  /* ---- rows ---- */

  function rowOf(element) {
    return element.closest(".section-row");
  }

  function rowById(id) {
    return list.querySelector('.section-row[data-section-id="' + id + '"]');
  }

  function idOf(row) {
    return Number(row.dataset.sectionId);
  }

  function allRows() {
    return Array.prototype.slice.call(
      list.querySelectorAll(".section-row")
    );
  }

  function parseRow(html) {
    // A <li> only parses inside a list element.
    var host = document.createElement("ul");
    host.innerHTML = html;
    return host.querySelector(".section-row");
  }

  // .row-head is swapped whole, so the badge, the summary and the ⋯
  // menu's can_show state all arrive fresh with it. .exp-restore does
  // not: it sits in .expanded-editor, which is deliberately left alone
  // because the open form lives there. So its one server-derived
  // attribute is carried over on its own. It has to be: POST /api/publish
  // is what first fills previous_published, and without this the button
  // an open row shows stays disabled — the one-step restore unreachable
  // in the very flow that needs it — until the page is reloaded.
  function carryRestoreState(row, fresh) {
    var button = row.querySelector(".exp-restore");
    var source = fresh.querySelector(".exp-restore");
    // The server decides can_restore; this reads its answer off the
    // fragment rather than working it out a second time here.
    if (button && source) button.disabled = source.disabled;
  }

  function refreshRow(id) {
    return fetch("/muokkaa/osiot/rivi/" + id, {
      headers: { "Accept": "text/html" }
    }).then(function (response) {
      if (!response.ok) return;
      return response.text().then(function (html) {
        var fresh = parseRow(html);
        var row = rowById(id);
        if (!fresh || !row) return;
        // Only these two subtrees, never the whole <li>: an open form and
        // the caret inside it have to survive a save.
        row
          .querySelector(".row-head")
          .replaceWith(fresh.querySelector(".row-head"));
        row
          .querySelector(".esikatselu-card")
          .replaceWith(fresh.querySelector(".esikatselu-card"));
        carryRestoreState(row, fresh);
      });
    });
  }

  function refreshAllRows() {
    return Promise.all(
      allRows().map(function (row) {
        return refreshRow(idOf(row));
      })
    );
  }

  /* ---- the inline editor ---- */

  function formOf(editor) {
    return editor.row.querySelector(".section-form");
  }

  // Error rendering is the host's; the shared builder draws controls and
  // nothing else. The box is scoped to the row's own form, because every
  // row can be open at once and a document-wide lookup would file one
  // row's refusal under another row's fields.
  function showErrors(editor, errors) {
    var form = formOf(editor);
    var box = form.querySelector(".form-errors");
    if (!box) {
      box = document.createElement("div");
      box.className = "form-errors";
      form.insertBefore(box, form.firstChild);
    }
    var kind = editor.row.dataset.kind;
    box.textContent = Object.keys(errors)
      .map(function (name) {
        return (labelFor(kind, name) || name) + ": " + errors[name];
      })
      .join(" · ");
  }

  function clearErrors(editor) {
    var box = formOf(editor).querySelector(".form-errors");
    if (box) box.remove();
  }

  // Redrawing is how a payload is replaced: the builder empties the mount
  // and binds every control to the draft it is handed, so Peruuta and
  // Palauta swap editor.draft and call this rather than setting values.
  function buildForm(editor) {
    window.createSectionForm(formOf(editor), {
      kind: editor.row.dataset.kind,
      draft: editor.draft,
      fields: FIELDS,
      labels: LABELS,
      onChange: function () {
        editor.autosave.schedule();
      }
    });
  }

  function openEditor(row) {
    var id = idOf(row);
    if (!editors[id]) {
      var editor = {
        row: row,
        // The builder mutates the draft in place, so the bootstrapped
        // payload is copied rather than handed over to be typed into.
        draft: deepCopy(payloads[id]),
        lastSaved: deepCopy(payloads[id]),
        autosave: null,
        saveInFlight: null
      };
      // save is a hoisted declaration, so it is safe to name here.
      editor.autosave = window.createAutosave(
        window.createAutosave.DELAY,
        function () {
          save(id);
        }
      );
      editors[id] = editor;
      buildForm(editor);
    }
    row.querySelector(".expanded-editor").hidden = false;
  }

  function closeEditor(row) {
    var editor = editors[idOf(row)];
    // A debounced change has to land before the row folds away: the fresh
    // .row-head that save fetches carries the summary the collapsed row
    // shows, so closing on a pending write would show a stale one.
    if (editor) editor.autosave.flush();
    row.querySelector(".expanded-editor").hidden = true;
  }

  function showSavedTime(editor, savedAt) {
    var when = new Date(savedAt * 1000);
    editor.row.querySelector(".exp-autosave-time").textContent =
      when.getHours() + "." + ("0" + when.getMinutes()).slice(-2);
  }

  function save(id) {
    var editor = editors[id];
    // A save now settles whatever the debounce had queued.
    editor.autosave.cancel();
    // The existing LLM-COP-4 draft route, so this write goes through the
    // same validator and the same serialization convention as the panel's.
    var payload = deepCopy(editor.draft);
    var request = fetch("/api/sections/" + id + "/draft", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify(payload)
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function (data) {
        if (!response.ok) {
          showErrors(editor, data.errors || {});
          return;
        }
        clearErrors(editor);
        editor.lastSaved = payload;
        showSavedTime(editor, data.saved_at);
        return refreshRow(id);
      });
    });
    editor.saveInFlight = request;
    request.then(
      function () {
        if (editor.saveInFlight === request) editor.saveInFlight = null;
      },
      function () {
        if (editor.saveInFlight === request) editor.saveInFlight = null;
      }
    );
    return request;
  }

  function cancel(id) {
    var editor = editors[id];
    if (!editor) return;
    editor.autosave.cancel();
    editor.draft = deepCopy(editor.lastSaved);
    clearErrors(editor);
    buildForm(editor);
  }

  function restore(id) {
    fetch("/api/sections/" + id + "/restore", {
      method: "POST",
      headers: JSON_HEADERS
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function (data) {
        if (!response.ok) return;
        // The restore landed in the draft only; the row's badge and card
        // come back from the fragment, and the disclaimer beside them
        // already says a Julkaise is still needed.
        var editor = editors[id];
        if (editor) {
          editor.autosave.cancel();
          editor.draft = deepCopy(data.payload);
          editor.lastSaved = deepCopy(data.payload);
          clearErrors(editor);
          buildForm(editor);
        }
        payloads[id] = data.payload;
        return refreshRow(id);
      });
    });
  }

  function setState(id, state) {
    fetch("/api/sections/" + id + "/state", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ state: state })
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      // A refusal is rendered by the row itself — the fresh fragment
      // carries the badge and the menu's disabled reason either way.
      return refreshRow(id);
    });
  }

  function toggleMenu(row) {
    var items = row.querySelector(".row-menu-items");
    var opening = items.hidden;
    list.querySelectorAll(".row-menu-items").forEach(function (other) {
      other.hidden = true;
    });
    items.hidden = !opening;
  }

  /* ---- one delegated listener for every row control ---- */

  list.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-action]");
    if (!trigger || !list.contains(trigger)) return;
    var row = rowOf(trigger);
    if (!row) return;
    var id = idOf(row);
    var action = trigger.dataset.action;
    if (action === "edit") {
      openEditor(row);
    } else if (action === "close") {
      closeEditor(row);
    } else if (action === "menu") {
      toggleMenu(row);
    } else if (action === "hide") {
      setState(id, "hidden");
    } else if (action === "show") {
      setState(id, "published");
    } else if (action === "save") {
      if (editors[id]) save(id);
    } else if (action === "cancel") {
      cancel(id);
    } else if (action === "restore") {
      restore(id);
    }
  });

  /* ---- reordering ---- */

  function applyOrder() {
    // The whole order, read off the DOM — the endpoint refuses anything
    // shorter, because a partial list is a row whose position nobody set.
    var ids = allRows().map(idOf);
    return fetch("/api/sections/order", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ ids: ids })
    }).then(function (response) {
      if (response.status === 401) window.location = "/yllapito";
    });
  }

  function reordering() {
    return list.classList.contains("reordering");
  }

  // draggable is the whole of what makes a real mouse drag possible, and
  // every row's flag is derived from the list's mode here and nowhere
  // else. Re-applied rather than toggled, so a row added while Järjestä
  // osiot is on is draggable at once instead of only after the mode is
  // switched off and on again.
  function applyDraggable() {
    var on = reordering();
    allRows().forEach(function (row) {
      row.draggable = on;
    });
  }

  jarjesta.addEventListener("click", function (event) {
    event.preventDefault();
    list.classList.toggle("reordering");
    applyDraggable();
  });

  list.addEventListener("dragstart", function (event) {
    var row = rowOf(event.target);
    if (!row || !reordering()) return;
    // dataTransfer, not a module variable: the id travels in the drag
    // itself, so nothing depends on setDragImage or effectAllowed.
    event.dataTransfer.setData("text/plain", String(idOf(row)));
  });

  list.addEventListener("dragover", function (event) {
    if (!reordering()) return;
    event.preventDefault(); // without this no drop ever fires
  });

  list.addEventListener("drop", function (event) {
    if (!reordering()) return;
    event.preventDefault();
    var target = rowOf(event.target);
    var dragged = rowById(Number(event.dataTransfer.getData("text/plain")));
    if (!target || !dragged || target === dragged) return;
    var rows = allRows();
    if (rows.indexOf(dragged) < rows.indexOf(target)) {
      target.after(dragged);
    } else {
      target.before(dragged);
    }
    applyOrder();
  });

  list.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    var handle = event.target.closest(".row-drag-handle");
    if (!handle) return;
    var row = rowOf(handle);
    if (event.key === "ArrowUp" && row.previousElementSibling) {
      row.previousElementSibling.before(row);
    } else if (event.key === "ArrowDown" && row.nextElementSibling) {
      row.nextElementSibling.after(row);
    } else {
      return;
    }
    event.preventDefault();
    handle.focus();
    applyOrder();
  });

  /* ---- adding a section ---- */

  // Taking the last offerable kind closes the control: the button goes
  // disabled and the reason beside it explains why. The sentence is not
  // written here — edit_sections.html renders it on every page and hides it
  // while a kind is still on offer, so this only flips the attribute, the
  // way carryRestoreState only copies one.
  //
  // Both functions here dereference addButton and addMenu, which are null
  // on a seeded install where no kind is offerable. Neither is ever called
  // in that case: the only caller is the listener below, wired inside the
  // same guard that establishes both.
  function closeAddIfEmpty() {
    if (addMenu.querySelector(".add-section-item")) return;
    addButton.disabled = true;
    addMenu.hidden = true;
    if (addReason) addReason.hidden = false;
  }

  function addSection(item) {
    addMenu.hidden = true;
    return fetch("/api/sections", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ kind: item.dataset.kind })
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function (data) {
        if (!response.ok) return;
        payloads[data.id] = data.payload;
        list.insertAdjacentHTML("beforeend", data.html);
        applyDraggable();
        // The topbar counts the rows, so appending one made it wrong. The
        // fresh string is the server's — the plural rule stays in
        // app/sectionlist.py beside the one the page was rendered with.
        topbarPage.textContent = data.page_label;
        item.remove();
        closeAddIfEmpty();
      });
    });
  }

  if (addButton && addMenu) {
    addButton.addEventListener("click", function () {
      addMenu.hidden = !addMenu.hidden;
    });

    addMenu.addEventListener("click", function (event) {
      var item = event.target.closest(".add-section-item");
      if (!item) return;
      addSection(item);
    });
  }

  /* ---- Julkaise ---- */

  julkaiseButton.addEventListener("click", function () {
    // Every pending autosave — debounced or in flight — must land before
    // the publish reads the drafts.
    var pending = [];
    Object.keys(editors).forEach(function (id) {
      // flush() hands back save()'s own request when one was debounced,
      // and null when none was — so an in-flight PUT is waited on in its
      // place and a quiet row contributes nothing.
      var editor = editors[id];
      var landing = editor.autosave.flush() || editor.saveInFlight;
      if (landing) pending.push(landing);
    });
    Promise.all(pending).then(publishNow);
  });

  function publishNow() {
    return fetch("/api/publish", {
      method: "POST",
      headers: { "Accept": "application/json" }
    }).then(function (response) {
      if (response.status === 401) {
        window.location = "/yllapito";
        return;
      }
      return response.json().then(function () {
        return refreshAllRows();
      });
    });
  }
})();
