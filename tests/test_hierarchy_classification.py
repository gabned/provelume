from __future__ import annotations

import json
import shutil
from pathlib import Path, PureWindowsPath

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.domain import HierarchyNode
from provelume.hierarchy import (
    HierarchyConflictError,
    HierarchyError,
    HierarchyNotFoundError,
    classification_id,
)
from provelume.hierarchy_model import portable_node_slug
from provelume.instance_validation import inspect_instance
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def _seed(tmp_path: Path) -> tuple[ProvelumeInstance, dict[str, dict[str, object]]]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "alpha.md").write_text("# Alpha\n\nDurable classification.\n", encoding="utf-8")
    (source / "beta.txt").write_text("Secondary material.\n", encoding="utf-8")
    instance = ProvelumeInstance.initialise(tmp_path / "instance", name="Hierarchy fixture")
    instance.ingest(source, source_name="Fixture files")
    documents = {item["title"]: item for item in instance.list_documents()}
    return instance, documents


def _original_snapshot(instance: ProvelumeInstance) -> dict[str, bytes]:
    selected = [
        *instance.store.paths.canonical_dir("originals").glob("*.json"),
        *(path for path in instance.store.paths.originals.rglob("*") if path.is_file()),
    ]
    return {
        path.relative_to(instance.root).as_posix(): path.read_bytes()
        for path in sorted(selected)
    }


def _classification_edges(
    instance: ProvelumeInstance,
    document_id: str,
) -> list[dict[str, object]]:
    return [
        edge
        for edge in instance.store.list_canonical("provenance")
        if edge["from_id"] == document_id
        and edge["relation"]
        in {"classified_primary_as", "classified_secondary_as"}
    ]


def test_stable_hierarchy_rename_move_and_classification_preserve_evidence(
    tmp_path: Path,
) -> None:
    instance, documents = _seed(tmp_path)
    document = documents["alpha.md"]
    document_id = str(document["id"])
    original_before = _original_snapshot(instance)
    document_before = instance.store.read_canonical("documents", document_id)

    work = instance.create_hierarchy_node("area", "Work")
    personal = instance.create_hierarchy_node("area", "Personal")
    research = instance.create_hierarchy_node(
        "area",
        "Research",
        parent_id=work["id"],
    )
    project = instance.create_hierarchy_node(
        "project",
        "Atlas",
        parent_id=research["id"],
    )
    collection = instance.create_hierarchy_node("collection", "References")

    classification = instance.classify_document(
        document_id,
        project["id"],
        secondary_node_ids=[collection["id"]],
    )
    edge_ids = {edge["id"] for edge in _classification_edges(instance, document_id)}
    assert classification["id"] == classification_id(document_id)
    assert classification["primary_node_id"] == project["id"]
    assert classification["secondary_node_ids"] == [collection["id"]]
    assert instance.list_documents(hierarchy_id=work["id"])[0]["id"] == document_id

    renamed = instance.rename_hierarchy_node(work["id"], "Client Work")
    moved = instance.move_hierarchy_node(research["id"], personal["id"])

    assert renamed["id"] == work["id"]
    assert renamed["slug"] != work["slug"]
    assert moved["id"] == research["id"]
    assert moved["slug"] == research["slug"]
    assert moved["parent_id"] == personal["id"]
    assert instance.list_documents(hierarchy_id=work["id"]) == []
    assert instance.list_documents(hierarchy_id=personal["id"])[0]["id"] == document_id
    assert instance.document_classification(document_id)["primary_node_id"] == project["id"]
    assert {edge["id"] for edge in _classification_edges(instance, document_id)} == edge_ids
    assert instance.store.read_canonical("documents", document_id) == document_before
    assert _original_snapshot(instance) == original_before

    provenance = instance.provenance(document_id)
    assert provenance is not None
    assert edge_ids <= {edge["id"] for edge in provenance["edges"]}
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    restarted = ProvelumeInstance(instance.root)
    assert restarted.get_hierarchy_node(project["id"])["portable_path"] == (
        f"{personal['slug']}/{research['slug']}/{project['slug']}"
    )
    assert restarted.document_classification(document_id) == (
        instance.document_classification(document_id)
    )


