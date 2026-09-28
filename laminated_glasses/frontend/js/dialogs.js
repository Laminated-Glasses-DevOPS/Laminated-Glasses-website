/* Laminated Glasses — dizaynga mos dialog oynalari.
 *
 * Brauzerning standart confirm()/alert()/prompt() oynalari o'rniga ishlatiladi.
 * Sayt (main.js) ham, admin panel (admin.js) ham shu faylni ulaydi.
 *
 *   await lgConfirm({ title, message, confirmText, cancelText, tone })  -> true | false
 *   await lgAlert({ title, message, tone })                              -> true
 *   await lgPrompt({ title, message, placeholder, value, type })         -> string | null
 *
 * tone: "danger" | "warning" | "info" | "success"
 * Klaviatura: Esc = bekor qilish, Enter = tasdiqlash, Tab oyna ichida aylanadi.
 */
(function () {
  "use strict";

  var ICONS = {
    danger: '<path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    warning: '<path d="M12 8v5m0 3h.01M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>',
    info: '<path d="M12 11v5m0-8h.01M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>',
    success: '<path d="M8 12.5l3 3 5-6M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z"/>'
  };

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function openDialog(opts) {
    return new Promise(function (resolve) {
      var tone = opts.tone || "info";
      var previouslyFocused = document.activeElement;
      var overlay = document.createElement("div");
      overlay.className = "lgd-overlay";
      overlay.setAttribute("role", opts.kind === "alert" ? "alertdialog" : "dialog");
      overlay.setAttribute("aria-modal", "true");

      var inputHtml = opts.kind === "prompt"
        ? '<input class="lgd-input" type="' + esc(opts.type || "text") + '" placeholder="' +
          esc(opts.placeholder || "") + '" value="' + esc(opts.value || "") + '" autocomplete="off" />' +
          '<div class="lgd-error" aria-live="polite"></div>'
        : "";

      overlay.innerHTML =
        '<div class="lgd-card lgd-' + esc(tone) + '">' +
          '<div class="lgd-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
          (ICONS[tone] || ICONS.info) + "</svg></div>" +
          '<h3 class="lgd-title">' + esc(opts.title || "") + "</h3>" +
          (opts.message ? '<p class="lgd-message">' + esc(opts.message) + "</p>" : "") +
          inputHtml +
          '<div class="lgd-actions">' +
            (opts.kind === "alert" ? "" : '<button type="button" class="lgd-btn lgd-btn-ghost" data-act="cancel">' + esc(opts.cancelText || "Bekor qilish") + "</button>") +
            '<button type="button" class="lgd-btn lgd-btn-main" data-act="ok">' + esc(opts.confirmText || (opts.kind === "alert" ? "Tushunarli" : "Tasdiqlash")) + "</button>" +
          "</div>" +
        "</div>";

      document.body.appendChild(overlay);
      document.body.classList.add("lgd-lock");
      requestAnimationFrame(function () { overlay.classList.add("open"); });

      var input = overlay.querySelector(".lgd-input");
      var errorEl = overlay.querySelector(".lgd-error");
      var okBtn = overlay.querySelector('[data-act="ok"]');
      var closed = false;

      function close(result) {
        if (closed) return;
        closed = true;
        document.removeEventListener("keydown", onKey, true);
        overlay.classList.remove("open");
        setTimeout(function () {
          overlay.remove();
          if (!document.querySelector(".lgd-overlay")) document.body.classList.remove("lgd-lock");
        }, 180);
        if (previouslyFocused && previouslyFocused.focus) {
          try { previouslyFocused.focus(); } catch (e) { /* jim */ }
        }
        resolve(result);
      }

      function submit() {
        if (opts.kind === "prompt") {
          var value = input.value.trim();
          if (opts.validate) {
            var problem = opts.validate(value);
            if (problem) { errorEl.textContent = problem; input.focus(); return; }
          }
          close(value);
        } else {
          close(true);
        }
      }

      function cancel() { close(opts.kind === "alert" ? true : (opts.kind === "prompt" ? null : false)); }

      function onKey(e) {
        if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel(); return; }
        if (e.key === "Enter" && !(e.target && e.target.dataset && e.target.dataset.act === "cancel")) {
          e.preventDefault(); e.stopPropagation(); submit(); return;
        }
        if (e.key === "Tab") {
          var f = overlay.querySelectorAll("button, input");
          if (!f.length) return;
          var first = f[0], last = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }

      document.addEventListener("keydown", onKey, true);
      overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) cancel(); });
      overlay.addEventListener("click", function (e) {
        var b = e.target.closest("[data-act]");
        if (!b) return;
        if (b.dataset.act === "ok") submit(); else cancel();
      });

      setTimeout(function () { (input || okBtn).focus(); }, 30);
    });
  }

  window.lgConfirm = function (o) { return openDialog(Object.assign({ kind: "confirm", tone: "warning" }, o)); };
  window.lgAlert = function (o) { return openDialog(Object.assign({ kind: "alert", tone: "info" }, o)); };
  window.lgPrompt = function (o) { return openDialog(Object.assign({ kind: "prompt", tone: "info" }, o)); };
})();
