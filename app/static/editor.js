/* The one rich-text editor (LLM-COP-4, shared with direct edit LLM-COP-6).
 *
 * createRichEditor(mount, options) attaches a toolbar (bold/italic, also
 * Ctrl+B / Ctrl+I) and a contenteditable area to the mount element and
 * returns { getHTML, setHTML, focus, exec, undo, editable }. getHTML
 * serializes the DOM back to the sanitizer's allowlist — only strong,
 * em, br and a[href] ever come out (b normalizes to strong, i to em;
 * block breaks become br; an unsafe href drops the link and keeps its
 * text, mirroring app/sanitize.py).
 *
 * Two optional keys let direct edit reuse this instead of forking it,
 * and neither changes the path taken when it is not passed:
 *   options.editable      adopt this existing element as the editable —
 *                         do not create one, do not append it
 *   options.toolbar=false build no toolbar; the caller drives commands
 *                         through exec()
 *
 * createUndoStack(read, write) is the one snapshot undo implementation,
 * exported so plain fields (which have no editor) share it.
 *
 * This module knows nothing about panels, sections, drafts or fetch —
 * options.onInput is its only way to speak.
 */
(function () {
  "use strict";

  var UNDO_LIMIT = 50;
  var UNDO_COALESCE = 600; // ms of quiet that ends one typing burst

  var SAFE_SCHEMES = ["http", "https", "mailto", "tel"];

  // Mirrors _DROP_WITH_CONTENT in app/sanitize.py: these go with their
  // subtree, not with their text kept. Keeping the text would hand the
  // server script or style source as ordinary characters, which it can
  // no longer tell apart — so it would store the junk as page copy.
  var DROP_WITH_CONTENT = ["script", "style"];

  function escapeText(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttribute(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  /* The client twin of app/sanitize.py's _safe_href: same rules, same
   * normalization. The server stays authoritative — it sanitizes every
   * draft write and again on render — this only keeps what the owner
   * sees identical to what gets stored. */
  function safeHref(value) {
    if (typeof value !== "string") return null;
    var text = value.replace(/[\u0000-\u001f\u007f]/g, "").trim();
    if (!text) return null;
    if (text.charAt(0) === "#") return text;
    var colon = text.indexOf(":");
    if (colon === -1) return null;
    var scheme = text.slice(0, colon);
    // ASCII scheme grammar, so no Unicode case fold smuggles a name in.
    if (!/^[A-Za-z][A-Za-z0-9+.-]*$/.test(scheme)) return null;
    if (SAFE_SCHEMES.indexOf(scheme.toLowerCase()) === -1) return null;
    return text;
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
        if (DROP_WITH_CONTENT.indexOf(tag) !== -1) {
          // Dropped with its subtree — no recursion, no text.
        } else if (tag === "br") {
          out += "<br>";
        } else if (tag === "b" || tag === "strong") {
          out += "<strong>" + serialize(child) + "</strong>";
        } else if (tag === "i" || tag === "em") {
          out += "<em>" + serialize(child) + "</em>";
        } else if (tag === "a") {
          // getAttribute, not .href: the raw value is what the server
          // will judge, and .href would resolve it against the page.
          var href = safeHref(child.getAttribute("href"));
          if (href === null) {
            out += serialize(child);
          } else {
            out +=
              '<a href="' +
              escapeAttribute(href) +
              '">' +
              serialize(child) +
              "</a>";
          }
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

  function placeCaretAtEnd(element) {
    var range = document.createRange();
    range.selectNodeContents(element);
    range.collapse(false);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }

  /* One snapshot stack over any read/write pair — the rich editor's
   * value, or a plain field's text. A burst of typing coalesces into a
   * single entry (the value as it stood before the burst began), so
   * Kumoa undoes a word rather than a keystroke. */
  function createUndoStack(read, write) {
    var stack = [];
    var previous = read();
    var coalescing = null;

    function settle() {
      coalescing = null;
      previous = read();
    }

    return {
      record: function () {
        if (coalescing) {
          clearTimeout(coalescing);
        } else {
          stack.push(previous);
          if (stack.length > UNDO_LIMIT) stack.shift();
        }
        coalescing = setTimeout(settle, UNDO_COALESCE);
      },
      undo: function () {
        if (coalescing) {
          clearTimeout(coalescing);
          coalescing = null;
        }
        if (!stack.length) return false;
        previous = stack.pop();
        write(previous);
        return true;
      },
      reset: function () {
        stack.length = 0;
        if (coalescing) {
          clearTimeout(coalescing);
          coalescing = null;
        }
        previous = read();
      }
    };
  }

  function createRichEditor(mount, options) {
    options = options || {};

    // Adopt mode: the element already exists in the page (direct edit
    // binds one of page.html's own elements) — take it as it is.
    var adopted = !!options.editable;
    var editable = options.editable || document.createElement("div");
    if (!adopted) editable.className = "rich-editor";
    editable.contentEditable = "true";

    var toolbar = null;

    function command(name, value) {
      editable.focus();
      document.execCommand(name, false, value === undefined ? null : value);
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

    if (options.toolbar !== false) {
      toolbar = document.createElement("div");
      toolbar.className = "rich-toolbar";
      addButton("B", "Lihavoi (Ctrl+B)", "bold");
      addButton("I", "Kursivoi (Ctrl+I)", "italic");
    }

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

    var undoStack = createUndoStack(
      function () {
        return serialize(editable);
      },
      function (html) {
        editable.innerHTML = html;
        placeCaretAtEnd(editable);
      }
    );

    editable.addEventListener("input", function () {
      undoStack.record();
      notify();
    });

    /* Paste is where foreign HTML arrives. Parse it inert (DOMParser
     * never runs scripts or fetches resources, unlike innerHTML on a
     * detached node), run it through the same serialize() that governs
     * getHTML(), and insert only that — so what the owner sees is
     * already what the server would keep. */
    editable.addEventListener("paste", function (event) {
      var data = event.clipboardData;
      if (!data) return;
      event.preventDefault();
      var pastedHTML = data.getData("text/html");
      var fragment;
      if (pastedHTML) {
        var parsed = new DOMParser().parseFromString(pastedHTML, "text/html");
        fragment = serialize(parsed.body);
      } else {
        fragment = escapeText(data.getData("text/plain")).replace(
          /\r\n|\r|\n/g,
          "<br>"
        );
      }
      document.execCommand("insertHTML", false, fragment);
      undoStack.record();
      notify();
    });

    if (toolbar) mount.appendChild(toolbar);
    if (!adopted) mount.appendChild(editable);

    return {
      getHTML: function () {
        return serialize(editable);
      },
      setHTML: function (html) {
        // Values arrive server-sanitized (strong/em/br/a[href] only).
        editable.innerHTML = html;
        undoStack.reset();
      },
      focus: function () {
        editable.focus();
      },
      exec: function (name, value) {
        command(name, value);
      },
      undo: function () {
        if (undoStack.undo()) notify();
      },
      editable: editable
    };
  }

  window.createRichEditor = createRichEditor;
  window.createUndoStack = createUndoStack;
})();