def test_portable_slugs_ordering_and_cycle_prevention(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    zulu = instance.create_hierarchy_node("area", "Zulu")
    alpha = instance.create_hierarchy_node("area", "Alpha")
    reserved = instance.create_hierarchy_node("project", 'CON: report? <2026>')
    child = instance.create_hierarchy_node("area", "Child", parent_id=alpha["id"])

    assert [node["name"] for node in instance.list_hierarchy_nodes()[:2]] == [
        "Alpha",
        "Child",
    ]
    assert reserved["slug"].endswith(reserved["id"].split("_", 1)[1])
    assert not set('<>:"/\\|?*').intersection(reserved["slug"])
    assert not reserved["slug"].endswith((".", " "))
    assert PureWindowsPath(reserved["slug"]).name == reserved["slug"]
    assert reserved["slug"].upper() not in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }

    with pytest.raises(HierarchyConflictError, match="cycle"):
        instance.move_hierarchy_node(alpha["id"], child["id"])
    assert instance.get_hierarchy_node(alpha["id"])["parent_id"] is None
    assert instance.get_hierarchy_node(child["id"])["parent_id"] == alpha["id"]

    with pytest.raises(HierarchyConflictError, match="own parent"):
        instance.move_hierarchy_node(zulu["id"], zulu["id"])
    with pytest.raises(HierarchyNotFoundError, match="not found"):
        instance.move_hierarchy_node(zulu["id"], "area_" + "f" * 32)
    with pytest.raises(HierarchyConflictError, match="area parent"):
        instance.move_hierarchy_node(zulu["id"], reserved["id"])
    with pytest.raises(HierarchyError, match="path separators"):
        instance.create_hierarchy_node("collection", "unsafe/name")

    before_restart = instance.hierarchy_tree()
    assert ProvelumeInstance(instance.root).hierarchy_tree() == before_restart


