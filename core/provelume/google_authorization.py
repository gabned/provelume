from __future__ import annotations

import hashlib
import hmac
import json
import re

from .google_contract import GOOGLE_ALLOWED_ORIGINS, GOOGLE_CAPABILITY_SCOPES, normalise_capability
from .google_sources import GoogleSourceManager
from .instance_lifecycle import InstanceLifecycleManager
from .oauth_authorization import OAuthPolicyError
from .storage import utc_now


class GoogleCapabilityAuthority:
    """Authorize exactly one real Google capability through the shared PKCE engine.

    The provider-neutral connector remains auth-mode none. Its actual network,
    lifecycle and configuration gates still bind each capability authorization.
    No global union grant or invented connector definition is created.
    """

    def __init__(self, sources: GoogleSourceManager, capability: str):
        self.sources = sources
        self.capability = normalise_capability(capability)

    def authorization_policy(self, instance_id):
        record = self.sources._instance_record(instance_id)
        connector = self.sources.connectors.get_instance(instance_id)
        item = record["capabilities"][self.capability]
        return {
            "active": connector["lifecycle_state"] == "active",
            "enabled": connector["configured_enabled"],
            "effective_network": connector["effective_network"],
            "allowed_origins": connector["allowed_origins"],
            "adapter_key": "google-readonly",
            "adapter_version": "1.0.0",
            "scopes": list(GOOGLE_CAPABILITY_SCOPES[self.capability]),
            "authorization": {"status": item["authorization_status"]},
        }

    def authorization_fingerprint(self, instance_id):
        record = self.sources._instance_record(instance_id)
        return hashlib.sha256(
            json.dumps(
                {
                    "connector": self.sources.connectors.authorization_fingerprint(instance_id),
                    "policy": self.authorization_policy(instance_id),
                    "capability": record["capabilities"][self.capability],
                    "account_binding": record.get("account_binding_sha256"),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    def complete_oauth_authorization(
        self, instance_id, *, grant, authorized_at, expected_record_sha256
    ):
        with InstanceLifecycleManager(self.sources.store)._hold(purpose="google-authorization"):
            if self.authorization_fingerprint(instance_id) != expected_record_sha256:
                raise OAuthPolicyError("Google capability policy changed during authorization")
            policy = self.authorization_policy(instance_id)
            if (
                not policy["active"]
                or not policy["enabled"]
                or policy["effective_network"] != "explicit"
                or set(policy["allowed_origins"]) != set(GOOGLE_ALLOWED_ORIGINS)
            ):
                raise OAuthPolicyError("Google authorization is blocked by current policy")
            binding = grant["account_identity"]
            if re.fullmatch(r"[0-9a-f]{64}", binding) is None:
                raise OAuthPolicyError("Google account equality binding is invalid")
            record = self.sources._instance_record(instance_id)
            expected = record.get("account_binding_sha256")
            if expected and not hmac.compare_digest(binding, expected):
                raise OAuthPolicyError("Google account equality binding changed")
            item = record["capabilities"][self.capability]
            updated = {
                **item,
                "state": "disabled",
                "authorization_status": "authorized",
                "credential_reference": grant["credential_reference"],
                "consent": "explicit",
                "authorized_at": authorized_at,
                "revoked_at": None,
                "revision": int(item["revision"]) + 1,
                "health": {
                    "status": "ready",
                    "code": "google_read_succeeded",
                    "checked_at": authorized_at,
                },
            }
            self.sources._write_instance_record(
                {
                    **record,
                    "account_binding_sha256": binding,
                    "guided_provisional": False,
                    "guided_provisional_until": None,
                    "capabilities": {**record["capabilities"], self.capability: updated},
                    "updated_at": utc_now(),
                }
            )
        return {
            "id": instance_id,
            "capability": self.capability,
            "authorization": {"status": "authorized"},
        }

    def revoke_oauth_authorization(self, instance_id, *, revoked_at):
        del revoked_at
        with InstanceLifecycleManager(self.sources.store)._hold(purpose="google-disconnect"):
            self.sources.revoke_capability(instance_id, self.capability)
        return {"id": instance_id, "authorization": {"status": "revoked"}}
