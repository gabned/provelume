"use strict";
(() => {
  const root = document.getElementById("annotation-editor");
  if (!root) return;
  const model = JSON.parse(root.dataset.model);
  const labels = JSON.parse(root.dataset.labels);
  const editable = root.dataset.editable === "true";
  const list = document.getElementById("annotation-segments");
  const status = document.getElementById("annotation-status");
  const save = document.getElementById("annotation-save");
  const player = document.getElementById("annotation-player");
  const pdf = document.getElementById("annotation-pdf");
  let segments = model.segments;
  let operations = [];
  let plan = null;
  let active = 0;
  let busy = false;
  let finished = false;
  let dirty = false;
  let planAction = "save";
  const element = (tag, text, parent) => {
    const node = document.createElement(tag);
    if (text !== null) node.textContent = text;
    if (parent) parent.append(node);
    return node;
  };
  function anchorDescription(anchor) {
    if (anchor.kind === "time") {
      const timestamp = milliseconds => {
        const seconds = Math.floor(milliseconds / 1000);
        const fraction = String(milliseconds % 1000).padStart(3, "0");
        return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}.${fraction}`;
      };
      return `${labels.time}: ${timestamp(anchor.start_ms)} – ${timestamp(anchor.end_ms)}`;
    }
    const page = `${labels.page} ${anchor.page}`;
    if (anchor.kind === "region") {
      const number = value => value.toLocaleString(document.documentElement.lang);
      return `${page} · ${labels.region}: x ${number(anchor.x)}, y ${number(anchor.y)} · ${labels.width} ${number(anchor.width)}, ${labels.height} ${number(anchor.height)} px`;
    }
    return page;
  }
  function select(index, seek = true) {
    active = Math.max(0, Math.min(index, segments.length - 1));
    const row = segments[active];
    for (const [i, card] of [...list.children].entries()) card.setAttribute("aria-current", String(i === active));
    document.getElementById("annotation-anchor").textContent = `${labels.anchor}: ${row.anchors.map(anchorDescription).join("; ")}`;
    const time = row.anchors.find(anchor => anchor.kind === "time");
    if (time && player && seek && Number.isFinite(player.duration)) player.currentTime = time.start_ms / 1000;
    const page = row.anchors.find(anchor => anchor.kind === "page" || anchor.kind === "region");
    if (page && pdf) {
      const next = `/review/annotations/${encodeURIComponent(root.dataset.subject)}/media#page=${page.page}`;
      if (pdf.getAttribute("src") !== next) pdf.setAttribute("src", next);
    }
    const region = document.getElementById("annotation-region");
    const svg = document.getElementById("annotation-overlay");
    if (region && svg) {
      if (page && page.kind === "region") {
        svg.setAttribute("viewBox", `0 0 ${page.page_width} ${page.page_height}`);
        for (const [key, value] of Object.entries({x: page.x, y: page.y, width: page.width, height: page.height})) region.setAttribute(key, String(value));
      } else region.setAttribute("width", "0");
    }
  }
  function unreviewed() { dirty = true; save.disabled = true; status.textContent = labels.dirty; }
  async function preview(action, parameters, nextOperations) {
    if (busy || !editable || finished) return;
    busy = true; save.disabled = true;
    for (const control of root.querySelectorAll("textarea, input, .annotation-actions button, #annotation-undo")) control.disabled = true;
    try {
      const response = await fetch(`/review/annotations/${encodeURIComponent(root.dataset.subject)}/preview`, {
        method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({csrf_token: root.dataset.token, action, parameters})
      });
      if (!response.ok) throw new Error("preview denied");
      plan = await response.json(); segments = plan.segments; planAction = action;
      operations = nextOperations; dirty = false;
      document.getElementById("annotation-diff").textContent = plan.diff.join("");
      status.textContent = labels.ready; render(); save.disabled = false;
    } catch (_) { plan = null; status.textContent = labels.error; }
    finally {
      busy = false;
      for (const [index, card] of [...list.children].entries()) {
        for (const control of card.querySelectorAll("textarea, input, button")) control.disabled = !editable || finished || planAction === "undo";
        card.querySelector(".annotation-actions button:last-child").disabled = !editable || finished || planAction === "undo" || index + 1 === segments.length;
      }
      document.getElementById("annotation-undo").disabled = !editable || finished || model.revision === 0;
    }
  }
  function pendingEdits() {
    const edits = [];
    for (const [index, card] of [...list.children].entries()) {
      const value = card.querySelector("textarea").value;
      const label = card.querySelector("input").value || null;
      if (value !== segments[index].text) edits.push({kind: "edit", segment: segments[index].id, text: value});
      if (label !== segments[index].speaker_label) edits.push({kind: "speaker", segment: segments[index].id, label});
    }
    return edits;
  }
  function propose(extra = []) {
    if (planAction === "undo") return;
    const next = [...operations, ...pendingEdits(), ...extra];
    if (next.length) preview("save", {operations: next}, next);
  }
  function render() {
    list.replaceChildren();
    segments.forEach((row, index) => {
      const card = element("article", null, list); card.className = "annotation-segment";
      const confidence = row.confidence === null ? labels.unknown : `${labels.confidence}: ${Math.round(row.confidence * 100)}%`;
      element("p", `${index + 1} · ${confidence}`, card);
      const label = element("label", labels.text, card);
      const textarea = element("textarea", null, label); textarea.value = row.text;
      textarea.maxLength = 100000; textarea.disabled = !editable || finished || planAction === "undo";
      textarea.addEventListener("focus", () => select(index));
      textarea.addEventListener("input", unreviewed);
      textarea.addEventListener("keydown", event => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); propose(); }
      });
      const speaker = element("label", labels.speaker, card);
      const input = element("input", null, speaker); input.value = row.speaker_label || "";
      input.maxLength = 200; input.disabled = !editable || finished || planAction === "undo";
      input.addEventListener("input", unreviewed);
      const actions = element("div", null, card); actions.className = "annotation-actions";
      const button = (text, click, disabled = false) => {
        const node = element("button", text, actions); node.type = "button";
        node.disabled = !editable || finished || disabled || planAction === "undo"; node.addEventListener("click", click);
      };
      button(labels.apply, () => propose());
      button(labels.split, () => {
        const offset = [...textarea.value.slice(0, textarea.selectionStart)].length;
        propose([{kind: "split", segment: row.id, offset}]);
      });
      button(labels.merge, () => propose([{kind: "merge", segment: row.id, next: segments[index + 1].id}]), index + 1 === segments.length);
    });
    select(active, false);
  }
  function uncertain(direction) {
    for (let offset = 1; offset <= segments.length; offset++) {
      const i = (active + direction * offset + segments.length) % segments.length;
      if (segments[i].confidence === null || segments[i].confidence < 0.5) {
        select(i); list.children[i].querySelector("textarea").focus(); return;
      }
    }
  }
  document.getElementById("annotation-previous").addEventListener("click", () => uncertain(-1));
  document.getElementById("annotation-next").addEventListener("click", () => uncertain(1));
  document.getElementById("annotation-undo").addEventListener("click", () => {
    if (dirty && !window.confirm(labels.dirty)) return;
    preview("undo", {revision: Number(document.getElementById("annotation-undo-target").value)}, []);
  });
  save.addEventListener("click", async () => {
    if (!plan || dirty || busy || finished) return;
    busy = true; save.disabled = true;
    try {
      const response = await fetch(`/review/annotations/${encodeURIComponent(root.dataset.subject)}/confirm`, {
        method: "POST", credentials: "same-origin", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({csrf_token: root.dataset.token, plan_revision: plan.plan_revision,
          authority_revision: plan.authority_revision, request_id: plan.request_id})
      });
      if (!response.ok) throw new Error("save denied");
      finished = true; dirty = false; status.textContent = labels.saved; render();
    } catch (_) { finished = true; status.textContent = labels.error; }
    finally { busy = false; }
  });
  if (player) player.addEventListener("timeupdate", () => {
    const time = player.currentTime * 1000;
    const i = segments.findIndex(row => row.anchors.some(a => a.kind === "time" && a.start_ms <= time && time <= a.end_ms));
    if (i >= 0) select(i, false);
  });
  window.addEventListener("beforeunload", event => { if (dirty || (plan && !finished)) { event.preventDefault(); event.returnValue = ""; } });
  render();
})();
