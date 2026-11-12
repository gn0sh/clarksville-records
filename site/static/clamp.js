/* "Show more" for long text (.clamp). Without this script the full text shows. With it, text taller than its
   data-lines is cut to that many lines and a button (aria-expanded) shows or hides the rest. The text stays in the
   page either way. First-party, no network.
   Layout is read once per pass (perf/clamp-layout-thrash): every write that clamps comes first, then every height is
   read, then the buttons are added or removed. Resize runs at most once per frame; opening a <details> measures only
   the .clamp inside it. */
(function () {
  var uid = 0;
  function buttonOf(el) {
    var n = el.nextElementSibling;
    return n && n.classList.contains("clamp-btn") ? n : null;
  }
  function addButton(el) {
    if (!el.id) { el.id = "clamp-" + (++uid); }
    var btn = document.createElement("button");
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
  function run(root) {
    var els = (root || document).querySelectorAll(".clamp"), todo = [], i, t;
    for (i = 0; i < els.length; i++) {                     // 1. writes: clamp every block not opened by its button
      var el = els[i], btn = buttonOf(el);
      el.style.setProperty("--lines", el.getAttribute("data-lines") || "2");
      if (btn && btn.getAttribute("aria-expanded") === "true") { continue; }
      el.classList.add("is-clamped");
      todo.push({ el: el, btn: btn });
    }
    for (i = 0; i < todo.length; i++) {                    // 2. reads: one layout for the whole pass
      t = todo[i];
      t.h = t.el.clientHeight;
      t.over = t.el.scrollHeight > t.h + 1;
    }
    for (i = 0; i < todo.length; i++) {                    // 3. writes: buttons
      t = todo[i];
      if (t.h === 0) { continue; }                         // inside a closed <details>: measured when it opens
      if (!t.over) {
        t.el.classList.remove("is-clamped");
        if (t.btn) { t.btn.remove(); }
      } else if (!t.btn) {
        addButton(t.el);
      }
    }
  }
  var queued = false;
  function onResize() {
    if (queued) { return; }
    queued = true;
    window.requestAnimationFrame(function () { queued = false; run(document); });
  }
  document.documentElement.classList.add("js-clamp");
  run(document);
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (d && d.open && d.querySelectorAll) { run(d); }   // a closed <details> needs nothing measured
  }, true);
  window.addEventListener("resize", onResize);
  window.addEventListener("load", function () { run(document); });
})();
