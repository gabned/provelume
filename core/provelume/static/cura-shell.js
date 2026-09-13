/* Fixed first-party presentation enhancement. No network, storage or user code. */
"use strict";
(() => {
  const navigation = document.querySelector("[data-cura-navigation]");
  const compact = window.matchMedia("(max-width: 60rem)");
  if (navigation) {
    const summary = navigation.querySelector("summary");
    const synchronize = () => { navigation.open = !compact.matches; };
    synchronize();
    compact.addEventListener("change", synchronize);
    navigation.addEventListener("focusout", (event) => {
      if (compact.matches && navigation.open && event.relatedTarget &&
          !navigation.contains(event.relatedTarget)) navigation.open = false;
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && compact.matches && navigation.open) {
        navigation.open = false;
        summary.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (compact.matches && navigation.open && !navigation.contains(event.target)) {
        navigation.open = false;
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
