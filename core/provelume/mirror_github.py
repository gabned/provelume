"""GitHub-specific identity, visibility, namespace and complete transfer gates."""

from __future__ import annotations

import time
from contextlib import contextmanager

from .mirror_contract import findings, fingerprint, parse, raw, require, sha
from .mirror_git import GitMirrors, active_generation, build_commit, git_work, publication_files
from .mirror_github_contract import PROBE, PROBE_OID, configuration, marker
from .mirror_github_credentials import GitHubCredentials, logical_binding
from .mirror_github_helper import configure_session


class GitHubMirrors(GitMirrors):
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

    def context(self, destination_id, *, inspection_operation=None, scheduled=False):
        with self.mirrors.guard():
            row, authority = self.mirrors.authority(
                destination_id, _inspection_operation=inspection_operation, scheduled=scheduled
            )
            identity = authority["identity"]
            require(identity["profile"] == "github", "github_profile_not_qualified")
            grant = self.mirrors._grant(identity)
            target = grant["destinations"][destination_id]["target"]
            configuration(target)
            require(not scheduled or target["visibility"] == "private", "public_consent_required")
            return (
                row,
                authority,
                {
                    **target,
                    "_destination_id": destination_id,
                    "_reference": grant["credential"]["reference"],
                },
            )

    @staticmethod
    def clean_target(target):
        return {key: value for key, value in target.items() if not key.startswith("_")}

    @contextmanager
    def target_session(self, target, *, deadline=None, inspection_operation=None):
        clean = self.clean_target(target)
        deadline = min(deadline or float("inf"), time.monotonic() + 120)
        with git_work(deadline=deadline) as session:
            # Missing/unsupported Git refuses before vault/network use.
            session.probe()
            binding = self.credentials.observe(target["_reference"], clean, deadline=deadline)
            if inspection_operation is None:
                self.credentials.verify_write(target["_reference"], clean, deadline=deadline)
            configure_session(
                session,
                store=self.store,
                destination_id=target["_destination_id"],
                binding=binding,
                reference=target["_reference"],
            )
            yield (
                {
                    "uri": binding["repository"]["clone_url"],
                    "binding": binding,
                    "marker": marker(clean),
                },
                session,
            )

    def active(self, session, entries, target):
        generation, payload = active_generation(session, entries, target["path"])
        if generation is not None:
            entry = entries.get(target["path"] + "/namespace.json")
            require(
                entry is not None
                and entry["mode"] == "100644"
                and parse(session.blob(entry["oid"], maximum=1024)) == marker(target),
                "github_namespace",
            )
        return generation, payload

    def build(self, session, *, plan, git_plan, target, entries):
        return build_commit(
            session,
            mirrors=self.mirrors,
            plan=plan,
            git_plan=git_plan,
            target=target,
            entries=entries,
            extra_files={target["path"] + "/namespace.json": raw(marker(target))},
        )

    def observation(self, row, pinned, head, payload):
        return {
            **super().observation(row, pinned, head, payload),
            "visibility": pinned["binding"]["repository"]["visibility"],
        }

    def extra_preview(self, plan, git_plan, target, pinned, session, entries):
        files = publication_files(self.mirrors, plan, target)
        files[target["path"] + "/namespace.json"] = raw(marker(target))
        transfer = {
            "schema": "provelume-github-transfer/v1",
            "files": [
                {"path": name, "sha256": sha(data), "size_bytes": len(data)}
                for name, data in sorted(files.items())
            ],
            "permission_probe": {
                "git_blob_sha": PROBE_OID,
                "sha256": sha(PROBE),
                "size_bytes": len(PROBE),
                "utf8_content": PROBE.decode("utf-8"),
            },
            "commit": {
                "identity": git_plan["commit_identity"],
                "created_at": plan["created_at"],
                "parent": git_plan["head"],
                "message": "Provelume mirror "
                + plan["generation"]
                + "\n\nOperation "
                + plan["id"]
                + "\n",
            },
        }
        require(
            not any("secret_pattern" in findings(data) for data in files.values())
            and "secret_pattern" not in findings(raw(transfer["commit"])),
            "secret_pattern",
        )
        return {
            "provider_binding": pinned["binding"],
            "transfer": transfer,
            "transfer_sha256": fingerprint(transfer),
        }

    def binding_matches(self, pinned, git_plan, *, recovery=False):
        if recovery:
            return logical_binding(pinned["binding"]) == logical_binding(
                git_plan["provider_binding"]
            )
        return super().binding_matches(pinned, git_plan)

    def validate_transfer(self, plan, git_plan, target, pinned, session, entries):
        fresh = self.extra_preview(plan, git_plan, target, pinned, session, entries)
        require(fresh == {key: git_plan[key] for key in fresh}, "github_transfer_changed")

    def verify_provider(self, pinned, target, session):
        fresh = self.credentials.observe(
            target["_reference"], self.clean_target(target), deadline=session.deadline
        )
        require(fresh == pinned["binding"], "github_access_changed")

    def admit_growth(self, pinned, manifest):
        # Local fetches/created objects retain S17's fixed storage bounds. No
        # server capacity/quota guarantee is invented from repository metadata.
        require(manifest["total_bytes"] <= 256 * 1024 * 1024, "limit")

    def public_consent(self, plan, git_plan, *, expected_transfer_sha256=None):
        if plan["observation"]["visibility"] == "public":
            require(
                not plan["scheduled"]
                and type(expected_transfer_sha256) is str
                and expected_transfer_sha256
                == git_plan["transfer_sha256"]
                == fingerprint(git_plan["transfer"]),
                "public_consent_required",
            )
            return True
        return False

    def proof(self, pinned, **arguments):
        proof = super().proof(pinned, **arguments)
        return {
            **proof,
            "profile": "github.com/2022-11-28",
            "provider_observation": {
                "repository_id": pinned["binding"]["repository"]["repository_id"],
                "access_sha256": logical_binding(pinned["binding"]),
                "visibility": pinned["binding"]["repository"]["visibility"],
            },
        }

    def initialize_local(self, *_args, **_kwargs):
        require(False, "github_preexisting_repository_required")
