from __future__ import annotations

import gzip
import http.client
import json
import os as stdlib_os
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient

from provelume import connector_cli, web_acquisition
from provelume.cli import main
from provelume.desktop import declare_startup_update_policy
from provelume.instance_backup import verify_backup
from provelume.instance_schema import build_instance_manifest
from provelume.instance_validation import inspect_instance
from provelume.oauth_authorization import (
    InstalledAppAuthorizationParameters,
    InstalledAppTokenExchange,
)
from provelume.operations import OperationLedger
from provelume.service import ProvelumeInstance
from provelume.storage import CANONICAL_KINDS, InstanceStore
from provelume.web import create_app
from provelume.web_acquisition import ManualWebAtomicityError
from provelume.web_transport import (
    ConnectionParameters,
    GuardedWebLimits,
    GuardedWebRequest,
    GuardedWebTransport,
    WebTransportBodyLimitError,
    WebTransportDestinationError,
    WebTransportDnsRebindingError,
    WebTransportHeaderError,
    WebTransportPolicyError,
    WebTransportRedirectError,
    WebTransportTimeoutError,
    WebTransportTruncatedError,
)

PUBLIC_IPV4 = "93.184.216.34"
URL = "https://public.example.test/article?view=full"


@dataclass
class SyntheticResponse:
    status: int = 200
    headers: Any = None
    body: bytes = b"synthetic acquisition body"
    timeout_on_read: bool = False
    incomplete_after_body: bool = False
    _offset: int = 0
    _incomplete_raised: bool = False

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(self.body))),
            ]

    def getheaders(self) -> Any:
        return self.headers

    def read(self, amount: int) -> bytes:
        if self.timeout_on_read:
            raise TimeoutError
        if self._offset < len(self.body):
            end = min(len(self.body), self._offset + amount)
            selected = self.body[self._offset : end]
            self._offset = end
            return selected
        if self.incomplete_after_body and not self._incomplete_raised:
            self._incomplete_raised = True
            raise http.client.IncompleteRead(b"")
        return b""


@dataclass
class SyntheticConnection:
    network: SyntheticNetwork
    parameters: ConnectionParameters
    response: SyntheticResponse
    closed: bool = False

    def request(self, method: str, target: str, headers: dict[str, str]) -> None:
        self.network.requests.append(
            {
                "method": method,
                "target": target,
                "headers": dict(headers),
                "parameters": self.parameters,
            }
        )

    def getresponse(self) -> SyntheticResponse:
        return self.response

    def set_read_timeout(self, seconds: float) -> None:
        assert seconds > 0

    def close(self) -> None:
        self.closed = True


@dataclass
class SyntheticNetwork:
    responses: list[SyntheticResponse]
    answers: dict[str, list[list[str]]] = field(default_factory=dict)
    requests: list[dict[str, Any]] = field(default_factory=list)
    resolver_calls: list[tuple[str, int]] = field(default_factory=list)
    connections: list[SyntheticConnection] = field(default_factory=list)

    def resolver(self, host: str, port: int) -> list[str]:
        self.resolver_calls.append((host, port))
        selected = self.answers.get(host)
        if selected is None:
            return [PUBLIC_IPV4]
        if len(selected) > 1:
            return selected.pop(0)
        return list(selected[0])

    def factory(self, parameters: ConnectionParameters) -> SyntheticConnection:
        if not self.responses:
            raise AssertionError("synthetic response queue is empty")
        connection = SyntheticConnection(self, parameters, self.responses.pop(0))
        self.connections.append(connection)
        return connection


def _manifest(
    *,
    adapter_key: str = "manual-web-fixture",
    authorization_modes: list[str] | None = None,
    oauth: bool = False,
) -> dict[str, object]:
    capabilities = ["manual_read", "source_selection"]
    if oauth:
        capabilities.append("oauth2_pkce_authorization")
    return {
        "adapter_key": adapter_key,
        "adapter_version": "1.0.0",
        "display_name": "Synthetic manual web fixture",
        "provider": "provider-independent",
        "conformance_profile": "provelume.connector.v1",
        "adapter_protocol_version": 1,
        "capabilities": capabilities,
        "authorization_modes": authorization_modes or ["none"],
        "source_kinds": ["web"],
        "data_categories": ["source.content", "source.metadata"],
        "multi_instance": True,
        "network_access": "explicit_only",
    }


