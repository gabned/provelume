from pathlib import Path

SCRIPT = Path("scripts/test_windows_installer.ps1")


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
    assert 'releases/download/v0.5.0/Provelume-Setup-0.5.0-x64.exe' in text
