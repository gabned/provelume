param([string]$Artifacts, [string]$Output = '.agent/custodia-frequency-diagnosis')
$ErrorActionPreference = 'Stop'

function Test-CustodiaCounterSample($Samples) {
    $rows = @($Samples)
    if ($rows.Count -eq 0) { throw 'Empty Actual Frequency sample.' }
    foreach ($row in $rows) {
        if ($row.Status -ne 0 -or $row.CookedValue -le 0 -or
            [double]::IsNaN($row.CookedValue) -or [double]::IsInfinity($row.CookedValue)) {
            throw 'Actual Frequency is unavailable on this guest. Refuse model observation.'
        }
    }
}

function Start-CustodiaFrequencySampler($Trace, $Ready, $Stop) {
    Start-Job -ArgumentList $Trace,$Ready,$Stop -ScriptBlock {
        param($trace,$ready,$stop)
        $ErrorActionPreference = 'Stop'
        $paths = @('\Processor Information(*)\Actual Frequency',
                   '\Processor Information(*)\% Processor Performance',
                   '\Processor Information(*)\% Processor Time')
        $reason = 'UNEXPECTED_END'
        try {
            Get-Counter $paths -SampleInterval 1 -Continuous -ErrorAction Stop | ForEach-Object {
                @{ kind = 'sample'; qpc_after_collect = [Diagnostics.Stopwatch]::GetTimestamp();
                   qpc_frequency = [Diagnostics.Stopwatch]::Frequency;
                   utc_after_collect = [DateTime]::UtcNow.ToString('o');
                   sample_utc = $_.Timestamp.ToUniversalTime().ToString('o');
                   counters = @($_.CounterSamples | ForEach-Object {
                       @{ counter = ($_.Path -split '\\')[-1]; instance = $_.InstanceName;
                          value = $_.CookedValue; status = $_.Status; timestamp_100ns = $_.Timestamp100nSec }
                   }) } | ConvertTo-Json -Depth 6 -Compress | Add-Content -Encoding utf8 $trace
                if (-not (Test-Path $ready)) { New-Item -ItemType File $ready | Out-Null }
                if (Test-Path $stop) { throw 'SAMPLER_STOP_REQUESTED' }
            }
        } catch {
            if ($_.Exception.Message -eq 'SAMPLER_STOP_REQUESTED' -and (Test-Path $stop)) {
                $reason = 'STOP_REQUESTED'
            } else {
                $reason = 'SAMPLER_ERROR'
                throw
            }
        } finally {
            @{ kind = 'end'; reason = $reason; end_utc = [DateTime]::UtcNow.ToString('o');
               qpc = [Diagnostics.Stopwatch]::GetTimestamp() } |
                ConvertTo-Json -Compress | Add-Content -Encoding utf8 $trace
        }
    }
}

