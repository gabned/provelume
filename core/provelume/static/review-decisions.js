"use strict";
(() => {
  const root = document.getElementById("review-decisions");
  if (!root) return;
  const labels = JSON.parse(root.dataset.labels);
  const domain = root.dataset.domain;
  const form = document.getElementById("review-selection");
  const status = document.getElementById("review-status");
  const previewButton = document.getElementById("review-preview");
  const confirmButton = document.getElementById("review-confirm");
  const confirmCheck = document.getElementById("review-confirm-check");
  const panel = document.getElementById("review-preview-panel");
  const actionControl = document.getElementById("review-action");
  const endpoint = `/review/decisions/${encodeURIComponent(domain)}/${encodeURIComponent(root.dataset.subject)}`;
  let plan = null;
  let generation = 0;
  let busy = false;
  let spent = false;
  const field = name => form.elements.namedItem(name);
  const value = name => field(name)?.value || "";
  const selected = name => Array.from(field(name)?.selectedOptions || []).map(option => option.value).sort();

  function syncControls() {
    form.querySelectorAll("[data-actions]").forEach(group => {
      group.hidden = !group.dataset.actions.split(" ").includes(actionControl.value);
      group.querySelectorAll("input, select").forEach(control => { control.disabled = group.hidden || spent; });
    });
    if (domain === "capabilities") {
      const automatic = value("mode") === "controlled-automatic";
      const automaticAction = root.dataset.subject === "processing" ? "run" : "apply_rule";
      form.querySelectorAll('[name="scope_action"]').forEach(control => {
        control.disabled = spent || (automatic && control.value !== automaticAction);
        if (automatic) control.checked = control.value === automaticAction;
      });
      field("scope_subject").disabled = spent || field("all_subjects").checked;
    }
    confirmButton.disabled = spent || busy || !plan || !plan.confirmable || !confirmCheck.checked;
  }

  function invalidate() {
    generation += 1;
    plan = null;
    confirmCheck.checked = false;
    if (!panel.hidden) status.textContent = labels.changed;
    panel.hidden = true;
    syncControls();
  }
  form.addEventListener("input", invalidate);
  form.addEventListener("change", invalidate);
  confirmCheck.addEventListener("change", syncControls);

  function parameters() {
    const action = actionControl.value;
    if (domain === "processing") {
      if (action === "save_policy") return {
        mode: value("mode"), path_prefix: value("path_prefix"), operations: selected("operations"),
        expires_at: value("expires_at"), max_jobs: Number(value("max_jobs")),
        max_input_bytes: Number(value("max_input_bytes")),
      };
      if (action === "run") return {version_id: value("version_id"), operation: value("operation")};
      return {};
    }
    if (domain === "iudicium") {
      if (action === "save_policy") return {
        job_id: value("job_id"), path_prefix: value("path_prefix"),
        target_ids: selected("target_ids"), languages: selected("languages"),
        expires_at: value("expires_at"), mode: value("mode"),
        max_applications: Number(value("max_applications")),
      };
      if (action === "apply") return {
        job_id: value("job_id"), policy_id: value("policy_id"),
        primary_node_id: value("primary_node_id"), secondary_node_ids: selected("secondary_node_ids"),
        reviewed: field("reviewed").checked,
      };
      if (action === "undo") return {application: value("application")};
      return {};
    }
    if (action === "classify" || action === "save_rule") {
      const result = {primary_node_id: value("primary_node_id"), secondary_node_ids: selected("secondary_node_ids")};
      if (action === "save_rule") Object.assign(result, {
        source_id: value("source_id"), path_prefix: value("path_prefix"),
        automatic_enabled: field("automatic_enabled").checked,
      });
      return result;
    }
    if (action === "apply_rule") return {rule_id: value("rule_id")};
    if (action === "new_version" || action === "select_current") {
      const result = {version_id: value("version_id")};
      if (domain === "duplicates") result.target_document_id = value("target_document_id");
      return result;
    }
    if (action === "configure") return {
      mode: value("mode"),
      scope: {
        subjects: field("all_subjects").checked ? ["*"] : selected("scope_subject"),
        actions: Array.from(form.querySelectorAll('[name="scope_action"]:checked')).filter(control => !control.disabled).map(control => control.value).sort(),
        sources: selected("scope_source"),
      },
    };
    return {};
  }

  async function post(suffix, fields) {
    const response = await fetch(endpoint + suffix + window.location.search, {
      method: "POST", credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({csrf_token: root.dataset.token, ...fields}),
    });
    if (!response.ok) throw new Error(labels.error);
    return response.json();
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (busy || spent) return;
    const current = generation;
    busy = true;
    plan = null;
    confirmCheck.checked = false;
    previewButton.disabled = true;
    status.textContent = labels.loading;
    syncControls();
    try {
      const result = await post("/preview", {action: actionControl.value, parameters: parameters()});
      if (current !== generation) { status.textContent = labels.changed; return; }
      plan = result;
      const rows = document.getElementById("review-changes");
      rows.replaceChildren();
      result.summary.changes.forEach(change => {
        const row = document.createElement("tr");
        [change.label, change.before, change.after].forEach((text, index) => {
          const cell = document.createElement(index === 0 ? "th" : "td");
          if (index === 0) cell.scope = "row";
          cell.textContent = text;
          row.append(cell);
        });
        rows.append(row);
      });
      document.getElementById("review-impact").textContent = result.summary.impact;
      document.getElementById("review-reversibility").textContent = result.summary.reversibility;
      document.getElementById("review-confidence").textContent = result.summary.confidence === null ? labels.unknown : String(result.summary.confidence);
      document.getElementById("review-evidence").textContent = JSON.stringify(result.summary.evidence, null, 2);
      document.getElementById("review-ambiguity").hidden = !result.summary.ambiguous;
      panel.hidden = false;
      status.textContent = result.confirmable ? "" : labels.permission_denied;
      document.getElementById("review-preview-title").focus();
    } catch (_error) {
      status.textContent = labels.error;
    } finally {
      busy = false;
      previewButton.disabled = spent || actionControl.options.length === 0;
      syncControls();
    }
  });

  confirmButton.addEventListener("click", async () => {
    if (busy || spent || !plan || !plan.confirmable || !confirmCheck.checked) return;
    busy = true;
    spent = true;
    previewButton.disabled = true;
    form.querySelectorAll("input, select, button").forEach(control => { control.disabled = true; });
    confirmCheck.disabled = true;
    document.getElementById("review-history-snapshot").hidden = true;
    document.getElementById("review-history-refresh").hidden = false;
    syncControls();
    try {
      const result = await post("/confirm", {
        plan_revision: plan.plan_revision, authority_revision: plan.authority_revision,
        request_id: plan.request_id,
      });
      status.textContent = `${labels.saved} ${result.receipt.id}`;
      if (domain === "processing" && "processing_job" in result) {
        if (result.processing_job) {
          const jobLink = document.createElement("a");
          jobLink.href = `/maintenance/jobs/${encodeURIComponent(result.processing_job)}` + window.location.search;
          jobLink.textContent = labels.processing_job;
          status.append(document.createTextNode(" "), jobLink);
        } else {
          status.append(document.createTextNode(" " + labels.processing_enqueue_pending));
        }
      }
      const link = document.createElement("a");
      link.href = endpoint + window.location.search;
      link.textContent = labels.fresh;
      status.append(document.createTextNode(" "), link);
    } catch (_error) {
      status.textContent = labels.uncertain;
    } finally {
      busy = false;
      syncControls();
    }
  });
  syncControls();
})();