def _enable_network(instance: ProvelumeInstance, enabled: bool = True) -> None:
    config = instance.store.read_config()
    config["network"]["external_access"] = enabled
    instance.store.write_config(config)
    instance.store._atomic_json(
        instance.store.paths.manifest,
        build_instance_manifest(config),
    )


def _configured(
    root: Path,
    *,
    url: str = URL,
) -> tuple[ProvelumeInstance, dict[str, Any], dict[str, Any]]:
    instance = ProvelumeInstance.initialise(root)
    _enable_network(instance)
    definition = instance.register_connector_definition(_manifest())
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="Synthetic account",
        provider_identity="synthetic-provider",
        endpoint="https://public.example.test",
        network_mode="explicit",
        allowed_origins=["https://public.example.test"],
        authorization_mode="none",
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="Synthetic article",
        source_kind="web",
        external_id=url,
    )
    return instance, connector, source


def _use_network(
    instance: ProvelumeInstance,
    network: SyntheticNetwork,
    *,
    limits: GuardedWebLimits | None = None,
) -> None:
    instance.web_transport = GuardedWebTransport(
        instance.store,
        instance.connectors,
        limits=limits,
        resolver=network.resolver,
        connection_factory=network.factory,
    )


def _request(connector: dict[str, Any], source: dict[str, Any], *, url: str = URL):
    return GuardedWebRequest(
        connector_instance_id=str(connector["id"]),
        source_id=str(source["id"]),
        url=url,
        network_authorization="explicit",
    )


def _snapshot(store: InstanceStore) -> dict[str, Any]:
    return {
        "canonical": {
            kind: store.list_canonical(kind)
            for kind in CANONICAL_KINDS
        },
        "originals": {
            str(item["id"]): store.original_bytes(str(item["id"]))
            for item in store.list_canonical("originals")
        },
        "derived_artifacts": store.list_derived_artifacts(),
        "derived_provenance": store.list_derived_provenance(),
        "derived_text": {
            path.name: path.read_bytes()
            for path in store.paths.derived_text.glob("*.txt")
        },
    }


