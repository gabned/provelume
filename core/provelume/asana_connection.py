"""Asana PKCE identities: read scopes only, external grants, no canonical secrets."""

from __future__ import annotations

import hashlib
import json
import re
import time
from threading import RLock
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

from .connectors import ConnectorManager
from .google_credentials import GoogleCredentialVault
from .instance_lifecycle import InstanceLifecycleManager
from .oauth_authorization import InstalledAppAuthorizationManager, _normalise_loopback_redirect
from .productivity_connectors import ProductivityConnectors
from .productivity_contract import ReadCredential, fingerprint, require, text
from .productivity_http import ProductivityHttp
from .review_decisions import checked_path, read_json
from .storage import utc_now

ORIGIN = "https://app.asana.com"
API = ORIGIN + "/api/1.0"
AUTHORIZE, TOKEN, REVOKE, TOKEN_INFO = (ORIGIN + "/-/" + name for name in (
    "oauth_authorize", "oauth_token", "oauth_revoke", "token_info"))
SCOPES = tuple(sorted(("tasks:read", "stories:read", "projects:read", "teams:read",
                       "workspaces:read", "users:read")))
KEY, VERSION = "concordia-asana-readonly", "1.0.0"
STATE_ROOT = "state/productivity-providers/asana"


def gid(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value) is not None)
    return value


def decode(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "response")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=unique)
        require(type(value) is dict, "response")
        return value
    except (ValueError, UnicodeError, RecursionError):
        from .productivity_contract import ProductivityError

        raise ProductivityError("response") from None


def _token(value):
    text(value, 8192)
    require(all(32 < ord(char) < 127 for char in value), "authorization_required")
    return value


class AsanaAuthority:
    def __init__(self, manager):
        self.manager = manager

    def authorization_policy(self, identity):
        connector = self.manager.connector(identity)
        record = self.manager.record(identity)
        return {"active": connector["lifecycle_state"] == "active",
                "enabled": connector["configured_enabled"],
                "effective_network": connector["effective_network"],
                "allowed_origins": connector["allowed_origins"], "adapter_key": KEY,
                "adapter_version": VERSION, "scopes": list(SCOPES),
                "authorization_consent_profile": "asana-scoped-pkce-v1",
                "authorization": {"status": record["status"]}}

    def authorization_fingerprint(self, identity):
        connector = self.manager.store.read_canonical("connector-instances", identity)
        require(connector is not None, "unsupported")
        definition = self.manager.store.read_canonical("connector-definitions",
                                                       connector["definition_id"])
        return fingerprint([connector, definition, self.manager.record(identity),
                            self.manager.store.read_config()["network"]])

    def complete_oauth_authorization(self, identity, *, grant, authorized_at,
                                     expected_record_sha256):
        manager = self.manager
        with InstanceLifecycleManager(manager.store)._hold(purpose="asana-authorization"), \
                manager.connectors.policy_commit_guard(purpose="asana-authorization"):
            require(self.authorization_fingerprint(identity) == expected_record_sha256, "stale")
            manager.network(identity)
            record = manager.record(identity)
            binding = grant["account_identity"]
            require(re.fullmatch(r"[0-9a-f]{64}", binding) is not None, "authorization_required")
            require(record["account_binding"] in {None, binding}, "account_mismatch")
            slot, reference = manager.link(identity), grant["credential_reference"]
            previous = manager.vault.read(slot)
            try:
                manager.vault.write(slot, reference)
                manager.write_record({**record, "status": "authorized", "account_binding": binding,
                                      "revision": record["revision"] + 1,
                                      "authorized_at": authorized_at})
            except Exception:
                if manager.vault.read(slot) == reference:
                    if previous is None:
                        manager.vault.delete(slot)
                    else:
                        manager.vault.write(slot, previous)
                raise
            if previous is not None and previous != reference:
                manager.vault.delete(previous["name"])
        return {"id": identity, "authorization": {"status": "authorized"}}


