"""Independent mirror policies, immutable previews and one-dispatch authority.

This shared layer performs no remote access. Each real transport/profile must
independently prove its observation, activation and final-manifest contract.
"""

from __future__ import annotations

import platform
import re
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .google_credentials import GoogleCredentialVault
from .instance_lifecycle import lifecycle_guard, lifecycle_writer
from .locks import InstanceLockManager
from .mirror_contract import (
    HASH,
    MAX_DESTINATIONS,
    MAX_PLANS,
    PLAN_SECONDS,
    PROFILES,
    destination_observation,
    diff,
    fingerprint,
    identifier,
    includes,
    inventory,
    label,
    parse,
    raw,
    require,
    selection,
)
from .mirror_snapshot import MirrorSnapshots
from .review_decisions import checked_path, read_bytes
from .storage import utc_now


@lifecycle_writer("mirror-contract")
def _joined_preview(store, engine, destination_id, observation, **arguments):
    # Join only the current thread's live kernel ownership, including scheduler execution.
    with InstanceLockManager(store).hold("mirrors", purpose="one-way mirror contract"):
        return engine._preview_locked(destination_id, observation, **arguments)


class Mirrors:
    def __init__(self, store, *, vault=None):
        self.store = store
        self.vault = (
            vault
            if vault is not None
            else GoogleCredentialVault(namespace="mirror", forbidden_root=store.paths.root)
        )
        self.snapshots = MirrorSnapshots(store)

    @contextmanager
    def guard(self):
        with (
            lifecycle_guard(self.store, purpose="mirror-contract"),
            InstanceLockManager(self.store).hold("mirrors", purpose="one-way mirror contract"),
        ):
            yield

    def device(self):
        return fingerprint(
            [
                self.store.read_config()["instance"]["id"],
                str(self.store.paths.root.resolve()),
                platform.node(),
            ]
        )

    def slot(self, identity):
        identifier(identity, "mirid")
        return "mirror_" + self.device()[:32] + "_" + identity

    def operation_slot(self, destination_id):
        identifier(destination_id, "mirdst")
        return "mirror_" + self.device()[:32] + "_" + destination_id + "_operations"

    def operation_ledger(self, destination_id, *, epoch=None):
        value = self.vault.read(self.operation_slot(destination_id))
        require(
            type(value) is dict
            and set(value)
            in (
                {
                    "schema",
                    "destination_id",
                    "identity_id",
                    "epoch",
                    "destination_sha256",
                    "serial",
                    "inflight",
                    "last_receipt",
                },
                {
                    "schema",
                    "destination_id",
                    "identity_id",
                    "epoch",
                    "destination_sha256",
                    "serial",
                    "inflight",
                    "last_receipt",
                    "schedule_fence",
                },
            ),
            "authorization_required",
        )
        require(
            value["schema"] == "provelume-mirror-operation-ledger/v1"
            and value["destination_id"] == destination_id
            and type(value["serial"]) is int
            and 0 <= value["serial"] < 2**63,
            "authorization_required",
        )
        identifier(value["identity_id"], "mirid")
        require(
            type(value["epoch"]) is str
            and HASH.fullmatch(value["epoch"])
            and type(value["destination_sha256"]) is str
            and HASH.fullmatch(value["destination_sha256"]),
            "authorization_required",
        )
        require(epoch is None or value["epoch"] == epoch, "authorization_required")
        if "schedule_fence" in value:
            require(
                type(value["schedule_fence"]) is str and HASH.fullmatch(value["schedule_fence"]),
                "integrity",
            )
        pending = value["inflight"]
        if pending is not None:
            require(
                type(pending) is dict
                and set(pending) == {"operation_id", "generation", "serial", "plan_sha256"},
                "integrity",
            )
            identifier(pending["operation_id"], "mirplan")
            require(
                type(pending["serial"]) is int
                and pending["serial"] == value["serial"]
                and type(pending["generation"]) is str
                and HASH.fullmatch(pending["generation"])
                and type(pending["plan_sha256"]) is str
                and HASH.fullmatch(pending["plan_sha256"]),
                "integrity",
            )
        terminal = value["last_receipt"]
        require(
            terminal is None
            or (
                type(terminal) is dict
                and terminal.get("schema")
                in {"provelume-mirror-receipt/v1", "provelume-mirror-not-applied/v1"}
                and type(terminal.get("operation_serial")) is int
                and 1 <= terminal["operation_serial"] <= value["serial"]
            ),
            "integrity",
        )
        require(len(raw(value)) <= 8192, "limit")
        return value

    def save_operation_ledger(self, value):
        slot = self.operation_slot(value["destination_id"])
        self.vault.write(slot, value)
        require(self.vault.read(slot) == value, "outcome_unknown")

    def _load(self, relative):
        data = read_bytes(self.store, "state/mirrors/" + relative)
        return None if data is None else parse(data)

    def _save(self, relative, value):
        raw(value)
        self.store._atomic_json(checked_path(self.store, "state/mirrors/" + relative), value)

    def access(self):
        value = self._load("access.json")
        if value is None:
            return {
                "revision": 0,
                "enabled": False,
                "github": False,
                "rsync": False,
                "device": self.device(),
            }
        require(set(value) == {"revision", "enabled", "github", "rsync", "device"})
        require(
            type(value["revision"]) is int
            and value["revision"] >= 1
            and all(type(value[key]) is bool for key in ("enabled", "github", "rsync"))
            and type(value["device"]) is str
            and HASH.fullmatch(value["device"])
        )
        if value["device"] != self.device():
            return {**value, "enabled": False, "github": False, "rsync": False}
        return value

    def set_access(self, *, enabled, github, rsync, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        require(type(expected_revision) is int and 0 <= expected_revision < 2**31, "stale")
        require(all(type(item) is bool for item in (enabled, github, rsync)))
        with self.guard():
            require(self.access()["revision"] == expected_revision, "stale")
            value = {
                "revision": expected_revision + 1,
                "enabled": enabled,
                "github": github,
                "rsync": rsync,
                "device": self.device(),
            }
            self._save("access.json", value)
            return deepcopy(value)

    def state(self):
        value = self._load("policies.json")
        if value is None:
            return {"schema": "provelume-mirrors/v1", "identities": [], "destinations": []}
        require(
            set(value) == {"schema", "identities", "destinations"}
            and value["schema"] == "provelume-mirrors/v1"
        )
        require(
            type(value["identities"]) is list
            and len(value["identities"]) <= MAX_DESTINATIONS
            and type(value["destinations"]) is list
            and len(value["destinations"]) <= MAX_DESTINATIONS,
            "limit",
        )
        identities, destinations = [], []
        for row in value["identities"]:
            require(
                type(row) is dict and set(row) == {"id", "name", "profile", "revision", "epoch"}
            )
            identities.append(identifier(row["id"], "mirid"))
            label(row["name"])
            require(
                row["profile"] in PROFILES
                and type(row["revision"]) is int
                and row["revision"] >= 1
                and HASH.fullmatch(row["epoch"])
            )
        for row in value["destinations"]:
            self._validate_destination(row)
            require(row["identity_id"] in identities)
            destinations.append(row["id"])
        require(
            len(set(identities)) == len(identities) and len(set(destinations)) == len(destinations)
        )
        return value

    @staticmethod
    def _validate_destination(row):
        require(
            type(row) is dict
            and set(row)
            == {
                "id",
                "identity_id",
                "name",
                "destination_sha256",
                "scope",
                "include_rules",
                "mode",
                "interval_seconds",
                "finding_policy",
                "public_allowlist",
                "revision",
                "device",
                "updated_at",
            }
        )
        identifier(row["id"], "mirdst")
        identifier(row["identity_id"], "mirid")
        label(row["name"])
        for key in ("destination_sha256", "device"):
            require(type(row[key]) is str and HASH.fullmatch(row[key]))
        selection(row["scope"])
        includes(row["include_rules"])
        require(row["mode"] in {"disabled", "manual", "scheduled"})
        require(row["finding_policy"] in {"block", "confirm_sensitive"})
        require(type(row["revision"]) is int and row["revision"] >= 1)
        interval = row["interval_seconds"]
        require(
            (row["mode"] == "scheduled" and type(interval) is int and 60 <= interval <= 604800)
            or (row["mode"] != "scheduled" and interval is None)
        )
        inventory(row["public_allowlist"])
        require(type(row["updated_at"]) is str)

    def identity(self, identity_id, *, state=None):
        identifier(identity_id, "mirid")
        rows = [row for row in (state or self.state())["identities"] if row["id"] == identity_id]
        require(len(rows) == 1, "identity")
        return rows[0]

    def destination(self, destination_id, *, state=None):
        identifier(destination_id, "mirdst")
        rows = [
            row for row in (state or self.state())["destinations"] if row["id"] == destination_id
        ]
        require(len(rows) == 1, "destination")
        return rows[0]

    def create_identity(self, *, name, profile, credential, confirmed):
        require(confirmed is True, "consent_required")
        label(name)
        require(profile in PROFILES and type(credential) is dict)
        require(
            set(credential) == {"reference"}
            and type(credential["reference"]) is str
            and len(credential["reference"]) <= 4096
        )
        with self.guard():
            state = self.state()
            require(len(state["identities"]) < MAX_DESTINATIONS, "limit")
            identity = {
                "id": "mirid_" + uuid4().hex,
                "name": name,
                "profile": profile,
                "revision": 1,
                "epoch": fingerprint([uuid4().hex]),
            }
            # No credential/reference/slot is persisted in canonical or portable policy records.
            self.vault.write(
                self.slot(identity["id"]),
                {
                    "epoch": identity["epoch"],
                    "credential": deepcopy(credential),
                    "destinations": {},
                },
            )
            state["identities"].append(identity)
            self._save("policies.json", state)
            return deepcopy(identity)

    def _grant(self, identity):
        grant = self.vault.read(self.slot(identity["id"]))
        require(
            type(grant) is dict
            and set(grant) == {"epoch", "credential", "destinations"}
            and grant["epoch"] == identity["epoch"],
            "authorization_required",
        )
        return grant

    def configure(
        self,
        *,
        identity_id,
        name,
        target,
        scope,
        include_rules,
        mode="disabled",
        interval_seconds=None,
        finding_policy="block",
        public_allowlist=None,
        destination_id=None,
        expected_revision=0,
        confirmed=False,
    ):
        require(confirmed is True, "consent_required")
        label(name)
        # Transport-specific target syntax is checked by its own later owner.
        require(type(target) is dict and 0 < len(target) <= 16)
        require(
            all(type(key) is str and type(item) in {str, int, bool} for key, item in target.items())
        )
        require(len(raw(target)) <= 4096, "limit")
        with self.guard():
            state = self.state()
            identity = self.identity(identity_id, state=state)
            grant = self._grant(identity)
            if destination_id is None:
                require(
                    expected_revision == 0 and len(state["destinations"]) < MAX_DESTINATIONS,
                    "stale",
                )
                destination_id = "mirdst_" + uuid4().hex
                previous = None
            else:
                previous = self.destination(destination_id, state=state)
                require(
                    previous["identity_id"] == identity_id
                    and previous["revision"] == expected_revision,
                    "stale",
                )
            row = {
                "id": destination_id,
                "identity_id": identity_id,
                "name": name,
                "destination_sha256": fingerprint([identity["profile"], target]),
                "scope": deepcopy(scope),
                "include_rules": deepcopy(include_rules),
                "mode": mode,
                "interval_seconds": interval_seconds,
                "finding_policy": finding_policy,
                "public_allowlist": public_allowlist or [],
                "revision": expected_revision + 1,
                "device": self.device(),
                "updated_at": utc_now(),
            }
            self._validate_destination(row)
            if previous is None:
                operations = {
                    "schema": "provelume-mirror-operation-ledger/v1",
                    "destination_id": destination_id,
                    "identity_id": identity_id,
                    "epoch": identity["epoch"],
                    "destination_sha256": row["destination_sha256"],
                    "serial": 0,
                    "inflight": None,
                    "last_receipt": None,
                }
            else:
                operations = self.operation_ledger(destination_id, epoch=identity["epoch"])
                require(
                    operations["inflight"] is None
                    or operations["destination_sha256"] == row["destination_sha256"],
                    "outcome_unknown",
                )
                operations["destination_sha256"] = row["destination_sha256"]
            # External immutable destination revision precedes the active local policy pointer.
            grant["destinations"][destination_id] = {
                "revision": row["revision"],
                "destination_sha256": row["destination_sha256"],
                "target": deepcopy(target),
            }
            self.vault.write(self.slot(identity_id), grant)
            self.save_operation_ledger(operations)
            if previous is not None:
                state["destinations"].remove(previous)
            state["destinations"].append(row)
            self._save("policies.json", state)
            return deepcopy(row)

    def authority(self, destination_id, *, scheduled=False, _inspection_operation=None):
        access = self.access()
        require(access["enabled"], "local_only")
        row = self.destination(destination_id)
        require(row["device"] == self.device(), "authorization_required")
        require(row["mode"] != "disabled", "disabled")
        require(not scheduled or row["mode"] == "scheduled", "disabled")
        identity = self.identity(row["identity_id"])
        require(identity["profile"] != "github" or access["github"], "github_disabled")
        require(identity["profile"] != "rsync-ssh" or access["rsync"], "rsync_disabled")
        grant = self._grant(identity)
        target = grant["destinations"].get(destination_id)
        require(
            type(target) is dict
            and target.get("revision") == row["revision"]
            and target.get("destination_sha256") == row["destination_sha256"],
            "stale",
        )
        require(
            fingerprint([identity["profile"], target["target"]]) == row["destination_sha256"],
            "stale",
        )
        operations = self.operation_ledger(destination_id, epoch=identity["epoch"])
        require(
            operations["identity_id"] == identity["id"]
            and operations["destination_sha256"] == row["destination_sha256"],
            "stale",
        )
        if _inspection_operation is None:
            require(operations["inflight"] is None, "outcome_unknown")
        else:
            # Read-only transport reconciliation cannot grant another dispatch.
            pending = operations["inflight"]
            require(
                pending is not None and pending["operation_id"] == _inspection_operation,
                "outcome_unknown",
            )
        require(
            not scheduled or operations.get("schedule_fence") != fingerprint(row), "outcome_unknown"
        )
        return row, {
            "identity": identity,
            "grant_epoch": grant["epoch"],
            "device": self.device(),
            "policy_sha256": fingerprint(row),
            "access_sha256": fingerprint(access),
            "operation_serial": operations["serial"],
        }

    def preview(
        self, destination_id, observation, *, expected_revision, scheduled=False, _deadline=None
    ):
        return _joined_preview(
            self.store,
            self,
            destination_id,
            observation,
            expected_revision=expected_revision,
            scheduled=scheduled,
            _deadline=_deadline,
        )

    def _preview_locked(
        self, destination_id, observation, *, expected_revision, scheduled=False, _deadline=None
    ):
        destination_observation(observation)
        row, authority = self.authority(destination_id, scheduled=scheduled)
        require(row["revision"] == expected_revision, "stale")
        require(observation["destination_sha256"] == row["destination_sha256"], "destination")
        generation, manifest = self.snapshots.build_locked(
            row["scope"], row["include_rules"], deadline=_deadline
        )
        now = datetime.now(UTC)
        existing = self.plans()
        for previous in existing:
            if (
                previous["state"] == "prepared"
                and previous["authority"] == authority
                and previous["generation"] == generation
                and previous["observation"] == observation
                and previous["scheduled"] == scheduled
                and datetime.fromisoformat(previous["expires_at"]) >= now
            ):
                return {
                    **deepcopy(previous),
                    "plan_sha256": fingerprint(previous),
                    "manifest": manifest,
                    "publication": "TRANSPORT_NOT_QUALIFIED",
                }
        require(len(existing) < MAX_PLANS, "plan_limit")
        plan = {
            "schema": "provelume-mirror-plan/v1",
            "id": "mirplan_" + uuid4().hex,
            "destination_id": destination_id,
            "authority": authority,
            "generation": generation,
            "observation": deepcopy(observation),
            "diff": diff(manifest["inventory"], observation["inventory"]),
            "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=PLAN_SECONDS)).isoformat(),
            "state": "prepared",
            "scheduled": scheduled,
        }
        self._save("plans/" + plan["id"] + ".json", plan)
        return {
            **deepcopy(plan),
            "plan_sha256": fingerprint(plan),
            "manifest": manifest,
            "publication": "TRANSPORT_NOT_QUALIFIED",
        }

    def plans(self):
        directory = checked_path(self.store, "state/mirrors/plans")
        if not directory.exists():
            return []
        values = []
        for item in directory.iterdir():
            require(len(values) < MAX_PLANS, "plan_limit")
            identifier(item.stem, "mirplan")
            require(item.suffix == ".json")
            values.append(self._load("plans/" + item.name))
        return values

    def plan(self, plan_id):
        identifier(plan_id, "mirplan")
        value = self._load("plans/" + plan_id + ".json")
        require(
            value is not None
            and set(value)
            == {
                "schema",
                "id",
                "destination_id",
                "authority",
                "generation",
                "observation",
                "diff",
                "created_at",
                "expires_at",
                "state",
                "scheduled",
            }
            and value["schema"] == "provelume-mirror-plan/v1"
            and value["id"] == plan_id
        )
        require(
            value["state"]
            in {"prepared", "dispatched", "completed", "unknown", "discarded", "not_applied"}
        )
        destination_observation(value["observation"])
        return value

    def validate_preview_locked(
        self, plan_id, *, expected_plan_sha256, observation, confirmed, public_confirmed=False
    ):
        require(confirmed is True, "consent_required")
        plan = self.plan(plan_id)
        require(plan["state"] == "prepared" and fingerprint(plan) == expected_plan_sha256, "stale")
        require(datetime.now(UTC) <= datetime.fromisoformat(plan["expires_at"]), "expired")
        row, authority = self.authority(plan["destination_id"], scheduled=plan["scheduled"])
        require(authority == plan["authority"], "stale")
        destination_observation(observation)
        require(
            observation == plan["observation"] and observation["writable"], "destination_changed"
        )
        generation, manifest = self.snapshots.build_locked(row["scope"], row["include_rules"])
        require(generation == plan["generation"], "source_changed")
        codes = {finding["code"] for finding in manifest["findings"]}
        require("secret_pattern" not in codes, "secret_pattern")
        require(not codes or row["finding_policy"] == "confirm_sensitive", "sensitive_pattern")
        require(observation["visibility"] != "unknown", "visibility_unknown")
        if observation["visibility"] == "public":
            require(
                public_confirmed is True and row["public_allowlist"] == manifest["inventory"],
                "public_consent_required",
            )
        return plan, manifest

    def dispatch(self, plan_id, **_arguments):
        # S16 cannot turn a caller-supplied visibility string or adapter into authority.
        identifier(plan_id, "mirplan")
        require(False, "transport_not_qualified")

    def _claim_locked(self, plan_id, **arguments):
        """For independently qualified transports only; caller holds guard through claim."""
        plan, manifest = self.validate_preview_locked(plan_id, **arguments)
        operations = self.operation_ledger(
            plan["destination_id"], epoch=plan["authority"]["grant_epoch"]
        )
        require(
            operations["serial"] == plan["authority"]["operation_serial"]
            and operations["inflight"] is None,
            "stale",
        )
        require(operations["serial"] < 2**63 - 1, "limit")
        operations["serial"] += 1
        operations["inflight"] = {
            "operation_id": plan_id,
            "generation": plan["generation"],
            "serial": operations["serial"],
            "plan_sha256": fingerprint(plan),
        }
        # This durable claim is outside every Instance backup/restore. Even a
        # crash before the local journal write consumes this plan permanently.
        self.save_operation_ledger(operations)
        plan["state"] = "dispatched"
        self._save("plans/" + plan_id + ".json", plan)
        return deepcopy(plan), manifest

    def _complete_locked(self, plan_id, *, operation_id, observation, transport_proof=None):
        """Transport supplies read-only operation proof and independently reread final inventory."""
        plan = self.plan(plan_id)
        require(
            operation_id == plan_id
            and plan["state"] in {"prepared", "dispatched", "unknown", "completed"},
            "stale",
        )
        destination_observation(observation)
        if transport_proof is not None:
            require(type(transport_proof) is dict)
            provider = transport_proof.get("provider_observation")
            hosted = transport_proof.get("profile") in {
                "github.com/2022-11-28",
                "gitlab.com/v4/classic-pat",
                "gitea/28.3.0/v1/current-token",
            }
            require(
                type(transport_proof) is dict
                and set(transport_proof)
                == (
                    {
                        "profile",
                        "commit_sha",
                        "observed_head",
                        "commit_written",
                        "git_version",
                        "evidence_mode",
                        "publication_time",
                    }
                    | ({"provider_observation"} if hosted else set())
                )
            )
            require(
                transport_proof["profile"]
                in {
                    "git-local/v1",
                    "github.com/2022-11-28",
                    "gitlab.com/v4/classic-pat",
                    "gitea/28.3.0/v1/current-token",
                }
                and type(transport_proof["commit_written"]) is bool
                and type(transport_proof["git_version"]) is str
                and len(transport_proof["git_version"]) <= 40
                and transport_proof["evidence_mode"]
                in {"direct_verified", "reconciled_current_state"}
                and transport_proof["publication_time"] is None
            )
            if hosted:
                require(
                    type(provider) is dict
                    and set(provider) == {"repository_id", "access_sha256", "visibility"}
                    and type(provider["repository_id"]) is int
                    and provider["repository_id"] > 0
                    and type(provider["access_sha256"]) is str
                    and HASH.fullmatch(provider["access_sha256"])
                    and provider["visibility"] == observation["visibility"]
                    and provider["visibility"] in {"private", "public"}
                )
            for key in ("commit_sha", "observed_head"):
                require(
                    type(transport_proof[key]) is str
                    and re.fullmatch(r"[0-9a-f]{40}", transport_proof[key])
                )
        manifest = self.snapshots.verify(plan["generation"])
        require(
            observation["destination_sha256"] == plan["observation"]["destination_sha256"]
            and observation["visibility"] == plan["observation"]["visibility"]
            and observation["inventory"] == manifest["inventory"],
            "destination_incomplete",
        )
        operations = self.operation_ledger(
            plan["destination_id"], epoch=plan["authority"]["grant_epoch"]
        )
        receipt = operations["last_receipt"]
        if receipt is not None and receipt["operation_id"] == plan_id:
            require(receipt["schema"] == "provelume-mirror-receipt/v1", "stale")
        if receipt is None or receipt["operation_id"] != plan_id:
            original = {**plan, "state": "prepared"}
            pending = operations["inflight"]
            require(
                pending is not None
                and pending["operation_id"] == plan_id
                and pending["generation"] == plan["generation"]
                and pending["plan_sha256"] == fingerprint(original),
                "stale",
            )
            receipt = {
                "schema": "provelume-mirror-receipt/v1",
                "operation_id": plan_id,
                "operation_serial": pending["serial"],
                "destination_sha256": observation["destination_sha256"],
                "generation": plan["generation"],
                "source_manifest_sha256": fingerprint(manifest["inventory"]),
                "destination_manifest_sha256": fingerprint(observation["inventory"]),
                "destination_revision_sha256": fingerprint(observation["revision"]),
                "files": len(manifest["inventory"]),
                "bytes": manifest["total_bytes"],
                "completed_at": utc_now(),
                "canonical_mutation": False,
                "destination_deletion": False,
                "backup_proof": False,
            }
            if transport_proof is not None:
                receipt["transport_proof"] = deepcopy(transport_proof)
            operations["inflight"] = None
            operations["last_receipt"] = receipt
            self.save_operation_ledger(operations)
        require(
            receipt["generation"] == plan["generation"]
            and receipt["destination_manifest_sha256"] == fingerprint(observation["inventory"]),
            "integrity",
        )
        # External terminal evidence is authoritative after same-root rollback;
        # restoring an older local receipt can never reopen its consumed serial.
        self._save("receipts/" + plan_id + ".json", receipt)
        plan["state"] = "completed"
        self._save("plans/" + plan_id + ".json", plan)
        return deepcopy(receipt)

    def _unknown_locked(self, plan_id):
        plan = self.plan(plan_id)
        require(plan["state"] in {"dispatched", "unknown"}, "stale")
        plan["state"] = "unknown"
        self._save("plans/" + plan_id + ".json", plan)

    def _not_applied_locked(self, plan_id, *, reason, proof_sha256):
        """A qualified transport supplies a definitive rejection, never a timeout inference."""
        require(reason in {"conflict", "credentials", "denied"})
        require(type(proof_sha256) is str and HASH.fullmatch(proof_sha256))
        plan = self.plan(plan_id)
        require(plan["state"] in {"prepared", "dispatched", "unknown", "not_applied"}, "stale")
        operations = self.operation_ledger(
            plan["destination_id"], epoch=plan["authority"]["grant_epoch"]
        )
        receipt = operations["last_receipt"]
        if receipt is None or receipt["operation_id"] != plan_id:
            pending = operations["inflight"]
            require(
                pending is not None
                and pending["operation_id"] == plan_id
                and pending["generation"] == plan["generation"]
                and pending["plan_sha256"] == fingerprint({**plan, "state": "prepared"}),
                "stale",
            )
            receipt = {
                "schema": "provelume-mirror-not-applied/v1",
                "operation_id": plan_id,
                "operation_serial": pending["serial"],
                "generation": plan["generation"],
                "destination_sha256": plan["observation"]["destination_sha256"],
                "reason": reason,
                "proof_sha256": proof_sha256,
                "completed_at": utc_now(),
                "canonical_mutation": False,
                "destination_deletion": False,
                "backup_proof": False,
            }
            operations["inflight"] = None
            if plan["scheduled"]:
                operations["schedule_fence"] = plan["authority"]["policy_sha256"]
            operations["last_receipt"] = receipt
            self.save_operation_ledger(operations)
        require(receipt["schema"] == "provelume-mirror-not-applied/v1", "stale")
        self._save("receipts/" + plan_id + ".json", receipt)
        plan["state"] = "not_applied"
        self._save("plans/" + plan_id + ".json", plan)
        return deepcopy(receipt)

    def _pause_scheduled(self, destination_id, *, expected_policy_sha256):
        """External fail-stop survives Instance backup/restore; no dispatch authority."""
        with self.guard():
            row = self.destination(destination_id)
            require(fingerprint(row) == expected_policy_sha256, "stale")
            identity = self.identity(row["identity_id"])
            operations = self.operation_ledger(destination_id, epoch=identity["epoch"])
            operations["schedule_fence"] = expected_policy_sha256
            self.save_operation_ledger(operations)

    def _recover_terminal_locked(self, plan_id):
        """Recover an external historical receipt; this performs no destination observation."""
        plan = self.plan(plan_id)
        operations = self.operation_ledger(
            plan["destination_id"], epoch=plan["authority"]["grant_epoch"]
        )
        receipt = operations["last_receipt"]
        if receipt is None or receipt.get("operation_id") != plan_id:
            return None
        require(
            receipt.get("generation") == plan["generation"]
            and receipt.get("destination_sha256") == plan["observation"]["destination_sha256"],
            "integrity",
        )
        self._save("receipts/" + plan_id + ".json", receipt)
        plan["state"] = (
            "completed" if receipt["schema"] == "provelume-mirror-receipt/v1" else "not_applied"
        )
        self._save("plans/" + plan_id + ".json", plan)
        return deepcopy(receipt)

    def disable(self, destination_id, *, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        require(type(expected_revision) is int and 1 <= expected_revision < 2**31, "stale")
        with self.guard():
            state = self.state()
            row = self.destination(destination_id, state=state)
            require(row["revision"] == expected_revision, "stale")
            row.update(mode="disabled", interval_seconds=None, revision=row["revision"] + 1)
            self._save("policies.json", state)
            return deepcopy(row)

    def forget_plan(self, plan_id, *, confirmed):
        require(confirmed is True, "consent_required")
        with self.guard():
            plan = self.plan(plan_id)
            pending = self.operation_ledger(plan["destination_id"])["inflight"]
            require(pending is None or pending["operation_id"] != plan_id, "outcome_unknown")
            require(plan["state"] in {"completed", "discarded", "not_applied"}, "outcome_unknown")
            checked_path(self.store, "state/mirrors/plans/" + plan_id + ".json").unlink()
            return {"forgotten_local_plan": True, "receipt_retained": True, "remote_effect": False}

    def drop_generation(self, generation, *, confirmed):
        require(confirmed is True, "consent_required")
        with self.guard():
            for destination in self.state()["destinations"]:
                pending = self.operation_ledger(destination["id"])["inflight"]
                require(pending is None or pending["generation"] != generation, "in_use")
            require(
                not any(
                    plan["generation"] == generation
                    and plan["state"] not in {"completed", "discarded", "not_applied"}
                    for plan in self.plans()
                ),
                "in_use",
            )
            self.snapshots.drop_locked(generation)
            return {"local_staging_removed": True, "remote_effect": False}

    def discard(self, plan_id, *, expected_plan_sha256, confirmed):
        require(confirmed is True, "consent_required")
        with self.guard():
            plan = self.plan(plan_id)
            require(
                plan["state"] == "prepared" and fingerprint(plan) == expected_plan_sha256, "stale"
            )
            plan["state"] = "discarded"
            self._save("plans/" + plan_id + ".json", plan)
            return {"state": "discarded", "remote_effect": False}

    def revoke(self, identity_id, *, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        require(type(expected_revision) is int and 1 <= expected_revision < 2**31, "stale")
        with self.guard():
            state = self.state()
            identity = self.identity(identity_id, state=state)
            require(identity["revision"] == expected_revision, "stale")
            self.vault.delete(self.slot(identity_id))
            identity["revision"] += 1
            identity["epoch"] = fingerprint([uuid4().hex])
            for row in state["destinations"]:
                if row["identity_id"] == identity_id:
                    row.update(mode="disabled", interval_seconds=None, revision=row["revision"] + 1)
            self._save("policies.json", state)
            return {
                "identity_id": identity_id,
                "state": "revoked",
                "remote_effect": False,
                "knowledge_deleted": False,
            }

    def view(self):
        # Passive GET/status never opens the OS vault, scans content or contacts a destination.
        state = self.state()
        return {
            **deepcopy(state),
            "access": self.access(),
            "plans": self.plans(),
            "scheduled": {
                row["id"]: self._load("scheduled/" + row["id"] + ".json")
                for row in state["destinations"]
            },
            "transport_qualification": "NOT_RUN",
            "publication": "TRANSPORT_NOT_QUALIFIED",
            "destination_deletion": False,
            "network_used": False,
            "process_used": False,
        }
