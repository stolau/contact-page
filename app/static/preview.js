/* Preview-only helper (LLM-COP-4): the edit shell postMessages the open
 * section's anchor; the matching section gets a highlight outline. Loaded
 * by page.html only when rendered as the draft preview — style.css is
 * the public page's and stays untouched, so the outline style lives here.
 */
(function () {
  "use strict";

  var style = document.createElement("style");
  style.textContent =
    ".preview-highlight { outline: 2px solid #1f6f5c; outline-offset: 4px; }";
  document.head.appendChild(style);

  window.addEventListener("message", function (event) {
    var data = event.data || {};
    if (typeof data.anchor !== "string") return;
    document
      .querySelectorAll(".preview-highlight")
      .forEach(function (element) {
        element.classList.remove("preview-highlight");
      });
    var section = document.getElementById(data.anchor);
    if (section) section.classList.add("preview-highlight");
  });
})();
