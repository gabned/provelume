"""One-way bounded rsync/SSH publication with durable external one-attempt claims."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from .mirror_contract import fingerprint, require
from .mirror_rsync_credentials import RsyncCredentials
from .mirror_rsync_protocol import PROFILE, pointer
from .mirror_rsync_transport import RsyncTransport, native_work
from .mirror_ssh_runtime import configuration, window_open
from .mirrors import Mirrors
from .scheduler_model import utc_instant


def server_identity(value):
    return {
        key: value[key]
        for key in (
            "helper",
            "profile",
            "configuration_sha256",
            "namespace",
            "root_sha256",
            "marker",
            "filesystem_profile",
            "rsync",
        )
    }


class RsyncMirrors:
    def __init__(self, store, *, mirrors=None, credentials=None, transport_factory=None):
        self.store = store
        self.mirrors = mirrors or Mirrors(store)
        self.credentials = credentials or RsyncCredentials(self.mirrors)
        self.transport_factory = transport_factory or RsyncTransport

    def status(self):
        return {
            "profile": PROFILE,
            "network_used": False,
            "process_used": False,
            "credentials_read": False,
            "target_probed": False,
            "components": "OPTIONAL_NOT_PROBED",
            "live_qualification": "NOT_RUN",
        }

    def create_identity(self, *, name, confirmed):
        generated = self.credentials.generate(confirmed=confirmed)
        try:
            identity = self.mirrors.create_identity(
                name=name,
                profile="rsync-ssh",
                credential={"reference": generated["reference"]},
                confirmed=confirmed,
            )
        except Exception:
            self.credentials.revoke(generated["reference"], confirmed=True)
            raise
        return {key: value for key, value in generated.items() if key != "reference"} | {
            "identity": identity,
            "remote_authorization": "DEDICATED_FORCED_COMMAND_KEY_REQUIRED",
            "remote_installation": "NOT_RUN",
        }

    def disconnect(self, identity_id, *, expected_revision, confirmed):
        identity = self.mirrors.identity(identity_id)
        require(identity["profile"] == "rsync-ssh", "rsync_profile_not_qualified")
        reference = self.mirrors._grant(identity)["credential"]["reference"]
        self.mirrors.revoke(identity_id, expected_revision=expected_revision, confirmed=confirmed)
        return self.credentials.revoke(reference, confirmed=confirmed)

    def context(self, destination_id, *, scheduled=False, inspection_operation=None):
        row, authority = self.mirrors.authority(
            destination_id, scheduled=scheduled, _inspection_operation=inspection_operation
        )
        require(authority["identity"]["profile"] == "rsync-ssh", "rsync_profile_not_qualified")
        grant = self.mirrors._grant(authority["identity"])
        target = configuration(grant["destinations"][destination_id]["target"])
        return row, authority, target, grant["credential"]["reference"]

    def window(self, target):
        instant = datetime.now(UTC)
        require(window_open(target, instant), "rsync_window_closed")
        end = instant.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            minutes=target["window_end_minute_utc"]
        )
        return time.monotonic() + (end - instant).total_seconds()

    def transport(self, session, target, reference):
        # Admission of both optional native components precedes credential reads.
        for name in ("ssh", "rsync"):
            session.component(name)
        value = self.credentials.read(reference)
        return self.transport_factory(
            session,
            target,
            value,
            instance_id=self.store.read_config()["instance"]["id"],
            device=self.mirrors.device(),
        ), self.credentials.binding(value)

    def request(self, target, action, *, plan=None, rsync_plan=None):
        value = {
            "schema": "provelume-rsync-request/v1",
            "action": action,
            "namespace": target["namespace"],
            "configuration_sha256": target["configuration_sha256"],
        }
        if plan is not None:
            value.update({"operation_id": plan["id"], "transport_sha256": fingerprint(rsync_plan)})
            if action != "operation":
                value.update(
                    {
                        "manifest": self.mirrors.snapshots.verify(plan["generation"]),
                        "expected_pointer": rsync_plan["active_pointer"],
                        "bandwidth_kib": target["bandwidth_kib"],
                    }
                )
        return value

    @staticmethod
    def observation(row, remote):
        return {
            "destination_sha256": row["destination_sha256"],
            "visibility": "private",
            "writable": True,
            "inventory": remote["inventory"],
            "revision": fingerprint([server_identity(remote), remote["active_pointer"]]),
        }

    def initialize(self, destination_id, *, expected_destination_sha256, confirmed):
        require(confirmed is True, "consent_required")
        with self.mirrors.guard():
            row, _authority, target, reference = self.context(destination_id)
            require(row["destination_sha256"] == expected_destination_sha256, "stale")
            with native_work(deadline=self.window(target)) as session:
                transport, _binding = self.transport(session, target, reference)
                remote = transport.rpc(self.request(target, "initialize"))
                return {
                    "status": "initialized",
                    "destination_sha256": row["destination_sha256"],
                    "server": server_identity(remote),
                    "network_used": True,
                    "canonical_mutation": False,
                }

    def prepare(
        self, destination_id, *, expected_revision, confirmed, scheduled=False, _deadline=None
    ):
        require(confirmed is True, "consent_required")
        with self.mirrors.guard():
            row, authority, target, reference = self.context(destination_id, scheduled=scheduled)
            require(row["revision"] == expected_revision, "stale")
            with native_work(deadline=_deadline) as session:
                transport, binding = self.transport(session, target, reference)
                remote = transport.rpc(self.request(target, "inspect"))
                plan = self.mirrors._preview_locked(
                    destination_id,
                    self.observation(row, remote),
                    expected_revision=expected_revision,
                    scheduled=scheduled,
                    _deadline=session.deadline,
                )
                rsync_plan = {
                    "schema": "provelume-rsync-plan/v1",
                    "plan_id": plan["id"],
                    "original_plan_sha256": plan["plan_sha256"],
                    "server": server_identity(remote),
                    "active_pointer": remote["active_pointer"],
                    "credential_binding": binding,
                    "client_components": {
                        name: {key: component[key] for key in ("version", "sha256")}
                        for name, component in transport.components.items()
                    },
                    "target_storage": remote["storage"],
                }
                self.mirrors._save("rsync/plans/" + plan["id"] + ".json", rsync_plan)
                require(
                    self.mirrors.authority(destination_id, scheduled=scheduled)[1] == authority,
                    "stale",
                )
                return {
                    **plan,
                    "rsync_plan": rsync_plan,
                    "rsync_plan_sha256": fingerprint(rsync_plan),
                    "publication": "PREVIEW_ONLY",
                }

    def rsync_plan(self, plan_id):
        plan = self.mirrors.plan(plan_id)
        rsync_plan = self.mirrors._load("rsync/plans/" + plan_id + ".json")
        require(
            type(rsync_plan) is dict
            and rsync_plan.get("schema") == "provelume-rsync-plan/v1"
            and rsync_plan.get("plan_id") == plan_id
            and rsync_plan.get("original_plan_sha256")
            == fingerprint({**plan, "state": "prepared"}),
            "rsync_plan",
        )
        return plan, rsync_plan

    @staticmethod
    def components_match(transport, rsync_plan):
        return rsync_plan["client_components"] == {
            name: {key: component[key] for key in ("version", "sha256")}
            for name, component in transport.components.items()
        }

    def pending(self, plan, rsync_plan, authority):
        pending = self.mirrors.operation_ledger(
            plan["destination_id"], epoch=authority["grant_epoch"]
        )["inflight"]
        require(
            type(pending) is dict
            and pending.get("transport_sha256") == fingerprint(rsync_plan)
            and pending.get("operation_id") == plan["id"],
            "stale",
        )
        require(
            {**authority, "operation_serial": plan["authority"]["operation_serial"]}
            == plan["authority"]
            and authority["operation_serial"] == plan["authority"]["operation_serial"] + 1,
            "stale",
        )

    @staticmethod
    def proof(remote, transport, *, noop, recovery=False):
        return {
            "profile": PROFILE,
            "root_sha256": remote["root_sha256"],
            "namespace": remote["namespace"],
            "configuration_sha256": remote["configuration_sha256"],
            "host_key_sha256": sha_host_key(transport.target),
            "active_pointer_sha256": fingerprint(remote["active_pointer"]),
            "activation_written": not noop,
            "filesystem_profile": remote["filesystem_profile"],
            "native_rsync": {
                key: transport.components["rsync"][key] for key in ("version", "sha256")
            },
            "native_ssh": {key: transport.components["ssh"][key] for key in ("version", "sha256")},
            "evidence_mode": "reconciled_current_state" if recovery else "direct_verified",
            "publication_time": None,
        }

    def verify_current(self, remote, transport, binding, rsync_plan):
        require(
            server_identity(remote) == rsync_plan["server"]
            and binding == rsync_plan["credential_binding"]
            and self.components_match(transport, rsync_plan),
            "rsync_binding_changed",
        )

    def activate(self, transport, target, plan, rsync_plan):
        self.window(target)
        status = transport.rpc(self.request(target, "operation", plan=plan, rsync_plan=rsync_plan))
        state = status["operation"]
        require(
            type(state) is dict
            and state.get("phase") == "VERIFIED"
            and state.get("activation_started") is False
            and state.get("native_child_stopped") is True
            and state.get("manifest_sha256") == plan["generation"]
            and state.get("transport_sha256") == fingerprint(rsync_plan)
            and status["active_pointer"] == rsync_plan["active_pointer"],
            "rsync_activation_not_proven_safe",
        )
        return transport.rpc(self.request(target, "activate", plan=plan, rsync_plan=rsync_plan))

    def complete(
        self,
        plan,
        rsync_plan,
        row,
        authority,
        target,
        reference,
        transport,
        remote,
        *,
        recovery=False,
    ):
        noop = (
            rsync_plan["active_pointer"] is not None
            and rsync_plan["active_pointer"]["generation"] == plan["generation"]
        )
        expected = (
            rsync_plan["active_pointer"]
            if noop
            else pointer(self.request(target, "activate", plan=plan, rsync_plan=rsync_plan))
        )
        require(
            remote["active_pointer"] == expected
            and server_identity(remote) == rsync_plan["server"],
            "outcome_unknown",
        )
        require(
            self.credentials.binding(self.credentials.read(reference))
            == rsync_plan["credential_binding"]
            and self.mirrors.authority(row["id"], _inspection_operation=plan["id"])[1] == authority,
            "stale",
        )
        receipt = self.mirrors._complete_locked(
            plan["id"],
            operation_id=plan["id"],
            observation=self.observation(row, remote),
            transport_proof=self.proof(remote, transport, noop=noop, recovery=recovery),
        )
        return {
            "receipt": receipt,
            "historical": False,
            "live_destination_checked": True,
            "network_used": True,
            "resend_allowed": False,
        }

    def publish(
        self,
        plan_id,
        *,
        expected_plan_sha256,
        expected_rsync_plan_sha256,
        confirmed,
        _deadline=None,
    ):
        require(confirmed is True and self.mirrors.access()["enabled"], "consent_required")
        with self.mirrors.guard():
            plan, rsync_plan = self.rsync_plan(plan_id)
            require(
                rsync_plan["original_plan_sha256"] == expected_plan_sha256
                and fingerprint(rsync_plan) == expected_rsync_plan_sha256,
                "stale",
            )
            historical = self.mirrors._recover_terminal_locked(plan_id)
            if historical is not None:
                return {
                    "receipt": historical,
                    "historical": True,
                    "live_destination_checked": False,
                    "network_used": False,
                }
            row, authority, target, reference = self.context(plan["destination_id"])
            require(plan["state"] == "prepared" and authority == plan["authority"], "stale")
            with native_work(
                deadline=min(_deadline or float("inf"), self.window(target))
            ) as session:
                transport, binding = self.transport(session, target, reference)
                before = transport.rpc(self.request(target, "inspect"))
                self.verify_current(before, transport, binding, rsync_plan)
                require(
                    before["active_pointer"] == rsync_plan["active_pointer"], "destination_changed"
                )
                self.mirrors._claim_locked(
                    plan_id,
                    transport_sha256=fingerprint(rsync_plan),
                    expected_plan_sha256=expected_plan_sha256,
                    observation=self.observation(row, before),
                    confirmed=True,
                )
                try:
                    noop = (
                        before["active_pointer"] is not None
                        and before["active_pointer"]["generation"] == plan["generation"]
                    )
                    if not noop:
                        transport.transfer(
                            self.request(target, "receive", plan=plan, rsync_plan=rsync_plan),
                            mirrors=self.mirrors,
                            plan=plan,
                        )
                        self.activate(transport, target, plan, rsync_plan)
                    after = transport.rpc(
                        self.request(target, "operation", plan=plan, rsync_plan=rsync_plan)
                    )
                    current = {**authority, "operation_serial": authority["operation_serial"] + 1}
                    return self.complete(
                        plan, rsync_plan, row, current, target, reference, transport, after
                    )
                except Exception:
                    self.mirrors._unknown_locked(plan_id)
                    raise

    def reconcile(self, plan_id, *, confirmed):
        require(confirmed is True and self.mirrors.access()["enabled"], "consent_required")
        with self.mirrors.guard():
            plan, rsync_plan = self.rsync_plan(plan_id)
            historical = self.mirrors._recover_terminal_locked(plan_id)
            if historical is not None:
                return {
                    "receipt": historical,
                    "historical": True,
                    "live_destination_checked": False,
                    "network_used": False,
                    "resend_allowed": False,
                }
            row, authority, target, reference = self.context(
                plan["destination_id"], inspection_operation=plan_id
            )
            self.pending(plan, rsync_plan, authority)
            with native_work() as session:
                transport, binding = self.transport(session, target, reference)
                remote = transport.rpc(
                    self.request(target, "operation", plan=plan, rsync_plan=rsync_plan)
                )
                self.verify_current(remote, transport, binding, rsync_plan)
                noop = (
                    rsync_plan["active_pointer"] is not None
                    and rsync_plan["active_pointer"]["generation"] == plan["generation"]
                )
                expected = (
                    rsync_plan["active_pointer"]
                    if noop
                    else pointer(self.request(target, "activate", plan=plan, rsync_plan=rsync_plan))
                )
                if remote["active_pointer"] != expected:
                    state = remote["operation"]
                    safe = (
                        type(state) is dict
                        and state.get("phase") in {"TRANSFER_INTERRUPTED", "VERIFIED"}
                        and state.get("activation_started") is False
                        and state.get("native_child_stopped") is True
                    )
                    return {
                        "outcome": "UNKNOWN",
                        "resend_allowed": False,
                        "explicit_resume_available": safe,
                        "live_destination_checked": True,
                        "network_used": True,
                    }
                return self.complete(
                    plan,
                    rsync_plan,
                    row,
                    authority,
                    target,
                    reference,
                    transport,
                    remote,
                    recovery=True,
                )

    def resume(self, plan_id, *, expected_rsync_plan_sha256, confirmed):
        require(confirmed is True and self.mirrors.access()["enabled"], "consent_required")
        with self.mirrors.guard():
            plan, rsync_plan = self.rsync_plan(plan_id)
            require(
                fingerprint(rsync_plan) == expected_rsync_plan_sha256
                and datetime.now(UTC) <= utc_instant(plan["expires_at"]),
                "stale",
            )
            row, authority, target, reference = self.context(
                plan["destination_id"], inspection_operation=plan_id
            )
            self.pending(plan, rsync_plan, authority)
            with native_work(deadline=self.window(target)) as session:
                transport, binding = self.transport(session, target, reference)
                status = transport.rpc(
                    self.request(target, "operation", plan=plan, rsync_plan=rsync_plan)
                )
                self.verify_current(status, transport, binding, rsync_plan)
                state = status["operation"]
                require(
                    type(state) is dict
                    and state.get("phase") in {"TRANSFER_INTERRUPTED", "VERIFIED"}
                    and state.get("activation_started") is False
                    and state.get("native_child_stopped") is True
                    and status["active_pointer"] == rsync_plan["active_pointer"],
                    "rsync_resume_not_proven_safe",
                )
                self.mirrors.snapshots.verify(plan["generation"])
                try:
                    if state["phase"] == "TRANSFER_INTERRUPTED":
                        transport.transfer(
                            self.request(target, "resume", plan=plan, rsync_plan=rsync_plan),
                            mirrors=self.mirrors,
                            plan=plan,
                        )
                    self.activate(transport, target, plan, rsync_plan)
                    after = transport.rpc(
                        self.request(target, "operation", plan=plan, rsync_plan=rsync_plan)
                    )
                    return self.complete(
                        plan, rsync_plan, row, authority, target, reference, transport, after
                    )
                except Exception:
                    self.mirrors._unknown_locked(plan_id)
                    raise


def sha_host_key(target):
    import base64

    from .mirror_contract import sha

    return sha(base64.b64decode(target["host_key"], validate=True))