def _acquire(
    instance: ProvelumeInstance,
    connector: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    return instance.acquire_manual_web(_request(connector, source))


def test_manual_acquisition_preserves_exact_bytes_hash_and_lineage(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    body = b"<h1>Public title</h1><script>private()</script><p>Readable body</p>"
    response = SyntheticResponse(
        headers=[
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
        body=body,
    )
    network = SyntheticNetwork([response])
    _use_network(instance, network)

    result = _acquire(instance, connector, source)
    acquisition = result["acquisition"]

    assert result["status"] == "completed"
    assert result["network_attempted"] is True
    assert result["original_verified"] is True
    assert acquisition["requested_url"] == URL
    assert acquisition["final_url"] == URL
    assert acquisition["locator"] == URL
    assert acquisition["observed_at"] == acquisition["retrieved_at"]
    assert acquisition["media_type"] == "text/html"
    assert acquisition["connector_instance_id"] == connector["id"]
    assert acquisition["authorized_origins"] == ["https://public.example.test"]
    assert acquisition["source_id"] == source["id"]
    assert acquisition["content_hash"] == result["original"]["sha256"]
    assert acquisition["response_size_bytes"] == len(body)
    assert instance.store.original_bytes(result["original"]["id"]) == body
    assert instance.extracted_text(result["document"]["id"]) == (
        "Public title\nReadable body"
    )
    assert result["derived"]["status"] == "created"
    assert result["derived"]["replaces_original"] is False
    assert {
        (edge["from_kind"], edge["relation"], edge["to_kind"])
        for edge in result["provenance"]
    } >= {
        ("source", "observed", "acquisition"),
        ("connector_instance", "acquired_via", "acquisition"),
        ("acquisition", "captured", "original"),
        ("acquisition", "matched", "version"),
        ("original", "materialized_as", "version"),
        ("version", "version_of", "document"),
        ("version", "extracted_to", "derived_artifact"),
    }
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
    operation = instance.connectors.operations.get(result["operation"]["id"])
    assert operation is not None
    evidence = json.dumps(operation)
    assert URL not in evidence
    assert "private()" not in evidence
    assert str(tmp_path) not in evidence
    assert network.requests[0]["method"] == "GET"
    assert all(connection.closed for connection in network.connections)


def test_successful_guarded_redirect_records_canonical_final_url(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    final_url = "https://public.example.test/final"
    body = b"redirected exact bytes"
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                status=302,
                headers=[
                    ("Location", final_url),
                    ("Content-Length", "0"),
                ],
                body=b"",
            ),
            SyntheticResponse(body=body),
        ]
    )
    _use_network(instance, network)

    result = _acquire(instance, connector, source)

    assert result["acquisition"]["requested_url"] == URL
    assert result["acquisition"]["final_url"] == final_url
    assert result["document"]["locator"] == URL
    assert instance.store.original_bytes(result["original"]["id"]) == body
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_replay_is_acquisition_preserving_and_canonical_content_idempotent(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    first_body = b"first exact body"
    second_body = b"second exact body"
    network = SyntheticNetwork(
        [
            SyntheticResponse(body=first_body),
            SyntheticResponse(body=first_body),
            SyntheticResponse(body=second_body),
            SyntheticResponse(body=first_body),
        ]
    )
    _use_network(instance, network)

    first = _acquire(instance, connector, source)
    original_before = dict(first["original"])
    original_bytes_before = instance.store.original_bytes(first["original"]["id"])
    replay = _acquire(instance, connector, source)
    changed = _acquire(instance, connector, source)
    reused = _acquire(instance, connector, source)

    assert [
        first["summary"]["outcome"],
        replay["summary"]["outcome"],
        changed["summary"]["outcome"],
        reused["summary"]["outcome"],
    ] == ["created", "unchanged", "version_created", "version_reused"]
    assert replay["idempotency"] == {
        "scope": "canonical_content",
        "acquisition_per_successful_request": True,
        "replay": True,
        "replay_of_acquisition_id": first["acquisition"]["id"],
        "exact_duplicate": True,
        "canonical_outcome": "unchanged",
    }
    assert reused["summary"]["version_id"] == first["summary"]["version_id"]
    assert len(instance.store.list_canonical("documents")) == 1
    assert len(instance.store.list_canonical("versions")) == 2
    assert len(instance.store.list_canonical("originals")) == 2
    assert len(instance.store.list_canonical("acquisitions")) == 4
    assert instance.store.read_canonical("originals", first["original"]["id"]) == (
        original_before
    )
    assert instance.store.original_bytes(first["original"]["id"]) == (
        original_bytes_before
    )
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_deep_validation_rejects_incomplete_manual_web_provenance(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse()]))
    result = _acquire(instance, connector, source)
    acquisition_id = str(result["acquisition"]["id"])
    captured = next(
        edge
        for edge in instance.store.list_canonical("provenance")
        if edge["from_id"] == acquisition_id and edge["relation"] == "captured"
    )
    (
        instance.store.paths.canonical_dir("provenance")
        / f"{captured['id']}.json"
    ).unlink()

    report = inspect_instance(instance.root, deep=True)

    assert report["status"] == "invalid"
    assert "manual_web_provenance_incomplete" in {
        error["code"] for error in report["errors"]
    }


def test_deep_validation_rejects_final_origin_outside_commit_allowlist(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse()]))
    result = _acquire(instance, connector, source)
    acquisition = dict(result["acquisition"])
    acquisition["final_url"] = "https://other.example.test/final"
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("acquisitions")
        / f"{acquisition['id']}.json",
        acquisition,
    )

    report = inspect_instance(instance.root, deep=True)

    assert report["status"] == "invalid"
    assert "manual_web_acquisition_invalid" in {
        error["code"] for error in report["errors"]
    }


