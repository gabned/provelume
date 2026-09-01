param(
    [Parameter(Mandatory = $true)][string]$Artifact,
    [Parameter(Mandatory = $true, ParameterSetName = "Release")][switch]$RequireSignedRelease,
    [Parameter(Mandatory = $true, ParameterSetName = "Development")][switch]$AllowUnsignedDevelopment,
    [Parameter(Mandatory = $true, ParameterSetName = "Release")][string]$ExpectedPublisher,
    [Parameter(Mandatory = $true, ParameterSetName = "Release")][string]$ExpectedSha256
)

$ErrorActionPreference = "Stop"
$ResolvedArtifact = (Resolve-Path -LiteralPath $Artifact).Path
$Digest = (Get-FileHash -LiteralPath $ResolvedArtifact -Algorithm SHA256).Hash.ToLowerInvariant()
$Signature = Get-AuthenticodeSignature -LiteralPath $ResolvedArtifact

$Evidence = [ordered]@{
    schema_version = 1
    artifact_sha256 = $Digest
    signature_status = [string]$Signature.Status
    publisher = $null
    timestamp_present = $false
    qualified = $false
    mode = if ($RequireSignedRelease) { "signed_release" } else { "unsigned_development" }
}

if ($RequireSignedRelease) {
    if ($ExpectedSha256 -notmatch '^[0-9a-fA-F]{64}$') {
        throw "Expected release SHA-256 must contain exactly 64 hexadecimal characters."
    }
    if ($Digest -ne $ExpectedSha256.ToLowerInvariant()) {
        throw "Exact release artifact SHA-256 does not match the authorized value."
    }
}

if ($AllowUnsignedDevelopment) {
    if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::NotSigned) {
        throw "Development artifact must be explicitly unsigned; an invalid or unexpected signature is rejected."
    }
    $Evidence.signature_status = "unsigned"
    $Evidence | ConvertTo-Json -Depth 4
    return
}

if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Exact release artifact does not have a valid Authenticode signature."
}
if (-not $Signature.SignerCertificate) {
    throw "Exact release artifact has no signer certificate."
}
if ($Signature.SignerCertificate.Subject -ne $ExpectedPublisher) {
    throw "Exact release artifact signer does not match the authorized publisher."
}
if (-not $Signature.TimeStamperCertificate) {
    throw "Exact release artifact has no authenticated timestamp certificate."
}
if ($Signature.TimeStamperCertificate.NotAfter -le [DateTime]::UtcNow) {
    throw "Exact release artifact timestamp certificate is expired."
}

$Evidence.publisher = $Signature.SignerCertificate.Subject
$Evidence.timestamp_present = $true
$Evidence.qualified = $true
$Evidence | ConvertTo-Json -Depth 4
