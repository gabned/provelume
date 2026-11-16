"""GitLab-only user, classic PAT, project role and visibility observations."""

import re
import time
from uuid import uuid4

from .mirror_contract import require
from .mirror_gitlab_contract import configuration, identity_observation, repository_observation
from .mirror_gitlab_http import GitLabHttp
from .mirror_hosted_credentials import HostedCredentials


class GitLabCredentials(HostedCredentials):
    provider = "gitlab"
    http_factory = GitLabHttp

    def observe_token(self, target, *, token, mode, deadline):
        configuration(target)
        require(mode == "classic-pat", "gitlab_token_profile")
        require(
            type(token) is str
            and 0 < len(token) <= 8192
            and all(32 < ord(char) < 127 for char in token),
            "authorization_required",
        )
        user = self.http.request("/user", token=token, deadline=deadline)
        token_info = self.http.request(
            "/personal_access_tokens/self", token=token, deadline=deadline
        )
        repository = repository_observation(
            self.http.request(
                "/projects/" + str(target["repository_id"]), token=token, deadline=deadline
            ),
            target,
        )
        identity = identity_observation(user, token_info, repository)
        version = self.http.request("/version", token=token, deadline=deadline)
        require(
            type(version) is dict
            and type(version.get("version")) is str
            and re.fullmatch(r"\d+\.\d+\.\d+(?:-pre)?", version["version"])
            and type(version.get("revision")) is str
            and re.fullmatch(r"[0-9a-f]{7,40}", version["revision"]),
            "gitlab_version_unknown",
        )
        # Actual service version is bound, never guessed from API v4 or GitHub.
        repository["server_version"] = version["version"]
        repository["server_revision"] = version["revision"]
        return {"repository": repository, "identity": identity}

    def connect(self, target, *, token, mode, confirmed, reference=None):
        require(confirmed is True, "consent_required")
        self.enabled()
        deadline = time.monotonic() + 120
        observed = self.observe_token(target, token=token, mode=mode, deadline=deadline)
        require(
            self.observe_token(target, token=token, mode=mode, deadline=deadline) == observed,
            "gitlab_access_changed",
        )
        if reference is not None:
            previous = self.read(reference)
            require(previous["identity"] == observed["identity"], "gitlab_identity_changed")
        else:
            reference = "mirror_gitlab_" + uuid4().hex
        self.enabled()
        value = {
            "schema": "provelume-gitlab-credential/v1",
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
            "capability_check": "CLASSIC_PAT_SELF_SCOPE_AND_PROJECT_ROLE",
            "remote_write": False,
            "publication": "NOT_RUN",
        }

    def verify_write(self, reference, target, *, deadline):
        # Classic PAT self-info proves Git write scope; no synthetic remote
        # mutation is needed or silently substituted for this native API proof.
        self.observe(reference, target, deadline=deadline)