class _FailingReplaceProxy:
    def __init__(self, failure_at: int):
        self.failure_at = failure_at
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(stdlib_os, name)

    def replace(self, source: Any, target: Any) -> None:
        self.calls += 1
        if self.calls == self.failure_at:
            raise OSError("synthetic atomic replacement failure")
        stdlib_os.replace(source, target)


class _CrashingReplaceProxy(_FailingReplaceProxy):
    def replace(self, source: Any, target: Any) -> None:
        self.calls += 1
        if self.calls == self.failure_at:
            raise KeyboardInterrupt
        stdlib_os.replace(source, target)


def test_atomic_commit_rolls_back_every_canonical_and_original_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse(body=b"rollback body")]))
    before = _snapshot(instance.store)
    monkeypatch.setattr(web_acquisition, "os", _FailingReplaceProxy(failure_at=4))

    with pytest.raises(ManualWebAtomicityError):
        _acquire(instance, connector, source)

    assert _snapshot(instance.store) == before
    assert not list(
        (instance.root.parent / f".{instance.root.name}.provelume" / "transactions").glob(
            "manual-web-*"
        )
    )
    operation = instance.connectors.operations.list(kind="connector.web.acquire")[0]
    assert operation["status"] == "failed"
    assert operation["error_code"] == "manual_web_atomic_commit_failed"
    assert URL not in json.dumps(operation)
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_interrupted_commit_is_durably_rolled_back_on_instance_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse(body=b"crash body")]))
    before = _snapshot(instance.store)
    monkeypatch.setattr(web_acquisition, "os", _CrashingReplaceProxy(failure_at=4))

    with pytest.raises(KeyboardInterrupt):
        _acquire(instance, connector, source)

    transaction_root = (
        instance.root.parent / f".{instance.root.name}.provelume" / "transactions"
    )
    assert list(transaction_root.glob("manual-web-*"))
    monkeypatch.setattr(web_acquisition, "os", stdlib_os)
    reopened = ProvelumeInstance(instance.root)

    assert _snapshot(reopened.store) == before
    assert reopened.manual_web_recovery == {
        "schema_version": 1,
        "status": "recovered",
        "rolled_back": 1,
        "committed_cleanups": 0,
    }
    assert not list(transaction_root.glob("manual-web-*"))
    operation = reopened.connectors.operations.list(kind="connector.web.acquire")[0]
    assert operation["status"] == "failed"
    assert operation["error_code"] == "manual_web_interrupted_rollback"
    assert inspect_instance(reopened.root, deep=True)["status"] == "valid"


