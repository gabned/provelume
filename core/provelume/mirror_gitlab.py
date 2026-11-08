"""Independent GitLab classic-PAT profile, never inferred from GitHub results."""

from .mirror_contract import require
from .mirror_gitlab_contract import PROFILE, configuration, marker
from .mirror_gitlab_credentials import GitLabCredentials
from .mirror_gitlab_helper import configure_session
from .mirror_hosted_git import HostedGitMirrors


class GitLabMirrors(HostedGitMirrors):
    provider = "gitlab"
    proof_profile = PROFILE
    configuration = staticmethod(configuration)
    marker = staticmethod(marker)
    configure_session = staticmethod(configure_session)

    def __init__(self, store, *, mirrors=None, credentials=None):
        super().__init__(store, mirrors=mirrors)
        self.credentials = credentials or GitLabCredentials(self.mirrors)

    def status(self):
        return {
            "profile": PROFILE,
            "git": "OPTIONAL_NOT_PROBED",
            "network_used": False,
            "process_used": False,
            "credentials_read": False,
            "live_qualification": "NOT_RUN",
        }

    @staticmethod
    def permission_check_descriptor():
        return {
            "method": "GET personal_access_tokens/self + current user + project permissions",
            "remote_mutation": False,
            "required_scope": "api OR read_api+write_repository",
        }

    def connect(self, *, name, target, token, mode, confirmed, identity_id=None):
        self.credentials.enabled()
        reference = None
        if identity_id is not None:
            identity = self.mirrors.identity(identity_id)
            require(identity["profile"] == "gitlab", "gitlab_profile_not_qualified")
            reference = self.mirrors._grant(identity)["credential"]["reference"]
        result = self.credentials.connect(
            target, token=token, mode=mode, confirmed=confirmed, reference=reference
        )
        if identity_id is None:
            identity = self.mirrors.create_identity(
                name=name,
                profile="gitlab",
                credential={"reference": result["reference"]},
                confirmed=confirmed,
            )
        return {key: value for key, value in result.items() if key != "reference"} | {
            "identity": identity
        }

    def disconnect(self, identity_id, *, expected_revision, confirmed):
        identity = self.mirrors.identity(identity_id)
        require(identity["profile"] == "gitlab", "gitlab_profile_not_qualified")
        reference = self.mirrors._grant(identity)["credential"]["reference"]
        self.mirrors.revoke(identity_id, expected_revision=expected_revision, confirmed=confirmed)
        return self.credentials.revoke(reference, confirmed=confirmed)
