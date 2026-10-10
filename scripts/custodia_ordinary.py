"""Public fixture and ordinary HTTP form driver; never imported by the product."""

from __future__ import annotations

import hashlib
import json
import time
from html.parser import HTMLParser


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.hidden, self.operation = {}, None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        row = dict(attrs)
        if tag == "input" and row.get("type") == "hidden" and row.get("name"):
            self.hidden[row["name"]] = row.get("value", "")
        if row.get("id") == "ai-model-operation":
            self.operation = {key.removeprefix("data-"): value for key, value in row.items()
                              if key in {"data-state", "data-action", "data-error",
                                         "data-diagnostic-stage", "data-native-code"}}

    def fields(self):
        return {k: self.hidden[k] for k in ("csrf_token", "mutation_nonce", "instance_id")}


def public_documents(instance, corpus, directory):
    from provelume import __version__

    raw = corpus.read_bytes()
    cases = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != (
        "95d9e829cbe25ec2227be7b55d0b6c73507180ebbbe1fd213085bbcdc40fd488"
    ):
        raise ValueError("corpus_identity")
    directory.mkdir()
    for index, case in enumerate(cases):
        (directory / f"public-{index}.txt").write_text(case["text"], encoding="utf-8")
    instance.ingest(directory)
    documents = {row["title"]: instance.get_document(row["id"])
                 for row in instance.store.list_canonical("documents")}
    result = []
    for index, case in enumerate(cases):
        document = documents[f"public-{index}.txt"]
        bundle = instance.representations.bundles.materialize(
            document["current_version"]["id"], recipe_id="custodia-public-corpus",
            recipe_version="1", recipe_settings={"case": case["id"]},
            output_payloads={"text.txt": ("text/plain", case["text"].encode())},
            implementation={"component": "provelume.core", "component_version": __version__,
                            "adapter": "custodia-public-fixture", "adapter_version": "1",
                            "settings": {}}, anchor_targets=({"kind": "page", "page": 1},),
        )
        result.append((case, document["id"], bundle))
    return result


def model_action(client, name, report, *, observe=lambda: None, save=lambda: None, **values):
    response = client.get("/settings/ai?lang=en")
    response.raise_for_status()
    page = Page(response.text)
    response = client.post("/settings/ai/model?lang=en", data={
        **page.fields(), "action": name, "acknowledge": "explicit", "path": "",
        "authority": page.hidden["authority"], **values})
    if response.status_code != 303:
        raise ValueError("model_action_http")
    end = time.monotonic() + (910 if name in {"import", "install"} else 70)
    while time.monotonic() < end:
        observe()
        response = client.get("/settings/ai?lang=en")
        response.raise_for_status()
        operation = Page(response.text).operation
        if operation and operation["action"] == name and operation["state"] != "running":
            report.setdefault("operations", {})[name] = operation
            save()
            if operation["state"] != "completed":
                raise ValueError("model_operation")
            return
        time.sleep(.1)
    raise ValueError("operation_timeout")


def document_jobs(client, instance, cases, report, *, observe=lambda: None, save=lambda: None):
    """No adapter replacement: real UI consent, scheduler, worker and stored citations."""
    report["synthesis"] = []
    for case, document, bundle in cases:
        path = f"/documents/{document}/synthesis"
        page = Page(client.get(path + "?lang=" + case["language"]).text)
        # This explicit operation handles expired proof by returning a fresh preview.
        response = client.post(path + "/verify-preview", data={
            **page.fields(), "selection": bundle["representation_id"] + ":" +
            bundle["outputs"][0]["id"], "version_id": bundle["version"]["id"],
            "task": case["task"], "language": case["language"]})
        response.raise_for_status()
        page = Page(response.text)
        if "ref" not in page.hidden:
            raise ValueError("synthesis_preview")
        before = {row["id"] for row in instance.scheduler.journal.list_jobs(limit=100)}
        started = time.monotonic()
        response = client.post("/operations/ai/synthesis/execute", data={
            **page.fields(), "ref": page.hidden["ref"], "acknowledge": "selected-document"})
        if response.status_code != 303:
            raise ValueError("synthesis_consent")
        end, job = time.monotonic() + 70, None
        while time.monotonic() < end:
            observe()
            rows = [row for row in instance.scheduler.journal.list_jobs(limit=100)
                    if row["id"] not in before]
            if len(rows) != 1:
                raise ValueError("synthesis_job_identity")
            job = rows[0]
            if job["status"] not in {"queued", "running"}:
                break
            time.sleep(.1)
        result = job["ai"]["result"]
        valid = job["status"] == "succeeded" and result and result["kind"] == "derived_ref"
        references, abstained = None, False
        if valid:
            body_path = instance.store.paths.derived_artifacts.parent / (
                "ai-synthesis-" + job["id"] + ".json")
            body = json.loads(body_path.read_bytes())
            references, abstained = body["references"], body["status"] == "abstained"
            page = client.get(f"/operations/ai/{job['id']}/synthesis")
            valid = page.status_code == 200 and all(
                f"/operations/ai/{job['id']}/synthesis/evidence/{index}" in page.text
                for index in references)
        gold = bool(valid and ((abstained and case["allow_abstention"]) or (
            not abstained and references in case["allowed_references"])))
        report["synthesis"].append({
            "case": case["id"], "task": case["task"], "language": case["language"],
            "status": job["status"], "valid": bool(valid), "gold": gold,
            "abstained": abstained, "required_abstention": case["require_abstention"],
            "references": references, "attempts": job["attempt"],
            "seconds": time.monotonic() - started})
        save()
    if not all(row["gold"] and row["attempts"] == 1 for row in report["synthesis"]):
        raise ValueError("synthesis_quality")
    report["checks"]["ordinary_document_synthesis_32_cases"] = "PASS"


def restart_off(instance):
    from provelume.ai_setup import AiSetup
    from provelume.service import ProvelumeInstance

    setup = AiSetup(ProvelumeInstance(instance))
    try:
        if setup.jobs.session_authorized:
            raise ValueError("restart_authority")
        return {"session_authorized": False, "model_present": setup.models._state()["active"]}
    finally:
        setup.close()
