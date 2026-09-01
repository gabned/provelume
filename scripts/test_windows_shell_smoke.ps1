param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$InstallDirectory,
    [Parameter(Mandatory = $true)][string]$InstanceDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$InstallerPath = (Resolve-Path -LiteralPath $Installer).Path
$InstallRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
$CollisionRoot = "$InstallRoot-collision"
$InstanceRoot = [System.IO.Path]::GetFullPath($InstanceDirectory)
$SyntheticLocalAppData = Join-Path (Split-Path $InstallRoot -Parent) "S07 Local AppData"
$SettingsPath = Join-Path $SyntheticLocalAppData "Provelume\launcher.json"
$EvidencePath = Join-Path (Split-Path $InstallerPath -Parent) "windows-shell-evidence.json"
$OriginalLocalAppData = $env:LOCALAPPDATA
$Service = $null
$Failed = $false
$Evidence = [ordered]@{
    schema_version = 1
    status = "RUNNING"
    failure_code = $null
    expected_commit = $ExpectedCommit
    exact_head = $ExpectedCommit
    default_port = 44851
    configured_port = $null
    collision_installer_exit_code = $null
    checks = [ordered]@{}
    native_tray = $null
    network_used_by_harness = $false
    private_content_logged = $false
}

function Set-FailureCode {
    param([string]$Code)
    $Evidence.failure_code = $Code
}

function Get-FreeLoopbackPort {
    $Probe = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $Probe.Start()
    try {
        return ([System.Net.IPEndPoint]$Probe.LocalEndpoint).Port
    }
    finally {
        $Probe.Stop()
    }
}

