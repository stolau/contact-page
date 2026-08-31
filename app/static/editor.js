/* The one rich-text editor (LLM-COP-4, shared with direct edit LLM-COP-6).
 *
 * createRichEditor(mount, options) attaches a toolbar (bold/italic, also
 * Ctrl+B / Ctrl+I) and a contenteditable area to the mount element and
 * returns { getHTML, setHTML, focus, editable }. getHTML serializes the
 * DOM back to the sanitizer's allowlist — only strong, em and br ever
 * come out (b normalizes to strong, i to em; block breaks become br).
 *
 * This module knows nothing about panels, sections, drafts or fetch —
 * options.onInput is its only way to speak.
 */
(function () {
  "use strict";

  function escapeText(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function serialize(node) {
    var out = "";
    var children = node.childNodes;
    for (var i = 0; i < children.length; i++) {
      var child = children[i];
      if (child.nodeType === Node.TEXT_NODE) {
        out += escapeText(child.nodeValue);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        var tag = child.tagName.toLowerCase();
        if (tag === "br") {
          out += "<br>";
        } else if (tag === "b" || tag === "strong") {
          out += "<strong>" + serialize(child) + "</strong>";
        } else if (tag === "i" || tag === "em") {
          out += "<em>" + serialize(child) + "</em>";
        } else if (tag === "div" || tag === "p") {
          // Browsers wrap lines in divs/ps inside contenteditable.
          out += (out ? "<br>" : "") + serialize(child);
        } else {
          out += serialize(child);
        }
      }
    }
    return out;
  }

  function createRichEditor(mount, options) {
    options = options || {};

    var toolbar = document.createElement("div");
    toolbar.className = "rich-toolbar";

    var editable = document.createElement("div");
    editable.className = "rich-editor";
    editable.contentEditable = "true";

    function command(name) {
      editable.focus();
      document.execCommand(name, false, null);
      notify();
    }

    function addButton(label, title, name) {
      var button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = title;
      // mousedown, so the text selection in the editable survives.
      button.addEventListener("mousedown", function (event) {
        event.preventDefault();
        command(name);
      });
      toolbar.appendChild(button);
    }

    addButton("B", "Lihavoi (Ctrl+B)", "bold");
    addButton("I", "Kursivoi (Ctrl+I)", "italic");

    editable.addEventListener("keydown", function (event) {
      if (!(event.ctrlKey || event.metaKey)) return;
      var key = event.key.toLowerCase();
      if (key === "b") {
        event.preventDefault();
        command("bold");
      } else if (key === "i") {
        event.preventDefault();
        command("italic");
      }
    });

    function notify() {
      if (options.onInput) options.onInput();
    }

    editable.addEventListener("input", notify);

    mount.appendChild(toolbar);
    mount.appendChild(editable);

    return {
      getHTML: function () {
        return serialize(editable);
      },
      setHTML: function (html) {
        // Values arrive server-sanitized (strong/em/br only).
        editable.innerHTML = html;
      },
      focus: function () {
        editable.focus();
      },
      editable: editable
    };
  }

  window.createRichEditor = createRichEditor;
})();
