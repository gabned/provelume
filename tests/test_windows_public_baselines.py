from pathlib import Path

SCRIPT = Path("scripts/test_windows_installer.ps1")
PIPELINE = Path(".github/workflows/release-pipeline.yml")


def test_windows_upgrade_uses_immutable_public_installer_baselines() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert 'version = "0.4.0"' in text
    assert 'commit = "a54ea64db7c3452d2be4dfdf761cdb6b6962c09b"' in text
    assert "size = 18051429" in text
    assert (
        'sha256 = "0d13b8940184befed42b6e96d3789b06c0cc6842bcd3473d8e26738d6df35749"'
        in text
    )

    assert 'version = "0.4.1"' in text
    assert 'commit = "6e34498e98a315baaef00314fd59772a3af008df"' in text
    assert "size = 18056957" in text
    assert (
        'sha256 = "ea2093cd63860e2575715617f3bde363646213841f60be1db97433b19052b46b"'
        in text
    )
    assert 'version = "0.5.0"' in text
    assert 'commit = "89c6b7c783e385c4e978cc2ae6bf602012aab77e"' in text
    assert "size = 18193123" in text
    assert (
        'sha256 = "c604de1006c6f86a52bf61ca54fe6371e0889f728eb89f25e38776165254ecab"'
        in text
    )
    assert 'version = "0.5.1"' in text
    assert 'commit = "b3156617dc2ce9c97cd32ee105c18634cd4b9776"' in text
    assert "size = 18206254" in text
    assert (
        'sha256 = "642de2931dc6fbc7f1a58fd490b73c45cef72719bc75c690713076f9bddf268b"'
        in text
    )
    assert 'version = "0.6.0"' in text
    assert 'commit = "bc02180fa116c2924b04f0a4c0bcf497a1efbd70"' in text
    assert "size = 18343369" in text
    assert (
        'sha256 = "da338c65b8698d411561bbcb02e0711a1467628e3551c74b0989a7efe7ef6bc3"'
        in text
    )
    assert 'releases/download/v0.6.0/Provelume-Setup-0.6.0-x64.exe' in text


def test_release_pipeline_uses_latest_immutable_public_installer() -> None:
    text = PIPELINE.read_text(encoding="utf-8")

    assert "published 0.6.0 upgrade baseline" in text
    assert 'Provelume-Setup-0.6.0-public.exe' in text
    assert 'releases/download/v0.6.0/Provelume-Setup-0.6.0-x64.exe' in text
    assert "Length -ne 18343369" in text
    assert "da338c65b8698d411561bbcb02e0711a1467628e3551c74b0989a7efe7ef6bc3" in text


def test_windows_upgrade_proves_controlled_instance_schema_migration() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert "LegacyInstanceConfigSha256" in text
    assert '$LegacyInstanceName = "Windows CI Instance – sintética 日本"' in text
    assert 'Get-YamlScalar -Text $LegacyConfigText -Key "name"' not in text
    assert "The installer mutated the Instance" in text
    assert 'Join-Path $InstanceRoot "instance-manifest.json"' in text
    assert "state\\migrations\\receipts\\instance-schema-1-to-2.json" in text
    assert '$Instance.schema_version -ne 2' in text
    assert '$Instance.manifest_schema_version -ne 1' in text
    assert '$Instance.migrations_applied -ne 1' in text
    assert '$Manifest.derived_state.indexes -ne "rebuild"' in text
    assert '$Manifest.derived_state.library -ne "rebuild"' in text
    assert '$Manifest.derived_state.state_artifacts -ne "include"' in text
    assert '$Receipt.preflight_content_fingerprint -notmatch' in text
    assert '$Receipt.backup.sha256 -notmatch' in text
    assert "ExpectedMigrationBackupSha256" in text
    assert 'instance_schema_migration_and_backup = "PASS"' in text
