/* app/static/editor.js — serialize(), the client twin of app/sanitize.py
 * (LLM-COP-14 covering LLM-COP-4 and LLM-COP-6).
 *
 * serialize() is not exported, so it is reached the way the product reaches
 * it: createRichEditor({}, {editable: root, toolbar: false}).getHTML().
 * Adopt mode with no toolbar never dereferences `mount` and never touches
 * `document` — editor.js:196 short-circuits the createElement, :197/:290
 * are gated on `adopted` and :221/:289 on `toolbar` — so a plain object
 * tree is enough and no DOM library is needed.
 *
 * WHAT THIS DOES NOT PROVE. The node trees below are hand-built literals.
 * They say what serialize() does with a given shape; they say NOTHING about
 * the shape Chrome's contenteditable actually hands it. The div/p branch at
 * editor.js:104-106 exists because "browsers wrap lines in divs/ps" — that
 * assumption is still unverified by any test and can only be settled in a
 * real browser. Nor is any of the event wiring, execCommand, paste handling
 * or caret placement covered; those need a DOM and are deferred.
 */
"use strict";

const test = require("node:test");
const assert = require("node:assert");

const { loadModule, el, text } = require("./harness.js");

/* One editable's worth of nodes through the real getHTML() path. */
function serialized(createRichEditor, children) {
  const root = el("div", {}, children);
  return createRichEditor({}, { editable: root, toolbar: false }).getHTML();
}

/* The contract the contrast case breaks: an href whose scheme is outside
 * the allowlist loses its <a> and keeps only its text, exactly as
 * app/sanitize.py's _safe_href does server-side. */
function unsafeSchemeContract(createRichEditor) {
  assert.strictEqual(
    serialized(createRichEditor, [
      el("a", { href: "javascript:alert(1)" }, [text("click me")])
    ]),
    "click me",
    "an unsafe scheme drops the link and keeps its text"
  );
}

test("b and i normalise to strong and em", () => {
  const { createRichEditor } = loadModule("editor.js");
  assert.strictEqual(
    serialized(createRichEditor, [
      el("b", {}, [text("bold")]),
      el("i", {}, [text("italic")]),
      el("strong", {}, [text("already")]),
      el("em", {}, [text("also")])
    ]),
    "<strong>bold</strong><em>italic</em><strong>already</strong><em>also</em>"
  );
});

test("text is escaped: & and < and > never come out raw", () => {
  const { createRichEditor } = loadModule("editor.js");
  assert.strictEqual(
    serialized(createRichEditor, [text("a < b & c > d")]),
    "a &lt; b &amp; c &gt; d"
  );
});

test("br survives and block wrappers become br", () => {
  const { createRichEditor } = loadModule("editor.js");
  assert.strictEqual(
    serialized(createRichEditor, [text("one"), el("br"), text("two")]),
    "one<br>two",
    "an explicit br is kept"
  );
  assert.strictEqual(
    serialized(createRichEditor, [
      el("div", {}, [text("first")]),
      el("p", {}, [text("second")])
    ]),
    "first<br>second",
    "the first wrapper adds no leading br; each one after it becomes a break"
  );
});

test("script and style are dropped with their content", () => {
  const { createRichEditor } = loadModule("editor.js");
  // Keeping the text would hand the server script source as ordinary page
  // copy, which it can no longer tell apart — see editor.js:33-35.
  assert.strictEqual(
    serialized(createRichEditor, [
      text("before"),
      el("script", {}, [text("alert(1)")]),
      el("style", {}, [text("body{display:none}")]),
      text("after")
    ]),
    "beforeafter"
  );
});

test("an unsafe scheme drops the link and keeps its text", () => {
  const { createRichEditor } = loadModule("editor.js");
  unsafeSchemeContract(createRichEditor);
});

test("a mailto: href survives, with its apostrophe escaped to &#x27;", () => {
  const { createRichEditor } = loadModule("editor.js");
  // &#x27; matches Python's html.escape(quote=True) byte for byte, so the
  // value does not change shape on its first save.
  assert.strictEqual(
    serialized(createRichEditor, [
      el("a", { href: "mailto:o'brien@example.com" }, [text("Sähköposti")])
    ]),
    '<a href="mailto:o&#x27;brien@example.com">Sähköposti</a>'
  );
});

test("an unknown tag unwraps, keeping its text and its allowed children", () => {
  const { createRichEditor } = loadModule("editor.js");
  assert.strictEqual(
    serialized(createRichEditor, [
      el("span", { style: "color:red" }, [
        text("plain "),
        el("b", {}, [text("bold")])
      ])
    ]),
    "plain <strong>bold</strong>"
  );
});

test("CONTRAST: dropping the scheme allowlist check lets javascript: through", () => {
  // loadModule OUTSIDE the assert.throws: a stale anchor must fail this
  // test loudly with AnchorNotFound, not satisfy it.
  const { createRichEditor } = loadModule("editor.js", {
    from: "SAFE_SCHEMES.indexOf(scheme.toLowerCase()) === -1",
    to: "false"
  });
  assert.throws(
    () => unsafeSchemeContract(createRichEditor),
    assert.AssertionError,
    "an allowlist that accepts every scheme must fail the contract"
  );
});
