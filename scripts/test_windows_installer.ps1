param(
    [Parameter(Mandatory = $true)][string]$Installer,
    [Parameter(Mandatory = $true)][string]$InstallDirectory,
    [Parameter(Mandatory = $true)][string]$InstanceDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedVersion,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][ValidateSet("development", "preview", "stable")][string]$ExpectedChannel
)

$ErrorActionPreference = "Stop"
$InstallerPath = (Resolve-Path $Installer).Path
$InstallRoot = [System.IO.Path]::GetFullPath($InstallDirectory)
$InstanceRoot = [System.IO.Path]::GetFullPath($InstanceDirectory)
$Diagnostics = Join-Path ([System.IO.Path]::GetTempPath()) "provelume-installed-$PID.json"

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

Invoke-WindowsProcess -FilePath $InstallerPath -Arguments @(
    "/SP-",
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART",
    "/DIR=`"$InstallRoot`""
)

$Executable = Join-Path $InstallRoot "Provelume.exe"
if (-not (Test-Path $Executable)) {
    throw "Silent install did not produce Provelume.exe."
}
Invoke-WindowsProcess -FilePath $Executable -Arguments @(
    "--diagnostics-file",
    "`"$Diagnostics`""
)
$Identity = Get-Content $Diagnostics -Raw | ConvertFrom-Json
if (
    $Identity.about.version -ne $ExpectedVersion -or
    $Identity.about.commit -ne $ExpectedCommit -or
    $Identity.about.channel -ne $ExpectedChannel -or
    $Identity.about.runtime.packaging -ne "windows_installer" -or
    -not $Identity.frozen -or
    $Identity.network_used
) {
    throw "Installed desktop identity does not match the expected offline Windows build."
}
if ($ExpectedChannel -eq "development") {
    if ($Identity.about.official_build_metadata -or $null -ne $Identity.about.tag) {
        throw "Development Windows build declares official release identity."
    }
}
elseif (
    -not $Identity.about.official_build_metadata -or
    $Identity.about.tag -ne "v$ExpectedVersion"
) {
    throw "Official Windows build is missing its release tag identity."
}

Invoke-WindowsProcess -FilePath $Executable -Arguments @(
    "--bootstrap-instance",
    "`"$InstanceRoot`"",
    "--instance-name",
    "Windows CI Instance"
)
$InstanceConfig = Join-Path $InstanceRoot "provelume.yml"
if (-not (Test-Path $InstanceConfig)) {
    throw "Installed desktop could not bootstrap an Instance."
}

$Uninstaller = Join-Path $InstallRoot "unins000.exe"
if (-not (Test-Path $Uninstaller)) {
    throw "Installed package has no uninstaller."
}
Invoke-WindowsProcess -FilePath $Uninstaller -Arguments @(
    "/VERYSILENT",
    "/SUPPRESSMSGBOXES",
    "/NORESTART"
)
if (Test-Path $Executable) {
    throw "Uninstall left the installed executable behind."
}
if (-not (Test-Path $InstanceConfig)) {
    throw "Uninstall removed the separate portable Instance."
}
