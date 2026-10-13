param([Parameter(Mandatory=$true)][string]$Artifacts,
      [string]$Output = '.agent/custodia-frequency-diagnosis')
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $Output | Out-Null
$Output = (Resolve-Path $Output).Path
$frequency = '\Processor Information(*)\Actual Frequency'
# Recheck on the actual execution guest; availability on a prior host is no grant.
$check = @(Get-Counter $frequency -SampleInterval 1 -MaxSamples 2 -ErrorAction Stop)
$valid = @($check[-1].CounterSamples | Where-Object { $_.Status -eq 0 -and $_.CookedValue -gt 0 -and -not [double]::IsNaN($_.CookedValue) -and -not [double]::IsInfinity($_.CookedValue) })
if ($valid.Count -ne $check[-1].CounterSamples.Count -or $valid.Count -eq 0) {
    throw 'Actual Frequency is unavailable on this guest. Refuse model observation.'
}
$cpu = Get-CimInstance Win32_Processor
@{ purpose = 'DIAGNOSTIC_ONLY'; qualification = 'NOT_EVALUATED'; original_fail = 38289564204;
   original_host_telemetry = 'MISSING_NOT_RECONSTRUCTED'; head = $env:GITHUB_SHA;
   cpu = $env:PROCESSOR_IDENTIFIER; nominal_mhz = @($cpu.MaxClockSpeed);
   frequency_semantics = 'GUEST_PDH_REPORTED_NOT_PHYSICAL_HOST_VERIFIED';
   pmc_instructions = 'UNAVAILABLE_IN_CAPABILITY_PROBES'; physical_host_contention = 'UNOBSERVED' } |
    ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $Output 'identity.json')
$ready = Join-Path $Output 'sampler-ready'
$stop = Join-Path $Output 'sampler-stop'
$trace = Join-Path $Output 'guest-frequency.jsonl'
if ((Test-Path $ready) -or (Test-Path $stop) -or (Test-Path $trace)) { throw 'Preserve existing observation; use a fresh output directory.' }
$job = Start-Job -ArgumentList $trace,$ready,$stop -ScriptBlock {
    param($trace,$ready,$stop)
    $ErrorActionPreference = 'Stop'
    $paths = @('\Processor Information(*)\Actual Frequency',
               '\Processor Information(*)\% Processor Performance',
               '\Processor Information(*)\% Processor Time')
    $clock = [Diagnostics.Stopwatch]::Frequency
    try {
        # One PDH collection gives simultaneous per-core counters. No nominal-Hz substitution.
        Get-Counter $paths -SampleInterval 1 -Continuous -ErrorAction Stop | ForEach-Object {
            $qpc = [Diagnostics.Stopwatch]::GetTimestamp()
            @{ qpc_after_collect = $qpc; qpc_frequency = $clock;
               utc_after_collect = [DateTime]::UtcNow.ToString('o');
               sample_utc = $_.Timestamp.ToUniversalTime().ToString('o');
               counters = @($_.CounterSamples | ForEach-Object {
                   @{ counter = ($_.Path -split '\\')[-1]; instance = $_.InstanceName;
                      value = $_.CookedValue; status = $_.Status; timestamp_100ns = $_.Timestamp100nSec }
               }) } | ConvertTo-Json -Depth 6 -Compress | Add-Content -Encoding utf8 $trace
            if (-not (Test-Path $ready)) { New-Item -ItemType File $ready | Out-Null }
            if (Test-Path $stop) { throw 'SAMPLER_STOP_REQUESTED' }
        }
    } finally {
        @{ end_utc = [DateTime]::UtcNow.ToString('o'); qpc = [Diagnostics.Stopwatch]::GetTimestamp() } |
            ConvertTo-Json -Compress | Add-Content -Encoding utf8 $trace
    }
}
try {
    $wait = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path $ready)) {
        if ($job.State -in @('Failed','Completed') -or $wait.Elapsed.TotalSeconds -gt 15) { throw 'Sampler did not start; refuse model observation.' }
        Start-Sleep -Milliseconds 100
    }
    # Existing fixed diagnostic windows and unchanged Core; never the qualification workflow.
    & .venv/Scripts/python.exe scripts/diagnose_custodia_windows.py --artifacts $Artifacts --output (Join-Path $Output 'diagnostic.json') --scheduler-trace
    $code = $LASTEXITCODE
    if ($job.State -ne 'Running') { throw 'Sampler ended during observation; coverage is invalid.' }
    if ($code -ne 0) { throw "Diagnostic exited $code; preserve all evidence." }
} finally {
    $premature = $job.State -ne 'Running'
    New-Item -ItemType File -Force $stop | Out-Null
    $null = Wait-Job $job -Timeout 4
    if ($job.State -eq 'Running') { Stop-Job $job }
    # Preserve sampler failure as evidence; do not silently promote partial coverage.
    @{ state = "$($job.State)"; stop_requested = $true; failed_before_stop = $premature;
       expected_stop_exception = 'SAMPLER_STOP_REQUESTED' } |
        ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Output 'sampler-status.json')
    Remove-Job $job -Force
}