def test_success_stages_terminal_operation_without_postcommit_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse()]))

    def unexpected(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("postcommit ledger/detail call")

    monkeypatch.setattr(OperationLedger, "close", unexpected)
    monkeypatch.setattr(web_acquisition.ManualWebAcquisitionManager, "get", unexpected)

    result = _acquire(instance, connector, source)

    assert result["status"] == "completed"
    operation = instance.connectors.operations.get(result["operation"]["id"])
    assert operation is not None
    assert operation["status"] == "completed"


class _AfterFetchMutation:
    def __init__(
        self,
        transport: GuardedWebTransport,
        mutate: Any,
    ):
        self.transport = transport
        self.mutate = mutate

    def fetch(self, request: GuardedWebRequest):
        response = self.transport.fetch(request)
        self.mutate()
        return response

    def assert_current_authority(
        self,
        request: GuardedWebRequest,
        *,
        final_url: str | None = None,
    ) -> str:
        return self.transport.assert_current_authority(request, final_url=final_url)

    def current_authority(
        self,
        request: GuardedWebRequest,
        *,
        final_url: str | None = None,
    ):
        return self.transport.current_authority(request, final_url=final_url)


@pytest.mark.parametrize("change", ["instance", "source", "global"])
def test_policy_changes_after_transport_and_before_commit_fail_closed(
    tmp_path: Path,
    change: str,
) -> None:
    instance, connector, source = _configured(tmp_path / change)
    network = SyntheticNetwork([SyntheticResponse(body=b"must not commit")])
    base = GuardedWebTransport(
        instance.store,
        instance.connectors,
        resolver=network.resolver,
        connection_factory=network.factory,
    )

    def mutate() -> None:
        other = ProvelumeInstance(instance.root)
        if change == "instance":
            other.disable_connector_instance(str(connector["id"]))
        elif change == "source":
            other.disable_connector_source(str(connector["id"]), str(source["id"]))
        else:
            _enable_network(other, False)

    instance.web_transport = _AfterFetchMutation(base, mutate)
    before = _snapshot(instance.store)

    with pytest.raises(WebTransportPolicyError):
        _acquire(instance, connector, source)

    after = _snapshot(instance.store)
    for kind in ("acquisitions", "documents", "versions", "originals", "provenance"):
        assert after["canonical"][kind] == before["canonical"][kind]
    assert after["originals"] == before["originals"]
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


@dataclass
class SyntheticOAuthAdapter:
    adapter_key: str = "manual-web-oauth"
    adapter_version: str = "1.0.0"
    authorization_endpoint: str = "https://oauth.example.test/authorize"
    token_endpoint: str = "https://oauth.example.test/token"

    def build_authorization_uri(
        self,
        request: InstalledAppAuthorizationParameters,
    ) -> str:
        return self.authorization_endpoint + "?" + urlencode(
            {
                "response_type": "code",
                "state": request.state,
                "code_challenge": request.code_challenge,
                "code_challenge_method": request.code_challenge_method,
                "redirect_uri": request.redirect_uri,
                "scope": " ".join(request.scopes),
                "prompt": "consent",
                "client_id": "synthetic-installed-app",
            }
        )

    def exchange_callback(self, exchange: InstalledAppTokenExchange) -> dict[str, Any]:
        return {
            "credential_reference": {
                "kind": "system_keyring",
                "name": "provelume:manual-web-oauth",
            },
            "account_identity": "synthetic-account",
            "granted_scopes": list(exchange.granted_scopes),
        }


def test_oauth_revocation_after_transport_and_before_commit_fails_closed(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "oauth-instance")
    _enable_network(instance)
    definition = instance.register_connector_definition(
        _manifest(
            adapter_key="manual-web-oauth",
            authorization_modes=["oauth2_pkce"],
            oauth=True,
        )
    )
    connector = instance.create_connector_instance(
        str(definition["id"]),
        name="OAuth web account",
        provider_identity="synthetic-provider",
        endpoint="https://public.example.test",
        network_mode="explicit",
        allowed_origins=[
            "https://public.example.test",
            "https://oauth.example.test",
        ],
        authorization_mode="oauth2_pkce",
        scopes=["content.read"],
    )
    source = instance.add_connector_source(
        str(connector["id"]),
        name="OAuth article",
        source_kind="web",
        external_id=URL,
    )
    adapter = SyntheticOAuthAdapter()
    redirect_uri = "http://127.0.0.1:49152/oauth/callback"
    authorization = instance.begin_connector_authorization(
        str(connector["id"]),
        adapter,
        redirect_uri=redirect_uri,
        consent=True,
    )
    state = parse_qs(urlsplit(authorization["authorization_uri"]).query)["state"][0]
    instance.complete_connector_authorization(
        str(connector["id"]),
        adapter,
        {
            "request_id": authorization["request_id"],
            "redirect_uri": redirect_uri,
            "state": state,
            "authorization_code": "sensitive-code",
            "granted_scopes": ["content.read"],
        },
    )
    network = SyntheticNetwork([SyntheticResponse(body=b"revoked before commit")])
    base = GuardedWebTransport(
        instance.store,
        instance.connectors,
        resolver=network.resolver,
        connection_factory=network.factory,
    )
    instance.web_transport = _AfterFetchMutation(
        base,
        lambda: ProvelumeInstance(instance.root).revoke_connector_authorization(
            str(connector["id"])
        ),
    )

    with pytest.raises(WebTransportPolicyError):
        _acquire(instance, connector, source)

    assert instance.store.list_canonical("acquisitions") == []
    assert instance.store.list_canonical("documents") == []
    assert instance.store.list_canonical("originals") == []
    evidence = json.dumps(instance.connectors.operations.list(limit=100))
    assert "sensitive-code" not in evidence
    assert URL not in evidence


class _ConcurrentGlobalDisable:
    def __init__(self, transport: GuardedWebTransport, instance_root: Path):
        self.transport = transport
        self.instance_root = instance_root
        self.started = Event()
        self.finished = Event()
        self.thread: Thread | None = None

    def fetch(self, request: GuardedWebRequest):
        return self.transport.fetch(request)

    def current_authority(
        self,
        request: GuardedWebRequest,
        *,
        final_url: str | None = None,
    ):
        authority = self.transport.current_authority(request, final_url=final_url)

        def disable() -> None:
            self.started.set()
            declare_startup_update_policy(self.instance_root, enabled=False)
            self.finished.set()

        self.thread = Thread(target=disable)
        self.thread.start()
        assert self.started.wait(timeout=2)
        assert not self.finished.is_set()
        return authority


def test_global_policy_writer_serializes_after_canonical_commit(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    network = SyntheticNetwork([SyntheticResponse(body=b"locked policy commit")])
    base = GuardedWebTransport(
        instance.store,
        instance.connectors,
        resolver=network.resolver,
        connection_factory=network.factory,
    )
    guarded = _ConcurrentGlobalDisable(base, instance.root)
    instance.web_transport = guarded

    result = _acquire(instance, connector, source)

    assert guarded.thread is not None
    guarded.thread.join(timeout=5)
    assert guarded.finished.is_set()
    assert instance.store.read_config()["network"]["external_access"] is False
    assert result["status"] == "completed"
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def _hostile_case(name: str) -> tuple[SyntheticNetwork, GuardedWebLimits | None, type[Exception]]:
    if name == "ssrf":
        return (
            SyntheticNetwork(
                [SyntheticResponse()],
                answers={"public.example.test": [["127.0.0.1"]]},
            ),
            None,
            WebTransportDestinationError,
        )
    if name == "rebinding":
        return (
            SyntheticNetwork(
                [SyntheticResponse()],
                answers={
                    "public.example.test": [[PUBLIC_IPV4], ["169.254.169.254"]]
                },
            ),
            None,
            WebTransportDnsRebindingError,
        )
    if name == "redirect":
        return (
            SyntheticNetwork(
                [
                    SyntheticResponse(
                        status=302,
                        headers=[
                            ("Location", "https://private.example.test/final"),
                            ("Content-Length", "0"),
                        ],
                        body=b"",
                    )
                ]
            ),
            None,
            WebTransportRedirectError,
        )
    if name == "timeout":
        return (
            SyntheticNetwork([SyntheticResponse(timeout_on_read=True)]),
            None,
            WebTransportTimeoutError,
        )
    if name == "malformed":
        return (
            SyntheticNetwork(
                [
                    SyntheticResponse(
                        headers=[
                            ("Content-Type", "text/plain"),
                            ("Content-Type", "text/html"),
                            ("Content-Length", "1"),
                        ],
                        body=b"x",
                    )
                ]
            ),
            None,
            WebTransportHeaderError,
        )
    if name == "truncated":
        return (
            SyntheticNetwork(
                [
                    SyntheticResponse(
                        headers=[
                            ("Content-Type", "text/plain"),
                            ("Content-Length", "100"),
                        ],
                        body=b"short",
                    )
                ]
            ),
            None,
            WebTransportTruncatedError,
        )
    if name == "oversize":
        return (
            SyntheticNetwork([SyntheticResponse(body=b"12345")]),
            GuardedWebLimits(max_compressed_bytes=4, max_decompressed_bytes=10),
            WebTransportBodyLimitError,
        )
    if name == "compressed":
        malformed = gzip.compress(b"private compressed body", mtime=0)[:-2]
        return (
            SyntheticNetwork(
                [
                    SyntheticResponse(
                        headers=[
                            ("Content-Type", "text/plain"),
                            ("Content-Encoding", "gzip"),
                            ("Content-Length", str(len(malformed))),
                        ],
                        body=malformed,
                    )
                ]
            ),
            None,
            WebTransportTruncatedError,
        )
    raise AssertionError(name)


@pytest.mark.parametrize(
    "name",
    [
        "ssrf",
        "rebinding",
        "redirect",
        "timeout",
        "malformed",
        "truncated",
        "oversize",
        "compressed",
    ],
)
def test_hostile_s04_failures_create_no_s05_partial_state(
    tmp_path: Path,
    name: str,
) -> None:
    instance, connector, source = _configured(tmp_path / name)
    network, limits, expected = _hostile_case(name)
    _use_network(instance, network, limits=limits)
    before = _snapshot(instance.store)

    with pytest.raises(expected):
        _acquire(instance, connector, source)

    assert _snapshot(instance.store) == before
    evidence = json.dumps(instance.connectors.operations.list(kind="connector.web.acquire"))
    assert URL not in evidence
    assert "private compressed body" not in evidence
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_multi_instance_acquisition_isolation(tmp_path: Path) -> None:
    instance, first_connector, first_source = _configured(tmp_path / "instance")
    definition_id = str(first_connector["definition_id"])
    second_connector = instance.create_connector_instance(
        definition_id,
        name="Second account",
        provider_identity="second-provider",
        endpoint="https://second.example.test",
        network_mode="explicit",
        allowed_origins=["https://second.example.test"],
        authorization_mode="none",
    )
    second_source = instance.add_connector_source(
        str(second_connector["id"]),
        name="Second article",
        source_kind="web",
        external_id="https://second.example.test/article",
    )
    _use_network(instance, SyntheticNetwork([SyntheticResponse(body=b"first only")]))

    result = _acquire(instance, first_connector, first_source)

    assert result["acquisition"]["connector_instance_id"] == first_connector["id"]
    assert instance.list_manual_web_acquisitions(
        str(second_connector["id"]),
        str(second_source["id"]),
    ) == []
    assert all(
        document["source_id"] == first_source["id"]
        for document in instance.store.list_canonical("documents")
    )
    assert instance.get_connector_instance(str(second_connector["id"])) is not None
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_backup_restore_and_portable_transfer_preserve_web_records(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path / "source-instance")
    body = b"portable exact web body"
    _use_network(
        instance,
        SyntheticNetwork(
            [SyntheticResponse(body=body), SyntheticResponse(body=b"later body")]
        ),
    )
    acquired = _acquire(instance, connector, source)
    backup_path = tmp_path / "backup.zip"
    backup = instance.backup(destination=backup_path, reason="manual-web-test")
    assert verify_backup(backup_path)["status"] == "valid"
    _acquire(instance, connector, source)
    assert len(instance.store.list_canonical("acquisitions")) == 2

    instance.restore(backup_path)
    restored = ProvelumeInstance(instance.root)
    assert len(restored.store.list_canonical("acquisitions")) == 1
    assert restored.store.original_bytes(acquired["original"]["id"]) == body
    assert restored.extracted_text(acquired["document"]["id"]) == body.decode()
    assert restored.validate_instance(deep=True)["status"] == "valid"

    portable_path = tmp_path / "portable.zip"
    restored.export_portable(portable_path)
    target = ProvelumeInstance.initialise(tmp_path / "target-instance")
    target.import_portable(portable_path)
    imported = ProvelumeInstance(target.root)
    detail = imported.get_manual_web_acquisition(
        str(connector["id"]),
        str(source["id"]),
        str(acquired["acquisition"]["id"]),
    )
    assert detail is not None
    assert detail["original"]["sha256"] == acquired["original"]["sha256"]
    assert imported.store.original_bytes(detail["original"]["id"]) == body
    assert imported.validate_instance(deep=True)["status"] == "valid"
    assert backup["content_fingerprint"] == restored.validate_instance(deep=True)[
        "content_fingerprint"
    ]


def test_web_media_type_controls_rebuild_even_when_url_has_file_suffix(
    tmp_path: Path,
) -> None:
    url = "https://public.example.test/not-really-a.pdf"
    instance, connector, source = _configured(tmp_path / "instance", url=url)
    body = b"<h1>Media type wins</h1>"
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "text/html"),
                    ("Content-Length", str(len(body))),
                ],
                body=body,
            )
        ]
    )
    _use_network(instance, network)
    result = instance.acquire_manual_web(
        _request(connector, source, url=url),
    )
    artifact = result["derived"]["artifact"]
    assert artifact is not None
    Path(instance.root, artifact["storage_ref"]).unlink()
    Path(
        instance.root,
        "state",
        "derived",
        "artifacts",
        f"{artifact['id']}.json",
    ).unlink()

    instance.rebuild_index()

    assert instance.extracted_text(result["document"]["id"]) == "Media type wins"


