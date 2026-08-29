from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Protocol
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from weakref import WeakValueDictionary

from .connector_model import (
    ConnectorError,
    ConnectorNotFoundError,
    normalise_connector_origin,
    normalise_oauth_scopes,
    normalise_secret_reference,
)
from .connectors import ConnectorManager
from .operations import OperationLedger
from .storage import InstanceStore

OAUTH_AUTHORIZATION_SCHEMA_VERSION = 1
DEFAULT_STATE_TTL_SECONDS = 300
MIN_STATE_TTL_SECONDS = 30
MAX_STATE_TTL_SECONDS = 600
MAX_PENDING_AUTHORIZATIONS = 32
MAX_TERMINAL_REQUESTS = 256

_REQUEST_ID = re.compile(r"oauth_request_[0-9a-f]{32}\Z")
_ADAPTER_KEY = re.compile(r"[a-z][a-z0-9-]{0,47}\Z")
_ADAPTER_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_URLSAFE_SECRET = re.compile(r"[A-Za-z0-9_-]{43,128}\Z")
_SENSITIVE_RESPONSE_KEYS = frozenset(
    {
        "access_token",
        "authorization_code",
        "client_assertion",
        "client_secret",
        "code_verifier",
        "id_token",
        "password",
        "refresh_token",
        "token",
    }
)
_CALLBACK_KEYS = frozenset(
    {"request_id", "redirect_uri", "state", "authorization_code", "granted_scopes"}
)
_GRANT_KEYS = frozenset({"credential_reference", "account_identity", "granted_scopes"})


class OAuthAuthorizationError(ConnectorError):
    pass


class OAuthPolicyError(OAuthAuthorizationError):
    pass


class OAuthStateMismatchError(OAuthAuthorizationError):
    pass


class OAuthReplayError(OAuthAuthorizationError):
    pass


class OAuthStateExpiredError(OAuthAuthorizationError):
    pass


class OAuthScopeError(OAuthAuthorizationError):
    pass


class OAuthCallbackError(OAuthAuthorizationError):
    pass


class OAuthAdapterError(OAuthAuthorizationError):
    pass


class OAuthSecretLeakError(OAuthAdapterError):
    pass


@dataclass(frozen=True, slots=True)
class InstalledAppAuthorizationParameters:
    request_id: str
    redirect_uri: str
    state: str = field(repr=False)
    code_challenge: str
    code_challenge_method: str
    scopes: tuple[str, ...]
    consent: str


@dataclass(frozen=True, slots=True)
class InstalledAppTokenExchange:
    redirect_uri: str
    authorization_code: str = field(repr=False)
    pkce_verifier: str = field(repr=False)
    granted_scopes: tuple[str, ...]


