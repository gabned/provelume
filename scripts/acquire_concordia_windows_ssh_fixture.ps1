param(
    [Parameter(Mandatory)][string]$OutputDirectory,
    [Parameter(Mandatory)][string]$Evidence
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not [OperatingSystem]::IsWindows() -or
    [Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -ne 'X64') {
    throw 'The SSH fixture requires native Windows x64.'
}

$release = '10.4.0.0p1-Preview'
$archiveUrl = "https://github.com/PowerShell/Win32-OpenSSH/releases/download/$release/OpenSSH-Win64.zip"
$archiveDigest = 'b67ff8becd203502190ec42ac7787c24c2cd3325ed7700485fe7a1c83d2a7957'
$archiveBytes = 6021393
$expectedVersion = 'OpenSSH_for_Windows_10.4p1 Win32-OpenSSH-GitHub, LibreSSL 4.3.3'
$components = @(
    @{
        name = 'ssh.exe'
        bytes = 1500960
        digest = 'ee115a1b833261034dcb2e5b862e6571f6dcedc084c555ea0df45ae7fd42c5e0'
        signer = 'd33927e4dda9b91def9f8ed282549a49217ed8cacf54577a690963cbc5eff3ed'
    },
    @{
        name = 'libcrypto.dll'
        bytes = 1801032
        digest = 'b4cbfd202d52ec0f094bfa328414c74b05b51234df95d2eb42e5fdb47160c9b5'
        signer = '36bdc0df7839b6e3dcbec49031c9edc06dd765fd794a6a2691e4f0ccfd01d3a2'
    }
)

function Assert-FileIdentity([string]$Path, [long]$ExpectedBytes, [string]$ExpectedDigest) {
    if ((Get-Item -LiteralPath $Path).Length -ne $ExpectedBytes -or
        (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ExpectedDigest) {
        throw 'The SSH fixture file identity does not match the selected release.'
    }
}

$destination = [IO.Path]::GetFullPath($OutputDirectory)
$receipt = [IO.Path]::GetFullPath($Evidence)
if ((Test-Path -LiteralPath $destination) -or (Test-Path -LiteralPath $receipt)) {
    throw 'The SSH fixture destination and evidence file must be fresh.'
}
$destinationParent = [IO.Path]::GetDirectoryName($destination)
$receiptParent = [IO.Path]::GetDirectoryName($receipt)
if (-not [IO.Directory]::Exists($destinationParent) -or -not [IO.Directory]::Exists($receiptParent)) {
    throw 'The SSH fixture destination and evidence parent directories must exist.'
}

$scratch = Join-Path $destinationParent ('.ssh-fixture-' + [Guid]::NewGuid().ToString('N'))
$stage = Join-Path $scratch 'components'
$archivePath = Join-Path $scratch 'OpenSSH-Win64.zip'
$null = [IO.Directory]::CreateDirectory($stage)
try {
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -TimeoutSec 60
    Assert-FileIdentity $archivePath $archiveBytes $archiveDigest

    $observed = @()
    $archive = [IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        foreach ($component in $components) {
            $entryName = 'OpenSSH-Win64/' + $component.name
            $members = @($archive.Entries | Where-Object FullName -CEQ $entryName)
            if ($members.Count -ne 1 -or $members[0].Length -ne $component.bytes) {
                throw 'The required SSH fixture archive member is missing, duplicated or has the wrong size.'
            }
            $file = Join-Path $stage $component.name
            [IO.Compression.ZipFileExtensions]::ExtractToFile($members[0], $file, $false)
            Assert-FileIdentity $file $component.bytes $component.digest
            $signature = Get-AuthenticodeSignature -LiteralPath $file
            if ($signature.Status -ne 'Valid' -or -not $signature.SignerCertificate) {
                throw 'Windows did not validate the SSH fixture Authenticode signature.'
            }
            $signer = [Convert]::ToHexString(
                [Security.Cryptography.SHA256]::HashData($signature.SignerCertificate.RawData)
            ).ToLowerInvariant()
            if ($signer -cne $component.signer) {
                throw 'The SSH fixture signer does not match the selected release.'
            }
            $observed += [ordered]@{
                name = $component.name
                bytes = $component.bytes
                sha256 = $component.digest
                authenticode = [string]$signature.Status
                signer_sha256 = $signer
            }
        }
    }
    finally {
        $archive.Dispose()
    }

    $start = [Diagnostics.ProcessStartInfo]::new((Join-Path $stage 'ssh.exe'))
    $start.ArgumentList.Add('-V')
    $start.UseShellExecute = $false
    $start.RedirectStandardError = $true
    $start.RedirectStandardOutput = $true
    $start.WorkingDirectory = $stage
    $start.Environment.Clear()
    $start.Environment['SystemRoot'] = $env:SystemRoot
    $start.Environment['WINDIR'] = $env:WINDIR
    $start.Environment['ProgramData'] = $scratch
    $process = [Diagnostics.Process]::Start($start)
    try {
        if (-not $process.WaitForExit(5000)) {
            $process.Kill($true)
            throw 'OpenSSH did not identify itself inside the 5-second fixture bound.'
        }
        $stderr = $process.StandardError.ReadToEnd()
        $stdout = $process.StandardOutput.ReadToEnd()
        if ($process.ExitCode -ne 0 -or $stdout -cne '' -or
            ($stderr -cne "$expectedVersion`r`n" -and $stderr -cne "$expectedVersion`n")) {
            throw 'OpenSSH did not report the expected native Windows version.'
        }
    }
    finally {
        $process.Dispose()
    }

    [IO.Directory]::Move($stage, $destination)
    $json = [ordered]@{
        schema = 'concordia-windows-ssh-component/v1'
        repository = 'PowerShell/Win32-OpenSSH'
        release = $release
        distribution = 'PREVIEW_QUALIFICATION_INPUT'
        asset_id = 645185877
        archive_url = $archiveUrl
        archive_bytes = $archiveBytes
        archive_sha256 = $archiveDigest
        version = $stderr.TrimEnd()
        components = $observed
    } | ConvertTo-Json -Depth 5
    $stream = [IO.File]::Open($receipt, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $receiptBytes = [Text.Encoding]::UTF8.GetBytes($json + "`n")
        $stream.Write($receiptBytes, 0, $receiptBytes.Length)
    }
    finally {
        $stream.Dispose()
    }
}
finally {
    [IO.Directory]::Delete($scratch, $true)
}
