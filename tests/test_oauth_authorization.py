from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest

from provelume.connector_model import ConnectorError
from provelume.domain import Acquisition, Document, DocumentVersion
from provelume.instance_schema import build_instance_manifest
from provelume.instance_validation import inspect_instance
from provelume.oauth_authorization import (
    InstalledAppAuthorizationManager,
    InstalledAppAuthorizationParameters,
    InstalledAppTokenExchange,
    OAuthCallbackError,
    OAuthPolicyError,
    OAuthReplayError,
    OAuthScopeError,
    OAuthSecretLeakError,
    OAuthStateExpiredError,
    OAuthStateMismatchError,
)
from provelume.service import ProvelumeInstance
from provelume.storage import utc_now

REDIRECT_URI = "http://127.0.0.1:49152/oauth/callback"
SCOPES = ["content.read", "metadata.read"]


@dataclass
class SyntheticOAuthAdapter:
    adapter_key: str = "synthetic-oauth"
    adapter_version: str = "1.0.0"
    authorization_endpoint: str = "https://oauth.example.test/authorize"
    token_endpoint: str = "https://oauth.example.test/token"
    credential_name: str = "provelume:oauth:fixture"
    account_identity: str = "synthetic-account"
    extra_grant: dict[str, Any] = field(default_factory=dict)
    exchanges: int = 0
    last_exchange: InstalledAppTokenExchange | None = None
    exchange_started: Event | None = None
    release_exchange: Event | None = None

    def build_authorization_uri(
        self,
        request: InstalledAppAuthorizationParameters,
    ) -> str:
        query = urlencode(
            {
                "response_type": "code",
                "redirect_uri": request.redirect_uri,
                "state": request.state,
                "code_challenge": request.code_challenge,
                "code_challenge_method": request.code_challenge_method,
                "scope": " ".join(request.scopes),
                "prompt": "consent",
                "client_id": "synthetic-installed-app",
            }
        )
        return f"{self.authorization_endpoint}?{query}"

    def exchange_callback(self, exchange: InstalledAppTokenExchange) -> dict[str, Any]:
        self.exchanges += 1
        self.last_exchange = exchange
        if self.exchange_started is not None:
            self.exchange_started.set()
        if self.release_exchange is not None and not self.release_exchange.wait(timeout=5):
            raise RuntimeError("synthetic exchange release timed out")
        return {
            "credential_reference": {
                "kind": "system_keyring",
                "name": self.credential_name,
            },
            "account_identity": self.account_identity,
            "granted_scopes": list(exchange.granted_scopes),
            **self.extra_grant,
        }


@dataclass
class MutableClock:
    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def _manifest() -> dict[str, object]:
    return {
        "adapter_key": "synthetic-oauth",
        "adapter_version": "1.0.0",
        "display_name": "Synthetic installed-app OAuth fixture",
        "provider": "provider-independent",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": [
            "manual_read",
            "oauth2_pkce_authorization",
            "source_selection",
        ],
        "authorization_modes": ["oauth2_pkce"],
        "source_kinds": ["web"],
        "data_categories": ["source.content", "source.metadata"],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def _configured(
    tmp_path: Path,
    *,
    scopes: list[str] | None = None,
) -> tuple[ProvelumeInstance, dict[str, Any]]:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    instance.store._atomic_json(
        instance.store.paths.manifest,
        build_instance_manifest(config),
    )
    definition = instance.register_connector_definition(_manifest())
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Synthetic OAuth account",
        provider_identity="synthetic-provider",
        endpoint="https://oauth.example.test",
        network_mode="explicit",
        allowed_origins=["https://oauth.example.test"],
        authorization_mode="oauth2_pkce",
        scopes=SCOPES if scopes is None else scopes,
    )
    return instance, connector


def _state(request: dict[str, Any]) -> str:
    return parse_qs(urlsplit(request["authorization_uri"]).query)["state"][0]


def _callback(
    request: dict[str, Any],
    *,
    state: str | None = None,
    redirect_uri: str = REDIRECT_URI,
    scopes: list[str] | None = None,
    code: str = "authorization-code-sensitive",
) -> dict[str, Any]:
    return {
        "request_id": request["request_id"],
        "redirect_uri": redirect_uri,
        "state": state or _state(request),
        "authorization_code": code,
        "granted_scopes": SCOPES if scopes is None else scopes,
    }


def _begin(
    instance: ProvelumeInstance,
    connector: dict[str, Any],
    adapter: SyntheticOAuthAdapter,
    *,
    ttl: int = 300,
) -> dict[str, Any]:
    return instance.begin_connector_authorization(
        str(connector["id"]),
        adapter,
        redirect_uri=REDIRECT_URI,
        consent=True,
        state_ttl_seconds=ttl,
    )


