"""Dedicated generated Ed25519 identities in the existing native OS mirror vault."""

import base64
import re
import secrets
from uuid import uuid4

from .mirror_contract import fingerprint, require, sha
from .mirror_ssh_agent import public_blob
from .mirror_ssh_crypto import public_key


class RsyncCredentials:
    def __init__(self, mirrors):
        self.mirrors, self.vault = mirrors, mirrors.vault

    def enabled(self):
        access = self.mirrors.access()
        require(access["enabled"], "local_only")
        require(access["rsync"], "rsync_disabled")

    @staticmethod
    def reference(value):
        require(
            type(value) is str and re.fullmatch(r"mirror_rsync_[0-9a-f]{32}", value),
            "ssh_credentials",
        )
        return value

    def generate(self, *, confirmed):
        require(confirmed is True, "consent_required")
        self.enabled()
        seed = secrets.token_bytes(32)
        public = public_blob(public_key(seed))
        reference = "mirror_rsync_" + uuid4().hex
        value = {
            "schema": "provelume-rsync-credential/v1",
            "seed": base64.b64encode(seed).decode("ascii"),
            "public_sha256": sha(public),
            "epoch": uuid4().hex,
            "device": self.mirrors.device(),
        }
        self.vault.write(reference, value)
        require(self.read(reference) == value, "ssh_credentials")
        return {
            "reference": reference,
            "public_key": "ssh-ed25519 " + base64.b64encode(public).decode("ascii"),
            "public_sha256": sha(public),
            "credential_binding_sha256": fingerprint(self.binding(value)),
            "network_used": False,
        }

    def read(self, reference):
        self.enabled()
        value = self.vault.read(self.reference(reference))
        require(
            type(value) is dict
            and set(value) == {"schema", "seed", "public_sha256", "epoch", "device"}
            and value["schema"] == "provelume-rsync-credential/v1"
            and value["device"] == self.mirrors.device(),
            "ssh_credentials",
        )
        require(
            type(value["seed"]) is str
            and len(value["seed"]) == 44
            and type(value["epoch"]) is str
            and re.fullmatch(r"[0-9a-f]{32}", value["epoch"]),
            "ssh_credentials",
        )
        seed = base64.b64decode(value["seed"], validate=True)
        require(
            len(seed) == 32 and sha(public_blob(public_key(seed))) == value["public_sha256"],
            "ssh_credentials",
        )
        return value

    @staticmethod
    def binding(value):
        return {key: value[key] for key in ("public_sha256", "epoch", "device")}

    def revoke(self, reference, *, confirmed):
        require(confirmed is True, "consent_required")
        self.vault.delete(self.reference(reference))
        return {
            "status": "locally_revoked",
            "network_used": False,
            "pending_writes": "INVALIDATED",
            "remote_authorized_key_removal": "NOT_CLAIMED",
        }
