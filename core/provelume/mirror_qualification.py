"""Automatic frozen/source mirror qualification: synthetic local staging only."""

from copy import deepcopy
from pathlib import Path

from .mirror_contract import MirrorError, require
from .mirrors import Mirrors
from .service import ProvelumeInstance
from .tududi_qualification import SyntheticVault


def qualify_mirrors(root):
    from .build_info import current_build_info

    root = Path(root).absolute()
    require(not root.exists() and not root.is_symlink(), "target_not_fresh")
    root.mkdir(parents=True)
    inputs = root / "Synthetic Inputs"
    inputs.mkdir()
    (inputs / "one.md").write_text(
        "# Synthetic mirror\n\nReadable local content.\n", encoding="utf-8"
    )
    (inputs / "two.md").write_text(
        "# Second scope\n\nSeparate selected content.\n", encoding="utf-8"
    )
    instance = ProvelumeInstance.initialise(root / "Synthetic Space")
    instance.ingest_run(inputs)
    documents = sorted(instance.store.list_canonical("documents"), key=lambda row: row["title"])
    area = instance.create_hierarchy_node("area", "Synthetic Area")
    project = instance.create_hierarchy_node("project", "Synthetic Project", parent_id=area["id"])
    instance.classify_document(documents[0]["id"], project["id"])
    vault = SyntheticVault()
    engine = Mirrors(instance.store, vault=vault)
    engine.set_access(enabled=True, github=False, rsync=False, expected_revision=0, confirmed=True)
    identities = [
        engine.create_identity(
            name="Synthetic " + name, profile="folder", credential={"reference": ""}, confirmed=True
        )
        for name in ("A", "B")
    ]
    destinations, plans = [], []
    before = engine.snapshots.source_fingerprint()
    for index, scope in enumerate(
        (
            {"kind": "instance", "id": instance.store.read_config()["instance"]["id"]},
            {"kind": "area", "id": area["id"]},
            {"kind": "project", "id": project["id"]},
        )
    ):
        destination = engine.configure(
            identity_id=identities[index % 2]["id"],
            name="Synthetic target " + str(index),
            target={"path": str(root / ("Target " + str(index)))},
            scope=scope,
            include_rules={"originals": [], "attachments": [], "ai_receipts": []},
            mode="manual",
            confirmed=True,
        )
        destinations.append(destination)
        observation = {
            "destination_sha256": destination["destination_sha256"],
            "visibility": "private",
            "writable": True,
            "inventory": [],
            "revision": "SYNTHETIC_ONLY",
        }
        plan = engine.preview(destination["id"], observation, expected_revision=1)
        plans.append((plan, observation))
        verified = engine.snapshots.verify(plan["generation"])
        require(
            len([row for row in verified["inventory"] if row["category"] == "markdown"])
            == (2 if index == 0 else 1),
            "qualification",
        )
        require(
            not any(
                row["category"] in {"original", "attachment", "ai_receipt"}
                for row in verified["inventory"]
            ),
            "qualification",
        )
    plan, observation = plans[0]
    with engine.guard():
        engine._claim_locked(
            plan["id"],
            expected_plan_sha256=plan["plan_sha256"],
            observation=observation,
            confirmed=True,
        )
        engine._unknown_locked(plan["id"])
    restarted = Mirrors(instance.store, vault=vault)
    try:
        with restarted.guard():
            restarted._claim_locked(
                plan["id"],
                expected_plan_sha256=plan["plan_sha256"],
                observation=observation,
                confirmed=True,
            )
    except MirrorError as error:
        require(error.code == "stale", "qualification")
    else:
        require(False, "qualification")
    completed = {
        **deepcopy(observation),
        "inventory": plan["manifest"]["inventory"],
        "revision": "SYNTHETIC_RECEIPT_ONLY",
    }
    with restarted.guard():
        receipt = restarted._complete_locked(
            plan["id"], operation_id=plan["id"], observation=completed
        )
    require(
        receipt["source_manifest_sha256"] == receipt["destination_manifest_sha256"], "qualification"
    )
    engine.revoke(identities[1]["id"], expected_revision=1, confirmed=True)
    require(engine.snapshots.source_fingerprint() == before, "qualification")
    archive = root / "Synthetic Portable.zip"
    instance.export_portable(archive, derived_state="rebuild")
    restored = ProvelumeInstance.initialise(root / "Restored Space")
    restored.import_portable(archive)
    imported = Mirrors(restored.store, vault=vault)
    require(len(restored.store.list_canonical("documents")) == 2, "qualification")
    # A different Instance root must not acquire external grant authority from imported data.
    try:
        imported.authority(destinations[0]["id"])
    except MirrorError as error:
        require(error.code in {"local_only", "authorization_required"}, "qualification")
    else:
        require(False, "qualification")
    try:
        engine.dispatch(plans[2][0]["id"], confirmed=True)
    except MirrorError as error:
        require(error.code == "transport_not_qualified", "qualification")
    else:
        require(False, "qualification")
    return {
        "schema": "provelume-mirror-qualification/v1",
        "result": "PASS",
        "build": current_build_info(),
        "execution_adapter": "synthetic_local_only",
        "network_used": False,
        "transport_process_used": False,
        "instance_area_project": "PASS",
        "independent_identities_destinations": "PASS",
        "immutable_complete_inventory": "PASS",
        "no_replay_unknown_receipt": "PASS",
        "offline_portable_no_grant": "PASS",
        "canonical_unchanged": True,
        "real_transports": "NOT_RUN",
        "publication": "TRANSPORT_NOT_QUALIFIED",
        "windows_11_pro_25h2_manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
    }