def _attach_original(
    instance: ProvelumeInstance,
    source_id: str,
) -> tuple[str, str, str, bytes]:
    data = b"exact OAuth-linked Original bytes"
    original = instance.store.store_original_bytes(data)
    suffix = uuid4().hex
    document_id = f"doc_{suffix}"
    version_id = f"ver_{suffix}"
    acquisition_id = f"acq_{suffix}"
    now = utc_now()
    instance.store.write_version(
        DocumentVersion(
            id=version_id,
            document_id=document_id,
            sequence=1,
            content_hash=original.sha256,
            original_id=original.id,
            media_type="text/plain",
            size_bytes=len(data),
            acquired_at=now,
        )
    )
    instance.store.write_document(
        Document(
            id=document_id,
            source_id=source_id,
            locator="https://content.example.test/item",
            title="Preserved OAuth item",
            media_type="text/plain",
            created_at=now,
            current_version_id=version_id,
        )
    )
    instance.store.write_acquisition(
        Acquisition(
            id=acquisition_id,
            source_id=source_id,
            locator="https://content.example.test/item",
            observed_at=now,
            content_hash=original.sha256,
            outcome="created",
            document_id=document_id,
            version_id=version_id,
        )
    )
    return original.id, document_id, acquisition_id, data


def test_pkce_callback_stores_only_external_reference_and_redacted_metadata(
    tmp_path: Path,
) -> None:
    instance, connector = _configured(tmp_path)
    adapter = SyntheticOAuthAdapter()
    request = _begin(instance, connector, adapter)
    state = _state(request)

    assert request["pkce"] == {"method": "S256"}
    assert request["consent"] == "explicit"
    assert request["network_attempted"] is False
    result = instance.complete_connector_authorization(
        str(connector["id"]),
        adapter,
        _callback(request),
    )

    selected = result["connector_instance"]
    assert selected["authorization"] == {
        "status": "authorized",
        "method": "oauth2_pkce",
        "authorized_at": selected["updated_at"],
        "revoked_at": None,
        "redirect_binding": "loopback",
        "consent": "explicit",
    }
    assert selected["credential_reference"] == {
        "kind": "system_keyring",
        "name": "provelume:oauth:fixture",
    }
    assert result["credential_material_stored"] is False
    assert adapter.last_exchange is not None
    verifier = adapter.last_exchange.pkce_verifier
    assert "authorization-code-sensitive" not in repr(adapter.last_exchange)
    assert verifier not in repr(adapter.last_exchange)

    instance_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in instance.root.rglob("*.json")
        if path.is_file()
    )
    for prohibited in ("authorization-code-sensitive", verifier, state):
        assert prohibited not in instance_text
    assert str(tmp_path) not in json.dumps(instance.connectors.operations.list(limit=100))
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_state_mismatch_replay_scope_escalation_and_callback_substitution_fail_closed(
    tmp_path: Path,
) -> None:
    instance, connector = _configured(tmp_path)
    adapter = SyntheticOAuthAdapter()
    canonical_path = (
        instance.store.paths.canonical_dir("connector-instances") / f"{connector['id']}.json"
    )
    original_record = canonical_path.read_bytes()

    mismatch = _begin(instance, connector, adapter)
    with pytest.raises(OAuthStateMismatchError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(mismatch, state="A" * 43),
        )
    assert adapter.exchanges == 0
    assert canonical_path.read_bytes() == original_record

    escalation = _begin(instance, connector, adapter)
    with pytest.raises(OAuthScopeError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(escalation, scopes=[*SCOPES, "content.write"]),
        )
    with pytest.raises(OAuthReplayError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(escalation),
        )

    substitution = _begin(instance, connector, adapter)
    with pytest.raises(OAuthCallbackError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(
                substitution,
                redirect_uri="http://127.0.0.1:49152/oauth/substituted",
            ),
        )
    assert adapter.exchanges == 0
    assert canonical_path.read_bytes() == original_record


def test_concurrent_callback_replay_exchanges_exactly_once(tmp_path: Path) -> None:
    instance, connector = _configured(tmp_path)
    adapter = SyntheticOAuthAdapter()
    request = _begin(instance, connector, adapter)
    callback = _callback(request)

    def complete() -> str:
        try:
            instance.complete_connector_authorization(
                str(connector["id"]),
                adapter,
                callback,
            )
        except OAuthReplayError:
            return "replay"
        return "authorized"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _index: complete(), range(2)))

    assert outcomes == ["authorized", "replay"]
    assert adapter.exchanges == 1


