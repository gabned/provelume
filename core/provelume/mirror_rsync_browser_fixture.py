"""Explicit synthetic wire for rendered previews; never native SSH/rsync evidence."""

import base64
import secrets
from uuid import uuid4

from .mirror_contract import fingerprint, require
from .mirror_rsync import RsyncMirrors
from .mirror_rsync_protocol import HELPER_VERSION, PROFILE
from .mirror_ssh_agent import public_blob
from .mirror_ssh_crypto import public_key
from .mirror_ssh_runtime import SSH_VERSION
from .tududi_qualification import SyntheticVault


def seed_browser_plan(instance, mirrors, *, scope):
    # No real credential store, native component or destination may enter this
    # fixture. Application GETs subsequently read its actual saved plan only.
    require(isinstance(mirrors.vault, SyntheticVault), "rsync_fixture_vault")
    access = mirrors.access()
    mirrors.set_access(
        enabled=True,
        github=access["github"],
        rsync=True,
        expected_revision=access["revision"],
        confirmed=True,
    )
    target = {
        "transport": "rsync-ssh",
        "host": "synthetic.example.test",
        "port": 2222,
        "username": "synthetic",
        "namespace": uuid4().hex,
        "configuration_sha256": fingerprint(["SYNTHETIC_BROWSER_CONFIGURATION"]),
        "host_key": base64.b64encode(public_blob(public_key(secrets.token_bytes(32)))).decode(),
        "bandwidth_kib": 1024,
        "window_start_minute_utc": 0,
        "window_end_minute_utc": 1440,
    }
    source = {
        "instance_id": instance.store.read_config()["instance"]["id"],
        "device_sha256": mirrors.device(),
    }
    root_hash = fingerprint(["SYNTHETIC_BROWSER_ROOT_NOT_A_NATIVE_OBSERVATION"])

    class SyntheticTransport:
        components = {
            name: {"version": version, "sha256": fingerprint(["SYNTHETIC", name])}
            for name, version in (("rsync", "3.5.2"), ("ssh", SSH_VERSION.decode()))
        }

        def rpc(self, value):
            require(value["action"] == "inspect", "rsync_fixture_read_only")
            return {
                "helper": HELPER_VERSION,
                "profile": PROFILE,
                "configuration_sha256": target["configuration_sha256"],
                "namespace": target["namespace"],
                "root_sha256": root_hash,
                "marker": {
                    "schema": "provelume-folder-target/v1",
                    **source,
                    "namespace": target["namespace"],
                    "root_sha256": root_hash,
                    "destination_sha256": fingerprint([PROFILE, target["namespace"], source]),
                },
                "filesystem_profile": "linux-local-renameat2/v1",
                "rsync": self.components["rsync"],
                "active_pointer": None,
                "inventory": [],
                "storage": {"generations": [], "staging": [], "files": 0, "bytes": 0},
            }

    class SyntheticPreview(RsyncMirrors):
        def transport(self, _session, _target, reference):
            return SyntheticTransport(), self.credentials.binding(self.credentials.read(reference))

    engine = SyntheticPreview(instance.store, mirrors=mirrors)
    identity = engine.create_identity(name="Synthetic SSH browser identity", confirmed=True)
    row = mirrors.configure(
        identity_id=identity["identity"]["id"],
        name="Synthetic SSH preview destination",
        target=target,
        scope=scope,
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return engine.prepare(row["id"], expected_revision=1, confirmed=True)