def test_api_browser_and_italian_views_share_read_only_service_detail(
    tmp_path: Path,
) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    _use_network(instance, SyntheticNetwork([SyntheticResponse(body=b"surface body")]))
    acquired = _acquire(instance, connector, source)
    acquisition_id = str(acquired["acquisition"]["id"])
    connector_id = str(connector["id"])
    source_id = str(source["id"])
    client = TestClient(create_app(instance.root))
    collection_path = (
        f"/api/v1/connectors/{connector_id}/sources/{source_id}/acquisitions"
    )
    detail_path = f"{collection_path}/{acquisition_id}"

    collection = client.get(collection_path)
    detail = client.get(detail_path)
    source_page = client.get(
        f"/connectors/{connector_id}/sources/{source_id}",
        params={"lang": "en"},
    )
    detail_page = client.get(
        f"/connectors/{connector_id}/sources/{source_id}/acquisitions/{acquisition_id}",
        params={"lang": "it"},
    )

    assert collection.status_code == detail.status_code == 200
    assert collection.json()[0] == acquired["summary"]
    assert detail.json()["acquisition"] == acquired["acquisition"]
    assert acquisition_id in source_page.text
    assert "Manual web acquisitions" in source_page.text
    assert "Acquisizione web manuale" in detail_page.text
    assert "URL canonico richiesto" in detail_page.text
    assert client.post(collection_path, json={}).status_code == 405
    assert client.post(detail_path, json={}).status_code == 405


