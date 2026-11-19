// MailBrief site: copy buttons, example tabs, canned chat demo. No dependencies.
// Everything here is an enhancement: without JS all content is still on the page.
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // ── theme toggle: the <head> script already applied the saved choice ──
  document.querySelectorAll(".theme").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var next = root.dataset.theme === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch (e) { /* private mode: still switches */ }
    });
  });

  // ── copy buttons on code blocks ───────────────────────────────────────
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) { // older browsers / odd file:// setups
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy") ? resolve() : reject(); } catch (e) { reject(e); }
      ta.remove();
    });
  }

  document.querySelectorAll(".code").forEach(function (block) {
    var pre = block.querySelector("pre");
    var btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Copy";
    btn.setAttribute("aria-label", "Copy this code");
    btn.addEventListener("click", function () {
      copyText(pre.textContent.replace(/\n$/, "")).then(function () {
        btn.textContent = "Copied";
        btn.classList.add("done");
      }, function () {
        btn.textContent = "Select and copy";
      }).then(function () {
        setTimeout(function () { btn.textContent = "Copy"; btn.classList.remove("done"); }, 1600);
      });
    });
    block.appendChild(btn);
  });

  // ── tabs (WAI-ARIA pattern: arrows move, Home/End jump) ───────────────
  document.querySelectorAll("[role=tablist]").forEach(function (list) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll("[role=tab]"));
    function select(tab, focus) {
      tabs.forEach(function (t) {
        var on = t === tab;
        t.setAttribute("aria-selected", on);
        t.tabIndex = on ? 0 : -1;
        document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () { select(tab); });
      tab.addEventListener("keydown", function (e) {
        var to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
        if (to === undefined) return;
        e.preventDefault();
        select(tabs[(to + tabs.length) % tabs.length], true);
      });
    });
    select(tabs[0]);
  });

  // ── chat demo: plays canned exchanges that are already in the HTML ────
  var demo = document.querySelector("[data-chat-demo]");
  if (demo) {
    var log = demo.querySelector(".tg-body");
    var exchanges = Array.prototype.slice.call(log.querySelectorAll("[data-exchange]"));
    var still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var row = document.createElement("div");
    row.className = "ask-row";
    row.setAttribute("role", "group");
    row.setAttribute("aria-label", "Play an example question");
    log.setAttribute("aria-live", "polite");
    log.tabIndex = 0; // scrollable region: reachable by keyboard
    log.setAttribute("role", "log");
    log.setAttribute("aria-label", "Example conversation");

    exchanges.forEach(function (ex, n) {
      var parts = Array.prototype.slice.call(ex.children);
      if (n > 0) ex.hidden = true; // the first exchange stays visible as the starting state
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = ex.getAttribute("data-exchange");
      btn.disabled = n === 0;
      btn.addEventListener("click", function () {
        btn.disabled = true;
        parts.slice(1).forEach(function (p) { p.hidden = true; });
        ex.hidden = false;
        var typing = document.createElement("div");
        typing.className = "typing";
        typing.textContent = "MailBrief is typing…";
        ex.appendChild(typing);
        typing.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
        setTimeout(function () {
          typing.remove();
          parts.slice(1).forEach(function (p) { p.hidden = false; });
          parts[0].scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
        }, still ? 0 : 1100);
      });
      row.appendChild(btn);
    });
    demo.appendChild(row);
  }
})();
