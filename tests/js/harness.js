/* The whole of the JavaScript suite's machinery (LLM-COP-14).
 *
 * There is no npm here and there is meant to be none: the modules under
 * app/static/ are plain IIFEs that end in `window.X = X`, so a vm sandbox
 * carrying nothing but `window` is enough to capture what they export.
 * loadModule() reads one of those files off disk and runs it in a fresh
 * context, handing back that context's `window`.
 *
 * The sandbox deliberately has NO `document`. These suites cover the parts
 * that are pure — serialize/sanitize, the undo stack, the autosave debounce
 * — and a subject that quietly starts reaching for the DOM should turn red
 * with a ReferenceError rather than pass by accident. `Node` is present only
 * as the two nodeType constants serialize() compares against.
 *
 * A contrast case proves a test would actually catch its defect: it loads
 * the same source with one string swapped and asserts the contract fails.
 * The swap happens on an in-memory copy of the source text — the file on
 * disk is opened read-only and is never written.
 */
"use strict";

const fs = require("fs");
const vm = require("vm");
const path = require("path");

// Derived, never absolute: tests/ and app/static/ are siblings under the
// repo root, so a hardcoded path would pass in one checkout and fail on
// merge and in CI.
const SRC = path.join(__dirname, "..", "..", "app", "static");

/* Deliberately not an AssertionError: a contrast case wraps its contract in
 * assert.throws(..., assert.AssertionError), and a stale anchor must fall
 * straight through that rather than be mistaken for the defect firing. */
class AnchorNotFound extends Error {
  constructor(name, from) {
    super(
      `anchor not found in ${name}: ${JSON.stringify(from)} — the source ` +
        `moved; re-read it and re-anchor the mutation`
    );
    this.name = "AnchorNotFound";
  }
}

/* Load app/static/<name> into a fresh sandbox and return its `window`.
 *
 * mutation, when given, is {from, to}: the exact source text to swap and
 * what to swap it for, applied to the in-memory string only. */
function loadModule(name, mutation) {
  let code = fs.readFileSync(path.join(SRC, name), "utf8");
  if (mutation) {
    // Exactly one occurrence. String.replace rewrites only the first, so a
    // non-unique anchor would mutate partially and could still look like a
    // passing contrast; a plain !includes() check would miss that entirely.
    const hits = code.split(mutation.from).length - 1;
    if (hits !== 1) throw new AnchorNotFound(name, mutation.from);
    // Replacer FUNCTION, so "$&", "$`" and "$'" inside `to` stay literal.
    code = code.replace(mutation.from, () => mutation.to);
  }
  const window = {};
  const sandbox = {
    window,
    setTimeout,
    clearTimeout,
    console,
    Node: { TEXT_NODE: 3, ELEMENT_NODE: 1 }
  };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: name });
  return sandbox.window;
}

/* The smallest node literals serialize() actually reads: nodeType,
 * nodeValue, childNodes, tagName, getAttribute. addEventListener is here
 * because createRichEditor binds keydown/input/paste to the editable it
 * adopts; it is never dispatched. */
function text(value) {
  return { nodeType: 3, nodeValue: value, childNodes: [] };
}

function el(tag, attrs, kids) {
  attrs = attrs || {};
  kids = kids || [];
  return {
    nodeType: 1,
    tagName: tag.toUpperCase(),
    childNodes: kids,
    getAttribute: (n) => (n in attrs ? attrs[n] : null),
    addEventListener: () => {}
  };
}

module.exports = { loadModule, el, text, AnchorNotFound, SRC };
