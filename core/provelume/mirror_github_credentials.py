"""GitHub-only access and explicit fixed public write-probe contract."""

import time
from uuid import uuid4

from .mirror_contract import require
from .mirror_github_contract import (
    PROBE_OID,
    access_identity,
    configuration,
    repository_observation,
    user_identity,
)
from .mirror_github_http import GitHubHttp
from .mirror_hosted_credentials import HostedCredentials
from .mirror_hosted_git import logical_binding  # noqa: F401 - compatibility export


class GitHubCredentials(HostedCredentials):
    provider = "github"
    http_factory = GitHubHttp

    def observe_token(self, target, *, token, mode, deadline):
        configuration(target)
        require(
            type(token) is str
            and 0 < len(token) <= 8192
            and all(32 < ord(char) < 127 for char in token),
            "authorization_required",
        )
        route = "/repos/" + target["repository"]
        principal = None
        if mode == "user":
            principal = user_identity(self.http.request("/user", token=token, deadline=deadline))
        else:
            require(mode == "installation", "github_identity")
            total, seen, found = None, set(), False
            for page in range(1, 6):
                result = self.http.request(
                    f"/installation/repositories?per_page=100&page={page}",
                    token=token,
                    deadline=deadline,
                )
                count, rows = result.get("total_count"), result.get("repositories")
                require(
                    type(count) is int
                    and 0 <= count <= 500
                    and type(rows) is list
                    and len(rows) <= 100,
                    "github_response",
                )
                require(total is None or count == total, "github_access_changed")
                total = count
                for row in rows:
                    require(
                        type(row) is dict and type(row.get("id")) is int and row["id"] not in seen,
                        "github_response",
                    )
                    seen.add(row["id"])
                    if row["id"] == target["repository_id"]:
                        require(
                            row.get("full_name") == target["repository"],
                            "github_repository_changed",
                        )
                        found = True
                if len(rows) < 100 or len(seen) == total:
                    break
            require(len(seen) == total and found, "github_access_unproven")
        repository = repository_observation(
            self.http.request(route, token=token, deadline=deadline), target
        )
        return {
            "repository": repository,
            "identity": access_identity(mode=mode, repository=repository, principal=principal),
        }

    def connect(
        self,
        target,
        *,
        token,
        mode,
        confirmed,
        probe_confirmed,
        public_probe_confirmed=False,
        reference=None,
    ):
        require(confirmed is True and probe_confirmed is True, "consent_required")
        self.enabled()
        configuration(target)
        require(
            target["visibility"] != "public" or public_probe_confirmed is True,
            "public_consent_required",
        )
        deadline = time.monotonic() + 120
        observed = self.observe_token(target, token=token, mode=mode, deadline=deadline)
        # A repo role is not token capability. Only this explicitly consented,
        # fixed public synthetic blob tests Contents(write); no ref is changed.
        proof = self.http.request(
            "/repos/" + target["repository"] + "/git/blobs",
            token=token,
            probe=True,
            deadline=deadline,
        )
        require(proof.get("sha") == PROBE_OID, "github_write_unproven")
        fresh = self.observe_token(target, token=token, mode=mode, deadline=deadline)
        require(fresh == observed, "github_access_changed")
        if reference is not None:
            previous = self.read(reference)
            require(previous["identity"] == observed["identity"], "github_identity_changed")
        else:
            reference = "mirror_github_" + uuid4().hex
        self.enabled()
        value = {
            "schema": "provelume-github-credential/v1",
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
            "permission_probe": {"git_blob_sha": PROBE_OID, "ref_changed": False},
            "publication": "NOT_RUN",
        }

    def verify_write(self, reference, target, *, deadline):
        value = self.read(reference)
        proof = self.http.request(
            "/repos/" + target["repository"] + "/git/blobs",
            token=value["token"],
            probe=True,
            deadline=deadline,
        )
        require(
            proof.get("sha") == PROBE_OID and self.read(reference) == value, "github_write_unproven"
        )