def test_revocation_serializes_through_in_flight_callback_exchange(tmp_path: Path) -> None:
    instance, connector = _configured(tmp_path)
    exchange_started = Event()
    release_exchange = Event()
    revoke_entered = Event()
    adapter = SyntheticOAuthAdapter(
        exchange_started=exchange_started,
        release_exchange=release_exchange,
    )
    request = _begin(instance, connector, adapter)

    def revoke() -> dict[str, Any]:
        revoke_entered.set()
        return instance.revoke_connector_authorization(str(connector["id"]))

    with ThreadPoolExecutor(max_workers=2) as executor:
        completion = executor.submit(
            instance.complete_connector_authorization,
            str(connector["id"]),
            adapter,
            _callback(request),
        )
        assert exchange_started.wait(timeout=2)
        revocation = executor.submit(revoke)
        assert revoke_entered.wait(timeout=2)
        assert not revocation.done()
        release_exchange.set()
        assert completion.result(timeout=5)["status"] == "authorized"
        revoked = revocation.result(timeout=5)

    assert revoked["status"] == "revoked"
    assert adapter.exchanges == 1
    selected = instance.get_connector_instance(str(connector["id"]))
    assert selected is not None
    assert selected["authorization"]["status"] == "revoked"
    assert selected["credential_reference"] is None


def test_parallel_distinct_callbacks_invoke_only_one_exchange(tmp_path: Path) -> None:
    instance, connector = _configured(tmp_path)
    exchange_started = Event()
    release_exchange = Event()
    adapter = SyntheticOAuthAdapter(
        exchange_started=exchange_started,
        release_exchange=release_exchange,
    )
    requests = [_begin(instance, connector, adapter) for _index in range(2)]
    ready = Barrier(3)

    def complete(request: dict[str, Any]) -> str:
        ready.wait(timeout=2)
        try:
            instance.complete_connector_authorization(
                str(connector["id"]),
                adapter,
                _callback(request),
            )
        except OAuthReplayError:
            return "superseded"
        return "authorized"

    with ThreadPoolExecutor(max_workers=2) as executor:
        completions = [executor.submit(complete, request) for request in requests]
        ready.wait(timeout=2)
        assert exchange_started.wait(timeout=2)
        assert adapter.exchanges == 1
        release_exchange.set()
        outcomes = sorted(item.result(timeout=5) for item in completions)

    assert outcomes == ["authorized", "superseded"]
    assert adapter.exchanges == 1


def test_callback_fails_if_connector_record_changes_after_request(tmp_path: Path) -> None:
    instance, connector = _configured(tmp_path)
    adapter = SyntheticOAuthAdapter()
    request = _begin(instance, connector, adapter)
    instance.update_connector_instance(
        str(connector["id"]),
        name="Changed during authorization",
    )

    with pytest.raises(OAuthCallbackError, match="changed during OAuth"):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(request),
        )
    assert adapter.exchanges == 0


def test_short_lived_state_and_consent_and_network_policy_are_fail_closed(
    tmp_path: Path,
) -> None:
    instance, connector = _configured(tmp_path)
    adapter = SyntheticOAuthAdapter()
    clock = MutableClock(datetime(2026, 8, 29, 12, 0, tzinfo=UTC))
    instance.oauth = InstalledAppAuthorizationManager(
        instance.store,
        instance.connectors,
        clock=clock,
    )
    request = _begin(instance, connector, adapter, ttl=30)
    clock.advance(31)
    with pytest.raises(OAuthStateExpiredError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(request),
        )

    with pytest.raises(OAuthPolicyError, match="explicit consent"):
        instance.begin_connector_authorization(
            str(connector["id"]),
            adapter,
            redirect_uri=REDIRECT_URI,
            consent=False,
        )
    config = instance.store.read_config()
    config["network"]["external_access"] = False
    instance.store.write_config(config)
    with pytest.raises(OAuthPolicyError, match="network policy"):
        _begin(instance, connector, adapter)
    assert adapter.exchanges == 0


def test_oauth_scope_tokens_are_case_sensitive_and_provider_independent(
    tmp_path: Path,
) -> None:
    scopes = [
        "Files.Read",
        "https://www.googleapis.com/auth/drive.readonly",
        "user:email",
    ]
    instance, connector = _configured(tmp_path, scopes=scopes)
    adapter = SyntheticOAuthAdapter()
    assert connector["scopes"] == sorted(scopes)
    request = _begin(instance, connector, adapter)
    completed = instance.complete_connector_authorization(
        str(connector["id"]),
        adapter,
        _callback(request, scopes=scopes),
    )
    assert completed["connector_instance"]["scopes"] == sorted(scopes)

    reauthorization = _begin(instance, connector, adapter)
    changed_case = [
        "files.read",
        "https://www.googleapis.com/auth/drive.readonly",
        "user:email",
    ]
    with pytest.raises(OAuthScopeError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(reauthorization, scopes=changed_case),
        )


