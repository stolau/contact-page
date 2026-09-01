/* The one schema-driven section form (extracted from edit.js by
 * LLM-COP-7), shared by the edit panel and the first-run wizard.
 *
 * createSectionForm(mount, options) empties the mount and draws one
 * control per field of options.kind, straight from the bootstrapped
 * field schema (app/fields.py) — no per-section form is hand-built by
 * either host, and neither host owns a second copy of these controls.
 *
 * It mutates options.draft in place and calls options.onChange after
 * every change; saving, in-flight state and error rendering are the
 * host's. It knows nothing of sections, routes or fetch.
 *
 *   kind            the section kind being drawn
 *   draft           the working payload, mutated in place
 *   fields          the whole FIELDS map (kind -> name -> descriptor)
 *   labels          the whole FIELD_LABELS map; dotted keys
 *                   ("days.label") name the parts of a list row
 *   helpers         per-field helper text, shown before the counter
 *   only            an explicit ordered field subset; the whole kind in
 *                   declaration order when null
 *   onChange        called after every edit
 *
 * A field with no label is not drawn (hero.portrait is the standing
 * case); its value still rides along in the payload, which both hosts
 * write whole.
 */
(function () {
  "use strict";

  function counterText(length, cap) {
    return length + " / " + cap + " merkkiä";
  }

  function createSectionForm(mount, options) {
    var kind = options.kind;
    var draft = options.draft;
    var fields = options.fields;
    var labels = options.labels;
    var helpers = options.helpers || {};
    var only = options.only || null;
    var onChange = options.onChange;

    function labelFor(name) {
      return (labels[kind] || {})[name];
    }

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

    function fitRows(area) {
      area.rows = area.value.split("\n").length;
    }

    function textControl(value, alwaysArea) {
      // An <input type="text"> drops "\n" on assignment, flattening a
      // value the page renders with white-space: pre-line (the hero fact
      // values). Such values get a textarea instead, auto-grown one row
      // per line — always for list-item parts, where they live, so a
      // line break survives the round trip byte-exact.
      var control;
      if (alwaysArea || value.indexOf("\n") !== -1) {
        control = document.createElement("textarea");
        control.addEventListener("input", function () {
          fitRows(control);
        });
      } else {
        control = document.createElement("input");
        control.type = "text";
      }
      control.value = value;
      if (control.tagName === "TEXTAREA") fitRows(control);
      return control;
    }

    function plainField(name, descriptor) {
      var field = document.createElement("div");
      field.className = "field";
      field.appendChild(fieldHead(labelFor(name)));
      var input = textControl(draft[name], false);
      var helper = helpers[name];
      var counter = null;
      if (descriptor.cap) input.maxLength = descriptor.cap;
      if (descriptor.cap || helper) {
        counter = document.createElement("div");
        counter.className = "field-counter";
      }
      function updateCounter() {
        if (!counter) return;
        // An uncapped field with a helper shows the helper alone —
        // counterText is never called without a cap to count against.
        var count = descriptor.cap
          ? counterText(input.value.length, descriptor.cap)
          : "";
        counter.textContent = helper && count
          ? helper + " · " + count
          : helper || count;
      }
      input.addEventListener("input", function () {
        draft[name] = input.value;
        updateCounter();
        onChange();
      });
      updateCounter();
      field.appendChild(input);
      if (counter) field.appendChild(counter);
      wireMuokataan(field);
      return field;
    }

    function richField(name) {
      var field = document.createElement("div");
      field.className = "field";
      field.appendChild(fieldHead(labelFor(name)));
      var editor = window.createRichEditor(field, {
        onInput: function () {
          draft[name] = editor.getHTML();
          onChange();
        }
      });
      editor.setHTML(draft[name]);
      wireMuokataan(field);
      return field;
    }

    function listRowInputs(name, itemShape, index) {
      var inputs = [];
      if (itemShape === "plain") {
        var input = textControl(draft[name][index], false);
        input.addEventListener("input", function () {
          draft[name][index] = input.value;
          onChange();
        });
        inputs.push(input);
      } else {
        Object.keys(itemShape).forEach(function (key) {
          var part = textControl(draft[name][index][key], true);
          part.placeholder = labelFor(name + "." + key) || key;
          part.addEventListener("input", function () {
            draft[name][index][key] = part.value;
            onChange();
          });
          inputs.push(part);
        });
      }
      return inputs;
    }

    function listField(name, descriptor) {
      var field = document.createElement("div");
      field.className = "field";
      field.appendChild(fieldHead(labelFor(name)));
      var rows = document.createElement("div");
      field.appendChild(rows);

      function buildRows() {
        rows.textContent = "";
        draft[name].forEach(function (item, index) {
          var row = document.createElement("div");
          row.className = "list-row";
          listRowInputs(name, descriptor.item, index).forEach(
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
            onChange();
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
        onChange();
      });

      buildRows();
      field.appendChild(add);
      wireMuokataan(field);
      return field;
    }

    mount.textContent = "";
    (only || Object.keys(fields[kind])).forEach(function (name) {
      // A field with no label is not drawn (hero.portrait — the
      // Muotokuva row stands for it); its value rides in the payload.
      if (!labelFor(name)) return;
      var descriptor = fields[kind][name];
      if (descriptor.type === "plain") {
        mount.appendChild(plainField(name, descriptor));
      } else if (descriptor.type === "rich") {
        mount.appendChild(richField(name));
      } else {
        mount.appendChild(listField(name, descriptor));
      }
    });
  }

  window.createSectionForm = createSectionForm;
})();