function Invoke-CustodiaFrequencyObservation {
    param([string]$Artifacts, [string]$Output,
          [scriptblock]$Probe = {
              @(Get-Counter '\Processor Information(*)\Actual Frequency' -SampleInterval 1 -MaxSamples 2 -ErrorAction Stop)[-1].CounterSamples
          },
          [scriptblock]$StartSampler = { param($t,$r,$s) Start-CustodiaFrequencySampler $t $r $s },
          [scriptblock]$Observe = {
              param($a,$o)
              & .venv/Scripts/python.exe scripts/diagnose_custodia_windows.py --artifacts $a --output (Join-Path $o 'diagnostic.json') --scheduler-trace
              if ($LASTEXITCODE -ne 0) { throw "Diagnostic exited $LASTEXITCODE; preserve evidence." }
          },
          [int]$StartupSeconds = 15, [int]$StopSeconds = 4)
    # Reject reuse before writing identity or probing anything.
    if ((Test-Path $Output) -and @(Get-ChildItem -Force $Output).Count -ne 0) {
        throw 'Preserve existing observation; use a fresh output directory.'
    }
    New-Item -ItemType Directory -Force $Output | Out-Null
    $Output = (Resolve-Path $Output).Path
    $ready = Join-Path $Output 'sampler-ready'
    $stop = Join-Path $Output 'sampler-stop'
    $trace = Join-Path $Output 'guest-frequency.jsonl'
    $job = $null
    $status = @{ purpose = 'DIAGNOSTIC_ONLY'; qualification = 'NOT_EVALUATED';
        collection = 'INCOMPLETE'; original_cause = 'NON_DIMOSTRATA';
        original_fail = 38289564204; physical_host_contention = 'UNOBSERVED';
        pmc_instructions = 'UNOBSERVED'; job_removed = $false }
    try {
        $probeRows = @(& $Probe)
        $probeRows | Select-Object Path,Status,CookedValue,Timestamp100nSec |
            ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 (Join-Path $Output 'actual-frequency-probe.json')
        Test-CustodiaCounterSample $probeRows
        @{ head = $env:GITHUB_SHA; cpu = $env:PROCESSOR_IDENTIFIER;
           qpc_frequency = [Diagnostics.Stopwatch]::Frequency;
           frequency_semantics = 'GUEST_PDH_REPORTED_NOT_PHYSICAL_HOST_VERIFIED' } |
            ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Output 'identity.json')
        $job = & $StartSampler $trace $ready $stop
        $wait = [Diagnostics.Stopwatch]::StartNew()
        while (-not (Test-Path $ready)) {
            if ($job.State -ne 'Running' -or $wait.Elapsed.TotalSeconds -gt $StartupSeconds) {
                throw 'Sampler did not start; refuse model observation.'
            }
            Start-Sleep -Milliseconds 100
        }
        if ($job.State -ne 'Running') { throw 'Sampler ended before observation.' }
        $status.observation_start_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
        & $Observe $Artifacts $Output
        $status.observation_end_qpc = [Diagnostics.Stopwatch]::GetTimestamp()
        if ($job.State -ne 'Running') { throw 'Sampler ended during observation.' }
    } catch {
        $status.error = $_.Exception.Message
    } finally {
        if ($null -ne $job) {
            $status.failed_before_stop = $job.State -ne 'Running'
            New-Item -ItemType File -Force $stop | Out-Null
            $null = Wait-Job $job -Timeout $StopSeconds
            $status.forced_stop = $job.State -eq 'Running'
            if ($status.forced_stop) { Stop-Job $job }
            $status.state = "$($job.State)"
            $jobErrors = @()
            $null = Receive-Job $job -ErrorAction SilentlyContinue -ErrorVariable jobErrors
            $status.job_errors = @($jobErrors | ForEach-Object { $_.Exception.Message })
            $id = $job.Id
            Remove-Job $job -Force
            $status.job_removed = $null -eq (Get-Job -Id $id -ErrorAction SilentlyContinue)
        }
        try {
            if ($null -eq $job -or $status.error -or $status.failed_before_stop -or
                $status.forced_stop -or $status.state -ne 'Completed' -or $status.job_errors.Count -ne 0) {
                throw 'Sampler/harness did not complete normally.'
            }
            $rows = @(Get-Content $trace | ForEach-Object { $_ | ConvertFrom-Json })
            $samples = @($rows | Where-Object kind -eq 'sample')
            if ($rows[-1].kind -ne 'end' -or $rows[-1].reason -ne 'STOP_REQUESTED' -or
                @($rows | Where-Object kind -eq 'end').Count -ne 1 -or $samples.Count -lt 2) {
                throw 'Missing samples or explicit requested-stop terminal.'
            }
            $previousQpc = 0L
            $previousTime = [DateTime]::MinValue
            foreach ($sample in $samples) {
                $time = if ($sample.sample_utc -is [DateTime]) { $sample.sample_utc.ToUniversalTime() } else { [DateTime]::Parse($sample.sample_utc).ToUniversalTime() }
                if ($sample.qpc_frequency -ne [Diagnostics.Stopwatch]::Frequency -or
                    $sample.qpc_after_collect -le $previousQpc -or $time -le $previousTime -or
                    ($previousQpc -gt 0 -and ($sample.qpc_after_collect - $previousQpc) / $sample.qpc_frequency -gt 2.5)) {
                    throw 'Clock inversion, frequency mismatch or sampling gap.'
                }
                foreach ($name in @('actual frequency','% processor performance','% processor time')) {
                    $counters = @($sample.counters | Where-Object { $_.counter -eq $name })
                    if ($counters.Count -eq 0) { throw 'Missing required counter channel.' }
                    foreach ($counter in $counters) {
                        if ($counter.status -ne 0 -or $counter.value -lt 0 -or
                            [double]::IsNaN($counter.value) -or [double]::IsInfinity($counter.value) -or
                            ($name -eq 'actual frequency' -and $counter.value -eq 0)) {
                            throw 'Invalid counter during observation.'
                        }
                    }
                }
                $previousQpc = $sample.qpc_after_collect
                $previousTime = $time
            }
            if ($samples[0].qpc_after_collect -gt $status.observation_start_qpc -or
                $samples[-1].qpc_after_collect -lt $status.observation_end_qpc) {
                throw 'Samples do not bracket observation.'
            }
            $status.collection = 'COLLECTED_REQUIRES_ETW_AND_CLOCK_ANALYSIS'
            $status.samples = $samples.Count
        } catch { $status.validation_error = $_.Exception.Message }
        $status | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $Output 'sampler-status.json')
    }
    if ($status.collection -eq 'INCOMPLETE') { throw 'INCOMPLETE observation; inspect retained sampler-status.json.' }
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not $Artifacts) { throw 'Artifacts path is required.' }
    Invoke-CustodiaFrequencyObservation -Artifacts $Artifacts -Output $Output
}