@pytest.mark.parametrize(
    "scope",
    ["", "two words", 'bad"quote', "bad\\slash", "café", "x" * 513],
)
def test_invalid_oauth_scope_tokens_fail_configuration_closed(
    tmp_path: Path,
    scope: str,
) -> None:
    with pytest.raises(ConnectorError, match="scope"):
        _configured(tmp_path, scopes=[scope])


def test_pre_s03_empty_scope_record_stays_valid_but_cannot_authorize(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    config = instance.store.read_config()
    config["network"]["external_access"] = True
    instance.store.write_config(config)
    instance.store._atomic_json(
        instance.store.paths.manifest,
        build_instance_manifest(config),
    )
    definition = instance.register_connector_definition(_manifest())
    connector_id = f"connector_instance_{uuid4().hex}"
    now = utc_now()
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("connector-instances") / f"{connector_id}.json",
        {
            "schema_version": 2,
            "id": connector_id,
            "definition_id": definition["id"],
            "name": "Legacy empty-scope OAuth",
            "provider_identity": "synthetic-provider",
            "account_identity": None,
            "endpoint": "https://oauth.example.test",
            "network_mode": "explicit",
            "allowed_origins": ["https://oauth.example.test"],
            "authorization_mode": "oauth2_pkce",
            "scopes": [],
            "credential_reference": None,
            "enabled": True,
            "lifecycle_state": "active",
            "removed_at": None,
            "cursors": {},
            "health": {
                "status": "not_checked",
                "checked_at": None,
                "code": "network_not_attempted",
            },
            "created_at": now,
            "updated_at": now,
        },
    )

    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    with pytest.raises(OAuthScopeError, match="at least one scope"):
        instance.begin_connector_authorization(
            connector_id,
            SyntheticOAuthAdapter(),
            redirect_uri=REDIRECT_URI,
            consent=True,
        )


def test_adapter_secret_leakage_is_rejected_without_canonical_or_evidence_leakage(
    tmp_path: Path,
) -> None:
    instance, connector = _configured(tmp_path)
    leaked_token = "synthetic-access-token-must-never-persist"
    adapter = SyntheticOAuthAdapter(extra_grant={"access_token": leaked_token})
    request = _begin(instance, connector, adapter)
    canonical_path = (
        instance.store.paths.canonical_dir("connector-instances") / f"{connector['id']}.json"
    )
    original_record = canonical_path.read_bytes()

    with pytest.raises(OAuthSecretLeakError):
        instance.complete_connector_authorization(
            str(connector["id"]),
            adapter,
            _callback(request),
        )
    assert adapter.exchanges == 1
    assert canonical_path.read_bytes() == original_record
    evidence = json.dumps(instance.connectors.operations.list(limit=100))
    assert leaked_token not in evidence
    assert "authorization-code-sensitive" not in evidence


def test_reauthorization_and_local_revocation_preserve_acquired_knowledge(
    tmp_path: Path,
) -> None:
    instance, connector = _configured(tmp_path)
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Authorized Source",
        source_kind="web",
        external_id="synthetic:authorized",
    )
    original_id, document_id, acquisition_id, original_bytes = _attach_original(
        instance,
        str(source["id"]),
    )
    first_adapter = SyntheticOAuthAdapter()
    first = _begin(instance, connector, first_adapter)
    instance.complete_connector_authorization(
        str(connector["id"]),
        first_adapter,
        _callback(first),
    )

    second_adapter = SyntheticOAuthAdapter(
        credential_name="provelume:oauth:reauthorized",
        account_identity="synthetic-account-next",
    )
    second = _begin(instance, connector, second_adapter)
    assert second["reauthorization"] is True
    reauthorized = instance.complete_connector_authorization(
        str(connector["id"]),
        second_adapter,
        _callback(second, code="second-authorization-code-sensitive"),
    )
    assert reauthorized["connector_instance"]["credential_reference"]["name"] == (
        "provelume:oauth:reauthorized"
    )

    revoked = instance.revoke_connector_authorization(str(connector["id"]))
    selected = revoked["connector_instance"]
    assert selected["authorization"]["status"] == "revoked"
    assert selected["credential_reference"] is None
    assert revoked["remote_mutation_attempted"] is False
    assert instance.store.original_bytes(original_id) == original_bytes
    assert instance.store.read_canonical("documents", document_id) is not None
    assert instance.store.read_canonical("acquisitions", acquisition_id) is not None
    retained_source = instance.store.read_canonical("sources", str(source["id"]))
    assert retained_source is not None and retained_source["lifecycle_state"] == "active"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