class AsanaInstalledAppAdapter:
    adapter_key, adapter_version = KEY, VERSION
    authorization_endpoint, token_endpoint = AUTHORIZE, TOKEN
    authorization_consent_profile = "asana-scoped-pkce-v1"

    def __init__(self, manager, identity, client):
        self.manager, self.identity, self.client = manager, identity, client
        self.slot, self.staged = "productivity_asana_grant_" + uuid4().hex, False

    def build_authorization_uri(self, request):
        return AUTHORIZE + "?" + urlencode({"client_id": self.client["client_id"],
            "redirect_uri": request.redirect_uri, "response_type": "code", "state": request.state,
            "scope": " ".join(request.scopes), "code_challenge": request.code_challenge,
            "code_challenge_method": "S256"})

    def exchange_callback(self, exchange):
        manager = self.manager
        raw = manager.call(TOKEN, fields={"client_id": self.client["client_id"],
            "client_secret": self.client["client_secret"], "grant_type": "authorization_code",
            "code": exchange.authorization_code, "code_verifier": exchange.pkce_verifier,
            "redirect_uri": exchange.redirect_uri})
        tokens = manager.validate_tokens(raw)
        account = manager.profile(tokens["access_token"])
        binding = fingerprint([self.identity, account])
        require(manager.record(self.identity)["account_binding"] in {None, binding},
                "account_mismatch")
        manager.vault.write(self.slot, {**tokens, "identity_id": self.identity,
            "client": self.client, "account_binding": binding, "grant_id": uuid4().hex})
        self.staged = True
        return {"credential_reference": {"kind": "system_keyring", "name": self.slot},
                "account_identity": binding, "granted_scopes": list(SCOPES)}

    def discard(self):
        if self.staged:
            self.manager.vault.delete(self.slot)


