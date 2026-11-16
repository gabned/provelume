"""Gitea-only exact server/current-token/user/repository access proof."""

import time
from uuid import uuid4

from .mirror_contract import fingerprint, require
from .mirror_gitea_contract import (
    PROFILE,
    VERSION,
    configuration,
    repository_observation,
    token_observation,
)
from .mirror_gitea_http import GiteaHttp
from .mirror_hosted_credentials import HostedCredentials


class GiteaCredentials(HostedCredentials):
    provider = "gitea"
    http_factory = GiteaHttp

    def observe_token(self, target, *, token, mode, deadline):
        configuration(target)
        require(mode == "current-token", "gitea_token_profile")
        require(
            type(token) is str
            and 0 < len(token) <= 8192
            and all(32 < ord(char) < 127 for char in token),
            "authorization_required",
        )

        def get(route):
            return self.http.request(
                route,
                token=token,
                endpoint=target["endpoint"],
                ca_pem=target["ca_pem"],
                deadline=deadline,
            )

        require(get("/version").get("version") == VERSION, "gitea_profile_not_qualified")
        user = get("/user")
        principal = token_observation(get("/token"), user, target)
        repository = repository_observation(get("/repos/" + target["repository"]), target)
        identity = {
            "mode": mode,
            "principal": principal,
            "repository_id": repository["repository_id"],
            "repository": repository["repository"],
            "grant_sha256": fingerprint(
                [PROFILE, target["endpoint"], principal, repository["repository_id"]]
            ),
        }
        return {"repository": repository, "identity": identity}

    def connect(self, target, *, token, mode, confirmed, reference=None):
        require(confirmed is True, "consent_required")
        self.enabled()
        deadline = time.monotonic() + 120
        observed = self.observe_token(target, token=token, mode=mode, deadline=deadline)
        require(
            self.observe_token(target, token=token, mode=mode, deadline=deadline) == observed,
            "gitea_access_changed",
        )
        if reference is not None:
            require(
                self.read(reference)["identity"] == observed["identity"], "gitea_identity_changed"
            )
        else:
            reference = "mirror_gitea_" + uuid4().hex
        self.enabled()
        value = {
            "schema": "provelume-gitea-credential/v1",
            "token": token,
            "mode": mode,
            "identity": observed["identity"],
            "epoch": uuid4().hex,
            "device": self.mirrors.device(),
        }
        self.vault.write(reference, value)
        require(self.vault.read(reference) == value, "authorization_required")
        return {
            "reference": reference,
            "identity": observed["identity"],
            "repository": observed["repository"],
            "credential_epoch": value["epoch"],
            "capability_check": "ACTUAL_CURRENT_TOKEN_SCOPES_AND_REPO_ROLE",
            "remote_write": False,
            "publication": "NOT_RUN",
        }

    def verify_write(self, reference, target, *, deadline):
        self.observe(reference, target, deadline=deadline)
