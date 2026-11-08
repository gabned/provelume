"""Actual local-folder conformance in the source and frozen operator; synthetic only."""

from __future__ import annotations

import errno
import json
import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from .google_credentials import GoogleCredentialVault
from .maintenance_local_files import MaintenanceTargetError
from .migration_permissions import make_private
from .mirror_contract import MirrorError, fingerprint, require
from .mirror_folder import FolderMirrors
from .mirror_folder_files import FolderTree
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def synthetic_fixture(root, *, vault=None):
    inputs = root / "Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text("# Synthetic folder mirror\n\nFinite independent input.\n")
    instance = ProvelumeInstance.initialise(root / "Instance")
    instance.ingest_run(inputs)
    mirrors = Mirrors(instance.store, vault=vault)
    mirrors.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identity = mirrors.create_identity(
        name="Synthetic native folder",
        profile="folder",
        credential={"reference": ""},
        confirmed=True,
    )
    target = root / "Fresh private destination"
    row = mirrors.configure(
        identity_id=identity["id"],
        name="Synthetic local target",
        target={"transport": "folder", "path": str(target)},
        scope={"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
        include_rules={"originals": [], "attachments": [], "ai_receipts": []},
        mode="manual",
        confirmed=True,
    )
    return instance, mirrors, FolderMirrors(instance.store, mirrors=mirrors), row, target


def qualify_folder_mirror(root, *, native_secure_store=False):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    make_private(root)
    native_vault = os.name == "nt" or native_secure_store
    environment = (
        patch.dict(os.environ, {"LOCALAPPDATA": str(root / "Synthetic Host")})
        if os.name == "nt"
        else nullcontext()
    )
    cases = []
    with environment:
        for after_activation in (False, True):
            selected = root / ("After activation" if after_activation else "Before activation")
            selected.mkdir()
            make_private(selected)
            vault = GoogleCredentialVault(namespace="mirror") if native_vault else SyntheticVault()
            instance, mirrors, engine, row, destination = synthetic_fixture(selected, vault=vault)
            initialized = engine.initialize_local(
                row["id"], expected_destination_sha256=row["destination_sha256"], confirmed=True
            )

            def prepare(engine=engine, row=row):
                return engine.prepare(row["id"], expected_revision=1, confirmed=True)

            def publish(plan, engine=engine):
                return engine.publish(
                    plan["id"],
                    expected_plan_sha256=plan["plan_sha256"],
                    expected_folder_plan_sha256=plan["folder_plan_sha256"],
                    confirmed=True,
                )

            canonical = mirrors.snapshots.source_fingerprint()
            first = publish(prepare())["receipt"]
            old_pointer = (destination / "active.json").read_bytes()
            noop = publish(prepare())["receipt"]
            require(
                not noop["transport_proof"]["activation_written"]
                and (destination / "active.json").read_bytes() == old_pointer,
                "folder_qualification",
            )
            require(mirrors.snapshots.source_fingerprint() == canonical, "folder_qualification")
            (selected / "Inputs" / "two.md").write_text("# Synthetic second folder generation\n")
            instance.ingest_run(selected / "Inputs")
            canonical = mirrors.snapshots.source_fingerprint()
            plan = prepare()
            backup = instance.backup(destination=selected / "Before interrupted transfer")
            original, attempts = FolderTree.rename, []

            def interrupted(
                tree,
                source,
                target,
                *,
                original=original,
                attempts=attempts,
                after_activation=after_activation,
                **options,
            ):
                if target != "active.json":
                    return original(tree, source, target, **options)
                attempts.append(True)
                if after_activation:
                    original(tree, source, target, **options)
                raise OSError(errno.ENOSPC, "Synthetic activation interruption")

            with patch.object(FolderTree, "rename", interrupted):
                try:
                    publish(plan)
                except (OSError, MaintenanceTargetError):
                    pass
                else:
                    require(False, "folder_qualification")
            require(len(attempts) == 1, "folder_qualification")
            if not after_activation:
                require(
                    (destination / "active.json").read_bytes() == old_pointer,
                    "folder_qualification",
                )
            require(
                instance.restore(backup["archive"])["status"] == "restored", "folder_qualification"
            )
            with (
                patch.object(FolderTree, "write", side_effect=AssertionError("recovery write")),
                patch.object(FolderTree, "rename", side_effect=AssertionError("recovery send")),
            ):
                recovered = engine.reconcile(plan["id"], confirmed=True)
                require(not recovered["resend_allowed"], "folder_qualification")
                if after_activation:
                    require(
                        recovered["receipt"]["transport_proof"]["evidence_mode"]
                        == "reconciled_current_state",
                        "folder_qualification",
                    )
                    require(publish(plan)["historical"], "folder_qualification")
                else:
                    require(recovered["outcome"] == "UNKNOWN", "folder_qualification")
                    try:
                        publish(plan)
                    except MirrorError as error:
                        require(error.code == "outcome_unknown", "folder_qualification")
                    else:
                        require(False, "folder_qualification")
            require(mirrors.snapshots.source_fingerprint() == canonical, "folder_qualification")
            old_generation = json.loads(old_pointer)["generation"]
            require(
                (destination / "generations" / old_generation / "manifest.json").is_file(),
                "folder_qualification",
            )
            cases.append(
                {
                    "fault": "after_activation" if after_activation else "before_activation",
                    "result": "PASS",
                    "initial_receipt_sha256": fingerprint(first),
                    "filesystem_profile": initialized["filesystem_profile"],
                    "actual_root_restore": "PASS",
                    "prior_generation_preserved": True,
                    "readonly_recovery": "PASS",
                    "activation_attempts": 1,
                    "resends": 0,
                    "expected_outcome": "COMPLETED" if after_activation else "UNKNOWN",
                }
            )
    return {
        "schema": "concordia-native-folder-qualification/v1",
        "result": "PASS",
        "commit": current_build_info().get("commit"),
        "cases": cases,
        "filesystem": "ACTUAL_NATIVE",
        "external_ledger_backend": (
            "NATIVE_CURRENT_USER_DPAPI"
            if os.name == "nt"
            else "NATIVE_SECRET_SERVICE"
            if native_vault
            else "SYNTHETIC_IN_MEMORY"
        ),
        "native_vault_qualification": "PASS" if native_vault else "NOT_RUN",
        "network_used": False,
        "process_used": False,
        "canonical_unchanged": True,
        "fault_injection": "CONTROLLED_ENOSPC_AT_ACTIVATION_BOUNDARY",
        "real_destinations": "NOT_RUN",
        "manuals": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
