"""External credential storage and renewal mechanics; provider proofs stay separate."""

import re

from .google_credentials import GoogleCredentialVault
from .mirror_contract import require


class HostedCredentials:
    def __init__(self, mirrors, *, vault=None, http=None):
        self.mirrors = mirrors
        self.vault = vault or GoogleCredentialVault(
            namespace="mirror", forbidden_root=mirrors.store.paths.root
        )
        self.http = http or self.http_factory()

    def enabled(self):
        access = self.mirrors.access()
        require(access["enabled"], "local_only")
        require(self.provider != "github" or access["github"], "github_disabled")

    def read(self, reference):
        self.enabled()  # Before any secure store access.
        require(
            type(reference) is str
            and re.fullmatch(r"mirror_" + self.provider + r"_[0-9a-f]{32}", reference),
            "authorization_required",
        )
        value = self.vault.read(reference)
        require(
            type(value) is dict
            and set(value) == {"schema", "token", "mode", "identity", "epoch", "device"}
            and value["schema"] == "provelume-" + self.provider + "-credential/v1"
            and value["device"] == self.mirrors.device(),
            "authorization_required",
        )
        return value

    def observe(self, reference, target, *, deadline):
        value = self.read(reference)
        observed = self.observe_token(
            target, token=value["token"], mode=value["mode"], deadline=deadline
        )
        require(value["identity"] == observed["identity"], self.provider + "_identity_changed")
        require(self.read(reference) == value, self.provider + "_credential_changed")
        return {
            **observed,
            "credential_epoch": value["epoch"],
            "device": value["device"],
            "namespace": target["namespace"],
        }

    def revoke(self, reference, *, confirmed):
        require(confirmed is True, "consent_required")
        # Local deletion remains available while the transport is disabled.
        require(
            type(reference) is str
            and re.fullmatch(r"mirror_" + self.provider + r"_[0-9a-f]{32}", reference)
        )
        self.vault.delete(reference)
        return {
            "status": "locally_revoked",
            "network_used": False,
            "pending_writes": "INVALIDATED",
            "remote_token_revocation": "NOT_CLAIMED",
        }
