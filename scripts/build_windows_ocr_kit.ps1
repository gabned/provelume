param(
    [Parameter(Mandatory = $true)][string]$CandidateWheel,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][string]$Commit
)
$ErrorActionPreference = "Stop"
$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Wheel = (Resolve-Path $CandidateWheel).Path
$Output = [System.IO.Path]::GetFullPath($OutputDirectory)
$Lock = Get-Content "$SourceRoot/packaging/ocr/windows-py312-x64.json" -Raw | ConvertFrom-Json
$ActualPython = python -c "import platform; print(platform.python_version())"
if ($LASTEXITCODE -ne 0 -or $ActualPython -ne $Lock.python -or $Commit -notmatch '^[0-9a-f]{40}$') {
    throw "OCR build requires the exact locked CPython and source identity."
}
$BuildRoot = Join-Path ([System.IO.Path]::GetTempPath()) "provelume-ocr-build-$PID"
if (Test-Path $BuildRoot) { throw "OCR build directory already exists; preserve it for diagnosis." }
New-Item -ItemType Directory -Path $BuildRoot | Out-Null
New-Item -ItemType Directory -Force -Path $Output | Out-Null
try {
    $Environment = Join-Path $BuildRoot "venv"
    python -m venv $Environment
    if ($LASTEXITCODE -ne 0) { throw "OCR build environment creation failed." }
    $BuildPython = Join-Path $Environment "Scripts/python.exe"
    & $BuildPython -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes `
        -r "$SourceRoot/build-lock/sbom-runtime-pip.requirements.txt"
    if ($LASTEXITCODE -ne 0) { throw "OCR pip bootstrap failed." }
    & $BuildPython -m pip install --disable-pip-version-check --only-binary=:all: --require-hashes `
        -r "$SourceRoot/build-lock/ocr-windows-py312-x86_64.requirements.txt"
    if ($LASTEXITCODE -ne 0) { throw "OCR worker lock failed." }
    & $BuildPython -m pip install --disable-pip-version-check --no-deps $Wheel
    if ($LASTEXITCODE -ne 0) { throw "OCR candidate wheel install failed." }
    & $BuildPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "OCR worker dependency consistency failed." }
    $BuildIdentity = Join-Path $BuildRoot "identity.json"
    & $BuildPython -I -c "import json,pathlib,sys; from provelume.build_info import current_build_info; pathlib.Path(sys.argv[1]).write_text(json.dumps(current_build_info()),encoding='utf-8')" $BuildIdentity
    if ($LASTEXITCODE -ne 0) { throw "OCR candidate identity unavailable." }
    $Identity = Get-Content $BuildIdentity -Raw | ConvertFrom-Json
    if ($Identity.commit -ne $Commit) { throw "OCR wheel source identity differs." }
    $Vcpkg = Join-Path $BuildRoot "vcpkg"
    git clone --no-checkout --filter=blob:none https://github.com/microsoft/vcpkg.git $Vcpkg
    if ($LASTEXITCODE -ne 0) { throw "Pinned native build source acquisition failed." }
    git -C $Vcpkg checkout --detach $Lock.vcpkg.commit
    if ($LASTEXITCODE -ne 0) { throw "Pinned native build source checkout failed." }
    & "$Vcpkg/bootstrap-vcpkg.bat" -disableMetrics
    if ($LASTEXITCODE -ne 0) { throw "Native source builder bootstrap failed." }
    $env:VCPKG_BINARY_SOURCES = "clear"
    $env:VCPKG_DISABLE_METRICS = "1"
    & "$Vcpkg/vcpkg.exe" install "tesseract:$($Lock.vcpkg.triplet)" `
        --overlay-triplets="$SourceRoot/packaging/ocr/triplets" --classic --clean-after-build
    if ($LASTEXITCODE -ne 0) { throw "Pinned OCR native source build failed." }
    Push-Location "$SourceRoot/packaging/ocr"
    try {
        & $BuildPython -m PyInstaller --noconfirm --clean --distpath "$BuildRoot/dist" `
            --workpath "$BuildRoot/work" worker.spec
        if ($LASTEXITCODE -ne 0) { throw "Dedicated OCR worker freezing failed." }
    } finally { Pop-Location }
    & $BuildPython "$SourceRoot/scripts/compose_windows_ocr_kit.py" `
        --worker "$BuildRoot/dist/ProvelumeOcrWorker" --vcpkg $Vcpkg `
        --identity $BuildIdentity --output $Output
    if ($LASTEXITCODE -ne 0) { throw "OCR inventory/composition failed." }
} finally {
    $NativeLogs = Join-Path $Vcpkg "buildtrees"
    if (Test-Path $NativeLogs) {
        Get-ChildItem $NativeLogs -Recurse -File -Filter *.log | ForEach-Object {
            $Relative = [System.IO.Path]::GetRelativePath($NativeLogs, $_.FullName)
            $Target = Join-Path $Output "native-build-logs/$Relative"
            New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
            Copy-Item -LiteralPath $_.FullName -Destination $Target
        }
    }
    Remove-Item -Recurse -Force $BuildRoot
}
