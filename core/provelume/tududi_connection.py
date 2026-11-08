"""Independent Tududi endpoints/accounts; GET only, external token bindings."""

import json
import time
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

from .connectors import ConnectorManager
from .google_credentials import GoogleCredentialVault
from .instance_lifecycle import InstanceLifecycleManager
from .productivity_connectors import ProductivityConnectors
from .productivity_contract import ReadCredential, fingerprint, require, text
from .productivity_http import ProductivityHttp, ProductivityHttpError
from .review_decisions import checked_path, read_json
from .storage import utc_now
from .tududi_contract import KEY, VERSION, decode, uid, zone

STATE_ROOT = "state/productivity-providers/tududi"


def endpoint(value):
    text(value, 2048)
    parsed = urlsplit(value)
    require(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
        and parsed.path in {"", "/"}
        and "\\" not in value
        and all(32 < ord(char) < 127 for char in value),
        "endpoint",
    )
    require(parsed.port is None or 1 <= parsed.port <= 65535, "endpoint")
    return "https://" + parsed.netloc.lower()


class TududiConnection:
    def __init__(self, store, *, vault=None, http=None):
        self.store, self.connectors = store, ConnectorManager(store)
        self.host = ProductivityConnectors(store)
        self.vault = (
            vault
            if vault is not None
            else GoogleCredentialVault(forbidden_root=store.paths.root, namespace="productivity")
        )
        self.http = http or ProductivityHttp()
        self.network_used, self.catalogs, self.lock = False, {}, RLock()

    @staticmethod
    def link(identity):
        require(identity.startswith("connector_instance_") and len(identity) == 51)
        return "productivity_tududi_link_" + identity

    def connector(self, identity):
        value = self.connectors.get_instance_policy(identity)
        require(value is not None and value["definition"]["adapter_key"] == KEY, "unsupported")
        return value

    def record(self, identity):
        self.connector(identity)
        value = read_json(self.store, f"{STATE_ROOT}/{identity}.json")
        if value is None:
            return {
                "schema": "tududi-authorization/v1",
                "identity_id": identity,
                "status": "not_authorized",
                "revision": 0,
                "account_binding": None,
                "declared_server_version": VERSION,
                "server_version_verified": False,
            }
        require(
            set(value)
            == {
                "schema",
                "identity_id",
                "status",
                "revision",
                "account_binding",
                "declared_server_version",
                "server_version_verified",
            }
            and value["schema"] == "tududi-authorization/v1"
            and value["identity_id"] == identity
            and type(value["revision"]) is int
            and value["revision"] > 0
            and value["status"] in {"authorized", "revoked"}
            and value["declared_server_version"] == VERSION
            and value["server_version_verified"] is False,
            "integrity",
        )
        return value

    def network(self, identity=None):
        require(self.store.read_config()["network"]["external_access"], "network_disabled")
        if identity is not None:
            value = self.connector(identity)
            require(
                value["configured_enabled"]
                and value["lifecycle_state"] == "active"
                and value["effective_network"] == "explicit",
                "disabled",
            )

    def authority(self, identity):
        row = self.store.read_canonical("connector-instances", identity)
        require(row is not None, "unsupported")
        return fingerprint(
            [
                row,
                self.store.read_canonical("connector-definitions", row["definition_id"]),
                self.record(identity),
                self.store.read_config()["network"],
            ]
        )

    def connect(self, configuration, *, name, confirmed, identity=None, expected_revision=0):
        require(confirmed is True, "consent_required")
        require(
            type(configuration) is dict
            and set(configuration) == {"endpoint", "token", "server_version"}
        )
        require(configuration["server_version"] == VERSION, "unsupported")
        origin = endpoint(configuration["endpoint"])
        token = text(configuration["token"], 8192)
        require(
            token.startswith("tt_") and all(32 < ord(char) < 127 for char in token),
            "authorization_required",
        )
        self.network(identity)
        if identity is None:
            require(expected_revision == 0, "stale")
            definition = self.connectors.register_definition(
                {
                    "adapter_key": KEY,
                    "adapter_version": "1.0.0",
                    "display_name": "Tududi readonly",
                    "provider": "tududi",
                    "conformance_profile": "provelume.connector.v1",
                    "adapter_protocol_version": 1,
                    "capabilities": [
                        "manual_read",
                        "source_selection",
                        "task_read",
                        "external_secret_authorization",
                    ],
                    "authorization_modes": ["none"],
                    "source_kinds": ["tasks"],
                    "data_categories": ["task.content"],
                    "multi_instance": True,
                    "network_access": "explicit_only",
                }
            )
            identity = self.connectors.create_instance(
                definition["id"],
                name=name,
                provider_identity="tududi",
                account_identity="tududi-local:" + uuid4().hex,
                network_mode="explicit",
                allowed_origins=[origin],
            )["id"]
        record, admitted = self.record(identity), self.authority(identity)
        require(
            record["revision"] == expected_revision
            and self.connector(identity)["allowed_origins"] == [origin],
            "stale",
        )
        self.network_used |= type(self.http) is ProductivityHttp
        profile = decode(self.http.request(origin + "/api/v1/profile", origin=origin, token=token))
        require(type(profile) is dict, "response")
        account, time_zone = uid(profile.get("uid")), text(profile.get("timezone"), 100)
        zone(time_zone)
        binding = fingerprint([identity, origin, account])
        require(record["account_binding"] in {None, binding}, "account_mismatch")
        slot = "productivity_tududi_grant_" + uuid4().hex
        reference = {"kind": "system_keyring", "name": slot}
        grant = {
            "identity_id": identity,
            "grant_id": uuid4().hex,
            "account_binding": binding,
            "endpoint": origin,
            "token": token,
            "time_zone": time_zone,
        }
        try:
            self.vault.write(slot, grant)
            with (
                InstanceLifecycleManager(self.store)._hold(purpose="tududi-authorize"),
                self.connectors.policy_commit_guard(purpose="tududi-authorize"),
            ):
                require(self.authority(identity) == admitted, "stale")
                previous = self.vault.read(self.link(identity))
                try:
                    self.vault.write(self.link(identity), reference)
                    self.store._atomic_json(
                        checked_path(self.store, f"{STATE_ROOT}/{identity}.json"),
                        {
                            **record,
                            "status": "authorized",
                            "revision": record["revision"] + 1,
                            "account_binding": binding,
                        },
                    )
                except Exception:
                    if self.vault.read(self.link(identity)) == reference:
                        if previous is None:
                            self.vault.delete(self.link(identity))
                        else:
                            self.vault.write(self.link(identity), previous)
                    raise
                if previous is not None:
                    self.vault.delete(previous["name"])
        except Exception:
            if self.vault.read(self.link(identity)) != reference:
                self.vault.delete(slot)
            raise
        return {
            "identity_id": identity,
            "status": "authorized",
            "declared_server_version": VERSION,
            "server_version_verified": False,
            "token_scopes_verified": False,
        }

    def resolve(self, identity, capability="task_read"):
        require(capability == "task_read", "unsupported")
        self.network(identity)
        record = self.record(identity)
        require(record["status"] == "authorized", "authorization_required")
        cooldown = read_json(self.store, f"{STATE_ROOT}/{identity}/cooldown.json")
        require(
            cooldown is None
            or cooldown["grant_revision"] != record["revision"]
            or cooldown["not_before"] <= time.time(),
            "rate_limited",
        )
        with self.lock:
            reference = self.vault.read(self.link(identity))
            require(
                type(reference) is dict
                and reference.get("kind") == "system_keyring"
                and str(reference.get("name", "")).startswith("productivity_tududi_grant_"),
                "authorization_required",
            )
            grant = self.vault.read(reference["name"])
            require(
                type(grant) is dict
                and grant.get("identity_id") == identity
                and grant.get("account_binding") == record["account_binding"]
                and self.connector(identity)["allowed_origins"] == [grant.get("endpoint")],
                "authorization_required",
            )
            return ReadCredential(
                identity, capability, fingerprint([record, grant["grant_id"]]), grant
            )

    def get(self, identity, path, *, deadline=None):
        credential = self.resolve(identity)
        grant, authority = credential.payload, self.authority(identity)
        grant_revision = self.record(identity)["revision"]
        require(path.startswith("/") and not path.startswith("//") and "#" not in path, "endpoint")
        self.network_used |= type(self.http) is ProductivityHttp
        try:
            raw = self.http.request(
                grant["endpoint"] + "/api/v1" + path,
                origin=grant["endpoint"],
                token=grant["token"],
                deadline=deadline,
            )
        except ProductivityHttpError as error:
            if error.status == 429:
                with self.connectors.policy_commit_guard(purpose="tududi-rate-limit"):
                    relative = f"{STATE_ROOT}/{identity}/cooldown.json"
                    previous = read_json(self.store, relative)
                    revision = grant_revision
                    if previous is None or previous["grant_revision"] <= revision:
                        self.store._atomic_json(
                            checked_path(self.store, relative),
                            {
                                "grant_revision": revision,
                                "not_before": max(
                                    time.time() + (error.retry_after or 60),
                                    previous["not_before"]
                                    if previous and previous["grant_revision"] == revision
                                    else 0,
                                ),
                            },
                        )
            raise
        require(
            self.authority(identity) == authority
            and self.resolve(identity).revision_sha256 == credential.revision_sha256,
            "stale",
        )
        require(type(raw) is bytes and len(raw) <= 1024 * 1024, "limit")
        return raw, decode(raw)

    def catalogue(self, identity, *, confirmed=False):
        require(confirmed is True, "consent_required")
        _raw, value = self.get(identity, "/projects?status=all", deadline=time.monotonic() + 60)
        require(
            type(value) is dict
            and type(value.get("projects")) is list
            and len(value["projects"]) <= 5000,
            "response",
        )
        rows = []
        for row in value["projects"]:
            require(type(row) is dict, "response")
            rows.append({"uid": uid(row.get("uid")), "name": text(row.get("name"), 500)})
        require(len({row["uid"] for row in rows}) == len(rows), "response")
        self.catalogs[identity] = {"projects": rows, "observed_at": utc_now()}
        return {"status": "catalogue_loaded"}

    def select_source(self, identity, *, name, scope, remote_id=None, confirmed=False):
        require(confirmed is True, "consent_required")
        require(self.record(identity)["status"] == "authorized", "authorization_required")
        if scope == "task" and type(remote_id) is str and "://" in remote_id:
            parsed = urlsplit(remote_id)
            require(
                not parsed.query
                and not parsed.fragment
                and parsed.username is None
                and parsed.password is None
                and parsed.path.startswith("/task/")
                and self.connector(identity)["allowed_origins"]
                == ["https://" + parsed.netloc.lower()]
                and parsed.scheme == "https",
                "selection",
            )
            pieces = parsed.path.strip("/").split("/")
            require(
                len(pieces) in {2, 3} and (len(pieces) == 2 or pieces[2] == "details"), "selection"
            )
            remote_id = pieces[1]
        require(
            scope in {"account", "project", "task"} and (remote_id is None) == (scope == "account"),
            "selection",
        )
        selection = {"scope": scope, "uid": uid(remote_id) if remote_id else None}
        source = self.connectors.add_source(
            identity,
            name=name,
            source_kind="tasks",
            external_id=json.dumps(selection, sort_keys=True),
        )
        if self.host.policy(source["id"]) is None:
            self.host.consent(
                source["id"],
                capabilities=["task_read"],
                mode="manual",
                expected_revision=0,
                confirmed=True,
            )
        return {"source_id": source["id"], "identity_id": identity}

    def disconnect(self, identity, *, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        with (
            InstanceLifecycleManager(self.store)._hold(purpose="tududi-disconnect"),
            self.connectors.policy_commit_guard(purpose="tududi-disconnect"),
        ):
            record = self.record(identity)
            require(record["revision"] == expected_revision, "stale")
            self.store._atomic_json(
                checked_path(self.store, f"{STATE_ROOT}/{identity}.json"),
                {**record, "status": "revoked", "revision": record["revision"] + 1},
            )
            reference = self.vault.read(self.link(identity))
            self.vault.delete(self.link(identity))
            if reference:
                self.vault.delete(reference["name"])
        return {"status": "revoked", "remote_revocation": "NOT_REQUESTED"}

    def view(self):
        identities = [
            row
            for row in self.connectors.list_instances()
            if row["definition"]["adapter_key"] == KEY and row["lifecycle_state"] != "removed"
        ]
        ids = {row["id"] for row in identities}
        return {
            "identities": [
                {
                    **row,
                    "tududi": self.record(row["id"]),
                    "catalogue": self.catalogs.get(row["id"], {}),
                }
                for row in identities
            ],
            "sources": [
                {
                    **row,
                    "policy": self.host.policy(row["id"]),
                    "last_run": read_json(
                        self.store, f"state/productivity-providers/tududi-status/{row['id']}.json"
                    ),
                }
                for row in self.store.list_canonical("sources")
                if row.get("kind") == "connector" and row.get("connector_instance_id") in ids
            ],
            "network_enabled": self.store.read_config()["network"]["external_access"],
        }
