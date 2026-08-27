from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


def test_repository_pins_deterministic_build_inputs() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        configuration = tomllib.load(handle)

    assert configuration["build-system"]["requires"] == ["hatchling==1.31.0"]
    assert configuration["build-system"]["build-backend"] == "hatchling.build"
    assert configuration["tool"]["hatch"]["build"]["reproducible"] is True

    release_requirements = {
        line.strip()
        for line in (root / "requirements-release.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "build==1.5.0" in release_requirements
    assert "cyclonedx-bom==7.3.1" in release_requirements
    assert "hatchling==1.31.0" in release_requirements
    assert all("==" in requirement for requirement in release_requirements)

    windows_lock = (root / "build-lock" / "windows-py312-x86_64.requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "pyinstaller==6.16.0" in windows_lock
    assert "pefile==2023.2.7" in windows_lock
    assert "pefile==2024.8.26" not in windows_lock
    assert "pywin32-ctypes==0.2.3" in windows_lock
    assert "setuptools==" in windows_lock
    assert "--hash=sha256:" in windows_lock
    assert "http://" not in windows_lock
    assert "https://" not in windows_lock


def test_release_workflows_use_the_shared_deterministic_builder() -> None:
    root = Path(__file__).resolve().parents[1]
    ci = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release_caller = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    release = (root / ".github/workflows/release-pipeline.yml").read_text(
        encoding="utf-8"
    )
    publication = (root / ".github/workflows/release-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/deterministic_build.py" in ci
    assert "scripts.deterministic_build" in release
    assert "build-determinism.json" in ci
    assert "deterministic-build-report.json" in release

    for workflow in (ci, release):
        assert "SOURCE_DATE_EPOCH" in workflow
        assert "build-info" in workflow
        assert "network_used" in workflow
        assert "python -m build --sdist --wheel" not in workflow

    assert "identity_status'] == 'development_build'" in ci
    assert "--tag \"$TAG\"" in release
    assert "--channel \"$CHANNEL\"" in release
    assert "--official" in release
    assert 'value["identity_status"] == "official_metadata_present"' in release
    assert '"$runtime/bin/provelume" verify-installation' in release
    assert 'installation["status"] == "package_integrity_verified"' in release
    assert 'installation["network_used"] is False' in release
    assert 'installation["origin"]["status"] == "not_established"' in release
    assert (
        'cp core/provelume/release_bundle.py "$release/verify-provelume-release.py"'
        in release
    )
    assert "uses: ./.github/workflows/release-pipeline.yml" in release_caller
    assert "uses: ./.github/workflows/release-publish.yml" in release_caller
    assert "source_commit:" in release
    assert "--commit \"$SOURCE_COMMIT\"" in release
    assert "ref: ${{ inputs.commit }}" in publication
    for workflow in (ci, release):
        assert 'sbom["serialNumber"] = f"urn:uuid:{serial}"' in workflow
        assert "uuid.uuid5(" in workflow
        assert "--output-reproducible" in workflow
    assert "CycloneDX serialNumber is missing or invalid" in publication
    assert "windows-package:" in release
    assert "scripts/build_windows_installer.ps1" in release
    assert "scripts/test_windows_installer.ps1" in release
    assert "provelume-windows-update.json" in release
    assert "Provelume-Setup-${VERSION}-x64.exe" in release
    assert "Attest unsigned Windows preview" in publication

    windows_builder = (root / "scripts/build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )
    assert "Installing the reviewed Windows dependency lock failed" in windows_builder
    assert "PyInstaller failed with exit code" in windows_builder
    assert "Inno Setup failed with exit code" in windows_builder
    windows_exercise = (root / "scripts/test_windows_installer.ps1").read_text(
        encoding="utf-8"
    )
    assert "PreviousInstaller" in windows_exercise
    assert "Windows CI Instance – sintética 日本" in windows_exercise
    assert "Get-AuthenticodeSignature" in windows_exercise
    assert "--ui-diagnostics-dpi" in windows_exercise
    assert "Assert-SingleProductRegistration" in windows_exercise
    assert '"{E41A426B-F5FC-473F-A096-875017656A31}_is1"' in windows_exercise
    assert 'DisplayName -eq "Provelume"' not in windows_exercise
    assert "Z:\\synthetic-missing-python" in windows_exercise
    assert "Provelume-Setup-0.4.0-public.exe" in windows_exercise
    assert (
        "0d13b8940184befed42b6e96d3789b06c0cc6842bcd3473d8e26738d6df35749"
        in windows_exercise
    )
    assert "-PreviousInstaller" not in ci
    assert "-PreviousInstaller" in release
    windows_spec = (root / "packaging/windows/provelume.spec").read_text(
        encoding="utf-8"
    )
    assert 'find_spec("pydantic_core._pydantic_core")' in windows_spec
    assert 'binaries = [(pydantic_core_spec.origin, "pydantic_core")]' in windows_spec


def test_official_release_web_request_is_fail_closed() -> None:
    root = Path(__file__).resolve().parents[1]
    caller = (root / ".github/workflows/release.yml").read_text(encoding="utf-8")
    pipeline = (root / ".github/workflows/release-pipeline.yml").read_text(
        encoding="utf-8"
    )
    publication = (root / ".github/workflows/release-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in caller
    assert '"release-request/v*.*.*/*"' in caller
    assert "Release commit must be a full lowercase SHA-1" in caller
    assert "git merge-base --is-ancestor" in caller
    assert "Release target is not reachable from public main" in caller
    assert "git/refs/heads/${request_branch}" in caller
    assert caller.count("contents: write") == 2
    assert "actions: write" not in caller

    assert "Official release tag does not resolve" in pipeline
    assert "Release tag does not resolve to the assured source commit" in publication
    assert "contents: write" not in pipeline

    workflow_names = {path.name for path in (root / ".github/workflows").glob("*.yml")}
    assert not any(name.startswith(("apply-", "one-shot")) for name in workflow_names)


def test_tracked_build_identity_is_a_neutral_development_placeholder() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "pyproject.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["project"]["version"]
    init_source = (root / "core" / "provelume" / "__init__.py").read_text(
        encoding="utf-8"
    )
    init_match = re.search(r'^__version__ = "([^"]+)"$', init_source, re.MULTILINE)
    value = json.loads(
        (root / "core" / "provelume" / "build_info.json").read_text(encoding="utf-8")
    )

    assert package_version == "0.4.0"
    assert init_match is not None
    assert init_match.group(1) == package_version
    assert value == {
        "channel": "development",
        "commit": None,
        "official": False,
        "schema_version": 1,
        "source_date_epoch": None,
        "source_date_utc": None,
        "source_repository": "gabned/provelume",
        "tag": None,
        "version": package_version,
    }