class InstalledAppOAuthAdapter(Protocol):
    adapter_key: str
    adapter_version: str
    authorization_endpoint: str
    token_endpoint: str

    def build_authorization_uri(
        self,
        request: InstalledAppAuthorizationParameters,
    ) -> str: ...

    def exchange_callback(
        self,
        exchange: InstalledAppTokenExchange,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class _AdapterContract:
    adapter_key: str
    adapter_version: str
    authorization_endpoint: str
    authorization_origin: str
    token_endpoint: str
    token_origin: str


@dataclass(frozen=True, slots=True)
class _PendingAuthorization:
    request_id: str
    connector_instance_id: str
    connector_record_sha256: str
    adapter: _AdapterContract
    redirect_uri: str
    scopes: tuple[str, ...]
    state: str = field(repr=False)
    verifier: str = field(repr=False)
    expires_at: datetime


def _normalise_scopes(value: Any) -> tuple[str, ...]:
    try:
        result = tuple(normalise_oauth_scopes(value))
    except ConnectorError as exc:
        raise OAuthScopeError(str(exc)) from exc
    if not result:
        raise OAuthScopeError("OAuth authorization requires at least one scope")
    return result


def _normalise_loopback_redirect(value: Any) -> str:
    if not isinstance(value, str) or value != value.strip() or "\\" in value:
        raise OAuthCallbackError("installed-app redirect URI is invalid")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise OAuthCallbackError("installed-app redirect URI is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1024 <= port <= 65535
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise OAuthCallbackError(
            "installed-app redirect URI must be an exact high-port loopback callback"
        )
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    canonical = f"http://{host}:{port}{parsed.path}"
    if value != canonical:
        raise OAuthCallbackError("installed-app redirect URI must use canonical exact form")
    return canonical


def _normalise_https_endpoint(value: Any, label: str) -> tuple[str, str]:
    if not isinstance(value, str) or value != value.strip() or "\\" in value:
        raise OAuthAdapterError(f"{label} is invalid")
    try:
        parsed = urlsplit(value)
    except (UnicodeError, ValueError) as exc:
        raise OAuthAdapterError(f"{label} is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/")
        or parsed.path == "/"
        or parsed.query
        or parsed.fragment
    ):
        raise OAuthAdapterError(f"{label} must be an HTTPS endpoint without credentials")
    origin = normalise_connector_origin(f"https://{parsed.netloc}")
    canonical = f"{origin}{parsed.path}"
    if value != canonical:
        raise OAuthAdapterError(f"{label} must use canonical exact form")
    return canonical, origin


def _adapter_contract(adapter: InstalledAppOAuthAdapter) -> _AdapterContract:
    adapter_key = getattr(adapter, "adapter_key", None)
    adapter_version = getattr(adapter, "adapter_version", None)
    if not isinstance(adapter_key, str) or _ADAPTER_KEY.fullmatch(adapter_key) is None:
        raise OAuthAdapterError("OAuth adapter key is invalid")
    if not isinstance(adapter_version, str) or _ADAPTER_VERSION.fullmatch(adapter_version) is None:
        raise OAuthAdapterError("OAuth adapter version is invalid")
    authorization_endpoint, authorization_origin = _normalise_https_endpoint(
        getattr(adapter, "authorization_endpoint", None),
        "OAuth authorization endpoint",
    )
    token_endpoint, token_origin = _normalise_https_endpoint(
        getattr(adapter, "token_endpoint", None),
        "OAuth token endpoint",
    )
    return _AdapterContract(
        adapter_key=adapter_key,
        adapter_version=adapter_version,
        authorization_endpoint=authorization_endpoint,
        authorization_origin=authorization_origin,
        token_endpoint=token_endpoint,
        token_origin=token_origin,
    )


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _single_query_value(query: Mapping[str, list[str]], key: str) -> str:
    values = query.get(key)
    if values is None or len(values) != 1:
        raise OAuthAdapterError(f"authorization URI must bind exactly one {key}")
    return values[0]


def _validate_authorization_uri(
    value: Any,
    *,
    contract: _AdapterContract,
    request: InstalledAppAuthorizationParameters,
) -> str:
    if not isinstance(value, str) or value != value.strip():
        raise OAuthAdapterError("OAuth adapter returned an invalid authorization URI")
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True)
    except (UnicodeError, ValueError) as exc:
        raise OAuthAdapterError("OAuth adapter returned an invalid authorization URI") from exc
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if base != contract.authorization_endpoint or parsed.fragment:
        raise OAuthAdapterError("OAuth adapter substituted the authorization endpoint")
    leaked = _SENSITIVE_RESPONSE_KEYS.intersection(query)
    if leaked:
        raise OAuthSecretLeakError("authorization URI contains prohibited secret material")
    expected = {
        "response_type": "code",
        "redirect_uri": request.redirect_uri,
        "state": request.state,
        "code_challenge": request.code_challenge,
        "code_challenge_method": "S256",
        "scope": " ".join(request.scopes),
        "prompt": "consent",
    }
    for key, selected in expected.items():
        if not hmac.compare_digest(_single_query_value(query, key), selected):
            raise OAuthAdapterError(f"authorization URI did not preserve the {key} binding")
    return value


