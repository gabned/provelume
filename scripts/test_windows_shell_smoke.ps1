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
    exact_head = $env:GITHUB_SHA
    default_port = 44851
    configured_port = $null
    checks = [ordered]@{}
    network_used_by_harness = $false
    private_content_logged = $false
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
    if ($env:GITHUB_SHA -and $env:GITHUB_SHA -ne $ExpectedCommit) {
        throw "Windows shell smoke is not bound to the workflow head."
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

    $OccupiedListener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $OccupiedListener.Start()
    try {
        $OccupiedPort = ([System.Net.IPEndPoint]$OccupiedListener.LocalEndpoint).Port
        $CollisionInstall = Invoke-Installer `
            -Target $CollisionRoot `
            -Port $OccupiedPort `
            -Tasks "traydefault"
        if ($CollisionInstall.ExitCode -eq 0) {
            throw "Installer accepted an occupied port."
        }
    }
    finally {
        $OccupiedListener.Stop()
    }
    if (Test-Path (Join-Path $CollisionRoot "Provelume.exe")) {
        throw "Failed occupied-port setup left an installed executable."
    }
    if (Test-Path $SettingsPath) {
        throw "Failed occupied-port setup left shell preferences."
    }
    $Evidence.checks.occupied_port_fail_closed_and_rolled_back = "PASS"

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
}
catch {
    $Failed = $true
    $Evidence.status = "FAIL"
    $Evidence.failure_code = "windows_shell_smoke_failed"
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
