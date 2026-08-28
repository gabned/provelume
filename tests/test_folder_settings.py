from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.configured_inbox import InboxManager
from provelume.folder_settings import (
    FolderOverlapError,
    FolderSettingsManager,
    ManagedFolderRelocationRequired,
)
from provelume.operations import OperationLedger
from provelume.service import ProvelumeInstance
from provelume.web import create_app


def test_folder_settings_defaults_are_backward_compatible_and_side_effect_free(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = FolderSettingsManager(instance.store)

    view = manager.local_view()

    assert view["name"] == "Local Inbox"
    assert view["drop"]["configured"] == "inbox/drop"
    assert view["managed"]["configured"] == "inbox/items"
    assert view["drop"]["path"] == str(instance.root / "inbox" / "drop")
    assert view["managed"]["path"] == str(instance.root / "inbox" / "items")
    assert not (instance.root / "inbox").exists()
    assert not (instance.root / "state" / "operations").exists()


def test_relative_folder_names_are_saved_inside_instance_and_logged(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = FolderSettingsManager(instance.store)

    result = manager.configure(
        name="Da classificare",
        drop_path="Arrivi",
        managed_path="Archivio gestito",
    )

    settings = result["settings"]
    assert settings["name"] == "Da classificare"
    assert settings["drop"]["configured"] == "Arrivi"
    assert settings["managed"]["configured"] == "Archivio gestito"
    assert (instance.root / "Arrivi").is_dir()
    assert (instance.root / "Archivio gestito").is_dir()
    config = instance.store.read_config()["folders"]["inbox"]
    assert config["drop_path"] == "Arrivi"
    assert config["managed_path"] == "Archivio gestito"

    operation = OperationLedger(instance.store).get(result["operation"]["id"])
    assert operation is not None
    assert operation["kind"] == "settings.folders"
    serialized = json.dumps(operation)
    assert str(instance.root) not in serialized
    assert "Arrivi" not in serialized
    assert operation["metrics"]["external_folders"] == 0


def test_external_drop_and_managed_folders_are_supported_and_redacted(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    external_drop = tmp_path / "incoming elsewhere"
    external_managed = tmp_path / "managed elsewhere"
    manager = FolderSettingsManager(instance.store)

    result = manager.configure(
        name="Ingresso documenti",
        drop_path=external_drop,
        managed_path=external_managed,
    )

    assert external_drop.is_dir()
    assert external_managed.is_dir()
    config = instance.store.read_config()["folders"]["inbox"]
    assert config["drop_path"] == str(external_drop.resolve())
    assert config["managed_path"] == str(external_managed.resolve())
    assert result["settings"]["drop"]["scope"] == "external"
    assert result["settings"]["managed"]["scope"] == "external"

    public = manager.public_view()
    public_json = json.dumps(public)
    assert str(external_drop.resolve()) not in public_json
    assert str(external_managed.resolve()) not in public_json
    assert public["drop"]["display"] == external_drop.name
    assert public["managed"]["display"] == external_managed.name

    external_drop.joinpath("capture.txt").write_text(
        "External configurable Inbox.\n",
        encoding="utf-8",
    )
    processed = InboxManager(instance.store).process_drop()
    assert processed["submission"]["status"] == "completed"
    assert not external_drop.joinpath("capture.txt").exists()
    staged_locator = processed["submission"]["items"][0]["locator"]
    assert external_managed.joinpath(*staged_locator.split("/")).is_file()
    source_id = processed["submission"]["source_id"]
    source_config = instance.store.read_config()["sources"][source_id]
    assert source_config["path"] == str(external_managed.resolve())
    assert source_config["name"] == "Ingresso documenti"


def test_folder_settings_reject_reserved_and_overlapping_paths(tmp_path: Path) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = FolderSettingsManager(instance.store)

    with pytest.raises(FolderOverlapError):
        manager.configure(drop_path=instance.root, managed_path="managed")
    with pytest.raises(FolderOverlapError):
        manager.configure(
            drop_path=instance.store.paths.originals / "incoming",
            managed_path="managed",
        )
    with pytest.raises(FolderOverlapError):
        manager.configure(drop_path="shared", managed_path="shared/managed")
    with pytest.raises(FolderOverlapError):
        manager.configure(drop_path=tmp_path, managed_path="managed")


def test_managed_folder_relocation_is_blocked_after_inbox_acquisition(
    tmp_path: Path,
) -> None:
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    manager = FolderSettingsManager(instance.store)
    manager.configure(
        name="Initial Inbox",
        drop_path="Drop A",
        managed_path="Managed A",
    )
    submitted = tmp_path / "submitted.txt"
    submitted.write_text("Relocation boundary.\n", encoding="utf-8")
    assert InboxManager(instance.store).submit(submitted)["submission"]["status"] == "completed"

    with pytest.raises(ManagedFolderRelocationRequired):
        manager.configure(managed_path="Managed B")

    changed = manager.configure(name="Renamed Inbox", drop_path="Drop B")
    assert changed["settings"]["name"] == "Renamed Inbox"
    assert changed["settings"]["drop"]["configured"] == "Drop B"
    assert changed["settings"]["managed"]["configured"] == "Managed A"
    source_id = InboxManager(instance.store)._source_id()
    source = instance.store.read_canonical("sources", source_id)
    assert source is not None
    assert source["name"] == "Renamed Inbox"


def test_folder_settings_cli_shows_physical_paths(tmp_path: Path, capsys) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    external_drop = tmp_path / "drop"
    external_managed = tmp_path / "managed"

    assert main(
        [
            "configure-inbox",
            str(instance_root),
            "--name",
            "CLI Inbox",
            "--drop",
            str(external_drop),
            "--managed",
            str(external_managed),
        ]
    ) == 0
    configured = json.loads(capsys.readouterr().out)
    assert configured["settings"]["name"] == "CLI Inbox"

    assert main(["folder-settings", str(instance_root)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["drop"]["path"] == str(external_drop.resolve())
    assert shown["managed"]["path"] == str(external_managed.resolve())


def test_settings_browser_mutation_is_loopback_only_and_api_is_redacted(
    tmp_path: Path,
) -> None:
    instance_root = tmp_path / "instance"
    ProvelumeInstance.initialise(instance_root)
    external_drop = tmp_path / "browser drop"
    external_managed = tmp_path / "browser managed"
    client = TestClient(create_app(instance_root))

    page = client.get("/settings?lang=it")
    assert page.status_code == 200
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token_match is not None
    token = token_match.group(1)

    saved = client.post(
        "/settings/folders?lang=it",
        data={
            "csrf_token": token,
            "lang": "it",
            "name": "Inbox Browser",
            "drop_path": str(external_drop),
            "managed_path": str(external_managed),
        },
    )
    assert saved.status_code == 200
    assert "validate e salvate" in saved.text

    public = client.get("/api/v1/settings/folders")
    assert public.status_code == 200
    payload = public.json()
    assert payload["name"] == "Inbox Browser"
    assert payload["drop"]["scope"] == "external"
    assert "path" not in payload["drop"]
    assert str(external_drop.resolve()) not in public.text
    assert client.post("/api/v1/settings/folders").status_code == 405

    invalid_token = client.post(
        "/settings/folders",
        data={
            "csrf_token": "invalid",
            "lang": "en",
            "name": "Changed",
            "drop_path": str(external_drop),
            "managed_path": str(external_managed),
        },
    )
    assert invalid_token.status_code == 403