function Invoke-Installer {
    param(
        [string]$Target,
        [int]$Port,
        [string]$Tasks
    )
    $Arguments = @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/DIR=`"$Target`"",
        "/LOCALPORT=$Port",
        "/TASKS=`"$Tasks`""
    )
    return Start-Process -FilePath $InstallerPath -ArgumentList $Arguments -Wait -PassThru
}

try {
    if ($ExpectedCommit -notmatch '^[0-9a-f]{40}$') {
        throw "ExpectedCommit must be a full lowercase Git SHA-1."
    }
    if (
        $env:PROVELUME_QUALIFIED_SHA -and
        $env:PROVELUME_QUALIFIED_SHA -ne $ExpectedCommit
    ) {
        throw "Windows shell smoke is not bound to the qualified candidate head."
    }
    New-Item -ItemType Directory -Force -Path $SyntheticLocalAppData | Out-Null
    $env:LOCALAPPDATA = $SyntheticLocalAppData
    $FirewallBefore = @(
        Get-NetFirewallRule -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -match 'Provelume' } |
            Sort-Object -Property Name |
            Select-Object -ExpandProperty Name
    )

    & (Join-Path $SourceRoot "scripts\verify_windows_signature.ps1") `
        -Artifact $InstallerPath -AllowUnsignedDevelopment | Out-Null
    $Evidence.checks.installer_explicitly_unsigned = "PASS"

    Set-FailureCode "occupied_port_collision_not_rejected"
    $OccupiedPort = Get-FreeLoopbackPort
    $HolderScript = Join-Path (Split-Path $InstallerPath -Parent) "hold-port.py"
    $HolderReady = Join-Path (Split-Path $InstallerPath -Parent) "hold-port.ready"
    @'
import pathlib
import socket
import sys
import time

port = int(sys.argv[1])
ready = pathlib.Path(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    ready.write_text("READY\n", encoding="ascii")
    time.sleep(120)
'@ | Set-Content -LiteralPath $HolderScript -Encoding utf8NoBOM
    $OccupiedHolder = Start-Process -FilePath python -ArgumentList @(
        $HolderScript,
        $OccupiedPort,
        $HolderReady
    ) -PassThru
    try {
        $ReadyDeadline = [DateTime]::UtcNow.AddSeconds(5)
        while (-not (Test-Path $HolderReady) -and [DateTime]::UtcNow -lt $ReadyDeadline) {
            Start-Sleep -Milliseconds 50
        }
        if (-not (Test-Path $HolderReady) -or $OccupiedHolder.HasExited) {
            throw "Exclusive Python collision fixture did not become ready."
        }
        & python -c @'
from provelume.shell_settings import probe_port
import sys
sys.exit(0 if not probe_port(sys.argv[1])["available"] else 2)
'@ $OccupiedPort
        if ($LASTEXITCODE -ne 0) {
            Set-FailureCode "occupied_port_source_probe_disagreed"
            throw "Source endpoint probe did not observe the exclusive collision fixture."
        }
        $Evidence.checks.source_probe_observed_occupied_port = "PASS"
        $CollisionInstall = Invoke-Installer `
            -Target $CollisionRoot `
            -Port $OccupiedPort `
            -Tasks "traydefault"
        $Evidence.collision_installer_exit_code = $CollisionInstall.ExitCode
        if ($OccupiedHolder.HasExited) {
            Set-FailureCode "occupied_port_fixture_expired"
            throw "Exclusive collision fixture expired before installer validation completed."
        }
        if ($CollisionInstall.ExitCode -eq 0) {
            Set-FailureCode "occupied_port_installer_returned_success"
            throw "Installer accepted an occupied port."
        }
    }
    finally {
        if (-not $OccupiedHolder.HasExited) {
            Stop-Process -Id $OccupiedHolder.Id -Force -ErrorAction SilentlyContinue
            $OccupiedHolder.WaitForExit(5000) | Out-Null
        }
        Remove-Item -LiteralPath $HolderScript, $HolderReady -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path (Join-Path $CollisionRoot "Provelume.exe")) {
        Set-FailureCode "occupied_port_left_runtime"
        throw "Failed occupied-port setup left an installed executable."
    }
    if (Test-Path $SettingsPath) {
        Set-FailureCode "occupied_port_left_preferences"
        throw "Failed occupied-port setup left shell preferences."
    }
    $Evidence.checks.occupied_port_fail_closed_and_rolled_back = "PASS"

    Set-FailureCode "configured_port_install_failed"
    $ConfiguredPort = Get-FreeLoopbackPort
    if ($ConfiguredPort -eq 44851) {
        $ConfiguredPort = Get-FreeLoopbackPort
    }
    $Installed = Invoke-Installer `
        -Target $InstallRoot `
        -Port $ConfiguredPort `
        -Tasks "desktopicon,traydefault"
    if ($Installed.ExitCode -ne 0) {
        throw "Fresh configured-port installation failed with exit code $($Installed.ExitCode)."
    }
    $Executable = Join-Path $InstallRoot "Provelume.exe"
    $Uninstaller = Join-Path $InstallRoot "unins000.exe"
    if (-not (Test-Path $Executable) -or -not (Test-Path $Uninstaller)) {
        throw "Installer did not create executable and uninstaller."
    }
    $Settings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if (
        $Settings.schema_version -ne 2 -or
        $Settings.endpoint.host -ne "127.0.0.1" -or
        $Settings.endpoint.port -ne $ConfiguredPort -or
        -not $Settings.shell.tray_enabled -or
        $Settings.shell.login_startup
    ) {
        throw "Fresh install did not persist the selected closed shell contract."
    }
    $Evidence.configured_port = $ConfiguredPort
    $Evidence.checks.custom_port_and_separate_startup_preferences = "PASS"

    Set-FailureCode "windows_identity_validation_failed"
    $VersionInfo = (Get-Item -LiteralPath $Executable).VersionInfo
    if (
        $VersionInfo.ProductName -ne "Provelume" -or
        $VersionInfo.FileDescription -ne "Provelume Windows Shell" -or
        $VersionInfo.FileVersion -notlike "$ExpectedVersion*"
    ) {
        throw "Executable product metadata is inconsistent."
    }
    Add-Type -AssemblyName System.Drawing
    $ApplicationIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($Executable)
    $InstallerIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($InstallerPath)
    $UninstallerIcon = [System.Drawing.Icon]::ExtractAssociatedIcon($Uninstaller)
    if ($null -eq $ApplicationIcon -or $null -eq $InstallerIcon -or $null -eq $UninstallerIcon) {
        throw "A Windows executable is missing an associated icon resource."
    }
    $Evidence.checks.executable_installer_uninstaller_identity = "PASS"

    $StartMenu = [Environment]::GetFolderPath("Programs")
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $StartShortcut = Join-Path $StartMenu "Provelume\Provelume.lnk"
    $DesktopShortcut = Join-Path $Desktop "Provelume.lnk"
    if (-not (Test-Path $StartShortcut) -or -not (Test-Path $DesktopShortcut)) {
        throw "Expected Start Menu or explicitly selected desktop shortcut is missing."
    }
    $Shell = New-Object -ComObject Shell.Application
    foreach ($Shortcut in @($StartShortcut, $DesktopShortcut)) {
        $Folder = $Shell.Namespace((Split-Path $Shortcut -Parent))
        $Item = $Folder.ParseName((Split-Path $Shortcut -Leaf))
        $AppId = $Item.ExtendedProperty("System.AppUserModel.ID")
        if ($AppId -ne "Provelume.Desktop") {
            throw "Shortcut AppUserModelID is inconsistent: $AppId"
        }
    }
    $Evidence.checks.shortcuts_and_app_user_model_id = "PASS"

    & $Executable --diagnostics-file $EvidencePath
    if ($LASTEXITCODE -ne 0) {
        throw "Installed shell diagnostics failed."
    }
    $Diagnostics = Get-Content -LiteralPath $EvidencePath -Raw | ConvertFrom-Json
    if (
        $Diagnostics.about.version -ne $ExpectedVersion -or
        $Diagnostics.about.commit -ne $ExpectedCommit -or
        $Diagnostics.windows_identity.app_user_model_id -ne "Provelume.Desktop" -or
        $Diagnostics.windows_identity.process_app_user_model_id -ne "configured" -or
        $Diagnostics.windows_identity.authenticode -ne "unsigned" -or
        $Diagnostics.windows_identity.icon.status -ne "versioned_asset" -or
        $Diagnostics.windows_identity.icon.sizes.Count -ne 9 -or
        $Diagnostics.network_used
    ) {
        throw "Installed shell diagnostics do not match exact-head identity."
    }
    & (Join-Path $SourceRoot "scripts\verify_windows_signature.ps1") `
        -Artifact $Executable -AllowUnsignedDevelopment | Out-Null
    & (Join-Path $SourceRoot "scripts\verify_windows_signature.ps1") `
        -Artifact $Uninstaller -AllowUnsignedDevelopment | Out-Null
    $Evidence.checks.exact_identity_and_unsigned_boundary = "PASS"

    Set-FailureCode "native_tray_lifecycle_failed"
    $NativeTrayEvidencePath = Join-Path `
        (Split-Path $InstallerPath -Parent) `
        "native-tray-evidence.json"
    & $Executable --native-tray-smoke-file $NativeTrayEvidencePath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $NativeTrayEvidencePath)) {
        throw "Installed native tray lifecycle failed."
    }
    $NativeTray = Get-Content -LiteralPath $NativeTrayEvidencePath -Raw | ConvertFrom-Json
    if (
        $NativeTray.status -ne "PASS" -or
        $null -ne $NativeTray.failure_code -or
        -not $NativeTray.frozen_executable -or
        $NativeTray.windows_identity -ne "configured" -or
        -not $NativeTray.labels_en_it_complete -or
        ($NativeTray.action_sequence -join ",") -ne "open,settings,restart,quit" -or
        -not $NativeTray.notification.notification_added -or
        -not $NativeTray.notification.notification_updated -or
        -not $NativeTray.notification.notification_deleted -or
        -not $NativeTray.notification.native_window_released -or
        -not $NativeTray.notification.thread_stopped -or
        $NativeTray.notification.icon_source -notin @(
            "versioned_asset",
            "executable_resource"
        ) -or
        $NativeTray.notification.network_used -or
        $NativeTray.network_used -or
        $NativeTray.private_content_logged
    ) {
        throw "Installed native tray evidence is incomplete or non-sanitized."
    }
    if (Get-Process -Name Provelume -ErrorAction SilentlyContinue) {
        throw "Installed native tray smoke left a Provelume process."
    }
    $Evidence.native_tray = $NativeTray
    $Evidence.checks.installed_native_tray_add_update_delete_and_actions = "PASS"

    Set-FailureCode "instance_or_service_lifecycle_failed"
    & $Executable --bootstrap-instance $InstanceRoot --instance-name "Synthetic S07"
    if ($LASTEXITCODE -ne 0) {
        throw "Synthetic Instance bootstrap failed."
    }
    $Service = Start-Process -FilePath $Executable -ArgumentList @(
        "--serve",
        "`"$InstanceRoot`"",
        "--port",
        $ConfiguredPort
    ) -PassThru
    $Ready = $false
    for ($Attempt = 1; $Attempt -le 60; $Attempt++) {
        if ($Service.HasExited) {
            break
        }
        try {
            $Health = Invoke-RestMethod `
                -Uri "http://127.0.0.1:$ConfiguredPort/health" `
                -TimeoutSec 1
            if ($Health.status -eq "ok") {
                $Ready = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 150
        }
    }
    if (-not $Ready) {
        throw "Installed loopback service did not become ready within the bounded probe."
    }
    $NetworkStatus = Invoke-RestMethod `
        -Uri "http://127.0.0.1:$ConfiguredPort/api/v1/security/network" `
        -TimeoutSec 2
    if (
        $NetworkStatus.status -ne "local_only" -or
        $NetworkStatus.policy.external_access
    ) {
        throw "Default installed Instance did not remain no-network/local-only."
    }
    $Listeners = Get-NetTCPConnection -OwningProcess $Service.Id -State Listen
    if (
        $Listeners.Count -ne 1 -or
        $Listeners[0].LocalAddress -notin @("127.0.0.1", "::1") -or
        $Listeners[0].LocalPort -ne $ConfiguredPort
    ) {
        throw "Installed service listener escaped the loopback endpoint contract."
    }
    $ExternalConnections = @(
        Get-NetTCPConnection -OwningProcess $Service.Id -State Established `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.RemoteAddress -notin @("127.0.0.1", "::1")
            }
    )
    if ($ExternalConnections.Count -ne 0) {
        throw "Installed local-only service opened an external TCP connection."
    }
    if (Get-NetUDPEndpoint -OwningProcess $Service.Id -ErrorAction SilentlyContinue) {
        throw "Installed local-only service opened an unexpected UDP endpoint."
    }
    $Service.CloseMainWindow() | Out-Null
    Stop-Process -Id $Service.Id -ErrorAction SilentlyContinue
    $Service.WaitForExit(5000) | Out-Null
    $Service = $null
    Start-Sleep -Milliseconds 250
    if (Get-NetTCPConnection -LocalPort $ConfiguredPort -State Listen -ErrorAction SilentlyContinue) {
        throw "Installed service left a loopback socket after shutdown."
    }
    if (Get-Process -Name Provelume -ErrorAction SilentlyContinue) {
        throw "Installed service left a Provelume process after shutdown."
    }
    $Evidence.checks.loopback_no_network_single_service_and_cleanup = "PASS"

    $Uninstall = Start-Process -FilePath $Uninstaller -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART"
    ) -Wait -PassThru
    if ($Uninstall.ExitCode -ne 0 -or (Test-Path $Executable)) {
        throw "Configured-port uninstall did not complete cleanly."
    }
    if (-not (Test-Path $SettingsPath) -or -not (Test-Path $InstanceRoot)) {
        throw "Uninstall removed shell preferences or user Instance data without consent."
    }
    $Evidence.checks.uninstall_preserves_preferences_and_instance = "PASS"

    Remove-Item -LiteralPath $SettingsPath -Force
    $DefaultInstall = Invoke-Installer `
        -Target $InstallRoot `
        -Port 44851 `
        -Tasks "traydefault,loginstartup"
    if ($DefaultInstall.ExitCode -ne 0) {
        throw "Default endpoint installation failed."
    }
    $DefaultSettings = Get-Content -LiteralPath $SettingsPath -Raw | ConvertFrom-Json
    if (
        $DefaultSettings.endpoint.port -ne 44851 -or
        -not $DefaultSettings.shell.tray_enabled -or
        -not $DefaultSettings.shell.login_startup
    ) {
        throw "Default endpoint or separate login-startup selection was not persisted."
    }
    $RunValue = Get-ItemPropertyValue `
        -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
        -Name "Provelume"
    if ($RunValue -notmatch '--tray') {
        throw "Explicit login-startup selection did not create the bounded Run entry."
    }
    $Evidence.checks.default_44851_and_login_startup_opt_in = "PASS"

    $FinalUninstaller = Join-Path $InstallRoot "unins000.exe"
    $FinalUninstall = Start-Process -FilePath $FinalUninstaller -ArgumentList @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART"
    ) -Wait -PassThru
    if ($FinalUninstall.ExitCode -ne 0) {
        throw "Final uninstall failed."
    }
    if (
        Get-ItemProperty `
            -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" `
            -Name "Provelume" `
            -ErrorAction SilentlyContinue
    ) {
        throw "Uninstall left a login-startup entry targeting the removed executable."
    }
    if (-not (Test-Path $SettingsPath) -or -not (Test-Path $InstanceRoot)) {
        throw "Final uninstall removed preserved preferences or Instance data."
    }
    $Evidence.checks.controlled_uninstall_cleanup = "PASS"

    $FirewallAfter = @(
        Get-NetFirewallRule -ErrorAction SilentlyContinue |
            Where-Object { $_.DisplayName -match 'Provelume' } |
            Sort-Object -Property Name |
            Select-Object -ExpandProperty Name
    )
    if (Compare-Object -ReferenceObject $FirewallBefore -DifferenceObject $FirewallAfter) {
        throw "Install, service or uninstall changed Provelume firewall rules."
    }
    $Evidence.checks.no_firewall_modification = "PASS"

    $Evidence.status = "PASS"
    $Evidence.failure_code = $null
}
catch {
    $Failed = $true
    $Evidence.status = "FAIL"
    if ($null -eq $Evidence.failure_code) {
        $Evidence.failure_code = "windows_shell_smoke_failed"
    }
}
finally {
    if ($null -ne $Service -and -not $Service.HasExited) {
        Stop-Process -Id $Service.Id -Force -ErrorAction SilentlyContinue
    }
    $env:LOCALAPPDATA = $OriginalLocalAppData
    New-Item -ItemType Directory -Force -Path (Split-Path $EvidencePath -Parent) | Out-Null
    $Evidence | ConvertTo-Json -Depth 6 | Set-Content `
        -LiteralPath $EvidencePath `
        -Encoding utf8NoBOM
}

if ($Failed) {
    throw "Windows shell smoke failed; the sanitized evidence records completed checks."
}
$Evidence | ConvertTo-Json -Depth 6