def _normalise_callback(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _CALLBACK_KEYS:
        raise OAuthCallbackError("OAuth callback has missing or unsupported fields")
    request_id = value.get("request_id")
    redirect_uri = value.get("redirect_uri")
    state = value.get("state")
    code = value.get("authorization_code")
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise OAuthCallbackError("OAuth callback request identity is invalid")
    if not isinstance(state, str) or _URLSAFE_SECRET.fullmatch(state) is None:
        raise OAuthCallbackError("OAuth callback state is invalid")
    if (
        not isinstance(code, str)
        or not code
        or len(code) > 2048
        or any(unicodedata.category(character) in {"Cc", "Cs"} for character in code)
    ):
        raise OAuthCallbackError("OAuth authorization code is invalid")
    return {
        "request_id": request_id,
        "redirect_uri": _normalise_loopback_redirect(redirect_uri),
        "state": state,
        "authorization_code": code,
        "granted_scopes": _normalise_scopes(value.get("granted_scopes")),
    }


def _normalise_account_identity(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise OAuthAdapterError("OAuth account identity must be text")
    selected = unicodedata.normalize("NFC", value.strip())
    if (
        not selected
        or len(selected) > 256
        or any(unicodedata.category(character) in {"Cc", "Cs"} for character in selected)
    ):
        raise OAuthAdapterError("OAuth account identity is invalid")
    return selected


def _normalise_grant(value: Any, expected_scopes: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OAuthAdapterError("OAuth adapter grant must be an object")
    extra = set(value) - _GRANT_KEYS
    if extra:
        if any(str(key).casefold() in _SENSITIVE_RESPONSE_KEYS for key in extra):
            raise OAuthSecretLeakError("OAuth adapter returned prohibited secret material")
        raise OAuthAdapterError("OAuth adapter grant has unsupported fields")
    if set(value) != _GRANT_KEYS:
        raise OAuthAdapterError("OAuth adapter grant has missing fields")
    scopes = _normalise_scopes(value.get("granted_scopes"))
    if scopes != expected_scopes:
        raise OAuthScopeError("OAuth adapter grant changed the least-privilege scope set")
    reference = normalise_secret_reference(value.get("credential_reference"))
    if reference is None:
        raise OAuthAdapterError("OAuth adapter must return an external credential reference")
    return {
        "credential_reference": reference,
        "account_identity": _normalise_account_identity(value.get("account_identity")),
        "granted_scopes": scopes,
    }


class InstalledAppAuthorizationManager:
    """Own short-lived installed-app OAuth state without persisting sensitive material."""

    def __init__(
        self,
        store: InstanceStore,
        connectors: ConnectorManager,
        *,
        clock: Callable[[], datetime] | None = None,
        secret_factory: Callable[[int], str] | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ):
        self.store = store
        self.connectors = connectors
        self.operations = OperationLedger(store)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._secret_factory = secret_factory or secrets.token_urlsafe
        self._request_id_factory = request_id_factory or (
            lambda: f"oauth_request_{uuid4().hex}"
        )
        self._pending: dict[str, _PendingAuthorization] = {}
        self._terminal: OrderedDict[str, str] = OrderedDict()
        self._state_lock = Lock()
        self._connector_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()

    @staticmethod
    def _operation_view(record: Any) -> dict[str, Any]:
        return {
            "id": record.id,
            "status": record.status,
            "completed_at": record.completed_at,
        }

    def _now(self) -> datetime:
        selected = self._clock()
        if selected.tzinfo is None or selected.utcoffset() is None:
            raise OAuthAuthorizationError("OAuth authorization clock must be offset-aware")
        return selected.astimezone(UTC)

    def _connector_lock(self, connector_instance_id: str) -> Lock:
        with self._state_lock:
            return self._connector_locks.setdefault(connector_instance_id, Lock())

    def _terminate(self, request_id: str, reason: str) -> None:
        self._terminal[request_id] = reason
        self._terminal.move_to_end(request_id)
        while len(self._terminal) > MAX_TERMINAL_REQUESTS:
            self._terminal.popitem(last=False)

    def _expire_pending(self, now: datetime) -> None:
        for request_id, pending in tuple(self._pending.items()):
            if now >= pending.expires_at:
                self._pending.pop(request_id, None)
                self._terminate(request_id, "expired")

    def _policy_contract(
        self,
        connector_instance_id: str,
        adapter: InstalledAppOAuthAdapter,
    ) -> tuple[dict[str, Any], _AdapterContract, tuple[str, ...]]:
        connector = self.connectors.get_instance(connector_instance_id)
        if connector is None:
            raise ConnectorNotFoundError(
                f"connector instance not found: {connector_instance_id}"
            )
        definition = connector["definition"]
        if (
            connector["lifecycle_state"] != "active"
            or not connector["configured_enabled"]
            or connector["authorization_mode"] != "oauth2_pkce"
            or "oauth2_pkce_authorization" not in definition["capabilities"]
        ):
            raise OAuthPolicyError(
                "OAuth authorization requires an active enabled PKCE connector instance"
            )
        if connector["effective_network"] != "explicit":
            raise OAuthPolicyError(
                "OAuth authorization is blocked by connector or Instance network policy"
            )
        contract = _adapter_contract(adapter)
        if (
            contract.adapter_key != definition["adapter_key"]
            or contract.adapter_version != definition["adapter_version"]
        ):
            raise OAuthAdapterError(
                "OAuth adapter identity does not match the connector definition"
            )
        allowed_origins = set(connector["allowed_origins"])
        if {
            contract.authorization_origin,
            contract.token_origin,
        } - allowed_origins:
            raise OAuthPolicyError(
                "OAuth endpoints must be explicitly present in the connector origin allowlist"
            )
        return connector, contract, _normalise_scopes(connector["scopes"])

    def _start_operation(self, kind: str, title: str, connector_instance_id: str) -> Any:
        return self.operations.start(
            kind,
            title,
            summary="Evaluate the installed-app OAuth boundary without logging sensitive material.",
            related={"connector_instance_id": connector_instance_id},
        )

    def _fail_operation(self, operation: Any, exc: Exception) -> None:
        current = self.operations.get_record(operation.id)
        if current is None or current.status != "running":
            return
        self.operations.append(
            operation.id,
            f"{operation.kind}.failed",
            "OAuth authorization failed closed without changing canonical knowledge.",
            level="error",
            details={
                "error_type": exc.__class__.__name__,
                "sensitive_material_logged": False,
                "original_action": "none",
            },
        )
        self.operations.close(
            operation.id,
            status="failed",
            summary="OAuth authorization failed closed without changing canonical knowledge.",
            metrics={"originals_deleted": 0, "originals_overwritten": 0},
            error_code="oauth_authorization_failed",
            error=exc.__class__.__name__,
        )

    def begin(
        self,
        connector_instance_id: str,
        adapter: InstalledAppOAuthAdapter,
        *,
        redirect_uri: str,
        consent: bool,
        state_ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS,
    ) -> dict[str, Any]:
        operation = self._start_operation(
            "connector.authorization.request",
            "Prepare installed-app OAuth authorization",
            connector_instance_id,
        )
        connector_lock = self._connector_lock(connector_instance_id)
        connector_lock.acquire()
        try:
            if consent is not True:
                raise OAuthPolicyError("OAuth authorization requires explicit consent")
            if (
                type(state_ttl_seconds) is not int
                or not MIN_STATE_TTL_SECONDS <= state_ttl_seconds <= MAX_STATE_TTL_SECONDS
            ):
                raise OAuthStateExpiredError(
                    "OAuth state lifetime is outside the short-lived bound"
                )
            now = self._now()
            with self._state_lock:
                self._expire_pending(now)
                if len(self._pending) >= MAX_PENDING_AUTHORIZATIONS:
                    raise OAuthPolicyError("too many pending OAuth authorization requests")
            connector, contract, scopes = self._policy_contract(
                connector_instance_id,
                adapter,
            )
            connector_record_sha256 = self.connectors.authorization_fingerprint(
                connector_instance_id
            )
            selected_redirect = _normalise_loopback_redirect(redirect_uri)
            request_id = self._request_id_factory()
            state = self._secret_factory(32)
            verifier = self._secret_factory(64)
            if (
                not isinstance(request_id, str)
                or _REQUEST_ID.fullmatch(request_id) is None
                or not isinstance(state, str)
                or _URLSAFE_SECRET.fullmatch(state) is None
                or not isinstance(verifier, str)
                or _URLSAFE_SECRET.fullmatch(verifier) is None
            ):
                raise OAuthAuthorizationError(
                    "OAuth request entropy source returned invalid material"
                )
            challenge = _pkce_challenge(verifier)
            parameters = InstalledAppAuthorizationParameters(
                request_id=request_id,
                redirect_uri=selected_redirect,
                state=state,
                code_challenge=challenge,
                code_challenge_method="S256",
                scopes=scopes,
                consent="explicit",
            )
            authorization_uri = _validate_authorization_uri(
                adapter.build_authorization_uri(parameters),
                contract=contract,
                request=parameters,
            )
            if (
                self.connectors.authorization_fingerprint(connector_instance_id)
                != connector_record_sha256
            ):
                raise OAuthPolicyError(
                    "connector instance changed while preparing OAuth authorization"
                )
            expires_at = now + timedelta(seconds=state_ttl_seconds)
            pending = _PendingAuthorization(
                request_id=request_id,
                connector_instance_id=connector_instance_id,
                connector_record_sha256=connector_record_sha256,
                adapter=contract,
                redirect_uri=selected_redirect,
                scopes=scopes,
                state=state,
                verifier=verifier,
                expires_at=expires_at,
            )
            with self._state_lock:
                self._expire_pending(self._now())
                if (
                    len(self._pending) >= MAX_PENDING_AUTHORIZATIONS
                    or request_id in self._pending
                    or request_id in self._terminal
                ):
                    raise OAuthPolicyError(
                        "OAuth request identity collided or the pending limit was reached"
                    )
                self._pending[request_id] = pending
            self.operations.append(
                operation.id,
                "connector.authorization.request.prepared",
                "A short-lived PKCE S256 request was prepared for explicit user consent.",
                details={
                    "pkce_method": "S256",
                    "redirect_binding": "loopback",
                    "consent": "explicit",
                    "state_ttl_seconds": state_ttl_seconds,
                    "scope_count": len(scopes),
                    "core_network_attempted": False,
                    "sensitive_material_logged": False,
                },
            )
            closed = self.operations.close(
                operation.id,
                status="completed",
                summary="Installed-app OAuth request prepared without Core network access.",
                metrics={
                    "scope_count": len(scopes),
                    "state_ttl_seconds": state_ttl_seconds,
                    "originals_deleted": 0,
                    "originals_overwritten": 0,
                },
            )
            return {
                "schema_version": OAUTH_AUTHORIZATION_SCHEMA_VERSION,
                "request_id": request_id,
                "authorization_uri": authorization_uri,
                "redirect_uri": selected_redirect,
                "expires_at": expires_at.isoformat(),
                "scopes": list(scopes),
                "pkce": {"method": "S256"},
                "consent": "explicit",
                "reauthorization": connector["authorization"]["status"]
                in {"authorized", "legacy_reference", "revoked"},
                "network_boundary": "policy_gated_adapter",
                "network_attempted": False,
                "operation": self._operation_view(closed),
            }
        except Exception as exc:
            self._fail_operation(operation, exc)
            raise
        finally:
            connector_lock.release()

    def complete(
        self,
        connector_instance_id: str,
        adapter: InstalledAppOAuthAdapter,
        callback: Mapping[str, Any],
    ) -> dict[str, Any]:
        operation = self._start_operation(
            "connector.authorization.callback",
            "Complete installed-app OAuth callback",
            connector_instance_id,
        )
        connector_lock = self._connector_lock(connector_instance_id)
        connector_lock.acquire()
        try:
            selected = _normalise_callback(callback)
            now = self._now()
            request_id = selected["request_id"]
            with self._state_lock:
                pending = self._pending.get(request_id)
                terminal = self._terminal.get(request_id)
                if pending is None:
                    if terminal == "expired":
                        raise OAuthStateExpiredError("OAuth authorization state has expired")
                    if terminal is not None:
                        raise OAuthReplayError(
                            "OAuth authorization callback was already consumed"
                        )
                    raise OAuthStateMismatchError("OAuth authorization state does not match")
                if pending.connector_instance_id != connector_instance_id:
                    raise OAuthStateMismatchError("OAuth authorization state does not match")
                if now >= pending.expires_at:
                    self._pending.pop(request_id, None)
                    self._terminate(request_id, "expired")
                    raise OAuthStateExpiredError("OAuth authorization state has expired")
                if not hmac.compare_digest(selected["state"], pending.state):
                    raise OAuthStateMismatchError("OAuth authorization state does not match")
                self._pending.pop(request_id, None)
                self._terminate(request_id, "callback_consumed")
            if not hmac.compare_digest(selected["redirect_uri"], pending.redirect_uri):
                raise OAuthCallbackError("OAuth callback redirect binding does not match")
            if selected["granted_scopes"] != pending.scopes:
                raise OAuthScopeError("OAuth callback changed the least-privilege scope set")
            _connector, contract, configured_scopes = self._policy_contract(
                connector_instance_id,
                adapter,
            )
            if contract != pending.adapter or configured_scopes != pending.scopes:
                raise OAuthCallbackError("OAuth adapter or policy changed during authorization")
            if (
                self.connectors.authorization_fingerprint(connector_instance_id)
                != pending.connector_record_sha256
            ):
                raise OAuthCallbackError(
                    "connector instance changed during OAuth authorization"
                )
            exchange = InstalledAppTokenExchange(
                redirect_uri=pending.redirect_uri,
                authorization_code=selected["authorization_code"],
                pkce_verifier=pending.verifier,
                granted_scopes=pending.scopes,
            )
            def grant_factory() -> dict[str, Any]:
                return _normalise_grant(
                    adapter.exchange_callback(exchange),
                    pending.scopes,
                )

            completed = self.connectors.complete_oauth_authorization(
                connector_instance_id,
                grant_factory=grant_factory,
                authorized_at=now.isoformat(),
                expected_record_sha256=pending.connector_record_sha256,
            )
            with self._state_lock:
                for sibling_id, sibling in tuple(self._pending.items()):
                    if sibling.connector_instance_id == connector_instance_id:
                        self._pending.pop(sibling_id, None)
                        self._terminate(sibling_id, "superseded")
            self.operations.append(
                operation.id,
                "connector.authorization.callback.completed",
                "PKCE callback bindings passed and only redacted authorization metadata was saved.",
                details={
                    "pkce_method": "S256",
                    "redirect_binding": "exact_loopback",
                    "scope_count": len(pending.scopes),
                    "credential_storage": "external_reference",
                    "sensitive_material_logged": False,
                    "original_action": "none",
                },
            )
            closed = self.operations.close(
                operation.id,
                status="completed",
                summary="Installed-app OAuth callback completed without Original mutation.",
                metrics={
                    "scope_count": len(pending.scopes),
                    "originals_deleted": 0,
                    "originals_overwritten": 0,
                },
            )
            return {
                "schema_version": OAUTH_AUTHORIZATION_SCHEMA_VERSION,
                "status": "authorized",
                "connector_instance": completed,
                "boundary_operation": self._operation_view(closed),
                "credential_material_stored": False,
                "originals_mutated": 0,
            }
        except Exception as exc:
            self._fail_operation(operation, exc)
            raise
        finally:
            connector_lock.release()

    def revoke(self, connector_instance_id: str) -> dict[str, Any]:
        with self._connector_lock(connector_instance_id):
            now = self._now()
            cancelled = 0
            with self._state_lock:
                for request_id, pending in tuple(self._pending.items()):
                    if pending.connector_instance_id == connector_instance_id:
                        self._pending.pop(request_id, None)
                        self._terminate(request_id, "revoked")
                        cancelled += 1
            result = self.connectors.revoke_oauth_authorization(
                connector_instance_id,
                revoked_at=now.isoformat(),
            )
            return {
                "status": result["authorization"]["status"],
                "connector_instance": result,
                "pending_requests_cancelled": cancelled,
                "remote_mutation_attempted": False,
                "credential_material_stored": False,
                "originals_mutated": 0,
            }
