param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [string]$PreviousInstaller,
    [string]$PreviousWheel,
    [Parameter(Mandatory = $true)][string]$InstallDirectory,
    [Parameter(Mandatory = $true)][string]$InstanceDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][ValidateSet("development", "preview", "stable")][string]$ExpectedChannel,
    [string]$PreviousVersion = "",
    [string]$PreviousCommit = "",
    [ValidateSet("preview", "stable")][string]$PreviousChannel = "preview"
)

$ErrorActionPreference = "Stop"
$InstallerPath = (Resolve-Path $Installer).Path
$ExpectedAppIdKey = "{E41A426B-F5FC-473F-A096-875017656A31}_is1"
if ([string]::IsNullOrWhiteSpace($PreviousInstaller)) {
    $PreviousInstaller = Join-Path (
        Split-Path $InstallerPath -Parent
    ) "Provelume-Setup-0.9.0-public.exe"
    Invoke-WebRequest `
        -Uri "https://github.com/gabned/provelume/releases/download/v0.9.0/Provelume-Setup-0.9.0-x64.exe" `
        -OutFile $PreviousInstaller
}
$PreviousInstallerPath = (Resolve-Path $PreviousInstaller).Path
$PreviousInstallerSize = (Get-Item $PreviousInstallerPath).Length
$PreviousInstallerSha256 = (
    Get-FileHash $PreviousInstallerPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$ApprovedPreviousBaselines = @(
    @{
        version = "0.4.0"
        commit = "a54ea64db7c3452d2be4dfdf761cdb6b6962c09b"
        size = 18051429
        sha256 = "0d13b8940184befed42b6e96d3789b06c0cc6842bcd3473d8e26738d6df35749"
    },
    @{
        version = "0.4.1"
        commit = "6e34498e98a315baaef00314fd59772a3af008df"
        size = 18056957
        sha256 = "ea2093cd63860e2575715617f3bde363646213841f60be1db97433b19052b46b"
    },
    @{
        version = "0.5.0"
        commit = "89c6b7c783e385c4e978cc2ae6bf602012aab77e"
        size = 18193123
        sha256 = "c604de1006c6f86a52bf61ca54fe6371e0889f728eb89f25e38776165254ecab"
    },
    @{
        version = "0.5.1"
        commit = "b3156617dc2ce9c97cd32ee105c18634cd4b9776"
        size = 18206254
        sha256 = "642de2931dc6fbc7f1a58fd490b73c45cef72719bc75c690713076f9bddf268b"
    },
    @{
        version = "0.6.0"
        commit = "bc02180fa116c2924b04f0a4c0bcf497a1efbd70"
        size = 18343369
        sha256 = "da338c65b8698d411561bbcb02e0711a1467628e3551c74b0989a7efe7ef6bc3"
    },
    @{
        version = "0.6.1"
        commit = "087094210be8c0d3c8d2d5a32de3f981f6e8be20"
        size = 18344455
        sha256 = "98e7b693903bc160ac45c11a7c114fed88019c403a98efc07bef5b7e5039afc3"
    },
    @{
        version = "0.7.0"
        commit = "1e1731969552497c2d3fe79b1c26eccdaad712c0"
        size = 18464821
        sha256 = "46d7df0f94f3e9431685741594489ffcc99e0edf3f4880644c87e280fdecd5cb"
        wheel_size = 294593
        wheel_sha256 = "1beba35635fca2bcafa5d4f1a93d035592751f18785339705e1dbb3df7bf2a41"
    },
    @{
        version = "0.9.0"
        commit = "e08125a8600f9c4300d0d173613a03f8bbc31327"
        size = 19161550
        sha256 = "e94c0722a92179c00d93db61f1aa5f3aab565f56d8382651471b3778dd503d68"
        wheel_size = 643901
        wheel_sha256 = "50eca9dc67672c79aa5570de0cad1454546d75a2b3fe5d6edae600bf73a5488f"
    }
)
$IdentifiedBaseline = $ApprovedPreviousBaselines |
    Where-Object {
        $_.size -eq $PreviousInstallerSize -and
        $_.sha256 -eq $PreviousInstallerSha256
    } |
    Select-Object -First 1
if ($null -eq $IdentifiedBaseline) {
    throw "Previous installer does not match an approved public Provelume baseline."
}
$PreviousWheelPath = $null
if ($IdentifiedBaseline.ContainsKey("wheel_size")) {
    if ([string]::IsNullOrWhiteSpace($PreviousWheel)) {
        $PreviousWheel = Join-Path (
            Split-Path $InstallerPath -Parent
        ) "provelume-$($IdentifiedBaseline.version)-py3-none-any.whl"
        Invoke-WebRequest `
            -Uri (
                "https://github.com/gabned/provelume/releases/download/" +
                "v$($IdentifiedBaseline.version)/" +
                "provelume-$($IdentifiedBaseline.version)-py3-none-any.whl"
            ) `
            -OutFile $PreviousWheel
    }
    $PreviousWheelPath = (Resolve-Path $PreviousWheel).Path
    $ObservedWheelSize = (Get-Item $PreviousWheelPath).Length
    $ObservedWheelSha256 = (
        Get-FileHash $PreviousWheelPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    if (
        $ObservedWheelSize -ne $IdentifiedBaseline.wheel_size -or
        $ObservedWheelSha256 -ne $IdentifiedBaseline.wheel_sha256
    ) {
        throw "Previous wheel does not match the approved public Provelume baseline."
    }
}
if (
    -not [string]::IsNullOrWhiteSpace($PreviousVersion) -and
    $PreviousVersion -ne $IdentifiedBaseline.version
) {
    throw "Supplied previous version does not match the verified installer bytes."
}
if (
    -not [string]::IsNullOrWhiteSpace($PreviousCommit) -and
    $PreviousCommit -ne $IdentifiedBaseline.commit
) {
    throw "Supplied previous commit does not match the verified installer bytes."
}
$PreviousVersion = $IdentifiedBaseline.version
$PreviousCommit = $IdentifiedBaseline.commit
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
$BaselineRuntimeRoot = Join-Path (Split-Path $InstallRoot -Parent) "Published Baseline Runtime"
$BaselineSourceRoot = Join-Path (Split-Path $InstallRoot -Parent) "Published Baseline Source"

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

function Get-YamlScalar {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Key
    )
    $Match = [regex]::Match(
        $Text,
        "(?m)^\s{2}$([regex]::Escape($Key)):\s*(?<value>[^\r\n]+?)\s*$"
    )
    if (-not $Match.Success) {
        throw "Instance configuration is missing the expected $Key value."
    }
    $Value = $Match.Groups["value"].Value.Trim()
    if (
        $Value.Length -ge 2 -and
        (($Value.StartsWith("'") -and $Value.EndsWith("'")) -or
        ($Value.StartsWith('"') -and $Value.EndsWith('"')))
    ) {
        return $Value.Substring(1, $Value.Length - 2)
    }
    return $Value
}

function Get-InstanceTreeFingerprint {
    param([Parameter(Mandatory = $true)][string]$Root)
    $Rows = @(
        Get-ChildItem -LiteralPath $Root -File -Recurse |
            ForEach-Object {
                $Relative = [System.IO.Path]::GetRelativePath($Root, $_.FullName).Replace("\", "/")
                $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                "$Relative`t$($_.Length)`t$Hash"
            } |
            Sort-Object
    )
    $Payload = [System.Text.UTF8Encoding]::new($false).GetBytes(
        (($Rows -join "`n") + "`n")
    )
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString(
            $Hasher.ComputeHash($Payload)
        ).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $Hasher.Dispose()
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

    # Redirect launcher state to a synthetic Unicode path and install a verified public baseline.
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
    $LegacyConfigText = [System.IO.File]::ReadAllText(
        $InstanceConfig,
        [System.Text.Encoding]::UTF8
    )
    $BaselineRequiresMigration = (
        [version]$PreviousVersion -lt [version]"0.6.0"
    )
    $ExpectedBaselineSchemaVersion = if ($BaselineRequiresMigration) { 1 } else { 2 }
    if (
        $LegacyConfigText -notmatch (
            "(?m)^schema_version:\s+$ExpectedBaselineSchemaVersion\s*$"
        )
    ) {
        throw (
            "Published baseline did not create the expected " +
            "schema-$ExpectedBaselineSchemaVersion Instance."
        )
    }
    $InstanceManifest = Join-Path $InstanceRoot "instance-manifest.json"
    $BaselineInstanceManifestSha256 = $null
    if ($BaselineRequiresMigration) {
        if (Test-Path $InstanceManifest) {
            throw "Legacy baseline unexpectedly created a current-schema Instance manifest."
        }
    }
    else {
        if (-not (Test-Path $InstanceManifest)) {
            throw "Current-schema baseline did not create an Instance manifest."
        }
        $BaselineInstanceManifestSha256 = (
            Get-FileHash $InstanceManifest -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    $LegacyInstanceId = Get-YamlScalar -Text $LegacyConfigText -Key "id"
    $LegacyInstanceName = "Windows CI Instance – sintética 日本"
    $LegacyInstanceCreatedAt = Get-YamlScalar -Text $LegacyConfigText -Key "created_at"
    [System.IO.File]::WriteAllText(
        (Join-Path $InstanceRoot "upgrade-preservation-marker.txt"),
        "synthetic upgrade preservation evidence`n",
        [System.Text.UTF8Encoding]::new($false)
    )
    $BaselineDocumentCount = 0
    if ($null -ne $PreviousWheelPath) {
        python -m venv $BaselineRuntimeRoot
        if ($LASTEXITCODE -ne 0) {
            throw "Creating the published baseline runtime failed."
        }
        $BaselinePython = Join-Path $BaselineRuntimeRoot "Scripts\python.exe"
        $BaselineWheelRoot = Join-Path $BaselineRuntimeRoot "verified-wheel"
        New-Item -ItemType Directory -Force -Path $BaselineWheelRoot | Out-Null
        $CanonicalPreviousWheelPath = Join-Path $BaselineWheelRoot (
            "provelume-$PreviousVersion-py3-none-any.whl"
        )
        Copy-Item -LiteralPath $PreviousWheelPath -Destination $CanonicalPreviousWheelPath
        & $BaselinePython -m pip install --disable-pip-version-check --require-hashes `
            -r (Join-Path $PSScriptRoot "..\build-lock\windows-py312-x86_64.requirements.txt")
        if ($LASTEXITCODE -ne 0) {
            throw "Installing the reviewed Windows runtime lock for the baseline failed."
        }
        & $BaselinePython -m pip install --disable-pip-version-check --no-deps `
            $CanonicalPreviousWheelPath
        if ($LASTEXITCODE -ne 0) {
            throw "Installing the immutable published baseline wheel failed."
        }
        New-Item -ItemType Directory -Force -Path $BaselineSourceRoot | Out-Null
        [System.IO.File]::WriteAllText(
            (Join-Path $BaselineSourceRoot "preserved-knowledge.md"),
            "# Preserved knowledge`n`nSynthetic $PreviousVersion upgrade evidence.`n",
            [System.Text.UTF8Encoding]::new($false)
        )
        & $BaselinePython -m provelume ingest $InstanceRoot $BaselineSourceRoot `
            --name "Published $PreviousVersion synthetic source"
        if ($LASTEXITCODE -ne 0) {
            throw "The immutable published baseline could not create canonical knowledge."
        }
        $BaselineDocumentCount = @(
            Get-ChildItem (Join-Path $InstanceRoot "knowledge\documents") -File
        ).Count
        if (
            $BaselineDocumentCount -lt 1 -or
            @(Get-ChildItem (Join-Path $InstanceRoot "originals") -File -Recurse).Count -lt 1 -or
            @(Get-ChildItem (Join-Path $InstanceRoot "state\ingestion") -File -Recurse).Count -lt 1
        ) {
            throw "Published baseline ingestion did not create canonical, Original and durable state."
        }
    }
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
    $LegacyInstanceConfigSha256 = (
        Get-FileHash $InstanceConfig -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $ExpectedMarkerSha256 = (
        Get-FileHash (Join-Path $InstanceRoot "upgrade-preservation-marker.txt") `
            -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $ExpectedSettingsSha256 = (
        Get-FileHash $SettingsPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $BaselineInstanceTreeSha256 = Get-InstanceTreeFingerprint -Root $InstanceRoot
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot

    # Install the candidate over the public baseline. The stable AppId must replace one product.
    Install-Provelume -Setup $InstallerPath -Directory $InstallRoot
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot
    $ManifestChangedByInstaller = if ($BaselineRequiresMigration) {
        Test-Path $InstanceManifest
    }
    else {
        -not (Test-Path $InstanceManifest) -or
        (Get-FileHash $InstanceManifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $BaselineInstanceManifestSha256
    }
    if (
        (Get-FileHash $InstanceConfig -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $LegacyInstanceConfigSha256 -or
        $ManifestChangedByInstaller -or
        (Get-InstanceTreeFingerprint -Root $InstanceRoot) -ne $BaselineInstanceTreeSha256
    ) {
        throw "The installer mutated the Instance instead of preserving Core authority."
    }

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
                $Layout.scroll_surface.viewport_width -le 1 -or
                $Layout.scroll_surface.viewport_height -le 1 -or
                $Layout.scroll_surface.content_width -le 0 -or
                $Layout.scroll_surface.content_height -le 0 -or
                $Layout.controls.open -ne "normal" -or
                $Layout.controls.stop -ne "disabled" -or
                $Layout.controls.choose -ne "normal" -or
                $Layout.controls.create -ne "normal" -or
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
            $BackendState = if ($Backend.HasExited) {
                "exit code $($Backend.ExitCode)"
            }
            else {
                "still running after the bounded readiness window"
            }
            throw "The candidate backend did not become ready on loopback ($BackendState)."
        }
        $ExpectedMigrationCount = if ($BaselineRequiresMigration) { 1 } else { 0 }
        $Build = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/build-info" -TimeoutSec 2
        $Instance = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/instance" -TimeoutSec 2
        $Network = Invoke-RestMethod "http://127.0.0.1:$Port/api/v1/security/network" -TimeoutSec 2
        $Documents = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/documents" -TimeoutSec 2
        $Policies = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/scheduler/policies" -TimeoutSec 2
        $Jobs = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/scheduler/jobs" -TimeoutSec 2
        $Receipts = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/scheduler/receipts" -TimeoutSec 2
        $MaintenanceRuns = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/maintenance/runs" -TimeoutSec 2
        $SourceRuns = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/maintenance/source-runs" -TimeoutSec 2
        $ResourceSnapshots = Invoke-RestMethod `
            "http://127.0.0.1:$Port/api/v1/maintenance/resource-statistics/snapshots" `
            -TimeoutSec 2
        $DocumentCount = @($Documents).Count
        $PolicyCount = @($Policies).Count
        $JobCount = @($Jobs).Count
        $ReceiptCount = @($Receipts).Count
        $MaintenanceRunCount = @($MaintenanceRuns).Count
        $SourceRunCount = @($SourceRuns).Count
        $ResourceSnapshotCount = @($ResourceSnapshots).Count
        $RuntimeBoundaryEvidence = [ordered]@{
            build_version = $Build.version
            build_commit = $Build.commit
            build_channel = $Build.channel
            instance_id = $Instance.id
            instance_name = $Instance.name
            instance_schema_version = $Instance.schema_version
            manifest_schema_version = $Instance.manifest_schema_version
            derived_indexes = $Instance.derived_state.indexes
            derived_library = $Instance.derived_state.library
            derived_state_artifacts = $Instance.derived_state.state_artifacts
            migrations_applied = $Instance.migrations_applied
            lifecycle_recoveries = $Instance.lifecycle_recoveries
            network_status = $Network.status
            network_external_access = $Network.policy.external_access
            enabled_external_components = $Network.summary.enabled_external_components
            network_used = $Network.network_used
            document_count = $DocumentCount
            baseline_document_count = $BaselineDocumentCount
            policy_count = $PolicyCount
            job_count = $JobCount
            receipt_count = $ReceiptCount
            maintenance_run_count = $MaintenanceRunCount
            source_run_count = $SourceRunCount
            resource_snapshot_count = $ResourceSnapshotCount
        }
        Write-Host (
            "Windows runtime boundary evidence: " +
            ($RuntimeBoundaryEvidence | ConvertTo-Json -Compress)
        )
        if (
            $Build.version -ne $ExpectedVersion -or
            $Build.commit -ne $ExpectedCommit -or
            $Build.channel -ne $ExpectedChannel -or
            $Instance.id -ne $LegacyInstanceId -or
            $Instance.name -ne $LegacyInstanceName -or
            $Instance.schema_version -ne 2 -or
            $Instance.manifest_schema_version -ne 1 -or
            $Instance.derived_state.indexes -ne "rebuild" -or
            $Instance.derived_state.library -ne "rebuild" -or
            $Instance.derived_state.state_artifacts -ne "include" -or
            $Instance.migrations_applied -ne $ExpectedMigrationCount -or
            $Instance.lifecycle_recoveries -ne 0 -or
            $Network.status -ne "local_only" -or
            $Network.policy.external_access -or
            $Network.summary.enabled_external_components -ne 0 -or
            $Network.network_used -or
            $DocumentCount -lt $BaselineDocumentCount -or
            $PolicyCount -ne 0 -or
            $JobCount -ne 0 -or
            $ReceiptCount -ne 0 -or
            $MaintenanceRunCount -ne 0 -or
            $SourceRunCount -ne 0 -or
            $ResourceSnapshotCount -ne 0
        ) {
            throw (
                "Candidate identity, preserved knowledge or default-disabled automation " +
                "boundary is inconsistent."
            )
        }
    }
    finally {
        if ($Backend -and -not $Backend.HasExited) {
            Stop-Process -Id $Backend.Id -Force
            $Backend.WaitForExit()
        }
    }

    # Cover runtime access as well as installer replacement with the exact tree proof.
    $PostStartupInstanceTreeSha256 = Get-InstanceTreeFingerprint -Root $InstanceRoot
    if (
        -not $BaselineRequiresMigration -and
        $PostStartupInstanceTreeSha256 -ne $BaselineInstanceTreeSha256
    ) {
        throw "Candidate startup mutated the preserved current-schema Instance tree."
    }

    # Verify either the controlled legacy migration or exact current-schema preservation.
    $MigrationReceiptPath = Join-Path $InstanceRoot (
        "state\migrations\receipts\instance-schema-1-to-2.json"
    )
    if (-not (Test-Path $InstanceManifest)) {
        throw "Core startup did not leave a current-schema Instance manifest."
    }
    $Manifest = Get-Content $InstanceManifest -Raw | ConvertFrom-Json
    if (
        $Manifest.schema_version -ne 1 -or
        $Manifest.instance_schema_version -ne 2 -or
        $Manifest.instance.id -ne $LegacyInstanceId -or
        $Manifest.instance.created_at -ne $LegacyInstanceCreatedAt -or
        $Manifest.derived_state.indexes -ne "rebuild" -or
        $Manifest.derived_state.library -ne "rebuild" -or
        $Manifest.derived_state.state_artifacts -ne "include" -or
        @($Manifest.migrations).Count -ne $ExpectedMigrationCount
    ) {
        throw "Current Instance manifest is inconsistent with the public baseline."
    }
    $MigrationBackupPath = $null
    $ExpectedMigrationReceiptSha256 = $null
    $ExpectedMigrationBackupSha256 = $null
    if ($BaselineRequiresMigration) {
        if (-not (Test-Path $MigrationReceiptPath)) {
            throw "Schema migration did not leave its durable receipt."
        }
        $Receipt = Get-Content $MigrationReceiptPath -Raw | ConvertFrom-Json
        if (
            $Manifest.migrations[0].id -ne "instance-schema-1-to-2" -or
            $Manifest.migrations[0].receipt -ne (
                "state/migrations/receipts/instance-schema-1-to-2.json"
            ) -or
            $Receipt.schema_version -ne 1 -or
            $Receipt.migration_id -ne "instance-schema-1-to-2" -or
            $Receipt.status -ne "completed" -or
            $Receipt.from_instance_schema_version -ne 1 -or
            $Receipt.to_instance_schema_version -ne 2 -or
            $Receipt.instance_id -ne $LegacyInstanceId -or
            $Receipt.preflight_content_fingerprint -notmatch '^[0-9a-f]{64}$' -or
            $Receipt.backup.archive_name -notmatch '^backup_[^\\/]+\.zip$' -or
            $Receipt.backup.sha256 -notmatch '^[0-9a-f]{64}$' -or
            $Receipt.backup.size_bytes -le 0
        ) {
            throw "Schema migration manifest or receipt is inconsistent."
        }
        $BackupDirectory = Join-Path (Split-Path $InstanceRoot -Parent) (
            ".$(Split-Path $InstanceRoot -Leaf).provelume\backups"
        )
        $MigrationBackupPath = Join-Path $BackupDirectory $Receipt.backup.archive_name
        if (
            -not (Test-Path $MigrationBackupPath) -or
            (Get-Item $MigrationBackupPath).Length -ne $Receipt.backup.size_bytes -or
            (Get-FileHash $MigrationBackupPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
                $Receipt.backup.sha256
        ) {
            throw "Schema migration rollback backup is missing or does not match its receipt."
        }
        $ExpectedMigrationReceiptSha256 = (
            Get-FileHash $MigrationReceiptPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        $ExpectedMigrationBackupSha256 = (
            Get-FileHash $MigrationBackupPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    }
    elseif (
        (Test-Path $MigrationReceiptPath) -or
        (Get-FileHash $InstanceConfig -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $LegacyInstanceConfigSha256 -or
        (Get-FileHash $InstanceManifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $BaselineInstanceManifestSha256
    ) {
        throw "Current-schema baseline gained unexpected migration evidence or manifest changes."
    }
    $MigratedConfigText = [System.IO.File]::ReadAllText(
        $InstanceConfig,
        [System.Text.Encoding]::UTF8
    )
    if (
        $MigratedConfigText -notmatch '(?m)^schema_version:\s+2\s*$' -or
        (Get-YamlScalar -Text $MigratedConfigText -Key "id") -ne $LegacyInstanceId -or
        (Get-YamlScalar -Text $MigratedConfigText -Key "created_at") -ne
            $LegacyInstanceCreatedAt
    ) {
        throw "Schema handling changed the stable Instance identity."
    }
    $ExpectedMigratedConfigSha256 = (
        Get-FileHash $InstanceConfig -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $ExpectedInstanceManifestSha256 = (
        Get-FileHash $InstanceManifest -Algorithm SHA256
    ).Hash.ToLowerInvariant()

    # Reinstall once more, then uninstall the candidate while retaining state and the Instance.
    Install-Provelume -Setup $InstallerPath -Directory $InstallRoot
    Assert-SingleProductRegistration -ExpectedInstallRoot $InstallRoot
    $PostReinstallInstanceTreeSha256 = Get-InstanceTreeFingerprint -Root $InstanceRoot
    if ($PostReinstallInstanceTreeSha256 -ne $PostStartupInstanceTreeSha256) {
        throw "Candidate reinstall mutated the verified post-startup Instance tree."
    }
    Uninstall-Provelume -Directory $InstallRoot
    if (Test-Path $Executable) {
        throw "Uninstall left the installed executable behind."
    }
    $SchemaEvidencePresent = if ($BaselineRequiresMigration) {
        (Test-Path $InstanceConfig) -and
        (Test-Path $InstanceManifest) -and
        (Test-Path $MigrationReceiptPath) -and
        (Test-Path $MigrationBackupPath)
    }
    else {
        (Test-Path $InstanceConfig) -and
        (Test-Path $InstanceManifest) -and
        -not (Test-Path $MigrationReceiptPath)
    }
    if (
        -not $SchemaEvidencePresent -or
        -not (Test-Path (Join-Path $InstanceRoot "upgrade-preservation-marker.txt")) -or
        -not (Test-Path $SettingsPath)
    ) {
        throw "Uninstall removed the separate Instance or launcher settings."
    }
    $ConfigText = [System.IO.File]::ReadAllText(
        $InstanceConfig,
        [System.Text.Encoding]::UTF8
    )
    $MarkerText = [System.IO.File]::ReadAllText(
        (Join-Path $InstanceRoot "upgrade-preservation-marker.txt"),
        [System.Text.Encoding]::UTF8
    )
    $SettingsAfterUninstall = Get-Content $SettingsPath -Raw | ConvertFrom-Json
    $SchemaEvidencePreserved = if ($BaselineRequiresMigration) {
        (Get-FileHash $MigrationReceiptPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq
            $ExpectedMigrationReceiptSha256 -and
        (Get-FileHash $MigrationBackupPath -Algorithm SHA256).Hash.ToLowerInvariant() -eq
            $ExpectedMigrationBackupSha256
    }
    else {
        -not (Test-Path $MigrationReceiptPath)
    }
    $PostUninstallInstanceTreeSha256 = Get-InstanceTreeFingerprint -Root $InstanceRoot
    if (
        $ConfigText -notmatch '(?m)^schema_version:\s+2\s*$' -or
        $ConfigText -notmatch '(?m)^instance:\s*$' -or
        (Get-YamlScalar -Text $ConfigText -Key "id") -ne $LegacyInstanceId -or
        (Get-YamlScalar -Text $ConfigText -Key "created_at") -ne
            $LegacyInstanceCreatedAt -or
        $MarkerText -ne "synthetic upgrade preservation evidence`n" -or
        $SettingsAfterUninstall.instance_path -ne $InstanceRoot -or
        (Get-FileHash $InstanceConfig -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $ExpectedMigratedConfigSha256 -or
        (Get-FileHash $InstanceManifest -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $ExpectedInstanceManifestSha256 -or
        -not $SchemaEvidencePreserved -or
        (Get-FileHash (Join-Path $InstanceRoot "upgrade-preservation-marker.txt") `
            -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedMarkerSha256 -or
        (Get-FileHash $SettingsPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            $ExpectedSettingsSha256 -or
        $PostUninstallInstanceTreeSha256 -ne $PostStartupInstanceTreeSha256
    ) {
        throw "The preserved Instance was not readable after uninstall."
    }
    $Summary = @{
        schema_version = 1
        synthetic_data_only = $true
        public_baseline = @{
            version = $PreviousVersion
            commit = $PreviousCommit
            channel = $PreviousChannel
            installer_sha256 = $PreviousInstallerSha256
            installer_size_bytes = $PreviousInstallerSize
        }
        candidate = @{
            version = $ExpectedVersion
            commit = $ExpectedCommit
            channel = $ExpectedChannel
        }
        instance_tree_fingerprints = @{
            baseline = $BaselineInstanceTreeSha256
            post_startup = $PostStartupInstanceTreeSha256
            post_reinstall = $PostReinstallInstanceTreeSha256
            post_uninstall = $PostUninstallInstanceTreeSha256
        }
        results = @{
            default_per_user_install = "PASS"
            unicode_install_and_instance_paths = "PASS"
            start_and_optional_desktop_shortcuts = "PASS"
            published_baseline_identity = "PASS"
            in_place_upgrade_and_single_app_id = "PASS"
            launcher_settings_preserved = "PASS"
            instance_originals_canonical_knowledge_and_state_preserved = "PASS"
            instance_schema_compatibility = "PASS"
            scheduler_refresh_network_delete_and_repair_default_disabled = "PASS"
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
    foreach ($TemporaryPath in @($BaselineRuntimeRoot, $BaselineSourceRoot)) {
        if (Test-Path $TemporaryPath) {
            Remove-Item -Recurse -Force $TemporaryPath
        }
    }
}
