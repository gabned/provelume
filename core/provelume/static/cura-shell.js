/* Fixed first-party presentation enhancement. No network, storage or user code. */
"use strict";
(() => {
  const confirmation = document.querySelector("[data-preference-confirm]");
  if (confirmation && typeof confirmation.showModal === "function") {
    // The server-rendered open dialog remains usable without JavaScript.
    confirmation.close();
    confirmation.showModal();
    const cancel = confirmation.querySelector("[data-preference-cancel]");
    confirmation.addEventListener("cancel", (event) => {
      event.preventDefault();
      cancel.click();
    });
    confirmation.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const controls = [...confirmation.querySelectorAll("button:not([disabled]),a[href]")];
      const first = controls[0], last = controls[controls.length - 1];
      if ((!event.shiftKey && document.activeElement === last) ||
          (event.shiftKey && document.activeElement === first)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    });
  }
  // A server-validated receipt supplies the initial interval. Both elapsed monotonic
  // time and the wall deadline can expire it; changing the clock cannot extend it.
  const started = performance.now();
  const cues = [...document.querySelectorAll("[data-release-cue]")].map((node) => ({
    node, seconds: Number(node.dataset.remainingSeconds),
    expires: Date.parse(node.dataset.expiresAt),
  }));
  let timer;
  const expire = () => {
    for (const cue of cues) {
      if (!Number.isFinite(cue.seconds) || !Number.isFinite(cue.expires) ||
          cue.seconds <= 0 || (performance.now() - started) / 1000 >= cue.seconds ||
          Date.now() >= cue.expires) cue.node.remove();
    }
    if (!cues.some((cue) => cue.node.isConnected)) window.clearInterval(timer);
  };
  expire();
  if (cues.some((cue) => cue.node.isConnected)) timer = window.setInterval(expire, 1000);
  document.addEventListener("visibilitychange", expire);
  window.addEventListener("pageshow", expire);
})();
