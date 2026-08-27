param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$PreviousInstaller,
    [Parameter(Mandatory = $true)][string]$InstallDirectory,
    [Parameter(Mandatory = $true)][string]$InstanceDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][ValidateSet("development", "preview", "stable")][string]$ExpectedChannel,
    [string]$PreviousVersion = "0.4.0",
    [string]$PreviousCommit = "a54ea64db7c3452d2be4dfdf761cdb6b6962c09b",
    [ValidateSet("preview", "stable")][string]$PreviousChannel = "preview"
)

$ErrorActionPreference = "Stop"
$InstallerPath = (Resolve-Path $Installer).Path
$PreviousInstallerSize = 18051429
$PreviousInstallerSha256 = "0d13b8940184befed42b6e96d3789b06c0cc6842bcd3473d8e26738d6df35749"
$ExpectedAppIdKey = "{E41A426B-F5FC-473F-A096-875017656A31}_is1"
if ([string]::IsNullOrWhiteSpace($PreviousInstaller)) {
    $PreviousInstaller = Join-Path (
        Split-Path $InstallerPath -Parent
    ) "Provelume-Setup-0.4.0-public.exe"
    Invoke-WebRequest `
        -Uri "https://github.com/gabned/provelume/releases/download/v0.4.0/Provelume-Setup-0.4.0-x64.exe" `
        -OutFile $PreviousInstaller
}
$PreviousInstallerPath = (Resolve-Path $PreviousInstaller).Path
if ((Get-Item $PreviousInstallerPath).Length -ne $PreviousInstallerSize) {
    throw "Published 0.4.0 installer size differs from the reviewed baseline."
}
$PreviousHash = (Get-FileHash $PreviousInstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($PreviousHash -ne $PreviousInstallerSha256) {
    throw "Published 0.4.0 installer SHA-256 differs from the reviewed baseline."
}
$InstallRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $InstallDirectory "Próvelume 日本")
)
$InstanceRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $InstanceDirectory "Sintética 日本")
)
$EvidenceRoot = Join-Path (Split-Path $InstallerPath -Parent) "windows-hardening-evidence"
$OriginalLocalAppData = $env:LOCALAPPDATA
$OriginalPath = $env:PATH
$OriginalPythonHome = $env:PYTHONHOME
$OriginalPythonPath = $env:PYTHONPATH
$SyntheticLocalAppData = Join-Path (Split-Path $InstallRoot -Parent) "Local AppData Próvelume 日本"
$SettingsPath = Join-Path $SyntheticLocalAppData "Provelume\launcher.json"

function Invoke-WindowsProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    $Process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -Wait -PassThru
    if ($Process.ExitCode -ne 0) {
        throw "Process failed with exit code $($Process.ExitCode): $FilePath"
    }
}

function Install-Provelume {
    param(
        [Parameter(Mandatory = $true)][string]$Setup,
        [string]$Directory,
        [switch]$DesktopShortcut
    )
    $Arguments = @("/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if ($Directory) {
        $Arguments += "/DIR=`"$Directory`""
    }
    if ($DesktopShortcut) {
        $Arguments += "/TASKS=desktopicon"
    }
    Invoke-WindowsProcess -FilePath $Setup -Arguments $Arguments
}

function Uninstall-Provelume {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $Uninstaller = Join-Path $Directory "unins000.exe"
    if (-not (Test-Path $Uninstaller)) {
        throw "Installed package has no uninstaller: $Directory"
    }
    Invoke-WindowsProcess -FilePath $Uninstaller -Arguments @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART"
    )
}

function Read-InstalledIdentity {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $Diagnostics = Join-Path $EvidenceRoot "$Name.json"
    Invoke-WindowsProcess -FilePath $Executable -Arguments @(
        "--diagnostics-file",
        "`"$Diagnostics`""
    )
    return Get-Content $Diagnostics -Raw | ConvertFrom-Json
}