def test_cli_requires_explicit_command_and_redacts_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_url = "https://public.example.test/article?private=secret-value"
    instance, connector, source = _configured(
        tmp_path / "instance",
        url=secret_url,
    )
    success = SyntheticNetwork([SyntheticResponse(body=b"CLI exact bytes")])
    _use_network(instance, success)
    monkeypatch.setattr(connector_cli, "ProvelumeInstance", lambda _root: instance)
    arguments = [
        "connector-web-acquire",
        str(instance.root),
        str(connector["id"]),
        str(source["id"]),
        secret_url,
        "--confirm-network",
    ]

    assert main(arguments) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["network_attempted"] is True
    assert result["acquisition"]["requested_url"] == secret_url

    failure = SyntheticNetwork(
        [SyntheticResponse(body=b"private response body", timeout_on_read=True)]
    )
    _use_network(instance, failure)
    assert main(arguments) == 2
    output = capsys.readouterr().out
    error = json.loads(output)
    assert error["error_code"] == "web_transport_timeout"
    assert secret_url not in output
    assert "private response body" not in output
    assert str(tmp_path) not in output


def test_unreadable_pdf_is_acquired_without_ocr_or_invented_text(tmp_path: Path) -> None:
    instance, connector, source = _configured(tmp_path / "instance")
    body = b"not a readable synthetic PDF"
    network = SyntheticNetwork(
        [
            SyntheticResponse(
                headers=[
                    ("Content-Type", "application/pdf"),
                    ("Content-Length", str(len(body))),
                ],
                body=body,
            )
        ]
    )
    _use_network(instance, network)

    result = _acquire(instance, connector, source)

    assert result["status"] == "completed"
    assert result["derived"] == {
        "status": "unavailable",
        "artifact": None,
        "rebuildable": True,
        "replaces_original": False,
    }
    assert instance.extracted_text(result["document"]["id"]) is None
    assert instance.store.original_bytes(result["original"]["id"]) == body
    operation = instance.connectors.operations.get(result["operation"]["id"])
    assert operation is not None
    assert any(event["code"] == "manual_web.derived_unavailable" for event in operation["events"])
    assert "OCR" not in json.dumps(operation)
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"