class AsanaConnection:
    def __init__(self, store, *, vault=None, http=None):
        self.store, self.connectors = store, ConnectorManager(store)
        self.host = ProductivityConnectors(store)
        self.vault = vault if vault is not None else GoogleCredentialVault(
            forbidden_root=store.paths.root, namespace="productivity")
        self.http = http or ProductivityHttp()
        self.network_used = False
        self.authority = AsanaAuthority(self)
        self.oauth = InstalledAppAuthorizationManager(
            store, self.connectors, authority=self.authority)
        self.sessions, self.catalogs, self.lock = {}, {}, RLock()
        self.client_slot = "productivity_asana_client_" + fingerprint(
            store.read_config()["instance"]["id"])

    @staticmethod
    def link(identity):
        require(re.fullmatch(r"connector_instance_[0-9a-f]{32}", identity) is not None)
        return "productivity_asana_link_" + identity

    def connector(self, identity):
        value = self.connectors.get_instance(identity)
        require(value is not None and value["definition"]["adapter_key"] == KEY, "unsupported")
        return value

    def record(self, identity):
        self.connector(identity)
        value = read_json(self.store, f"{STATE_ROOT}/{identity}.json")
        if value is None:
            return {"schema": "asana-authorization/v1", "identity_id": identity,
                    "status": "not_authorized", "revision": 0, "account_binding": None,
                    "authorized_at": None}
        require(set(value) == {"schema", "identity_id", "status", "revision", "account_binding",
                               "authorized_at"} and value["schema"] == "asana-authorization/v1"
                and value["identity_id"] == identity and type(value["revision"]) is int
                and value["revision"] > 0 and value["status"] in {"authorized", "revoked"},
                "integrity")
        return value

    def write_record(self, value):
        path = checked_path(self.store, f"{STATE_ROOT}/{value['identity_id']}.json")
        self.store._atomic_json(path, value)

    def network(self, identity=None):
        require(self.store.read_config()["network"]["external_access"], "network_disabled")
        if identity is not None:
            value = self.connector(identity)
            require(value["configured_enabled"] and value["lifecycle_state"] == "active"
                    and value["effective_network"] == "explicit"
                    and value["allowed_origins"] == [ORIGIN], "disabled")

    def configure(self, client):
        require(type(client) is dict and set(client) == {"client_id", "client_secret"})
        text(client["client_id"], 200)
        text(client["client_secret"], 512)
        self.vault.write(self.client_slot, client)

    def call(self, url, *, token=None, fields=None, deadline=None):
        self.network_used |= type(self.http) is ProductivityHttp
        return decode(self.http.request(url, origin=ORIGIN, token=token, fields=fields,
                                        deadline=deadline))

    def profile(self, token):
        value = self.call(API + "/users/me?opt_fields=gid", token=token)
        require(type(value.get("data")) is dict, "response")
        return gid(value["data"].get("gid"))

    def validate_tokens(self, raw, *, previous=None):
        access = _token(raw.get("access_token"))
        refresh = _token(raw.get("refresh_token") or (previous or {}).get("refresh_token"))
        seconds = raw.get("expires_in")
        require(type(seconds) is int and 60 <= seconds <= 86400
                and str(raw.get("token_type", "")).lower() == "bearer", "authorization_required")
        info = self.call(TOKEN_INFO, fields={"token": access})
        observed = tuple(sorted(set(str(info.get("scope", "")).split())))
        require(info.get("active") is True and observed == SCOPES, "scope_mismatch")
        return {"access_token": access, "refresh_token": refresh,
                "expires_at": time.time() + seconds,
                "scopes": list(SCOPES)}

    def begin(self, *, name, redirect_uri, confirmed, identity=None):
        require(confirmed is True, "consent_required")
        redirect_uri = _normalise_loopback_redirect(redirect_uri)
        self.network(identity)
        client = self.vault.read(self.client_slot)
        require(client is not None, "client_required")
        if identity is None:
            definition = self.connectors.register_definition({"adapter_key": KEY,
                "adapter_version": VERSION, "display_name": "Asana readonly", "provider": "asana",
                "conformance_profile": "provelume.connector.v1", "adapter_protocol_version": 1,
                "capabilities": ["manual_read", "source_selection", "task_read",
                                 "external_secret_authorization"],
                "authorization_modes": ["none"], "source_kinds": ["tasks"],
                "data_categories": ["task.content"], "multi_instance": True,
                "network_access": "explicit_only"})
            identity = self.connectors.create_instance(definition["id"], name=name,
                provider_identity="asana", account_identity="asana-local:" + uuid4().hex,
                network_mode="explicit", allowed_origins=[ORIGIN])["id"]
        with self.lock:
            self.sessions = {key: value for key, value in self.sessions.items()
                             if value["deadline"] > time.monotonic()}
            require(len(self.sessions) < 32, "limit")
            self.oauth.cancel(identity)
            adapter = AsanaInstalledAppAdapter(self, identity, client)
            request = self.oauth.begin(identity, adapter, redirect_uri=redirect_uri, consent=True)
            state = parse_qs(urlsplit(request["authorization_uri"]).query)["state"][0]
            self.sessions[hashlib.sha256(state.encode()).hexdigest()] = {
                "identity": identity, "request_id": request["request_id"], "redirect": redirect_uri,
                "adapter": adapter, "deadline": time.monotonic() + 300}
            return {**request, "identity_id": identity}

    def complete(self, query, *, redirect_uri):
        require(type(query) is bytes and len(query) <= 8192, "callback")
        values = parse_qs(query.decode("ascii"), keep_blank_values=True, strict_parsing=True,
                          max_num_fields=8)
        require(all(len(value) == 1 for value in values.values()) and values.get("state"),
                "callback")
        fields = {key: value[0] for key, value in values.items()}
        key = hashlib.sha256(fields["state"].encode()).hexdigest()
        with self.lock:
            session = self.sessions.pop(key, None)
        require(session is not None and session["deadline"] > time.monotonic()
                and session["redirect"] == redirect_uri, "callback")
        adapter = session["adapter"]
        try:
            require("error" not in fields and fields.get("code"), "consent_cancelled")
            if "scope" in fields:
                require(tuple(sorted(set(fields["scope"].split()))) == SCOPES, "scope_mismatch")
            self.network(session["identity"])
            self.oauth.complete(session["identity"], adapter, {
                "request_id": session["request_id"], "redirect_uri": redirect_uri,
                "state": fields["state"], "authorization_code": fields["code"],
                "granted_scopes": list(SCOPES)})
            return {"identity_id": session["identity"], "status": "authorized"}
        except Exception:
            self.oauth.cancel(session["identity"])
            adapter.discard()
            raise

    def resolve(self, identity, capability):
        require(capability == "task_read", "unsupported")
        self.network(identity)
        record = self.record(identity)
        require(record["status"] == "authorized", "authorization_required")
        cooldown = read_json(self.store, f"{STATE_ROOT}/{identity}/cooldown.json")
        require(cooldown is None or cooldown["grant_revision"] != record["revision"]
                or cooldown["not_before"] <= time.time(), "rate_limited")
        with self.lock:
            reference = self.vault.read(self.link(identity))
            require(type(reference) is dict and reference.get("kind") == "system_keyring"
                    and str(reference.get("name", "")).startswith("productivity_asana_grant_"),
                    "authorization_required")
            slot = reference["name"]
            grant = self.vault.read(slot)
            require(type(grant) is dict and grant.get("identity_id") == identity
                    and grant.get("account_binding") == record["account_binding"]
                    and grant.get("scopes") == list(SCOPES), "authorization_required")
            if grant["expires_at"] < time.time() + 30:
                client = grant["client"]
                raw = self.call(TOKEN, fields={"client_id": client["client_id"],
                    "client_secret": client["client_secret"], "grant_type": "refresh_token",
                    "refresh_token": grant["refresh_token"]})
                updated = self.validate_tokens(raw, previous=grant)
                require(fingerprint([identity, self.profile(updated["access_token"])])
                        == record["account_binding"], "account_mismatch")
                require(self.record(identity) == record
                        and self.vault.read(self.link(identity)) == reference, "stale")
                grant = {**grant, **updated}
                self.vault.write(slot, grant)
            revision = fingerprint([record, grant["grant_id"]])
            return ReadCredential(identity, capability, revision,
                                   {"access_token": _token(grant["access_token"])})

    def credential_epoch(self, identity):
        """Recheck external authority without refresh/network inside a commit guard."""
        self.network(identity)
        record = self.record(identity)
        require(record["status"] == "authorized", "authorization_required")
        reference = self.vault.read(self.link(identity))
        require(type(reference) is dict and reference.get("kind") == "system_keyring"
                and str(reference.get("name", "")).startswith("productivity_asana_grant_"),
                "authorization_required")
        grant = self.vault.read(reference["name"])
        require(type(grant) is dict and grant.get("identity_id") == identity
                and grant.get("account_binding") == record["account_binding"]
                and grant.get("scopes") == list(SCOPES), "authorization_required")
        return fingerprint([record, grant["grant_id"]])

    def record_rate_limit(self, identity, grant_revision, seconds):
        relative = f"{STATE_ROOT}/{identity}/cooldown.json"
        with self.connectors.policy_commit_guard(purpose="asana-rate-limit"):
            previous = read_json(self.store, relative)
            if previous and previous["grant_revision"] > grant_revision:
                return
            deadline = time.time() + (seconds or 60)
            if previous and previous["grant_revision"] == grant_revision:
                deadline = max(deadline, previous["not_before"])
            self.store._atomic_json(checked_path(self.store, relative), {
                "not_before": deadline, "grant_revision": grant_revision, "status": "rate_limited"})

    def disconnect(self, identity, *, expected_revision, confirmed):
        require(confirmed is True, "consent_required")
        self.oauth.cancel(identity)
        with InstanceLifecycleManager(self.store)._hold(purpose="asana-disconnect"), \
                self.connectors.policy_commit_guard(purpose="asana-disconnect"):
            record = self.record(identity)
            require(record["revision"] == expected_revision, "stale")
            self.write_record({**record, "status": "revoked", "revision": record["revision"] + 1})
            reference = self.vault.read(self.link(identity))
            self.vault.delete(self.link(identity))
            if reference:
                self.vault.delete(reference["name"])
        return {"status": "revoked", "remote_revocation": "NOT_REQUESTED", "at": utc_now()}

    def select_source(self, identity, *, name, scope, workspace, team=None, project=None,
                      confirmed=False):
        require(confirmed is True, "consent_required")
        require(self.record(identity)["status"] == "authorized", "authorization_required")
        require(scope in {"workspace", "organization", "team", "project"})
        selection = {"scope": scope, "workspace": gid(workspace),
                     "team": gid(team) if team is not None else None,
                     "project": gid(project) if project is not None else None}
        require(scope != "team" or team is not None)
        require(scope != "project" or project is not None)
        require(team is None or scope == "team")
        require(project is None or scope == "project")
        source = self.connectors.add_source(identity, name=name, source_kind="tasks",
                                            external_id=json.dumps(selection, sort_keys=True))
        if self.host.policy(source["id"]) is None:
            self.host.consent(source["id"], capabilities=["task_read"], mode="manual",
                              expected_revision=0, confirmed=True)
        return {"source_id": source["id"], "identity_id": identity}

    def catalogue(self, identity, *, workspace=None, confirmed=False):
        require(confirmed is True, "consent_required")
        self.network(identity)
        admitted = self.authority.authorization_fingerprint(identity)
        grant_revision = self.record(identity)["revision"]
        deadline = time.monotonic() + 60
        if workspace is None:
            collections = [("workspaces", "/workspaces",
                            {"opt_fields": "gid,name,is_organization"})]
        else:
            workspace = gid(workspace)
            collections = [("projects", "/projects", {"workspace": workspace,
                            "opt_fields": "gid,name,workspace.gid,team.gid"})]
            known = self.catalogs.get(identity, {}).get("workspaces", [])
            selected = next((row for row in known if row["gid"] == workspace), None)
            require(selected is not None, "selection")
            if selected.get("is_organization"):
                collections.append(("teams", "/organizations/" + workspace + "/teams",
                                    {"opt_fields": "gid,name"}))
        result = {}
        for name, path, options in collections:
            rows, seen, cursor = [], set(), None
            for _index in range(50):
                require(self.authority.authorization_fingerprint(identity) == admitted, "stale")
                credential = self.resolve(identity, "task_read")
                # The pinned public /workspaces operation is not paginated.
                params = dict(options) if name == "workspaces" else {**options, "limit": 100}
                if cursor is not None:
                    params["offset"] = cursor
                from .productivity_http import ProductivityHttpError

                try:
                    data = self.call(API + path + "?" + urlencode(params),
                        token=credential.payload["access_token"], deadline=deadline)
                except ProductivityHttpError as error:
                    if error.status == 429:
                        self.record_rate_limit(identity, grant_revision, error.retry_after)
                    raise
                require(self.authority.authorization_fingerprint(identity) == admitted, "stale")
                require(type(data.get("data")) is list and len(data["data"])
                        <= (5000 if name == "workspaces" else 100), "response")
                for row in data["data"]:
                    require(type(row) is dict)
                    gid(row.get("gid"))
                    text(row.get("name"), 500)
                    rows.append(row)
                require(len(rows) <= 5000, "limit")
                page = data.get("next_page")
                require(name != "workspaces" or page is None, "unsupported")
                if page is None:
                    break
                cursor = page.get("offset")
                require(type(cursor) is str and len(cursor) <= 2048 and cursor not in seen,
                        "cursor_loop")
                seen.add(cursor)
            else:
                require(False, "limit")
            result[name] = rows
        with self.lock:
            self.catalogs[identity] = {**self.catalogs.get(identity, {}), **result,
                "workspace": workspace, "observed_at": utc_now(),
                "workspace_is_organization": bool(selected.get("is_organization"))
                if workspace is not None else False}
        return {"status": "catalogue_loaded"}

    def revoke_remote(self, identity, *, expected_revision, confirmed):
        from .productivity_contract import ProductivityError

        require(confirmed is True, "consent_required")
        self.network(identity)
        record = self.record(identity)
        require(record["revision"] == expected_revision and record["status"] == "authorized",
                "stale")
        reference = self.vault.read(self.link(identity))
        require(type(reference) is dict, "authorization_required")
        grant = self.vault.read(reference["name"])
        require(type(grant) is dict and grant["identity_id"] == identity, "authorization_required")
        outcome = "UNKNOWN"
        try:
            self.http.request(REVOKE, origin=ORIGIN, fields={
                "client_id": grant["client"]["client_id"],
                "client_secret": grant["client"]["client_secret"], "token": grant["refresh_token"]})
            outcome = "CONFIRMED"
        except (ProductivityError, OSError):
            pass
        # CAS preserves any newer authorization. No compensation re-enables the
        # old grant, and the provider is never mutated again after uncertainty.
        result = self.disconnect(identity, expected_revision=expected_revision, confirmed=True)
        receipt = {"identity_sha256": fingerprint(identity), "grant_revision": expected_revision,
                   "remote_revocation": outcome, "local": result["status"], "at": utc_now()}
        self.store._atomic_json(checked_path(self.store,
            f"{STATE_ROOT}/revocations/{uuid4().hex}.json"), receipt)
        return receipt

    def view(self):
        identities = [item for item in self.connectors.list_instances()
                      if item["definition"]["adapter_key"] == KEY
                      and item["lifecycle_state"] != "removed"]
        sources = [item for item in self.store.list_canonical("sources") if item.get("kind")
                   == "connector" and item.get("connector_instance_id") in {
                       identity["id"] for identity in identities}]
        return {"identities": [{**item, "asana": self.record(item["id"]),
                                "catalogue": self.catalogs.get(item["id"], {})}
                               for item in identities],
                "sources": [{**item, "policy": self.host.policy(item["id"]),
                    "last_run": read_json(self.store,
                        f"state/productivity-providers/asana-status/{item['id']}.json")}
                            for item in sources],
                "network_enabled": self.store.read_config()["network"]["external_access"]}
