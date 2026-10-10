/* Fixed presentation only: native disclosures work without JavaScript. */
"use strict";
(() => {
  const navigation = document.querySelector("[data-cura-navigation]");
  const compact = matchMedia("(max-width: 60rem)");
  const menus = [...document.querySelectorAll("[data-header-menu]")];
  if (navigation) menus.push(navigation);
  const active = () => menus.filter(menu => menu !== navigation || compact.matches);
  if (navigation) {
    const sync = () => {
      if (compact.matches) navigation.setAttribute("name", "provelume-header");
      else navigation.removeAttribute("name");
      navigation.open = !compact.matches;
    };
    sync();
    compact.addEventListener("change", sync);
  }
  for (const menu of menus) {
    menu.addEventListener("toggle", () => {
      if (menu.open && active().includes(menu)) {
        for (const other of active()) if (other !== menu) other.open = false;
      }
    });
    menu.addEventListener("focusout", event => {
      if (!active().includes(menu) || !event.relatedTarget ||
          menu.contains(event.relatedTarget)) return;
      const target = event.relatedTarget.closest("[data-header-menu], [data-cura-navigation]");
      // Wait for native activation between header disclosures: closing here can
      // move a mobile pointer target before its click reaches the new summary.
      if (!active().includes(target)) menu.open = false;
    });
  }
  document.addEventListener("click", event => {
    for (const menu of active()) if (menu.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape" || event.defaultPrevented) return;
    const menu = active().find(item => item.open);
    if (!menu) return;
    const inside = menu.contains(document.activeElement);
    menu.open = false;
    if (inside) {
      menu.querySelector("summary").focus();
      event.preventDefault();
    }
  });
})();
