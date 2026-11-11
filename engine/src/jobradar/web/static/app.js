// Long actions (LLM calls, scans): disable the button and show progress text.
document.querySelectorAll("form[data-busy]").forEach(function (form) {
  form.addEventListener("submit", function () {
    var btn = form.querySelector("button[type=submit], button:not([type])");
    if (btn) {
      btn.disabled = true;
      btn.textContent = form.getAttribute("data-busy");
    }
  });
});
// Confirm destructive status changes.
document.querySelectorAll("form[data-confirm]").forEach(function (form) {
  form.addEventListener("submit", function (e) {
    if (!window.confirm(form.getAttribute("data-confirm"))) { e.preventDefault(); }
  });
});
// While a scan runs: move the progress bar live; list and status pages reload once when it ends.
(function () {
  var fill = document.querySelector(".runbar-fill");
  var info = document.querySelector(".runinfo");
  if (document.body.dataset.running !== "1" || !fill || !info) { return; }
  var misses = 0;
  function show(p, fallback) {
    var pct = Math.round(((p && p.fraction) || 0) * 100);
    fill.style.width = pct + "%";
    var text = (p && p.label) || fallback;
    if (p && p.detail) { text += ": " + p.detail; }
    info.textContent = text + " · %" + pct;
  }
  function finished(p) {
    document.body.dataset.running = "0";
    if (document.body.dataset.reload === "1") { window.location.reload(); return; }
    var ok = p && p.stage === "done";
    show(ok || (p && p.stage === "failed") ? p : {label: "Tarama durdu", fraction: (p && p.fraction) || 0}, "");
    var btn = document.querySelector('form[action="/cycle"] button');
    if (btn) { btn.disabled = false; btn.textContent = "Şimdi tara"; }
  }
  function tick() {
    fetch("/api/status", {credentials: "same-origin", cache: "no-store"})
      .then(function (r) { if (!r.ok) { throw new Error(String(r.status)); } return r.json(); })
      .then(function (d) {
        misses = 0;
        if (d.running) { show(d.progress, "Tarama sürüyor"); setTimeout(tick, 2500); }
        else { finished(d.progress); }
      })
      .catch(function () { misses += 1; if (misses < 6) { setTimeout(tick, 5000); } });
  }
  setTimeout(tick, 2500);
})();

// Copy buttons: <button data-copy-target="ID"> copies the text of element ID, <button data-copy="text"> copies text.
function jrCopy(text, btn) {
  function done() {
    if (!btn) { return; }
    var old = btn.textContent;
    btn.textContent = "Kopyalandı";
    btn.classList.add("copied");
    setTimeout(function () { btn.textContent = old; btn.classList.remove("copied"); }, 1300);
  }
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, function () { fallback(); });
  } else { fallback(); }
  function fallback() {
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); done(); } catch (e) { window.prompt("Kopyala:", text); }
    document.body.removeChild(ta);
  }
}
document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-copy-target], [data-copy]");
  if (!btn) { return; }
  e.preventDefault();
  var text = btn.hasAttribute("data-copy") ? btn.getAttribute("data-copy")
    : (document.getElementById(btn.getAttribute("data-copy-target")) || {}).textContent || "";
  jrCopy(text.trim(), btn);
});
// Answers: switch every value between German and English.
document.querySelectorAll("[data-lang-switch]").forEach(function (seg) {
  var scope = document.getElementById(seg.getAttribute("data-lang-switch"));
  if (!scope) { return; }
  seg.querySelectorAll("button[data-lang]").forEach(function (b) {
    b.addEventListener("click", function () {
      var lang = b.getAttribute("data-lang");
      seg.querySelectorAll("button").forEach(function (x) { x.classList.toggle("on", x === b); });
      scope.querySelectorAll("[data-de]").forEach(function (el) {
        el.textContent = el.getAttribute("data-" + lang) || el.getAttribute("data-de");
      });
    });
  });
});
