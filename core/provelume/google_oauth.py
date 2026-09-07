from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .google_contract import GOOGLE_CAPABILITY_SCOPES, GoogleAdapterError, GoogleAuthorizationError
from .google_credentials import GoogleCredentialError, GoogleCredentialVault
from .oauth_authorization import InstalledAppAuthorizationParameters, InstalledAppTokenExchange

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
# Google Cloud downloads still use the legacy URL as client metadata. Both
# exact values are accepted here; authorization always uses the fixed v2 URL.
CLIENT_AUTHORIZATION_ENDPOINTS = (
    "https://accounts.google.com/o/oauth2/auth",
    AUTHORIZATION_ENDPOINT,
)
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOCATION_ENDPOINT = "https://oauth2.googleapis.com/revoke"
PROFILE_ENDPOINTS = {
    "gmail": "https://gmail.googleapis.com/gmail/v1/users/me/profile?fields=emailAddress",
    "drive": "https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)",
}
_REFRESH_LOCK = Lock()


class GoogleConnectionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def desktop_client(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not isinstance(value.get("installed"), Mapping):
        raise GoogleConnectionError("google_client_invalid")
    raw = value["installed"]
    client_id = raw.get("client_id")
    secret = raw.get("client_secret", "")
    project = raw.get("project_id")
    if (
        not isinstance(client_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}\.apps\.googleusercontent\.com", client_id)
        or not isinstance(secret, str)
        or len(secret) > 256
        or any(ord(c) < 32 or ord(c) > 126 for c in secret)
        or not isinstance(project, str)
        or not re.fullmatch(r"[a-z0-9-]{1,100}", project)
        or raw.get("auth_uri", AUTHORIZATION_ENDPOINT) not in CLIENT_AUTHORIZATION_ENDPOINTS
        or raw.get("token_uri", TOKEN_ENDPOINT) != TOKEN_ENDPOINT
    ):
        raise GoogleConnectionError("google_client_invalid")
    # Do not persist download metadata, certificates, redirects or account identifiers.
    return {"client_id": client_id, "client_secret": secret, "project_id": project}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class GoogleOAuthTransport:
    """Closed endpoints; bounded HTTPS; no redirects, retries, or provider writes."""

    def request(self, endpoint: str, *, fields=None, token: str | None = None) -> dict[str, Any]:
        if endpoint not in {TOKEN_ENDPOINT, REVOCATION_ENDPOINT, *PROFILE_ENDPOINTS.values()}:
            raise GoogleConnectionError("google_connection_failed")
        is_post = endpoint in {TOKEN_ENDPOINT, REVOCATION_ENDPOINT}
        if is_post != (fields is not None) or (not is_post and token is None):
            raise GoogleConnectionError("google_connection_failed")
        headers = {"Accept": "application/json"}
        data = None
        if is_post:
            data = urlencode(fields).encode("ascii")
            if len(data) > 16 * 1024:
                raise GoogleConnectionError("google_connection_failed")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(endpoint, data=data, headers=headers, method="POST" if is_post else "GET")
        try:
            with build_opener(_NoRedirect()).open(request, timeout=15) as response:
                raw = response.read(64 * 1024 + 1)
                if len(raw) > 64 * 1024 or response.status != 200:
                    raise GoogleConnectionError("google_connection_failed")
                if endpoint == REVOCATION_ENDPOINT:
                    return {}
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError
                return result
        except HTTPError as exc:
            if exc.code in {400, 401, 403}:
                raise GoogleConnectionError("google_reconnect_required") from None
            raise GoogleConnectionError("google_connection_failed") from None
        except (URLError, OSError, ValueError):
            raise GoogleConnectionError("google_connection_failed") from None


def _token(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 8192:
        raise GoogleConnectionError("google_connection_failed")
    if any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise GoogleConnectionError("google_connection_failed")
    return value


def validated_tokens(raw: dict[str, Any], capability: str, *, previous=None) -> dict[str, Any]:
    expected = GOOGLE_CAPABILITY_SCOPES[capability]
    scopes = raw.get("scope")
    if scopes is None and previous is not None:
        scopes = " ".join(previous["scopes"])
    if not isinstance(scopes, str) or tuple(sorted(set(scopes.split()))) != expected:
        raise GoogleConnectionError("google_scope_mismatch")
    seconds = raw.get("expires_in")
    if type(seconds) is not int or not 60 <= seconds <= 86400:
        raise GoogleConnectionError("google_connection_failed")
    if str(raw.get("token_type", "")).casefold() != "bearer":
        raise GoogleConnectionError("google_connection_failed")
    return {
        "access_token": _token(raw.get("access_token")),
        "refresh_token": _token(raw.get("refresh_token", (previous or {}).get("refresh_token"))),
        "expires_at": time.time() + seconds,
        "scopes": list(expected),
    }


def _account_identity(transport, capability: str, access_token: str) -> str:
    profile = transport.request(PROFILE_ENDPOINTS[capability], token=access_token)
    email = (
        profile.get("emailAddress")
        if capability == "gmail"
        else (
            profile.get("user", {}).get("emailAddress")
            if isinstance(profile.get("user"), dict)
            else None
        )
    )
    if not isinstance(email, str) or not 3 <= len(email) <= 320 or "@" not in email:
        raise GoogleConnectionError("google_connection_failed")
    return email.strip().casefold()


def account_binding(transport, capability: str, access_token: str, instance_id: str) -> str:
    identity = _account_identity(transport, capability, access_token)
    return hashlib.sha256(f"{instance_id}:{identity}".encode()).hexdigest()


class GoogleInstalledAppAdapter:
    adapter_key = "google-readonly"
    adapter_version = "1.0.0"
    authorization_endpoint = AUTHORIZATION_ENDPOINT
    token_endpoint = TOKEN_ENDPOINT

    def __init__(self, *, instance_id, capability, client, vault, transport, expected_binding=None):
        self.instance_id = instance_id
        self.capability = capability
        self.client = client
        self.vault = vault
        self.transport = transport
        self.expected_binding = expected_binding
        self.slot = f"google_grant_{uuid4().hex}"
        self.staged = False

    def build_authorization_uri(self, request: InstalledAppAuthorizationParameters) -> str:
        return (
            AUTHORIZATION_ENDPOINT
            + "?"
            + urlencode(
                {
                    "client_id": self.client["client_id"],
                    "response_type": "code",
                    "redirect_uri": request.redirect_uri,
                    "state": request.state,
                    "code_challenge": request.code_challenge,
                    "code_challenge_method": "S256",
                    "scope": " ".join(request.scopes),
                    "prompt": "consent",
                    "access_type": "offline",
                    "include_granted_scopes": "false",
                }
            )
        )

    def exchange_callback(self, exchange: InstalledAppTokenExchange) -> Mapping[str, Any]:
        raw = self.transport.request(
            TOKEN_ENDPOINT,
            fields={
                "client_id": self.client["client_id"],
                "client_secret": self.client["client_secret"],
                "grant_type": "authorization_code",
                "code": exchange.authorization_code,
                "code_verifier": exchange.pkce_verifier,
                "redirect_uri": exchange.redirect_uri,
            },
        )
        tokens = validated_tokens(raw, self.capability)
        identity = _account_identity(self.transport, self.capability, tokens["access_token"])
        binding = hashlib.sha256(f"{self.instance_id}:{identity}".encode()).hexdigest()
        revocation_binding = hashlib.sha256(
            f"{self.client['project_id']}:{identity}".encode()
        ).hexdigest()
        if self.expected_binding and not hmac.compare_digest(binding, self.expected_binding):
            raise GoogleConnectionError("google_account_mismatch")
        self.vault.write(
            self.slot,
            {
                **tokens,
                "client": self.client,
                "capability": self.capability,
                "account_binding_sha256": binding,
                "revocation_binding_sha256": revocation_binding,
            },
        )
        self.staged = True
        return {
            "credential_reference": {"kind": "system_keyring", "name": self.slot},
            "account_identity": binding,
            "granted_scopes": list(exchange.granted_scopes),
        }

    def discard(self) -> None:
        if self.staged:
            self.vault.delete(self.slot)
            self.staged = False


def resolve_google_credential(reference, *, vault=None, transport=None) -> str:
    """Called only after the existing Source/connector/global network gates."""
    vault = vault or GoogleCredentialVault()
    transport = transport or GoogleOAuthTransport()
    slot = reference["name"]
    try:
        with _REFRESH_LOCK:
            record = vault.read(slot)
            if record is None:
                raise GoogleAuthorizationError(expired=True)
            if time.time() + 60 < record["expires_at"]:
                return _token(record["access_token"])
            client = record["client"]
            raw = transport.request(
                TOKEN_ENDPOINT,
                fields={
                    "client_id": client["client_id"],
                    "client_secret": client["client_secret"],
                    "refresh_token": _token(record["refresh_token"]),
                    "grant_type": "refresh_token",
                },
            )
            tokens = validated_tokens(raw, record["capability"], previous=record)
            vault.write(slot, {**record, **tokens})
            return tokens["access_token"]
    except GoogleConnectionError as exc:
        if exc.code == "google_connection_failed":
            raise GoogleAdapterError(
                "google_retryable_failure", "Google connection is unavailable"
            ) from None
        raise GoogleAuthorizationError(expired=True) from None
    except GoogleCredentialError:
        raise GoogleAdapterError(
            "google_secure_store_unavailable", "Google system credential store is unavailable"
        ) from None
    except (KeyError, TypeError):
        raise GoogleAuthorizationError(expired=True) from None
