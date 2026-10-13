param([string]$Output = '.agent/custodia-frequency-synthetic')
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot/observe_custodia_guest_frequency.ps1" -Output $Output
New-Item -ItemType Directory -Force $Output | Out-Null
$Output = (Resolve-Path $Output).Path
$results = @()
foreach ($scenario in @('normal','probe-invalid','startup-error','early-end','late-error','hung','invalid-counter','clock-inversion','harness-error','missing-terminal')) {
    $directory = Join-Path $Output $scenario
    $global:CustodiaSyntheticScenario = $scenario
    $probe = {
        [pscustomobject]@{ Status = 0; CookedValue = $(if ($global:CustodiaSyntheticScenario -eq 'probe-invalid') { 0 } else { 3000 }) }
    }
    $start = {
        param($trace,$ready,$stop)
        Start-Job -ArgumentList $trace,$ready,$stop,$global:CustodiaSyntheticScenario -ScriptBlock {
            param($trace,$ready,$stop,$mode)
            $ErrorActionPreference = 'Stop'
            if ($mode -eq 'startup-error') { throw 'synthetic startup' }
            $count = 0
            while ($true) {
                $count++
                $qpc = [Diagnostics.Stopwatch]::GetTimestamp()
                if ($mode -eq 'clock-inversion' -and $count -eq 3) { $qpc = 1 }
                @{ kind='sample'; qpc_after_collect=$qpc; qpc_frequency=[Diagnostics.Stopwatch]::Frequency;
                   sample_utc=[DateTime]::UtcNow.ToString('o');
                   counters=@('actual frequency','% processor performance','% processor time') | ForEach-Object {
                       @{ counter=$_; value=3000; status=$(if ($mode -eq 'invalid-counter' -and $count -eq 3) { 1 } else { 0 }) }
                   } } | ConvertTo-Json -Depth 5 -Compress | Add-Content $trace
                if (-not (Test-Path $ready)) { New-Item -ItemType File $ready | Out-Null }
                if ($mode -eq 'early-end' -and $count -eq 2) { break }
                if (Test-Path $stop) {
                    if ($mode -eq 'late-error') { throw 'synthetic late failure' }
                    if ($mode -eq 'hung') { Start-Sleep 30 }
                    if ($mode -ne 'missing-terminal') {
                        @{ kind='end'; reason='STOP_REQUESTED' } | ConvertTo-Json -Compress | Add-Content $trace
                    }
                    break
                }
                Start-Sleep -Milliseconds 50
            }
        }
    }
    $observe = {
        param($artifacts,$directory)
        New-Item -ItemType File (Join-Path $directory 'harness-called') | Out-Null
        Start-Sleep -Milliseconds 400
        if ($global:CustodiaSyntheticScenario -eq 'harness-error') { throw 'synthetic harness failure' }
    }
    $failed = $false
    try { Invoke-CustodiaFrequencyObservation -Artifacts synthetic -Output $directory -Probe $probe -StartSampler $start -Observe $observe -StopSeconds 1 }
    catch { $failed = $true }
    $status = Get-Content (Join-Path $directory 'sampler-status.json') -Raw | ConvertFrom-Json
    if ($failed -ne ($scenario -ne 'normal')) { throw "Wrong outcome: $scenario" }
    if ($scenario -ne 'probe-invalid' -and -not $status.job_removed) { throw "Job leaked: $scenario" }
    if ($scenario -in @('probe-invalid','startup-error') -and (Test-Path (Join-Path $directory 'harness-called'))) { throw 'Harness invoked without telemetry.' }
    $results += @{ scenario=$scenario; result='PASS'; observed_collection=$status.collection; job_removed=$status.job_removed }
}
# Fresh-directory refusal must preserve all original bytes, before even a probe.
$preserved = Get-FileHash (Join-Path $Output 'normal/sampler-status.json')
$refused = $false
try { Invoke-CustodiaFrequencyObservation -Artifacts synthetic -Output (Join-Path $Output 'normal') -Probe { throw 'must not probe' } }
catch { $refused = $_.Exception.Message -like 'Preserve existing*' }
if (-not $refused -or (Get-FileHash $preserved.Path).Hash -ne $preserved.Hash) { throw 'Existing evidence overwritten.' }
$results += @{ scenario='fresh-directory-preservation'; result='PASS' }
$results | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Output 'results.json')
$results | Format-Table
