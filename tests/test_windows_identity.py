from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_windows_icon_is_public_multi_resolution_and_reproducible() -> None:
    manifest = json.loads(
        (ROOT / "assets/windows/icon-manifest.json").read_text(encoding="utf-8")
    )
    icon = (ROOT / manifest["output"]).read_bytes()
    reserved, image_type, count = struct.unpack_from("<HHH", icon)
    assert (reserved, image_type, count) == (0, 1, 9)
    sizes = []
    for index in range(count):
        width, height, colors, reserved_byte, planes, bits, length, offset = struct.unpack_from(
            "<BBBBHHII",
            icon,
            6 + index * 16,
        )
        assert colors == reserved_byte == 0
        assert planes == 1
        assert bits == 32
        assert icon[offset : offset + 8] == b"\x89PNG\r\n\x1a\n"
        assert len(icon[offset : offset + length]) == length
        sizes.append(256 if width == 0 else width)
        assert height == width
    assert sizes == manifest["sizes"] == [16, 20, 24, 32, 40, 48, 64, 128, 256]
    assert manifest["external_resources"] is False
    assert manifest["accessible_text_replacement"] is False

    checked = subprocess.run(
        [sys.executable, "scripts/generate_windows_icon.py", "--check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
    svg = (ROOT / manifest["source"]).read_text(encoding="utf-8")
    assert "<title" in svg and "<desc" in svg
    assert "http://" not in svg.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in svg


def test_executable_installer_shortcut_and_uninstaller_identity_are_declared() -> None:
    spec = (ROOT / "packaging/windows/provelume.spec").read_text(encoding="utf-8")
    installer = (ROOT / "packaging/windows/provelume.iss").read_text(encoding="utf-8")
    metadata = (ROOT / "packaging/windows/version_info.txt").read_text(encoding="utf-8")

    assert 'icon=str(ICON)' in spec
    assert 'version=str(VERSION_INFO)' in spec
    assert '[(str(ICON), "assets")]' in spec
    assert "SetupIconFile={#MyIconFile}" in installer
    assert "UninstallDisplayIcon={app}\\Provelume.exe" in installer
    assert installer.count('AppUserModelID: "Provelume.Desktop"') == 2
    assert 'IconFilename: "{app}\\Provelume.exe"' in installer
    assert "AppName=Provelume" in installer
    assert "UninstallDisplayName=Provelume" in installer
    assert "FileDescription', 'Provelume Windows Shell'" in metadata
    assert "ProductName', 'Provelume'" in metadata
    assert "FileVersion', '0.10.0'" in metadata
    assert "ProductVersion', '0.10.0'" in metadata


def test_installer_endpoint_tray_login_upgrade_and_uninstall_contract_is_explicit() -> None:
    installer = (ROOT / "packaging/windows/provelume.iss").read_text(encoding="utf-8")

    assert "{param:LOCALPORT|44851}" in installer
    assert "SelectedPort < 1024" in installer
    assert "SelectedPort > 65535" in installer
    assert "--initialize-shell-settings" in installer
    assert "Arguments := '--validate-port ' + IntToStr(ValidatedInstallPort)" in installer
    assert "if not ExistingShellSettings then" in installer
    assert "--install-tray" in installer
    assert "--install-login-startup" in installer
    assert 'Name: "traydefault"' in installer
    assert 'Name: "loginstartup"' in installer
    assert "ExistingShellSettings" in installer
    assert "function PrepareToInstall(var NeedsRestart: Boolean): String;" in installer
    assert "NeedsRestart := False" in installer
    assert "[Net.Sockets.Socket]::new" in installer
    assert "[Net.IPAddress]::Loopback" in installer
    assert "$socket.ExclusiveAddressUse=$true" in installer
    assert "IntToStr(SelectedPort)" in installer
    assert "ValidatedInstallPort := SelectedPort" in installer
    assert "IntToStr(ValidatedInstallPort)" in installer
    assert "Result := ExpandConstant('{cm:EndpointPreflightUnavailable}')" in installer
    assert installer.index("function PrepareToInstall") < installer.index(
        "procedure CurStepChanged"
    )
    assert "--remove-login-startup" in installer
    assert "Launcher state and Instance data intentionally live elsewhere" in installer
    lowered = installer.casefold()
    assert "new-netfirewallrule" not in lowered
    assert "netsh" not in lowered
    assert "0.0.0.0" not in lowered
    assert "-executionpolicy" not in lowered
    assert "--install-port ' + portpage.values[0]" not in lowered


def test_signing_path_is_fail_closed_and_unsigned_development_is_truthful() -> None:
    signing = (ROOT / "scripts/verify_windows_signature.ps1").read_text(encoding="utf-8")
    build = (ROOT / "scripts/build_windows_installer.ps1").read_text(encoding="utf-8")
    installer = (ROOT / "packaging/windows/provelume.iss").read_text(encoding="utf-8")

    for token in (
        "RequireSignedRelease",
        "AllowUnsignedDevelopment",
        "ExpectedPublisher",
        "ExpectedSha256",
        "SignatureStatus]::Valid",
        "SignerCertificate.Subject",
        "TimeStamperCertificate",
        "artifact_sha256",
        "Exact release artifact SHA-256 does not match",
        'signature_status = "unsigned"',
    ):
        assert token in signing
    assert build.count("-AllowUnsignedDevelopment") == 2
    assert "SignedUninstaller=no" in installer
    assert "not an Authenticode claim" in installer
    assert "certificate" not in installer.casefold()

    credential_suffixes = {".p12", ".pfx", ".pem", ".key"}
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.splitlines()
    assert not [path for path in tracked if Path(path).suffix.casefold() in credential_suffixes]


def test_windows_shell_smoke_is_bounded_sanitized_and_exact_head_aware() -> None:
    smoke = (ROOT / "scripts/test_windows_shell_smoke.ps1").read_text(encoding="utf-8")
    for token in (
        "PROVELUME_QUALIFIED_SHA",
        "ExpectedCommit",
        "occupied_port_fail_closed_and_rolled_back",
        "shortcuts_and_app_user_model_id",
        "installed_native_tray_add_update_delete_and_actions",
        "loopback_no_network_single_service_and_cleanup",
        "default_44851_and_login_startup_opt_in",
        "private_content_logged = $false",
        "network_used_by_harness = $false",
        'failure_code = "windows_shell_smoke_failed"',
        'Set-FailureCode "occupied_port_collision_not_rejected"',
        'Set-FailureCode "occupied_port_installer_returned_success"',
        'Set-FailureCode "occupied_port_fixture_expired"',
        'Set-FailureCode "occupied_port_source_probe_disagreed"',
        "source_probe_observed_occupied_port",
        'Set-FailureCode "occupied_port_left_runtime"',
        'Set-FailureCode "occupied_port_left_preferences"',
        "collision_installer_exit_code",
        "final_uninstall_exit_code",
        'listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)',
        'ready.write_text("READY\\n", encoding="ascii")',
        "time.sleep(120)",
        "$OccupiedHolder.WaitForExit(5000)",
        'Set-FailureCode "native_tray_lifecycle_failed"',
        "WaitForExit(5000)",
        "--native-tray-smoke-file",
        '$DiagnosticsProcess = Invoke-BoundedProcess',
        '$NativeTrayProcess = Invoke-BoundedProcess',
        '$BootstrapProcess = Invoke-BoundedProcess',
        '"installed-shell-diagnostics.json"',
        'Set-FailureCode "instance_bootstrap_failed"',
        'Set-FailureCode "loopback_service_startup_failed"',
        'Set-FailureCode "loopback_service_exited_before_ready"',
        "[DateTime]::UtcNow.AddSeconds(30)",
        "service_exit_code",
        "service_ready_attempts",
        '$Health.ok -eq $true',
        'Set-FailureCode "local_only_network_policy_failed"',
        'Set-FailureCode "loopback_listener_contract_failed"',
        'Set-FailureCode "service_cleanup_failed"',
        'Set-FailureCode "configured_uninstall_failed"',
        'Set-FailureCode "default_reinstall_failed"',
        'Set-FailureCode "final_uninstall_failed"',
        "notification_added",
        "notification_updated",
        "notification_deleted",
        "function Get-RegisteredUninstaller",
        '"{E41A426B-F5FC-473F-A096-875017656A31}_is1"',
        "Registered uninstaller points outside the expected installation root",
        '$Evidence.checks.registered_final_uninstaller = "PASS"',
    ):
        assert token in smoke
    for token in (
        "function Invoke-BoundedProcess",
        "$Process.WaitForExit($TimeoutMilliseconds)",
        "$Process.WaitForExit(5000)",
        "$FrozenProcessTimeoutMilliseconds = 30000",
        "$InstallerProcessTimeoutMilliseconds = 90000",
        "$UninstallerProcessTimeoutMilliseconds = 60000",
    ):
        assert token in smoke
    assert "Start-Process -FilePath $InstallerPath -ArgumentList $Arguments -Wait" not in smoke
    assert '$FinalUninstaller = Join-Path $InstallRoot "unins000.exe"' not in smoke
    assert "Invoke-WebRequest" not in smoke
    assert "Start-Sleep -Seconds" not in smoke
    workflow = (ROOT / ".github/workflows/windows-shell-smoke.yml").read_text(encoding="utf-8")
    assert "if: always()" in workflow
    assert "qualification_incomplete" in workflow
    assert "github.event.pull_request.head.sha || github.sha" in workflow
    assert workflow.count("$env:PROVELUME_QUALIFIED_SHA") >= 6
    assert "-ExpectedCommit $env:GITHUB_SHA" not in workflow
    assert (
        "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in workflow
    )
    assert "actions/upload-artifact@b7c566a772e6b6fb58ed0dc250532a479d7789f" not in workflow


def test_native_tray_uses_pointer_safe_win32_handles_and_bounded_shutdown() -> None:
    tray = (ROOT / "core/provelume/windows_tray.py").read_text(encoding="utf-8")
    desktop = (ROOT / "core/provelume/desktop.py").read_text(encoding="utf-8")
    for token in (
        "PostMessageW",
        "post_message.argtypes",
        "CreateWindowExW.restype = wintypes.HWND",
        "DefWindowProcW.restype = ctypes.c_ssize_t",
        "self._stop_requested",
        "thread.join(timeout=5)",
        "daemon=True",
        "NIM_DELETE",
        "notification_added",
        "notification_updated",
        "notification_deleted",
    ):
        assert token in tray
    for token in (
        "CreateMutexW.restype = wintypes.HANDLE",
        "CloseHandle.argtypes = [wintypes.HANDLE]",
        "def write_native_tray_smoke",
        "--native-tray-smoke-file",
    ):
        assert token in desktop
