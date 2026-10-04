"""Instance-owned S07 configuration and private, expiring consent previews.

This host composes the S01-S06 contracts. It is not an adapter or a scheduler.
Only the fixed public test fixture can be enqueued; document previews cannot execute.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import asdict, replace
from pathlib import Path

from .ai_context import (
    ContextLimits,
    OutputBytes,
    RedactionConfig,
    Selection,
    SourceSnapshot,
    TaskTemplate,
    VersionIdentity,
    explain_prepared,
    preview_context,
    task_payload,
)
from .ai_contract import (
    Assurance,
    Capability,
    ContextBinding,
    GovernanceSnapshot,
    Limits,
    Locality,
    LocalityEvidence,
    Mode,
    PolicyRule,
    Profile,
    Scope,
    ScopeRef,
    digest,
)
from .ai_job_contract import Budget, check
from .ai_job_runtime import NativeConfig, NativeJobAdapter, ProviderJobAdapter
from .ai_model_download import ArtifactDownload
from .ai_models import ModelError
from .ai_provider import CallInputs, CredentialReference, Destination, ProviderConfig
from .ai_provider_http import ChatJsonAdapter
from .ai_runtime import LocalRuntime, native_selection
from .ai_runtime_contract import MODEL_ID
from .maintenance_local_files import open_local_file
from .representations import build_representation_bundle, canonical_json_bytes

MODES = {
    "off": Mode.OFF,
    "local": Mode.LOCAL_ONLY,
    "external": Mode.REMOTE,
    "hybrid": Mode.FALLBACK,
}
TEST_TEXT = "Public synthetic connection test. Contact ada@example.test."
LIMITS = Limits(4096, 128, 2, 60)
PREVIEW_SECONDS = 600


class AiSetup:
    def __init__(self, instance, *, runtime_directory=None, credentials=None):
        self.instance = instance
        self.instance_id = instance.scheduler.journal.instance_id
        self.path = instance.scheduler.journal.root / "ai-setup.json"
        self.models = instance.ai_model_lifecycle()
        self.runtime = LocalRuntime(runtime_directory or Path(__file__).parent / "native-ai")
        self.credentials = credentials or (lambda *_: None)
        self.lock = threading.RLock()
        self.previews = {}
        self.local_evidence = None
        self.self_test_evidence = None
        self.operation = None
        self.observed_model = None
        self.cancel = threading.Event()
        self.jobs = instance.bind_ai_execution(current=self.current, adapters={})

    def configuration(self):
        if not self.path.exists():
            return {
                "schema_version": 1,
                "instance_id": self.instance_id,
                "revision": 0,
                "mode": "off",
                "endpoint": "",
                "model": "",
                "credential": "",
                "order": "local,external",
                "job_units": 8448,
                "period_units": 84480,
            }
        with open_local_file(self.path) as stream:
            raw = stream.read(8193)
        check(len(raw) <= 8192, "ai_setup_invalid")
        value = json.loads(raw)
        self.validate(value, self.instance_id)
        return value

    @staticmethod
    def validate(value, instance_id):
        check(
            type(value) is dict
            and set(value)
            == {
                "schema_version",
                "instance_id",
                "revision",
                "mode",
                "endpoint",
                "model",
                "credential",
                "order",
                "job_units",
                "period_units",
            },
            "ai_setup_invalid",
        )
        check(
            type(value["schema_version"]) is int
            and value["schema_version"] == 1
            and value["instance_id"] == instance_id,
            "ai_wrong_instance",
        )
        check(type(value["revision"]) is int and value["revision"] >= 0)
        check(
            type(value["mode"]) is str
            and type(value["order"]) is str
            and value["mode"] in MODES
            and value["order"] in {"local,external", "external,local"},
            "ai_setup_invalid",
        )
        for key in ("endpoint", "model", "credential"):
            check(type(value[key]) is str and len(value[key]) <= 2048, "ai_setup_invalid")
        AiSetup.budget(value)
        if value["endpoint"] or value["mode"] in {"external", "hybrid"}:
            AiSetup.external(value)

    @staticmethod
    def budget(value):
        # External pricing is not qualified. A zero monetary hard cap fails closed
        # until an independently defensible quote exists; UNKNOWN is never free.
        return Budget(
            value["job_units"], value["period_units"], queue=8, job_micros=0, period_micros=0
        )

    @staticmethod
    def external(value):
        reference = (
            CredentialReference("system_keyring", value["credential"])
            if value["credential"]
            else None
        )
        config = ProviderConfig(value["endpoint"], Destination.REMOTE, reference)
        profile = Profile(
            "external",
            "compatible",
            value["model"],
            digest(value["model"]),
            config.fingerprint,
            (Capability.STRUCTURED_OUTPUT,),
            LIMITS,
        )
        return profile, config

    def save(self, value, revision):
        with self.lock:
            current = self.configuration()
            check(current["revision"] == revision, "ai_setup_stale")
            updated = {**current, **value, "revision": revision + 1}
            self.validate(updated, self.instance_id)

            def write():
                check(self.configuration()["revision"] == revision, "ai_setup_stale")
                self.instance.store._atomic_json(self.path, updated)
                self.previews.clear()

            self.jobs.change_authority(write)
            # Saving never enables a session. It revokes the old execution envelope.
            self.jobs.configure(mode="off")
            return updated

    def profiles(self, value):
        local = replace(
            self.models.registry.entry(MODEL_ID).profile,
            route_revision=NativeConfig().fingerprint,
            limits=LIMITS,
        )
        configs = {local.id: NativeConfig()}
        profiles = [local]
        evidence = []
        if self.local_evidence is not None:
            evidence.append(
                LocalityEvidence(
                    local.fingerprint,
                    Locality.LOCAL,
                    Assurance.MANAGED_OFFLINE,
                    self.local_evidence,
                )
            )
        if value["endpoint"]:
            external, config = self.external(value)
            profiles.append(external)
            configs[external.id] = config
            # Configuration is not live provider qualification. No evidence is
            # manufactured from a label, URL, loopback address or successful preflight.
        names = {"local": local.id, "external": "external"}
        order = value["order"].split(",") if value["mode"] == "hybrid" else [value["mode"]]
        route = tuple(names[n] for n in order if n in names)
        return tuple(profiles), tuple(evidence), configs, route

    def synthetic_source(self):
        raw = TEST_TEXT.encode()
        version = VersionIdentity(
            self.instance_id,
            "synthetic_test",
            "synthetic_v1",
            "synthetic_original",
            digest(TEST_TEXT),
            len(raw),
        )
        output = {
            "id": "rout_" + digest(TEST_TEXT),
            "media_type": "text/plain",
            "storage_ref": "state/derived/ai-public-test.txt",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
        }
        bundle = build_representation_bundle(
            version={
                "id": version.version_id,
                "original_id": version.original_id,
                "original_sha256": version.original_sha256,
                "original_size_bytes": version.original_size_bytes,
            },
            recipe_id="synthetic-connection-test",
            recipe_version="1",
            recipe_settings={},
            outputs=[output],
            implementation={
                "component": "provelume.core",
                "component_version": "0.11.0",
                "adapter": "public-test",
                "adapter_version": "1",
                "settings": {},
            },
            anchor_targets=({"kind": "page", "page": 1},),
            created_at="2026-10-04T00:00:00+00:00",
        )
        rid = bundle["representation_id"]
        source = SourceSnapshot(
            version, (canonical_json_bytes(bundle),), (OutputBytes(rid, output["id"], raw),)
        )
        selection = Selection(
            version,
            rid,
            digest(bundle),
            output["id"],
            bundle["anchors"][0]["id"],
            0,
            len(TEST_TEXT),
        )
        return source, (selection,)

    def prepare(self, key, source, selections, *, configuration, redaction=None, governance=None):
        profiles, evidence, configs, route = self.profiles(configuration)
        # S07's executable test has no document associations. Real document preview
        # never borrows this synthetic policy inventory or obtains dispatch authority.
        scopes = (
            ScopeRef(Scope.INSTANCE, self.instance_id),
            ScopeRef(Scope.SOURCE, "synthetic_test"),
            ScopeRef(Scope.CATEGORY, "public_test"),
        )
        if governance is not None:
            scopes = governance[0]
        context = ContextBinding(
            self.instance_id,
            source.version.document_id,
            source.version.version_id,
            digest(asdict(source.version)),
            digest(key),
        )
        snapshot = GovernanceSnapshot(
            context,
            scopes,
            digest(
                {
                    "configuration": configuration,
                    "associations": governance[1] if governance else "public_test",
                }
            ),
            configuration["mode"] in {"external", "hybrid"},
            True,
        )
        rules = tuple(
            PolicyRule(
                scope,
                digest(configuration),
                limits=LIMITS,
                allowed_profiles=tuple(p.id for p in profiles) if i == 0 else None,
                allowed_capabilities=(Capability.STRUCTURED_OUTPUT,) if i == 0 else None,
                mode=MODES[configuration["mode"]] if i == 0 else None,
                route=route if i == 0 else (),
            )
            for i, scope in enumerate(scopes)
        )
        current = dict(
            limits=ContextLimits(),
            request_limits=LIMITS,
            template=TaskTemplate("context-check-partial-v1", True),
            redaction=redaction or RedactionConfig(),
            snapshot=snapshot,
            rules=rules,
        )
        preview = preview_context(source, selections, **current)
        plan = explain_prepared(
            preview, source, selections, profiles=profiles, evidence=evidence, **current
        )
        return preview, plan, current, profiles, evidence, configs

    def preview_test(self):
        with self.lock:
            self._expire()
            check(len(self.previews) < 32, "ai_preview_capacity")
            key = secrets.token_hex(32)
            source, selections = self.synthetic_source()
            config = self.configuration()
            prepared = self.prepare(key, source, selections, configuration=config)
            self.previews[key] = dict(
                created=time.monotonic(),
                configuration=config,
                source=source,
                selections=selections,
                prepared=prepared,
                approved=False,
                job=None,
                generation=self.jobs._control()["generation"],
            )
            return key, prepared

    def _expire(self):
        now = time.monotonic()
        self.previews = {
            k: v for k, v in self.previews.items() if now - v["created"] < PREVIEW_SECONDS
        }

    def current(self, ref, route):
        # Called under the existing journal transaction, including every cancel poll.
        # No setup lock here: lock order must not invert the journal's authority barrier.
        row = self.previews.get(ref)
        check(
            row is not None
            and row["approved"]
            and time.monotonic() - row["created"] < PREVIEW_SECONDS,
            "ai_consent_missing",
        )
        config = self.configuration()
        check(config == row["configuration"], "ai_setup_stale")
        check(self.jobs._control()["generation"] == row["generation"], "ai_setup_stale")
        check(row["source"].version.document_id == "synthetic_test", "ai_document_preview_only")
        prepared = row["prepared"]
        profiles_now, evidence_now, configs_now, _ = self.profiles(config)
        check((profiles_now, evidence_now, configs_now) == prepared[3:], "ai_setup_stale")
        # S06 revalidates these current inputs (including in-place changes) on
        # every poll. Do not rebuild the private payload inside a cancellation poll.
        preview, plan, current, profiles, evidence, configs = prepared
        check(type(route) is int and 0 <= route < len(plan.routes), "ai_route_changed")
        profile = next(
            p for p in profiles if p.fingerprint == plan.routes[route].profile_fingerprint
        )
        return CallInputs(
            plan,
            preview,
            row["source"],
            row["selections"],
            current,
            profiles,
            evidence,
            configs[profile.id],
            route,
        )

    def approve(self, ref):
        with self.lock:
            self._expire()
            row = self.previews.get(ref)
            check(row is not None, "ai_consent_missing")
            check(self.configuration() == row["configuration"], "ai_setup_stale")

            def approve_current():
                row.update(approved=True)
                try:
                    self.current(ref, 0).prepare()
                except Exception:
                    row.update(approved=False)
                    raise

            # Consent is not session enablement, enqueue or dispatch.
            self.jobs.change_authority(approve_current)

    def enqueue(self, ref):
        with self.lock:
            self.current(ref, 0).prepare()
            job = self.jobs.enqueue(ref, request_key=ref, budget=self.budget(self.configuration()))
            self.previews[ref]["job"] = job["id"]
            return job

    def enable(self):
        with self.lock:
            config = self.configuration()
            check(config["mode"] != "off", "ai_off")
            profiles, _, configs, _ = self.profiles(config)
            self.jobs.adapters = {
                p.fingerprint: (
                    NativeJobAdapter(self.runtime, self.models)
                    if isinstance(configs[p.id], NativeConfig)
                    else ProviderJobAdapter(ChatJsonAdapter(credentials=self.credentials))
                )
                for p in profiles
            }
            return self.jobs.configure(mode="enabled", budget=self.budget(config))

    def control(self, action, revision):
        with self.lock:
            check(self.configuration()["revision"] == revision, "ai_setup_stale")
            if action == "enable":
                return self.enable()
            check(action in {"paused", "off"}, "ai_setup_invalid")
            return self.jobs.configure(mode=action)

    def close(self):
        self.cancel.set()
        if self.jobs.session_authorized:
            self.jobs.configure(mode="off")
        self.runtime.close()
        self.previews.clear()

    def read(self):
        # Registry/control reads only. ModelStore.status verifies gigabytes and must
        # not be called by page rendering/polling. Only an explicit operation does it.
        with self.lock:
            return {
                "configuration": self.configuration(),
                "control": self.jobs.status(),
                "registry": self.models.registry.inventory(),
                "operation": dict(self.operation) if self.operation else None,
                "self_test": self.self_test_evidence.public_record()
                if self.self_test_evidence
                else None,
                "locality_verified": self.local_evidence is not None,
                "observed_model": self.observed_model,
                "model_actions": self.model_actions(),
            }

    def model_actions(self):
        entry = self.models.registry.entry(MODEL_ID)
        installed = self.models._path(entry).is_file()
        state = self.models._state()
        actions = ["runtime", "verify", "recover"]
        if state["active"] != MODEL_ID:
            actions += ["install", "import"]
            if installed:
                actions += ["remove"]
        if installed:
            actions += ["self_test"]
        if self.local_evidence is not None and self.self_test_evidence is not None:
            actions += ["activate"]
        if state["active"] is not None:
            actions += ["deactivate"]
        if state["previous"] is not None and self.local_evidence is not None:
            actions += ["rollback"]
        return actions

    def begin_operation(self, action):
        with self.lock:
            check(self.operation is None or self.operation["state"] != "running", "ai_setup_busy")
            check(action in self.model_actions(), "ai_setup_invalid")
            self.cancel = threading.Event()
            self.operation = {
                "id": secrets.token_hex(16),
                "action": action,
                "state": "running",
                "bytes": 0,
                "error": None,
                "cancel_requested": False,
            }
            return self.operation["id"]

    def cancel_operation(self, identity):
        with self.lock:
            check(
                self.operation is not None
                and self.operation["id"] == identity
                and self.operation["state"] == "running",
                "ai_setup_stale",
            )
            self.operation["cancel_requested"] = True
            self.cancel.set()

    def run_operation(self, identity, *, path=None):
        with self.lock:
            check(self.operation is not None and self.operation["id"] == identity)
            operation = self.operation
        action, selection = operation["action"], native_selection()
        try:
            if action in {"self_test", "activate", "rollback"}:
                self.runtime.validate_installation()
            if action == "runtime":
                check(path is not None, "ai_setup_invalid")
                candidate = LocalRuntime(Path(path))
                candidate.validate_installation()
                self.jobs.configure(mode="off")
                self.runtime.close()
                self.runtime = candidate
                self.local_evidence = None
                self.self_test_evidence = None
            elif action == "install":
                host = self

                class Progress:
                    def fetch(self, entry, **kwargs):
                        for chunk in ArtifactDownload().fetch(entry, **kwargs):
                            with host.lock:
                                operation["bytes"] += len(chunk)
                            yield chunk

                self.models.install(
                    MODEL_ID,
                    selection,
                    requested=True,
                    license_accepted=self.models.registry.entry(MODEL_ID).license,
                    cancel=self.cancel.is_set,
                    transport=Progress(),
                )
            elif action == "import":
                check(path is not None, "ai_setup_invalid")
                self.models.import_offline(
                    MODEL_ID,
                    Path(path),
                    selection,
                    requested=True,
                    license_accepted=self.models.registry.entry(MODEL_ID).license,
                    cancel=self.cancel.is_set,
                )
            elif action == "verify":
                self.models.verify(MODEL_ID, selection)
                self.observed_model = "verified_bytes"
            elif action == "self_test":
                self.self_test_evidence = None
                self.local_evidence = None
                evidence = self.models.self_test(
                    MODEL_ID, selection, self.runtime, requested=True, cancel=self.cancel.is_set
                )
                self.self_test_evidence = evidence
                observation = self.runtime.last_observation or {}
                proof = observation.get("load", {}).get("limits", {})
                if (
                    evidence.result == "PASSED"
                    and proof.get("network_control") == "seccomp:socket-syscalls-EPERM"
                ):
                    self.local_evidence = digest(proof)
            elif action == "activate":
                check(self.local_evidence is not None, "ai_locality_unqualified")
                self.models.activate(MODEL_ID, selection, self.self_test_evidence, requested=True)
            elif action == "deactivate":
                self.jobs.configure(mode="off")
                self.runtime.close()
                self.models.deactivate(requested=True)
                self.self_test_evidence = None
                self.local_evidence = None
            elif action == "remove":
                self.models.remove(MODEL_ID, requested=True)
                self.observed_model = "missing"
                self.self_test_evidence = None
                self.local_evidence = None
            elif action == "recover":
                self.models.recover(requested=True)
                self.self_test_evidence = None
                self.local_evidence = None
            elif action == "rollback":
                check(self.local_evidence is not None, "ai_locality_unqualified")
                self.models.rollback(selection, self.runtime, requested=True)
            with self.lock:
                operation["state"] = "completed"
        except Exception as exc:
            with self.lock:
                operation["state"] = "cancelled" if self.cancel.is_set() else "failed"
                # Closed error vocabulary only; arbitrary paths/exception text are private.
                operation["error"] = exc.code if isinstance(exc, ModelError) else "unavailable"

    def payload(self, prepared):
        return task_payload(prepared[0], prepared[2]["template"]).decode()

    def document_preview(self, document_id, *, representation_id, output_id, anchor_id, start, end):
        """Private explicit read of one exact, existing representation selection.

        It deliberately returns no executable CallInputs or reusable consent ref.
        S07 has no product document task. The manifest scopes this preview to
        the selected admitted representation; it does not claim Original coverage.
        """
        from .representations import safe_instance_path

        document = self.instance.get_document(document_id)
        check(
            document is not None and document["current_version"] is not None, "ai_context_mismatch"
        )
        bundle = self.instance.representations.bundles.get(representation_id, deep=False)
        check(
            bundle is not None and bundle["version"]["id"] == document["current_version"]["id"],
            "ai_context_mismatch",
        )
        output = next((o for o in bundle["outputs"] if o["id"] == output_id), None)
        check(
            output is not None
            and output["media_type"] == "text/plain"
            and output["size_bytes"] <= 1024 * 1024,
            "ai_context_mismatch",
        )
        with open_local_file(
            safe_instance_path(self.instance.root, output["storage_ref"])
        ) as stream:
            raw = stream.read(1024 * 1024 + 1)
        version = VersionIdentity(
            self.instance_id,
            document_id,
            bundle["version"]["id"],
            bundle["version"]["original_id"],
            bundle["version"]["original_sha256"],
            bundle["version"]["original_size_bytes"],
        )
        source = SourceSnapshot(
            version,
            (canonical_json_bytes(bundle),),
            (OutputBytes(representation_id, output_id, raw),),
        )
        selection = Selection(
            version, representation_id, digest(bundle), output_id, anchor_id, start, end
        )
        governance = self.document_governance(document)
        prepared = self.prepare(
            secrets.token_hex(32),
            source,
            (selection,),
            configuration=self.configuration(),
            governance=governance,
        )
        return prepared, document

    def document_choices(self, document_id):
        document = self.instance.get_document(document_id)
        check(document is not None and document["current_version"] is not None)
        store = self.instance.representations.bundles
        choices = []
        # Metadata only, bounded scan. No output read, model load or endpoint probe.
        for index, path in enumerate(sorted(store.root.glob("repr_*/bundle.json"))):
            check(index < 500, "ai_limit_exceeded")
            bundle = store.get(path.parent.name, deep=False)
            if bundle is None or bundle["version"]["id"] != document["current_version"]["id"]:
                continue
            for output in bundle["outputs"]:
                if output["media_type"] != "text/plain" or output["size_bytes"] > 1024 * 1024:
                    continue
                for anchor in bundle["anchors"]:
                    if anchor["kind"] == "page":
                        choices.append((bundle["representation_id"], output["id"], anchor["id"]))
        return document, choices

    def document_governance(self, document):
        # Include every duplicate acquisition and every ancestor of all associated
        # Area/Project nodes. No browser-provided subset controls this inventory.
        store = self.instance.store
        version = document["current_version"]
        acquisitions = [
            a
            for a in store.list_canonical("acquisitions")
            if a.get("document_id") == document["id"]
            or a.get("content_hash") == version["content_hash"]
        ]
        sources = {document["source_id"], *(a["source_id"] for a in acquisitions)}
        related_ids = {document["id"], *(a["document_id"] for a in acquisitions)}
        nodes = {n["id"]: n for n in store.list_canonical("hierarchy")}
        classes = [
            c for c in store.list_canonical("classifications") if c["document_id"] in related_ids
        ]
        selected = set()
        for classification in classes:
            for node in (classification["primary_node_id"], *classification["secondary_node_ids"]):
                visited = set()
                while node:
                    check(node in nodes and node not in visited, "ai_missing_policy")
                    visited.add(node)
                    selected.add(node)
                    node = nodes[node]["parent_id"]
        scopes = [ScopeRef(Scope.INSTANCE, self.instance_id)]
        scopes.extend(ScopeRef(Scope.SOURCE, s) for s in sorted(sources))
        scopes.append(ScopeRef(Scope.CATEGORY, "media_" + digest(document["media_type"])))
        scopes.extend(
            ScopeRef(Scope(nodes[n]["kind"]), n)
            for n in sorted(selected)
            if nodes[n]["kind"] in {"area", "project"}
        )
        facts = {
            "document": document,
            "acquisitions": acquisitions,
            "sources": [store.read_canonical("sources", s) for s in sorted(sources)],
            "classifications": classes,
            "ancestors": [nodes[n] for n in sorted(selected)],
        }
        check(all(facts["sources"]), "ai_missing_policy")
        return tuple(scopes), digest(facts)
