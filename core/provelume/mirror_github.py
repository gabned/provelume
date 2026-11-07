"""Independent GitHub.com profile; shared Git mechanics confer no provider qualification."""

from .mirror_contract import require, sha
from .mirror_github_contract import PROBE, PROBE_OID, configuration, marker
from .mirror_github_credentials import GitHubCredentials
from .mirror_github_helper import configure_session
from .mirror_hosted_git import HostedGitMirrors


class GitHubMirrors(HostedGitMirrors):
    provider = "github"
    proof_profile = "github.com/2022-11-28"
    configuration = staticmethod(configuration)
    marker = staticmethod(marker)
    configure_session = staticmethod(configure_session)

    @staticmethod
    def permission_check_descriptor():
        return {
            "git_blob_sha": PROBE_OID,
            "sha256": sha(PROBE),
            "size_bytes": len(PROBE),
            "utf8_content": PROBE.decode("utf-8"),
        }

    def __init__(self, store, *, mirrors=None, credentials=None):
        super().__init__(store, mirrors=mirrors)
        self.credentials = credentials or GitHubCredentials(self.mirrors)

    def connect(
        self,
        *,
        name,
        target,
        token,
        mode,
        confirmed,
        probe_confirmed,
        public_probe_confirmed=False,
        identity_id=None,
    ):
        self.credentials.enabled()
        reference = None
        if identity_id is not None:
            identity = self.mirrors.identity(identity_id)
            require(identity["profile"] == "github", "github_profile_not_qualified")
            reference = self.mirrors._grant(identity)["credential"]["reference"]
        result = self.credentials.connect(
            target,
            token=token,
            mode=mode,
            confirmed=confirmed,
            probe_confirmed=probe_confirmed,
            public_probe_confirmed=public_probe_confirmed,
            reference=reference,
        )
        if identity_id is None:
            identity = self.mirrors.create_identity(
                name=name,
                profile="github",
                credential={"reference": result["reference"]},
                confirmed=confirmed,
            )
        return {key: value for key, value in result.items() if key != "reference"} | {
            "identity": identity
        }

    def disconnect(self, identity_id, *, expected_revision, confirmed):
        identity = self.mirrors.identity(identity_id)
        require(identity["profile"] == "github", "github_profile_not_qualified")
        reference = self.mirrors._grant(identity)["credential"]["reference"]
        self.mirrors.revoke(identity_id, expected_revision=expected_revision, confirmed=confirmed)
        return self.credentials.revoke(reference, confirmed=confirmed)

    def status(self):
        return {
            "profile": "github.com/2022-11-28",
            "git": "OPTIONAL_NOT_PROBED",
            "network_used": False,
            "process_used": False,
            "credentials_read": False,
            "live_qualification": "NOT_RUN",
        }
