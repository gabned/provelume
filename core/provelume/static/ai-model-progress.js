/* Read-only, bounded observation of an explicitly started local model operation. */
"use strict";
(() => {
  const root = document.querySelector("[data-ai-model-watch]");
  if (!root || root.dataset.state !== "running") return;
  const url = new URL(root.dataset.url, location.origin);
  if (url.origin !== location.origin) return;
  url.searchParams.set("operation", root.dataset.operation);
  url.searchParams.set("session", root.dataset.session);
  const notice = root.querySelector("[data-ai-refresh-status]");
  const manual = root.querySelector("[data-ai-refresh]");
  const number = new Intl.NumberFormat(document.documentElement.lang, {maximumFractionDigits: 2});
  let stopped = false, busy = false, active = true, timer, controller, failures = 0, generation = 0;
  const schedule = (delay = 2000) => {
    clearTimeout(timer);
    if (!stopped && active && !document.hidden) timer = setTimeout(refresh, delay);
  };
  const phase = text => {
    const node = root.querySelector("[data-ai-phase]");
    if (node && node.textContent !== text) node.textContent = text;
  };
  async function refresh() {
    if (busy || stopped || !active || document.hidden) return;
    busy = true;
    const turn = generation;
    controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {signal: controller.signal, credentials: "same-origin",
        cache: "no-store", redirect: "error", headers: {Accept: "application/json"}});
      if (turn !== generation || stopped) return;
      if (response.status === 409 || response.status === 403) {
        stopped = true;
        notice.textContent = root.dataset.stale;
        return;
      }
      if (!response.ok) throw new Error("status unavailable");
      const value = await response.json();
      if (turn !== generation || stopped) return;
      if (value.instance !== root.dataset.instance || value.session !== root.dataset.session ||
          value.operation !== root.dataset.operation ||
          !["running", "completed", "cancelled", "failed"].includes(value.state) ||
          !Number.isSafeInteger(value.bytes) || value.bytes < 0 ||
          !Number.isSafeInteger(value.total) || value.total <= 0) {
        stopped = true;
        notice.textContent = root.dataset.stale;
        return;
      }
      if (value.state !== "running") {
        const keys = ["ai-model-progress", "ai-model-actions", "ai-session-state"];
        if (!value.fragments || keys.some(key => typeof value.fragments[key] !== "string")) {
          throw new Error("incomplete status");
        }
        const focusWasInside = keys.some(key =>
          document.getElementById(key).contains(document.activeElement));
        for (const key of keys) {
          const fragment = new DOMParser().parseFromString(value.fragments[key], "text/html");
          document.getElementById(key).replaceChildren(...fragment.body.childNodes);
        }
        root.dataset.state = value.state;
        stopped = true;
        // Announce completion once, not every byte. Keep unrelated form focus intact.
        notice.textContent = root.querySelector("[data-ai-operation-state]").textContent;
        if (focusWasInside) root.querySelector("#ai-model-operation").focus({preventScroll: true});
      } else {
        const cancelNonce = root.querySelector('#ai-model-actions input[name="mutation_nonce"]');
        if (cancelNonce && typeof value.cancel_nonce === "string") {
          cancelNonce.value = value.cancel_nonce;
        }
        const cancelButton = root.querySelector("#ai-model-actions button");
        if (cancelButton) cancelButton.disabled = value.cancel_requested;
        const operation = root.querySelector("#ai-model-operation");
        operation.dataset.bytes = String(value.bytes);
        operation.querySelector("[data-ai-bytes]").textContent =
          `${number.format(value.bytes / 1000000)} MB`;
        const progress = root.querySelector("[data-ai-progress]");
        if (value.action === "install" && value.bytes < value.total) {
          progress.max = value.total;
          progress.value = value.bytes;
        } else progress.removeAttribute("value");
        phase(value.cancel_requested ? root.dataset.cancelling :
          value.action === "install" && value.bytes >= value.total ?
            root.dataset.verifying : root.dataset.running);
        notice.textContent = "";
      }
      failures = 0;
    } catch {
      if (turn === generation && !stopped) {
        failures = Math.min(failures + 1, 4);
        notice.textContent = root.dataset.unavailable;
      }
    } finally {
      clearTimeout(timeout);
      busy = false;
      schedule(Math.min(30000, 2000 * 2 ** failures));
    }
  }
  manual.addEventListener("click", event => {
    if (!stopped) { event.preventDefault(); clearTimeout(timer); refresh(); }
  });
  document.addEventListener("visibilitychange", () => {
    generation++;
    clearTimeout(timer);
    if (controller) controller.abort();
    if (!document.hidden) schedule(0);
  });
  window.addEventListener("pagehide", () => {
    active = false;
    generation++;
    clearTimeout(timer);
    if (controller) controller.abort();
  });
  window.addEventListener("pageshow", () => { active = true; schedule(0); });
  schedule();
})();
