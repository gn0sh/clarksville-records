/* "Show more" for long text (.clamp). Without this script the full text shows. With it, text taller than its
   data-lines is cut to that many lines and a button (aria-expanded) shows or hides the rest. The text stays in the
   page either way. First-party, no network. */
(function () {
  var uid = 0;
  function measure(el) {
    var btn = el.nextElementSibling && el.nextElementSibling.classList.contains("clamp-btn") ? el.nextElementSibling : null;
    if (btn && btn.getAttribute("aria-expanded") === "true") { return; }
    el.classList.add("is-clamped");
    var over = el.scrollHeight > el.clientHeight + 1;
    if (el.clientHeight === 0) { return; }  // inside a closed <details>: measured when it opens
    if (!over) {
      el.classList.remove("is-clamped");
      if (btn) { btn.remove(); }
      return;
    }
    if (btn) { return; }
    if (!el.id) { el.id = "clamp-" + (++uid); }
    btn = document.createElement("button");
    btn.type = "button";
    btn.className = "clamp-btn";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", el.id);
    btn.textContent = "Show more";
    btn.addEventListener("click", function () {
      var open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      btn.textContent = open ? "Show more" : "Show less";
      el.classList.toggle("is-clamped", open);
    });
    el.insertAdjacentElement("afterend", btn);
  }
  function run() {
    var els = document.querySelectorAll(".clamp");
    for (var i = 0; i < els.length; i++) { els[i].style.setProperty("--lines", els[i].getAttribute("data-lines") || "2"); measure(els[i]); }
  }
  document.documentElement.classList.add("js-clamp");
  run();
  document.addEventListener("toggle", run, true);
  window.addEventListener("resize", run);
  window.addEventListener("load", run);
})();
