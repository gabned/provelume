from __future__ import annotations

import hashlib
import hmac
import json
import time
from threading import Lock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from .google_authorization import GoogleCapabilityAuthority
from .google_connection_evidence import GoogleConnectionEvidence
from .google_contract import (
    GOOGLE_ALLOWED_ORIGINS,
    GOOGLE_CAPABILITIES,
    GoogleAuthorizationError,
    normalise_capability,
)
from .google_credentials import GoogleCredentialError, GoogleCredentialVault
from .google_oauth import (
    REVOCATION_ENDPOINT,
    GoogleConnectionError,
    GoogleInstalledAppAdapter,
    GoogleOAuthTransport,
    account_binding,
    desktop_client,
    resolve_google_credential,
)
from .google_sources import GoogleSourceManager
from .instance_lifecycle import InstanceLifecycleManager
from .oauth_authorization import InstalledAppAuthorizationManager, _normalise_loopback_redirect
from .storage import utc_now


class GoogleConnectionManager:
    """Shared Windows-hosted/Browser journey; GET never reads secrets or uses network."""

    def __init__(self, store, *, vault=None, transport=None):
        self.store = store
        self.sources = GoogleSourceManager(store)
        self.vault = vault or GoogleCredentialVault(forbidden_root=store.paths.root)
        self.transport = transport or GoogleOAuthTransport()
        self.evidence = GoogleConnectionEvidence(store)
        self._lock = Lock()
        self._sessions = {}
        self._oauth = {
            capability: InstalledAppAuthorizationManager(
                store,
                self.sources.connectors,
                authority=GoogleCapabilityAuthority(self.sources, capability),
            )
            for capability in GOOGLE_CAPABILITIES
        }
        self._client_slot = (
            "google_client_" + hashlib.sha256(str(store.paths.root.resolve()).encode()).hexdigest()
        )

    def configure(self, payload: str):
        if not isinstance(payload, str) or len(payload.encode()) > 16 * 1024:
            raise GoogleConnectionError("google_client_invalid")
        try:
            value = desktop_client(json.loads(payload))
        except (ValueError, TypeError):
            raise GoogleConnectionError("google_client_invalid") from None
        self.vault.write(self._client_slot, value)
        return {"status": "google_client_saved"}

    def set_network(self, *, enabled, consent):
        if type(enabled) is not bool or consent is not True:
            raise GoogleConnectionError("google_consent_required")
        with InstanceLifecycleManager(self.store)._hold(purpose="google-network-consent"):
            config = self.store.read_config()
            config["network"]["external_access"] = enabled
            self.store.write_config(config)
        self.evidence.record("online" if enabled else "offline")
        return {"status": "google_network_enabled" if enabled else "google_network_disabled"}

    def _network(self, instance_id=None):
        if not self.store.read_config().get("network", {}).get("external_access", False):
            raise GoogleConnectionError("google_network_disabled")
        if instance_id is not None:
            connector = self.sources.connectors.get_instance(instance_id)
            if (
                connector is None
                or not connector["configured_enabled"]
                or connector["lifecycle_state"] != "active"
                or connector["effective_network"] != "explicit"
                or set(connector["allowed_origins"]) != set(GOOGLE_ALLOWED_ORIGINS)
            ):
                raise GoogleConnectionError("google_network_disabled")

    @staticmethod
    def _link_slot(instance_id, capability):
        return f"google_link_{instance_id}_{capability}"

    def _owned_reference(self, instance_id, capability):
        record = self.sources._instance_record(instance_id)
        reference = record["capabilities"][capability].get("credential_reference")
        if reference and reference["name"].startswith("google_grant_"):
            return reference
        if record.get("account_binding_sha256"):
            return self.vault.read(self._link_slot(instance_id, capability))
        return None

    def _expire(self):
        for key, session in tuple(self._sessions.items()):
            if time.monotonic() >= session["deadline"]:
                self._oauth[session["capability"]].cancel(session["instance_id"])
                self._sessions.pop(key, None)
                self._discard_provisional(session["instance_id"])
        # Recover abandoned requests after process restart, on an explicit control action.
        for connection in self.sources.list_instances():
            identity = connection["connector"]["id"]
            record = self.sources._instance_record(identity)
            deadline = record.get("guided_provisional_until")
            if (
                record.get("guided_provisional") is True
                and isinstance(deadline, (int, float))
                and deadline <= time.time()
            ):
                self._discard_provisional(identity)

    def _discard_provisional(self, instance_id):
        if any(value["instance_id"] == instance_id for value in self._sessions.values()):
            return
        with InstanceLifecycleManager(self.store)._hold(purpose="google-provisional-cleanup"):
            record = self.sources._instance_record(instance_id)
            if (
                record.get("guided_provisional") is not True
                or any(
                    item["authorization_status"] == "authorized"
                    for item in record["capabilities"].values()
                )
                or self.sources.list_sources(connector_instance_id=instance_id)
            ):
                return
            # Existing lifecycle tombstone retains audit metadata without an active Google card.
            self.sources.connectors.remove_instance(instance_id)

    def begin(self, *, capability, redirect_uri, consent, instance_id=None, name="Google"):
        selected = normalise_capability(capability)
        redirect = _normalise_loopback_redirect(redirect_uri)
        if consent is not True:
            raise GoogleConnectionError("google_consent_required")
        self._network(instance_id)
        with self._lock:
            self._expire()
            if len(self._sessions) >= 32:
                raise GoogleConnectionError("google_connection_busy")
            client = self.vault.read(self._client_slot)
            if client is None:
                raise GoogleConnectionError("google_client_required")
            if instance_id is None:
                result = self.sources.create_instance(
                    name=name, account_identity=f"google-local:{uuid4().hex}"
                )
                instance_id = result["connector"]["id"]
                record = self.sources._instance_record(instance_id)
                self.sources._write_instance_record(
                    {
                        **record,
                        "guided_provisional": True,
                        "guided_provisional_until": time.time() + 300,
                    }
                )
                self.sources.connectors.enable_instance(instance_id)
            record = self.sources._instance_record(instance_id)
            if record.get("guided_provisional") and any(
                value["instance_id"] == instance_id and value["capability"] != selected
                for value in self._sessions.values()
            ):
                raise GoogleConnectionError("google_connection_busy")
            expected_binding = record.get("account_binding_sha256")
            if not expected_binding and self.sources.list_sources(
                connector_instance_id=instance_id
            ):
                legacy = self.sources.connectors.get_instance(instance_id).get("account_identity")
                if not isinstance(legacy, str) or "@" not in legacy:
                    raise GoogleConnectionError("google_legacy_connection")
                expected_binding = hashlib.sha256(
                    f"{instance_id}:{legacy.strip().casefold()}".encode()
                ).hexdigest()
            # One consent per capability/connection; abandon earlier pending consent explicitly.
            self._oauth[selected].cancel(instance_id)
            for key, value in tuple(self._sessions.items()):
                if (value["instance_id"], value["capability"]) == (instance_id, selected):
                    self._sessions.pop(key)
            adapter = GoogleInstalledAppAdapter(
                instance_id=instance_id,
                capability=selected,
                client=client,
                vault=self.vault,
                transport=self.transport,
                expected_binding=expected_binding,
            )
            try:
                result = self._oauth[selected].begin(
                    instance_id, adapter, redirect_uri=redirect, consent=True
                )
            except Exception:
                self._discard_provisional(instance_id)
                raise
            state = parse_qs(urlsplit(result["authorization_uri"]).query)["state"][0]
            key = hashlib.sha256(state.encode()).hexdigest()
            self._sessions[key] = {
                "instance_id": instance_id,
                "capability": selected,
                "adapter": adapter,
                "request_id": result["request_id"],
                "redirect_uri": redirect,
                "deadline": time.monotonic() + 300,
                "scopes": result["scopes"],
            }
            return {**result, "instance_id": instance_id, "capability": selected}

    def complete(self, query: bytes, *, redirect_uri):
        if len(query) > 8192:
            raise GoogleConnectionError("google_callback_invalid")
        try:
            fields = parse_qs(
                query.decode("ascii"),
                keep_blank_values=True,
                strict_parsing=True,
                max_num_fields=12,
            )
        except (UnicodeError, ValueError):
            raise GoogleConnectionError("google_callback_invalid") from None
        if any(len(value) != 1 for value in fields.values()) or not fields.get("state"):
            raise GoogleConnectionError("google_callback_invalid")
        state = fields["state"][0]
        if len(state) > 128:
            raise GoogleConnectionError("google_callback_invalid")
        key = hashlib.sha256(state.encode()).hexdigest()
        with self._lock:
            self._expire()
            session = self._sessions.get(key)
            if session is None:
                raise GoogleConnectionError("google_callback_invalid")
            if not hmac.compare_digest(redirect_uri, session["redirect_uri"]):
                raise GoogleConnectionError("google_callback_invalid")
            self._sessions.pop(key)
        try:
            return self._complete_session(session, fields, state, redirect_uri)
        except Exception:
            self._oauth[session["capability"]].cancel(session["instance_id"])
            self._discard_provisional(session["instance_id"])
            raise

    def _complete_session(self, session, fields, state, redirect_uri):
        selected = session["capability"]
        instance_id = session["instance_id"]
        adapter = session["adapter"]
        if "error" in fields:
            self._oauth[selected].cancel(instance_id)
            raise GoogleConnectionError("google_consent_cancelled")
        if not fields.get("code") or not fields.get("scope"):
            self._oauth[selected].cancel(instance_id)
            raise GoogleConnectionError("google_callback_invalid")
        self._network(instance_id)
        previous = self._owned_reference(instance_id, selected)
        try:
            self._oauth[selected].complete(
                instance_id,
                adapter,
                {
                    "request_id": session["request_id"],
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "authorization_code": fields["code"][0],
                    "granted_scopes": fields["scope"][0].split(),
                },
            )
        except Exception:
            adapter.discard()
            raise
        # A connection test already succeeded before the atomic grant commit.
        # Enrollment is idempotent and leaves acquisition disabled until explicit Start.
        source = self.sources.create_source(
            instance_id,
            name="Gmail" if selected == "gmail" else "Google Drive",
            capability=selected,
            selection_kind="mailbox" if selected == "gmail" else "folder",
            selectors=["me"] if selected == "gmail" else ["root"],
        )
        self.vault.write(
            self._link_slot(instance_id, selected), {"kind": "system_keyring", "name": adapter.slot}
        )
        if previous:
            self.vault.delete(previous["name"])
        self.evidence.record(
            "connected",
            capability=selected,
            source_id=source["id"],
            live=type(self.transport) is GoogleOAuthTransport,
        )
        return {"status": "google_connected", "instance_id": instance_id, "source_id": source["id"]}

    def cancel(self, instance_id, capability):
        selected = normalise_capability(capability)
        count = self._oauth[selected].cancel(instance_id)
        with self._lock:
            for key, session in tuple(self._sessions.items()):
                if (session["instance_id"], session["capability"]) == (instance_id, selected):
                    self._sessions.pop(key)
            self._discard_provisional(instance_id)
        return {"status": "google_consent_cancelled", "cancelled": count}

    def test(self, instance_id, capability):
        selected = normalise_capability(capability)
        self._network(instance_id)
        record = self.sources._instance_record(instance_id)
        item = self.sources.capability_record(instance_id, selected)
        if not item["credential_reference"]["name"].startswith("google_grant_"):
            raise GoogleConnectionError("google_legacy_connection")
        try:
            token = resolve_google_credential(
                item["credential_reference"], vault=self.vault, transport=self.transport
            )
            binding = account_binding(self.transport, selected, token, instance_id)
            if not hmac.compare_digest(binding, record.get("account_binding_sha256", "")):
                raise GoogleConnectionError("google_account_mismatch")
        except GoogleConnectionError as exc:
            if exc.code in {"google_reconnect_required", "google_account_mismatch"}:
                self.sources.mark_reauthorization_required(
                    instance_id, selected, code="google_authorization_expired"
                )
            raise
        except GoogleAuthorizationError:
            self.sources.mark_reauthorization_required(
                instance_id, selected, code="google_authorization_expired"
            )
            raise GoogleConnectionError("google_reconnect_required") from None
        self.evidence.record(
            "tested", capability=selected, live=type(self.transport) is GoogleOAuthTransport
        )
        return {"status": "google_connected"}

    def disconnect(self, instance_id, capability):
        selected = normalise_capability(capability)
        self.cancel(instance_id, selected)
        reference = self._owned_reference(instance_id, selected)
        self._oauth[selected].revoke(instance_id)
        if reference and reference["name"].startswith("google_grant_"):
            self.vault.delete(reference["name"])
            self.vault.delete(self._link_slot(instance_id, selected))
        self.evidence.record("disconnected", capability=selected)
        return {"status": "google_disconnected", "remote_mutation_attempted": False}

    def revoke_project(self, instance_id, capability, *, consent):
        if consent is not True:
            raise GoogleConnectionError("google_consent_required")
        selected = normalise_capability(capability)
        self._network(instance_id)
        reference = self._owned_reference(instance_id, selected)
        record = self.vault.read(reference["name"]) if reference else None
        if record is None:
            raise GoogleConnectionError("google_reconnect_required")
        project = record["client"]["project_id"]
        affected = []
        # Resolve the whole local impact before the irreversible remote revocation.
        for connection in self.sources.list_instances(local=True):
            for cap in connection["capabilities"]:
                reference = self._owned_reference(connection["connector"]["id"], cap)
                if not reference or not reference["name"].startswith("google_grant_"):
                    continue
                secret = self.vault.read(reference["name"])
                if (
                    secret
                    and secret["client"]["project_id"] == project
                    and secret.get("revocation_binding_sha256")
                    == record.get("revocation_binding_sha256")
                ):
                    affected.append((connection["connector"]["id"], cap, reference))
        self.transport.request(REVOCATION_ENDPOINT, fields={"token": record["refresh_token"]})
        for identity, cap, _reference in affected:
            self.cancel(identity, cap)
            self._oauth[cap].revoke(identity)
        cleanup_failed = False
        for identity, cap, reference in affected:
            try:
                self.vault.delete(reference["name"])
                self.vault.delete(self._link_slot(identity, cap))
            except GoogleCredentialError:
                cleanup_failed = True
        self.evidence.record(
            "project_revoked",
            capability=selected,
            live=type(self.transport) is GoogleOAuthTransport,
        )
        if cleanup_failed:
            raise GoogleCredentialError("google_secure_store_unavailable")
        return {"status": "google_project_revoked", "affected_capabilities": len(affected)}

    def view(self):
        network = bool(self.store.read_config().get("network", {}).get("external_access", False))
        connections = []
        for value in self.sources.list_instances():
            capabilities = []
            for name, item in value["capabilities"].items():
                state = {
                    "authorized": "connected",
                    "not_authorized": "disconnected",
                    "reauthorization_required": "expired",
                    "revoked": "revoked",
                }[item["authorization_status"]]
                capabilities.append({"name": name, "status": state, "enabled": item["state"]})
            connections.append(
                {
                    "id": value["connector"]["id"],
                    "name": value["connector"]["name"],
                    "capabilities": capabilities,
                }
            )
        return {
            "schema_version": 1,
            "network_enabled": network,
            "connections": connections,
            "sources": self.sources.list_sources(include_removed=False),
            "read_only": True,
            "observed_at": utc_now(),
        }