def test_move_rejects_a_subtree_that_would_exceed_maximum_depth(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    timestamp = "2026-08-28T00:00:00Z"

    def write_area(sequence: int, name: str, parent_id: str | None) -> str:
        node_id = f"area_{sequence:032x}"
        instance.store.write_hierarchy_node(
            HierarchyNode(
                schema_version=1,
                id=node_id,
                kind="area",
                name=name,
                slug=portable_node_slug(name, node_id, "area"),
                parent_id=parent_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        return node_id

    parent_id = None
    for level in range(63):
        parent_id = write_area(level + 1, f"Destination {level + 1}", parent_id)

    subtree_id = write_area(64, "Subtree", None)
    child_id = write_area(65, "Subtree child", subtree_id)

    with pytest.raises(HierarchyConflictError, match="64-level limit"):
        instance.move_hierarchy_node(subtree_id, parent_id)

    assert instance.get_hierarchy_node(subtree_id)["parent_id"] is None
    assert instance.get_hierarchy_node(child_id)["depth"] == 1
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_one_primary_secondary_associations_are_idempotent_and_historical(
    tmp_path: Path,
) -> None:
    instance, documents = _seed(tmp_path)
    document_id = str(documents["alpha.md"]["id"])
    area = instance.create_hierarchy_node("area", "Area")
    project = instance.create_hierarchy_node("project", "Project", parent_id=area["id"])
    collection = instance.create_hierarchy_node("collection", "Collection")

    first = instance.classify_document(
        document_id,
        project["id"],
        secondary_node_ids=[collection["id"], collection["id"]],
    )
    first_edges = _classification_edges(instance, document_id)
    repeated = instance.classify_document(
        document_id,
        project["id"],
        secondary_node_ids=[collection["id"]],
    )
    assert repeated == first
    assert _classification_edges(instance, document_id) == first_edges

    missing_edge = first_edges[0]
    (
        instance.store.paths.canonical_dir("provenance")
        / f"{missing_edge['id']}.json"
    ).unlink()
    assert "classification_provenance_missing" in {
        item["code"] for item in inspect_instance(instance.root, deep=True)["errors"]
    }
    repaired = instance.classify_document(
        document_id,
        project["id"],
        secondary_node_ids=[collection["id"]],
    )
    assert repaired == first
    assert _classification_edges(instance, document_id) == first_edges
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    changed = instance.classify_document(
        document_id,
        area["id"],
        secondary_node_ids=[project["id"]],
    )
    assert changed["id"] == first["id"]
    assert changed["created_at"] == first["created_at"]
    assert changed["primary_node_id"] == area["id"]
    assert changed["secondary_node_ids"] == [project["id"]]
    historical_targets = {edge["to_id"] for edge in _classification_edges(instance, document_id)}
    assert historical_targets == {area["id"], project["id"], collection["id"]}

    with pytest.raises(HierarchyConflictError, match="secondary"):
        instance.classify_document(
            document_id,
            area["id"],
            secondary_node_ids=[area["id"]],
        )
    with pytest.raises(HierarchyNotFoundError, match="document"):
        instance.classify_document("doc_" + "f" * 32, area["id"])
    with pytest.raises(HierarchyNotFoundError, match="hierarchy"):
        instance.classify_document(document_id, "area_" + "f" * 32)


def test_schema_two_additive_directories_and_deep_integrity_findings(tmp_path: Path) -> None:
    instance, documents = _seed(tmp_path)
    shutil.rmtree(instance.store.paths.canonical_dir("hierarchy"))
    shutil.rmtree(instance.store.paths.canonical_dir("classifications"))
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"

    first = instance.create_hierarchy_node("area", "First")
    second = instance.create_hierarchy_node("area", "Second", parent_id=first["id"])
    instance.classify_document(str(documents["alpha.md"]["id"]), second["id"])
    assert instance.store.paths.canonical_dir("hierarchy").is_dir()
    assert instance.store.paths.canonical_dir("classifications").is_dir()

    first_record = instance.store.read_canonical("hierarchy", first["id"])
    assert first_record is not None
    first_record["parent_id"] = second["id"]
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("hierarchy") / f"{first['id']}.json",
        first_record,
    )
    classification = instance.store.list_canonical("classifications")[0]
    classification["secondary_node_ids"] = ["collection_" + "f" * 32]
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("classifications")
        / f"{classification['id']}.json",
        classification,
    )

    report = inspect_instance(instance.root, deep=True)
    codes = {item["code"] for item in report["errors"]}
    assert report["status"] == "invalid"
    assert "hierarchy_cycle" in codes
    assert "classification_secondary_missing" in codes


@pytest.mark.parametrize("kind", ["hierarchy", "classifications"])
def test_additive_canonical_path_must_be_a_directory(
    tmp_path: Path,
    kind: str,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    directory = instance.store.paths.canonical_dir(kind)
    shutil.rmtree(directory)
    directory.write_text("not a directory\n", encoding="utf-8")

    report = inspect_instance(instance.root, deep=True)

    assert report["status"] == "invalid"
    assert {
        (item["code"], item.get("path")) for item in report["errors"]
    } >= {("canonical_directory_invalid", f"knowledge/{kind}")}


@pytest.mark.parametrize("document_id", ["", "   "])
def test_blank_classification_document_id_is_reported_without_crashing(
    tmp_path: Path,
    document_id: str,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    area = instance.create_hierarchy_node("area", "Area")
    record_id = "classification_" + "f" * 32
    instance.store._atomic_json(
        instance.store.paths.canonical_dir("classifications") / f"{record_id}.json",
        {
            "schema_version": 1,
            "id": record_id,
            "document_id": document_id,
            "primary_node_id": area["id"],
            "secondary_node_ids": [],
            "created_at": "2026-08-28T00:00:00Z",
            "updated_at": "2026-08-28T00:00:00Z",
        },
    )

    report = inspect_instance(instance.root, deep=True)

    assert report["status"] == "invalid"
    assert "classification_identity_invalid" in {
        item["code"] for item in report["errors"]
    }


def test_backup_restore_round_trip_includes_canonical_hierarchy(tmp_path: Path) -> None:
    instance, documents = _seed(tmp_path)
    document_id = str(documents["alpha.md"]["id"])
    first = instance.create_hierarchy_node("area", "First")
    second = instance.create_hierarchy_node("area", "Second")
    instance.classify_document(document_id, first["id"])
    backup = instance.backup(destination=tmp_path / "classified.zip")

    instance.classify_document(document_id, second["id"])
    assert instance.document_classification(document_id)["primary_node_id"] == second["id"]
    instance.restore(backup["archive"])

    assert instance.document_classification(document_id)["primary_node_id"] == first["id"]
    assert {node["id"] for node in instance.list_hierarchy_nodes()} == {
        first["id"],
        second["id"],
    }
    assert inspect_instance(instance.root, deep=True)["status"] == "valid"


def test_hierarchy_cli_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    instance, documents = _seed(tmp_path)
    root = str(instance.root)
    document_id = str(documents["alpha.md"]["id"])

    assert main(["hierarchy-create", root, "area", "CLI Area"]) == 0
    area = json.loads(capsys.readouterr().out)
    assert main(
        [
            "hierarchy-create",
            root,
            "project",
            "CLI Project",
            "--parent-id",
            area["id"],
        ]
    ) == 0
    project = json.loads(capsys.readouterr().out)
    assert main(
        ["classify", root, document_id, "--primary", project["id"]]
    ) == 0
    classification = json.loads(capsys.readouterr().out)
    assert classification["primary_node_id"] == project["id"]

    assert main(["hierarchy-list", root]) == 0
    hierarchy = json.loads(capsys.readouterr().out)
    assert hierarchy["tree"][0]["children"][0]["id"] == project["id"]
    assert main(["classification", root, document_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["classification"]["id"] == classification["id"]

    assert main(["hierarchy-move", root, project["id"]]) == 0
    moved = json.loads(capsys.readouterr().out)
    assert moved["parent_id"] is None
    assert main(["hierarchy-rename", root, project["id"], "Renamed"]) == 0
    renamed = json.loads(capsys.readouterr().out)
    assert renamed["id"] == project["id"]

    assert main(["hierarchy-rename", root, "area_" + "f" * 32, "Missing"]) == 3
    error = json.loads(capsys.readouterr().out)
    assert error["status"] == "not_found"


def test_read_only_api_and_browser_share_hierarchy_navigation(tmp_path: Path) -> None:
    instance, documents = _seed(tmp_path)
    alpha_id = str(documents["alpha.md"]["id"])
    beta_id = str(documents["beta.txt"]["id"])
    area = instance.create_hierarchy_node("area", "Knowledge")
    project = instance.create_hierarchy_node(
        "project",
        "Provelume",
        parent_id=area["id"],
    )
    collection = instance.create_hierarchy_node("collection", "Launch")
    instance.classify_document(
        alpha_id,
        project["id"],
        secondary_node_ids=[collection["id"]],
    )
    client = TestClient(create_app(instance.root))

    hierarchy = client.get("/api/v1/hierarchy")
    assert hierarchy.status_code == 200
    assert hierarchy.json()["tree"][0]["id"] == area["id"]
    assert client.get(f"/api/v1/hierarchy/{project['id']}").json()["depth"] == 1
    assert client.get("/api/v1/hierarchy/area_" + "f" * 32).status_code == 404
    assert client.post("/api/v1/hierarchy", json={}).status_code == 405

    subtree = client.get(
        "/api/v1/documents",
        params={"hierarchy_id": area["id"]},
    ).json()
    assert [item["id"] for item in subtree] == [alpha_id]
    direct = client.get(
        "/api/v1/documents",
        params={"hierarchy_id": area["id"], "include_descendants": False},
    ).json()
    assert direct == []
    assert client.get(
        "/api/v1/documents",
        params={"hierarchy_id": "area_" + "f" * 32},
    ).status_code == 404

    classification = client.get(
        f"/api/v1/documents/{alpha_id}/classification"
    ).json()["classification"]
    assert classification["primary"]["id"] == project["id"]
    assert client.get(f"/api/v1/documents/{beta_id}/classification").json() == {
        "document_id": beta_id,
        "classification": None,
    }
    assert client.post(
        f"/api/v1/documents/{alpha_id}/classification",
        json={},
    ).status_code == 405

    browse = client.get("/browse", params={"hierarchy_id": area["id"]})
    assert browse.status_code == 200
    assert "Library hierarchy" in browse.text
    assert "Knowledge / Provelume" in browse.text
    assert "alpha.md" in browse.text
    assert "beta.txt" not in browse.text
    italian = client.get(
        "/browse",
        params={"hierarchy_id": area["id"], "lang": "it"},
    )
    assert "Gerarchia della libreria" in italian.text
    detail = client.get(f"/documents/{alpha_id}")
    assert "Library classification" in detail.text
    assert "Knowledge / Provelume" in detail.text
    summary = client.get("/api/v1/instance").json()
    assert summary["hierarchy_nodes"] == 3
    assert summary["classifications"] == 1
