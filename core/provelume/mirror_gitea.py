"""Independent Gitea current-token profile over the qualified common Git mechanics."""

from .mirror_contract import require, sha
from .mirror_gitea_contract import PROFILE, configuration, marker
from .mirror_gitea_credentials import GiteaCredentials
from .mirror_gitea_helper import configure_session
from .mirror_hosted_git import HostedGitMirrors


class GiteaMirrors(HostedGitMirrors):
    provider = "gitea"
    proof_profile = PROFILE
    configuration = staticmethod(configuration)
    marker = staticmethod(marker)

    def __init__(self, store, *, mirrors=None, credentials=None):
        super().__init__(store, mirrors=mirrors)
        self.credentials = credentials or GiteaCredentials(self.mirrors)

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
            "method": "GET version + user + current token + repository permissions",
            "remote_mutation": False,
            "required_scope": "write:repository + read:user OR all",
        }

    def connect(self, *, name, target, token, mode, confirmed, identity_id=None):
        self.credentials.enabled()
        reference = None
        if identity_id is not None:
            identity = self.mirrors.identity(identity_id)
            require(identity["profile"] == "gitea", "gitea_profile_not_qualified")
            reference = self.mirrors._grant(identity)["credential"]["reference"]
        result = self.credentials.connect(
            target, token=token, mode=mode, confirmed=confirmed, reference=reference
        )
        if identity_id is None:
            identity = self.mirrors.create_identity(
                name=name,
                profile="gitea",
                credential={"reference": result["reference"]},
                confirmed=confirmed,
            )
        return {key: value for key, value in result.items() if key != "reference"} | {
            "identity": identity
        }

    def disconnect(self, identity_id, *, expected_revision, confirmed):
        identity = self.mirrors.identity(identity_id)
        require(identity["profile"] == "gitea", "gitea_profile_not_qualified")
        reference = self.mirrors._grant(identity)["credential"]["reference"]
        self.mirrors.revoke(identity_id, expected_revision=expected_revision, confirmed=confirmed)
        return self.credentials.revoke(reference, confirmed=confirmed)

    def configure_session(self, session, *, store, destination_id, binding, reference):
        configure_session(
            session,
            store=store,
            destination_id=destination_id,
            binding=binding,
            reference=reference,
        )
        row = self.mirrors.destination(destination_id)
        identity = self.mirrors.identity(row["identity_id"])
        target = self.mirrors._grant(identity)["destinations"][destination_id]["target"]
        configuration(target)
        require(
            binding["repository"]["trust_sha256"] == sha(target["ca_pem"].encode("ascii")),
            "gitea_certificate",
        )
        if target["ca_pem"]:
            path = session.work / "gitea-ca.pem"
            path.write_bytes(target["ca_pem"].encode("ascii"))
            session.transport_configuration += ["-c", "http.sslCAInfo=" + str(path)]
