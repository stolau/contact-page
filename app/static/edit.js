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
  // The picture rows are NOT queried here: there are two of them now
  // (LLM-COP-30) and every control inside one is reached through the row it
  // belongs to. See createImageRow below.
  var kuvaRows = document.querySelectorAll(".kuva-row");
  var ilmoitusRow = document.querySelector(".ilmoitus-row");
  var ilmoitusToggle = document.querySelector(".ilmoitus-toggle");
  var muotoRow = document.querySelector(".muoto-row");
  var muotoOptions = document.querySelectorAll(".muoto-option");
  var muutOsiotList = document.querySelector(".muut-osiot-list");
  var savedNote = document.querySelector(".draft-saved-note");
  var savedTime = document.querySelector(".saved-time");
  var peruutaNote = document.querySelector(".peruuta-note");
  var previewFrame = document.querySelector(".preview-frame");
  var preview = document.querySelector(".preview");
  var panelTabs = document.querySelectorAll(".panel-tab[data-tab]");
  var panelBodies = document.querySelectorAll(".panel-body[data-panel]");
  var tyyliOptions = document.querySelectorAll(".tyyli-option");
  var variInputs = document.querySelectorAll(".vari-input");
  var variResets = document.querySelectorAll(".vari-reset");

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

  // Does this kind declare this field? (LLM-COP-28.) The one predicate that
  // decides which of the panel's own rows — the three picture rows and the
  // shape row — are shown for the open section. It replaced the last
  // field-name literal in this file, `section.kind !== "hero"`, which was
  // right only while hero was the only kind with a picture.
  //
  // KEYED ON THE SCHEMA, NOT ON `draft`, and that is deliberate: a payload is
  // data, and a pre-migration or hand-written row could be short a key, so
  // asking the payload would hide the row precisely on the store that most
  // needs it. FIELDS is the declaration itself (app/fields.py, bootstrapped
  // by app/edit.py), so it answers what the kind HAS rather than what one row
  // happens to carry.
  //
  // hasOwnProperty through Object.prototype: FIELDS comes from JSON.parse, so
  // a kind named "constructor" or a field named "toString" would answer true
  // to a bare `in`.
  function declares(kind, field) {
    return Object.prototype.hasOwnProperty.call(FIELDS[kind] || {}, field);
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
    // The KIND, not a boolean: each picture row is shown for the kinds that
    // declare its own field, so the hero's two rows and the section row can
    // no longer share one answer (LLM-COP-28).
    refreshImageRows(section.kind);
    refreshNoticeRow(section.kind !== "yhteydenotto");
    refreshShapeRow(section.kind);
    // The style mark's SOURCE changes with the open section — `draft` when
    // the hero is open, hero.payload otherwise — so switching sections owes
    // it a refresh even though the stored value did not move. The two colour
    // swatches read the same two sources and owe the same refresh.
    refreshStyleOptions();
    refreshColorInputs();
    clearErrors();
    buildForm();
    buildMuutOsiot();
    highlightPreview();
  }

  /* ---- the picture rows (LLM-COP-21; two since LLM-COP-30, three since
         LLM-COP-28's generic section row) ---- */

  // hero.portrait, hero.background and every editorial band's own `image`
  // are in no form: all are plain fields
  // deliberately absent from FIELD_LABELS, so the schema-driven builder
  // never draws them. Each row's two buttons are its field's only writers —
  // Vaihda sets a reference, Poista clears it — and both then go through the
  // ordinary save().
  //
  // Errors do NOT go through showErrors: that maps every key through
  // labelFor, and LABELS.hero.portrait / .background and every kind's
  // .image are undefined by
  // design, so the owner would read a raw "portrait: ..." key in an
  // otherwise Finnish panel. The server's message is already Finnish and
  // already actionable, so it goes verbatim into the row's own error
  // element.
  //
  // ONE factory per row, and every control is queried WITHIN the row: the
  // three control classes appear three times in the document now, so a
  // document-wide query would silently take whichever came first in the DOM.
  // Which field a row writes is the row's own data-field, so the order the
  // rows are written in edit.html is not load-bearing.
  //
  // Which SECTION a row writes is never asked, and does not need to be: a
  // row is only ever visible while a section whose kind declares its field is
  // open (see declares above), so `draft` is always that field's payload.
  // The hero's two rows and the section row therefore share one factory
  // unchanged — the generic row cost it one line, the `field` on its return.

  function createImageRow(row) {
    var field = row.dataset.field;
    var vaihdaButton = row.querySelector(".vaihda-button");
    var vaihdaInput = row.querySelector(".vaihda-input");
    var poistaButton = row.querySelector(".poista-button");
    var error = row.querySelector(".kuva-error");

    function refresh() {
      var gone = !(draft && draft[field]);
      // Poista only exists for a section that actually has a picture. The
      // attribute alone is enough: `.button[hidden] { display: none }` in
      // edit.css gives it back its meaning against .button's own
      // display: inline-block, the way sections.css and wizard.css do.
      poistaButton.hidden = gone;
      error.hidden = true;
      error.textContent = "";
    }

    function showError(message) {
      error.textContent = message;
      error.hidden = false;
    }

    function setRef(ref) {
      draft[field] = ref;
      return save().then(refresh);
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
      refresh();
      var body = new FormData();
      body.append("kuva", file);
      // Accept must be explicit. auth.require_admin compares the quality of
      // application/json against text/html, and a bare fetch sends */*, so
      // an expired session would answer a 302 to /yllapito rather than a 401
      // — fetch follows it and response.json() then throws on an HTML body.
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
            showError(data.error || "Kuvan lähetys epäonnistui.");
            return;
          }
          return setRef(data.ref);
        });
      });
    });

    poistaButton.addEventListener("click", function () {
      // This takes the picture off the page. The file follows on the save,
      // through the count: it goes only when no section names the digest any
      // more and the retention floor has passed (LLM-COP-27).
      setRef("");
    });

    // `field` rides out with the element (LLM-COP-28): visibility is now
    // per-row — does the open kind declare THIS row's field? — so the caller
    // needs the name the factory already had in hand.
    return { element: row, field: field, refresh: refresh };
  }

  var imageRows = Array.prototype.map.call(kuvaRows, createImageRow);

  // Called with the open section's KIND, or with nothing when only the
  // Poista buttons need re-reading (Peruuta below).
  function refreshImageRows(kind) {
    imageRows.forEach(function (imageRow) {
      if (kind !== undefined) {
        imageRow.element.hidden = !declares(kind, imageRow.field);
      }
      imageRow.refresh();
    });
  }

  /* ---- the availability notice's toggle (USR-COP-4) ---- */

  // yhteydenotto.notice_on is a flag, not content: "on" means shown and
  // anything else means not (app/notice.py). It is deliberately absent from
  // FIELD_LABELS, so the schema-driven builder never draws it and this row
  // is its only editor — the same arrangement hero.portrait and
  // hero.background have with the two picture rows above.
  //
  // Unlike those, and unlike the Ulkoasu tab's three hero controls, this
  // field belongs to the section the row is VISIBLE FOR. The row is hidden
  // unless yhteydenotto is open, so `draft` is always this field's payload
  // and none of setHeroValue's "which section is open" branching is needed:
  // write into draft, refresh, save, exactly as the generated form does.
  //
  // notice_text is never touched here. That is the whole point of two
  // fields: switching the notice off must not cost the owner the sentence
  // they wrote.

  function refreshNoticeRow(hidden) {
    if (!ilmoitusRow || !ilmoitusToggle) return;
    if (hidden !== undefined) ilmoitusRow.hidden = hidden;
    // What the box shows is what is STORED, the same rule the style mark
    // and the colour swatches follow — never what was last clicked.
    ilmoitusToggle.checked = draft && draft.notice_on === "on";
  }

  if (ilmoitusToggle) {
    ilmoitusToggle.addEventListener("change", function () {
      // "" rather than "off": every value app/notice.py does not recognise
      // means not shown, and "" is what the seed and the migration store,
      // so a toggled-off row is byte-identical to a never-touched one.
      draft.notice_on = ilmoitusToggle.checked ? "on" : "";
      // Saved at once rather than through the debounce: a click is a whole
      // decision, not a keystroke in the middle of one.
      save();
    });
  }

  /* ---- the section picture's shape (LLM-COP-28) ---- */

  // image_shape is a constrained vocabulary, not content: "square" is the
  // square and everything else — "", an unknown value, a value some later
  // build stopped writing — is the circle (app/shapes.py). It is deliberately
  // absent from FIELD_LABELS, so the schema-driven builder never draws it and
  // this row is its only editor, the arrangement the picture rows and the
  // notice toggle both have.
  //
  // Like the notice toggle and unlike the Ulkoasu tab's three hero controls,
  // the field belongs to the section the row is VISIBLE FOR: the row is
  // hidden unless a kind that declares image_shape is open, so `draft` is
  // always this field's payload and none of setHeroValue's "which section is
  // open" branching is needed.
  //
  // ITS OWN TOGGLE, not refreshImageRows': the row is not a .kuva-row — no
  // uploader, no error element — and that class is both the picture-row loop
  // and a browser-suite scoping handle. This is refreshNoticeRow's shape with
  // the schema predicate the picture rows now use.

  // A three-line mirror of app/shapes.py's resolve_shape. Two copies of one
  // vocabulary is the price of marking the row without a round trip; the
  // fallback is the same in both, and it is the ONE place this file may
  // decide what a stored value means.
  function resolveShape(value) {
    return value === "square" ? "square" : "circle";
  }

  function refreshShapeRow(kind) {
    if (!muotoRow) return;
    if (kind !== undefined) muotoRow.hidden = !declares(kind, "image_shape");
    // The mark shows resolve_shape's ANSWER, not the raw stored value, and
    // that is a deliberate divergence from the Ulkoasu tab's style list,
    // whose mark says what is STORED so that "" (unchosen) can be told apart
    // from "v1". The shape has no third state: "" IS the circle and the page
    // draws one, so marking neither option would tell the owner their round
    // picture is neither round nor square.
    var active = resolveShape(draft && draft.image_shape);
    muotoOptions.forEach(function (option) {
      option.classList.toggle("active", option.dataset.shape === active);
    });
  }

  function setShape(value) {
    draft.image_shape = value;
    refreshShapeRow();
    // Saved at once rather than through the debounce, the notice toggle's
    // reason: a click is a whole decision, not a keystroke in the middle of
    // one. The mark is set optimistically first, as every other field in the
    // panel behaves on a failed save — the value stays, showErrors explains,
    // Peruuta reverts it.
    return save();
  }

  muotoOptions.forEach(function (option) {
    option.addEventListener("click", function () {
      setShape(option.dataset.shape);
    });
  });

  /* ---- ulkoasu: the site-wide style (LLM-COP-22) and the two colours
         (USR-COP-2) ---- */

  // All three are fields on the HERO payload, so they follow draft and
  // publish like any other content — but their controls sit outside the
  // section form and are reachable while another section is open. Hence two
  // branches everywhere below: the hero open (the value lives in `draft`)
  // and the hero not open (it lives in that section's `payload`).

  function heroSection() {
    for (var index = 0; index < sections.length; index++) {
      if (sections[index].kind === "hero") return sections[index];
    }
    return undefined;
  }

  function heroValueNow(key) {
    var hero = heroSection();
    if (!hero) return "";
    return (sections[current] === hero ? draft : hero.payload)[key] || "";
  }

  function refreshStyleOptions() {
    var active = heroValueNow("style");
    tyyliOptions.forEach(function (option) {
      option.classList.toggle("active", option.dataset.style === active);
    });
  }

  // The swatch shows the STORED colour when there is one and the skin's own
  // colour otherwise, which is the same rule the style mark follows — what
  // the panel displays is what is stored, never what was last clicked. A
  // colour input has no empty state, so "nothing chosen" is drawn as the
  // default the server rendered into data-default.
  function refreshColorInputs() {
    variInputs.forEach(function (input) {
      input.value =
        heroValueNow("color_" + input.dataset.color) || input.dataset.default;
    });
  }

  function setHeroValue(key, value, refresh) {
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
        draft[key] = value;
        refresh();
        return save().then(refresh, refresh);
      }
      // Hero not open: nothing is marked on the click. The mark comes from
      // hero.payload, which advances only on a successful PUT, so an
      // aborted fetch or a 400 leaves it exactly where it was.
      var payload = deepCopy(hero.payload);
      payload[key] = value;
      return putDraft(hero, payload).then(refresh, refresh);
    });
  }

  // ONE LINE, and it stays one line. The whole shipped style write path —
  // including the aborted-request case — is fenced by
  // tests/browser/test_browser_panel.py, and that fence is only worth
  // anything while setStyle really is setHeroValue with the key bound.
  function setStyle(value) {
    return setHeroValue("style", value, refreshStyleOptions);
  }

  tyyliOptions.forEach(function (option) {
    option.addEventListener("click", function () {
      setStyle(option.dataset.style);
    });
  });

  variInputs.forEach(function (input) {
    // `change`, NOT `input`, and this is not a preference. <input
    // type="color"> fires `input` CONTINUOUSLY while the picker is dragged —
    // dozens of events for one choice — and every one of them would flow
    // through setHeroValue into a draft write, against the queued and
    // in-flight save machinery whose stale-copy window the comment above
    // describes as narrowed but still open. `change` fires once, when the
    // owner has settled on a colour.
    input.addEventListener("change", function () {
      setHeroValue(
        "color_" + input.dataset.color,
        input.value,
        refreshColorInputs
      );
    });
  });

  variResets.forEach(function (button) {
    // Palauta stores "", which is "skin default" — not the default colour
    // itself. Storing the literal would freeze the site's colours at
    // whatever the current skin's happen to be, so switching skin afterwards
    // would carry the old skin's palette across (app/palette.py).
    button.addEventListener("click", function () {
      setHeroValue("color_" + button.dataset.color, "", refreshColorInputs);
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
      // Peruuta is the third writer of each picture field, after Vaihda and
      // Poista, so it owes them the same refresh. Without it: Poista, then a
      // failed save on some other field, then Peruuta — the picture is
      // back on the page but its Poista button is not, and the only way
      // back is to leave the section and return. No visibility argument:
      // Peruuta cannot change which section is open.
      refreshImageRows();
      // And the same debt for the notice box, the fourth writer of `draft`:
      // an optimistic tick left by a failed save has to go back with the
      // rest of the draft, or the panel claims a notice the store says is
      // off. Again no visibility argument, for the same reason.
      refreshNoticeRow();
      // And the same debt for the shape row, the fifth writer of `draft`:
      // setShape marks optimistically, so a mark left by a failed save has to
      // go back with the rest of the draft. Again no visibility argument, for
      // the same reason.
      refreshShapeRow();
      // Same debt for the style: Peruuta is a writer of draft.style too,
      // through the hero-open branch of setStyle, so an optimistic mark left
      // by a failed style write has to go back with the rest of the draft.
      // And for the two colours, which take the same hero-open branch.
      refreshStyleOptions();
      refreshColorInputs();
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
