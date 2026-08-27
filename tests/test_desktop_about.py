from __future__ import annotations

import json
from pathlib import Path

from provelume.about import current_about
from provelume.desktop import (
    LauncherSettings,
    declare_startup_update_policy,
    diagnostics_payload,
    load_settings,
    main,
    save_settings,
)
from provelume.service import ProvelumeInstance


def test_about_is_local_and_describes_preview_update_boundary() -> None:
    value = current_about()

    assert value["product"] == "Provelume"
    assert value["version"] == "0.3.0"
    assert value["runtime"]["packaging"] == "python_package"
    assert value["updates"] == {
        "manual_check_available": True,
        "check_on_start_default": False,
        "automatic_apply": False,
        "initial_transport": "github_releases",
        "network_required_for_check": True,
        "instance_content_sent": False,
        "publisher_authentication": "not_established",
        "platform_signature": "not_verified",
    }


def test_launcher_settings_round_trip_and_malformed_fallback(tmp_path: Path) -> None:
    path = tmp_path / "launcher.json"
    expected = LauncherSettings(
        instance_path=str(tmp_path / "Mia's knowledge"),
        update_channel="stable",
        check_on_start=True,
        language="it",
    )
    save_settings(expected, path)
    assert load_settings(path) == expected

    path.write_text('{"schema_version": true}', encoding="utf-8")
    fallback = load_settings(path)
    assert fallback.schema_version == 1
    assert fallback.update_channel == "preview"
    assert fallback.check_on_start is False


def test_desktop_diagnostics_and_headless_instance_bootstrap(tmp_path: Path) -> None:
    diagnostics = diagnostics_payload()
    assert diagnostics["desktop_shell"] is True
    assert diagnostics["network_used"] is False
    assert diagnostics["about"]["version"] == "0.3.0"

    root = tmp_path / "Instance with spaces"
    assert main(["--bootstrap-instance", str(root), "--instance-name", "Desktop Demo"]) == 0
    instance = ProvelumeInstance(root)
    assert instance.instance_summary()["name"] == "Desktop Demo"

    output = tmp_path / "diagnostics.json"
    assert main(["--diagnostics-file", str(output)]) == 0
    assert json.loads(output.read_text())["settings_schema_version"] == 1


def test_startup_update_opt_in_is_visible_in_instance_network_status(tmp_path: Path) -> None:
    root = tmp_path / "instance"
    instance = ProvelumeInstance.initialise(root)

    declare_startup_update_policy(root, enabled=True)
    enabled = instance.network_status()
    update = next(
        component
        for component in enabled["components"]
        if component["id"] == "builtin.update_checks"
    )
    assert update["enabled"] is True
    assert update["endpoint"] == "https://api.github.com"
    assert update["data_categories"] == []

    declare_startup_update_policy(root, enabled=False)
    disabled = instance.network_status()
    update = next(
        component
        for component in disabled["components"]
        if component["id"] == "builtin.update_checks"
    )
    assert update["enabled"] is False