function Assert-Identity {
    param(
        [Parameter(Mandatory = $true)]$Identity,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$Commit,
        [Parameter(Mandatory = $true)][string]$Channel
    )
    if (
        $Identity.about.version -ne $Version -or
        $Identity.about.commit -ne $Commit -or
        $Identity.about.channel -ne $Channel -or
        $Identity.about.runtime.packaging -ne "windows_installer" -or
        -not $Identity.frozen -or
        $Identity.network_used
    ) {
        throw "Installed desktop identity does not match the expected offline Windows build."
    }
    if ($Channel -eq "development") {
        if ($Identity.about.official_build_metadata -or $null -ne $Identity.about.tag) {
            throw "Development Windows build declares official release identity."
        }
    }
    elseif (
        -not $Identity.about.official_build_metadata -or
        $Identity.about.tag -ne "v$Version"
    ) {
        throw "Official Windows build is missing its release tag identity."
    }
}

function Get-ProvelumeUninstallEntries {
    $RegistryRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    return @(
        foreach ($Root in $RegistryRoots) {
            if (Test-Path $Root) {
                Get-ChildItem $Root |
                    Where-Object { $_.PSChildName -eq $ExpectedAppIdKey } |
                    ForEach-Object { Get-ItemProperty $_.PSPath }
            }
        }
    )
}

