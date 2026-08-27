param(
    [Parameter(Mandatory = $true)][string]$CandidateWheel,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$Version,
    [Parameter(Mandatory = $true)][string]$Tag,
    [Parameter(Mandatory = $true)][ValidateSet("development", "preview", "stable")][string]$Channel,
    [Parameter(Mandatory = $true)][string]$Commit
)

$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Wheel = (Resolve-Path $CandidateWheel).Path
$Output = [System.IO.Path]::GetFullPath($OutputDirectory)

if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Version must use exact X.Y.Z syntax."
}
if ($Tag -ne "v$Version") {
    throw "Tag must match the package version."
}
if ($Commit -notmatch '^[0-9a-f]{40}$') {
    throw "Commit must be a full lowercase Git SHA-1."
}
if ((Split-Path $Wheel -Leaf) -notlike "provelume-$Version-*.whl") {
    throw "Candidate wheel filename does not match the requested version."
}

New-Item -ItemType Directory -Force -Path $Output | Out-Null
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) "provelume-windows-build-$PID"
$BuildEnvironment = Join-Path $BuildRoot "venv"
$Dist = Join-Path $BuildRoot "dist"
$Work = Join-Path $BuildRoot "work"
$Diagnostics = Join-Path $BuildRoot "desktop-diagnostics.json"

try {
    if (Test-Path $BuildRoot) {
        Remove-Item -Recurse -Force $BuildRoot
    }
    New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
    python -m venv $BuildEnvironment
    $BuildPython = Join-Path $BuildEnvironment "Scripts\python.exe"
    & $BuildPython -m pip install --disable-pip-version-check --require-hashes `
        -r (Join-Path $SourceRoot "build-lock\windows-py312-x86_64.requirements.txt")
    & $BuildPython -m pip install --disable-pip-version-check --no-deps $Wheel
    & $BuildPython -m pip check

    Push-Location (Join-Path $SourceRoot "packaging\windows")
    try {
        & $BuildPython -m PyInstaller --noconfirm --clean `
            --distpath $Dist --workpath $Work provelume.spec
    }
    finally {
        Pop-Location
    }

    $Executable = Join-Path $Dist "Provelume\Provelume.exe"
    if (-not (Test-Path $Executable)) {
        throw "PyInstaller did not produce Provelume.exe."
    }
    & $Executable --diagnostics-file $Diagnostics
    $Identity = Get-Content $Diagnostics -Raw | ConvertFrom-Json
    if (
        $Identity.about.version -ne $Version -or
        $Identity.about.commit -ne $Commit -or
        $Identity.about.channel -ne $Channel
    ) {
        throw "Frozen desktop identity does not match the candidate wheel."
    }
    if (-not $Identity.frozen -or $Identity.network_used) {
        throw "Frozen desktop diagnostics do not match the offline contract."
    }

    $Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
    if (-not $Iscc) {
        $KnownIscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
        if (Test-Path $KnownIscc) {
            $Iscc = $KnownIscc
        }
    }
    if (-not $Iscc) {
        throw "Inno Setup 6 compiler was not found."
    }

    $Stage = Join-Path $Dist "Provelume"
    $InstallerScript = Join-Path $SourceRoot "packaging\windows\provelume.iss"
    & $Iscc "/DMyAppVersion=$Version" "/DMyStageDir=$Stage" `
        "/DMyOutputDir=$Output" $InstallerScript
    $Installer = Join-Path $Output "Provelume-Setup-$Version-x64.exe"
    if (-not (Test-Path $Installer)) {
        throw "Inno Setup did not produce the expected installer."
    }

    & $BuildPython (Join-Path $SourceRoot "scripts\windows_package_manifest.py") `
        --installer $Installer --version $Version --tag $Tag --channel $Channel `
        --commit $Commit --output (Join-Path $Output "provelume-windows-update.json")
}
finally {
    if (Test-Path $BuildRoot) {
        Remove-Item -Recurse -Force $BuildRoot
    }
}