function Assert-SingleProductRegistration {
    param([Parameter(Mandatory = $true)][string]$ExpectedInstallRoot)
    $Entries = @(Get-ProvelumeUninstallEntries)
    if ($Entries.Count -ne 1) {
        throw "Expected one Provelume product registration, found $($Entries.Count)."
    }
    $RegisteredRoot = [System.IO.Path]::GetFullPath([string]$Entries[0].InstallLocation)
    if ($RegisteredRoot.TrimEnd("\") -ne $ExpectedInstallRoot.TrimEnd("\")) {
        throw "The Provelume AppId registration points to a different installation directory."
    }
}

function Get-FreeLoopbackPort {
    $Listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    $Listener.Start()
    try {
        return [int]$Listener.LocalEndpoint.Port
    }
    finally {
        $Listener.Stop()
    }
}

New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null
New-Item -ItemType Directory -Force -Path $SyntheticLocalAppData | Out-Null

try {
    foreach ($UnsignedInstaller in @($InstallerPath, $PreviousInstallerPath)) {
        $Signature = Get-AuthenticodeSignature $UnsignedInstaller
        if ($Signature.Status -ne "NotSigned") {
            throw "Windows preview installer unexpectedly changed signing state: $UnsignedInstaller"
        }
    }

    # Exercise the setup default and both shortcut contracts before the in-place upgrade path.
    $DefaultInstallRoot = Join-Path $OriginalLocalAppData "Programs\Provelume"
    Install-Provelume -Setup $InstallerPath -DesktopShortcut
    $DefaultExecutable = Join-Path $DefaultInstallRoot "Provelume.exe"
    if (-not (Test-Path $DefaultExecutable)) {
        throw "Default per-user install did not produce Provelume.exe."
    }
    $StartShortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "Provelume\Provelume.lnk"
    $DesktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Provelume.lnk"
    if (-not (Test-Path $StartShortcut) -or -not (Test-Path $DesktopShortcut)) {
        throw "The Start or explicitly requested desktop shortcut is missing."
    }
    Assert-SingleProductRegistration -ExpectedInstallRoot $DefaultInstallRoot
    $DefaultIdentity = Read-InstalledIdentity -Executable $DefaultExecutable -Name "default-path"
    Assert-Identity -Identity $DefaultIdentity -Version $ExpectedVersion `
        -Commit $ExpectedCommit -Channel $ExpectedChannel
    Uninstall-Provelume -Directory $DefaultInstallRoot
    if (
        (Test-Path $DefaultExecutable) -or
        (Test-Path $StartShortcut) -or
        (Test-Path $DesktopShortcut)
    ) {
        throw "Default uninstall left runtime files or product shortcuts behind."
    }

    # Redirect launcher state to a synthetic Unicode path and install the real public baseline.
    $env:LOCALAPPDATA = $SyntheticLocalAppData
    Install-Provelume -Setup $PreviousInstallerPath -Directory $InstallRoot
    $Executable = Join-Path $InstallRoot "Provelume.exe"
    if (-not (Test-Path $Executable)) {
        throw "Published baseline install did not produce Provelume.exe."
    }
    $PreviousIdentity = Read-InstalledIdentity -Executable $Executable -Name "published-baseline"
    Assert-Identity -Identity $PreviousIdentity -Version $PreviousVersion `
        -Commit $PreviousCommit -Channel $PreviousChannel

    Invoke-WindowsProcess -FilePath $Executable -Arguments @(
        "--bootstrap-instance",
        "`"$InstanceRoot`"",
        "--instance-name",
        "`"Windows CI Instance – sintética 日本`""
    )
    $InstanceConfig = Join-Path $InstanceRoot "provelume.yml"
    if (-not (Test-Path $InstanceConfig)) {
        throw "Published baseline could not bootstrap the synthetic Instance."
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $InstanceRoot "upgrade-preservation-marker.txt"),
        "synthetic upgrade preservation evidence`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    New-Item -ItemType Directory -Force -Path (Split-Path $SettingsPath -Parent) | Out-Null
    $Settings = @{
        schema_version = 1
        instance_path = $InstanceRoot
        update_channel = "stable"
        check_on_start = $true
        language = "it"
    }
    [System.IO.File]::WriteAllText(
        $SettingsPath,
        (($Settings | ConvertTo-Json) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot

    # Install the candidate over the public baseline. The stable AppId must replace one product.
    Install-Provelume -Setup $InstallerPath -Directory $InstallRoot
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot

    # The frozen product must run without Git or Python on PATH and ignore hostile Python env vars.
    try {
        $env:PATH = "$env:SystemRoot\System32"
        $env:PYTHONHOME = "Z:\synthetic-missing-python"
        $env:PYTHONPATH = "Z:\synthetic-missing-modules"
        $CandidateIdentity = Read-InstalledIdentity -Executable $Executable -Name "candidate"
    }
    finally {
        $env:PATH = $OriginalPath
        $env:PYTHONHOME = $OriginalPythonHome
        $env:PYTHONPATH = $OriginalPythonPath
    }
    Assert-Identity -Identity $CandidateIdentity -Version $ExpectedVersion `
        -Commit $ExpectedCommit -Channel $ExpectedChannel

    $PreservedSettings = Get-Content $SettingsPath -Raw | ConvertFrom-Json
    if (
        $PreservedSettings.instance_path -ne $InstanceRoot -or
        $PreservedSettings.update_channel -ne "stable" -or
        -not $PreservedSettings.check_on_start -or
        $PreservedSettings.language -ne "it"
    ) {
        throw "In-place upgrade did not preserve launcher settings."
    }
    if (
        -not (Test-Path $InstanceConfig) -or
        -not (Test-Path (Join-Path $InstanceRoot "upgrade-preservation-marker.txt"))
    ) {
        throw "In-place upgrade did not preserve the synthetic Instance."
    }

    # Exercise the actual frozen Tk layout at every supported DPI probe and reduced resolution.
    foreach ($Language in @("en", "it")) {
        foreach ($Dpi in @(100, 125, 150, 200)) {
            $LayoutEvidence = Join-Path $EvidenceRoot "layout-$Language-$Dpi.json"
            Invoke-WindowsProcess -FilePath $Executable -Arguments @(
                "--ui-diagnostics-file", "`"$LayoutEvidence`"",
                "--ui-diagnostics-language", $Language,
                "--ui-diagnostics-dpi", "$Dpi",
                "--ui-diagnostics-width", "640",
                "--ui-diagnostics-height", "480"
            )
            $Layout = Get-Content $LayoutEvidence -Raw | ConvertFrom-Json
            if (
                $Layout.network_used -or
                $Layout.instance_content_sent -or
                -not $Layout.all_action_labels_present -or
                $Layout.window.width -gt $Layout.modeled_viewport.width -or
                $Layout.window.height -gt $Layout.modeled_viewport.height -or
                $Layout.scroll_surface.content_width -le 0 -or
                $Layout.scroll_surface.content_height -le 0 -or
                $Layout.controls.open -ne "normal" -or
                $Layout.controls.stop -ne "disabled" -or
                $Layout.controls.check -ne "normal" -or
                $Layout.controls.download -ne "disabled"
            ) {
                throw "Frozen launcher layout diagnostics failed for $Language at $Dpi percent."
            }
        }
    }

    # Start the bundled backend and verify identity plus the preserved Instance through loopback.
    $Port = Get-FreeLoopbackPort
    $Backend = Start-Process -FilePath $Executable -ArgumentList @(
        "--serve", "`"$InstanceRoot`"", "--port", "$Port"
    ) -PassThru
    try {
        $Ready = $false
        for ($Attempt = 1; $Attempt -le 80; $Attempt++) {
            if ($Backend.HasExited) {
                break
            }
            try {
                $Health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 1
                if ($Health.ok) {
                    $Ready = $true
                    break
                }
            }
            catch {
                Start-Sleep -Milliseconds 200
            }
        }
        if (-not $Ready) {
            throw "The candidate backend did not become ready on loopback."
        }
        $Build = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/build-info" -TimeoutSec 2
        $Instance = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/instance" -TimeoutSec 2
        if (
            $Build.version -ne $ExpectedVersion -or
            $Build.commit -ne $ExpectedCommit -or
            $Build.channel -ne $ExpectedChannel -or
            $Instance.name -ne "Windows CI Instance – sintética 日本"
        ) {
            throw "Candidate backend identity or preserved Instance is inconsistent."
        }
    }
    finally {
        if ($Backend -and -not $Backend.HasExited) {
            Stop-Process -Id $Backend.Id -Force
            $Backend.WaitForExit()
        }
    }

    # Reinstall once more, then uninstall the candidate while retaining state and the Instance.
    Install-Provelume -Setup $InstallerPath -Directory $InstallRoot
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot
    Uninstall-Provelume -Directory $InstallRoot
    if (Test-Path $Executable) {
        throw "Uninstall left the installed executable behind."
    }
    if (-not (Test-Path $InstanceConfig) -or -not (Test-Path $SettingsPath)) {
        throw "Uninstall removed the separate Instance or launcher settings."
    }
    python -c "from pathlib import Path; from provelume.service import ProvelumeInstance; root=Path(r'''$InstanceRoot'''); assert ProvelumeInstance(root).instance_summary()['name'] == 'Windows CI Instance – sintética 日本'"
    if ($LASTEXITCODE -ne 0) {
        throw "The preserved Instance was not readable after uninstall."
    }
    $Summary = @{
        schema_version = 1
        synthetic_data_only = $true
        public_baseline = @{
            version = $PreviousVersion
            commit = $PreviousCommit
            channel = $PreviousChannel
            installer_sha256 = "0d13b8940184befed42b6e96d3789b06c0cc6842bcd3473d8e26738d6df35749"
            installer_size_bytes = 18051429
        }
        candidate = @{
            version = $ExpectedVersion
            commit = $ExpectedCommit
            channel = $ExpectedChannel
        }
        results = @{
            default_per_user_install = "PASS"
            unicode_install_and_instance_paths = "PASS"
            start_and_optional_desktop_shortcuts = "PASS"
            published_baseline_identity = "PASS"
            in_place_upgrade_and_single_app_id = "PASS"
            launcher_settings_preserved = "PASS"
            instance_preserved_and_readable = "PASS"
            bundled_runtime_without_python_or_git = "PASS"
            loopback_backend_identity_and_readiness = "PASS"
            reinstall_and_uninstall = "PASS"
            unsigned_preview_boundary = "PASS"
            en_it_dpi_layout_probes = "PASS"
            windows_10_22h2 = "BLOCKED"
            subjective_visual_quality = "MANUAL_CHECK_REQUIRED"
        }
    }
    [System.IO.File]::WriteAllText(
        (Join-Path $EvidenceRoot "windows-hardening-summary.json"),
        (($Summary | ConvertTo-Json -Depth 5) + "`n"),
        [System.Text.UTF8Encoding]::new($false)
    )
}
finally {
    $env:LOCALAPPDATA = $OriginalLocalAppData
    $env:PATH = $OriginalPath
    $env:PYTHONHOME = $OriginalPythonHome
    $env:PYTHONPATH = $OriginalPythonPath
}
