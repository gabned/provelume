param([string]$Output = '.agent/custodia-telemetry/capabilities.json')
$ErrorActionPreference = 'Stop'
$directory = Split-Path -Parent $Output
New-Item -ItemType Directory -Force $directory | Out-Null
$report = [ordered]@{
    schema = 'custodia-windows-telemetry-capabilities/v1'
    purpose = 'CAPABILITY_PROBE_ONLY'
    qualification = 'NOT_EVALUATED'
    observed_at = [DateTime]::UtcNow.ToString('o')
    head = $env:GITHUB_SHA
    original_fail_run = 38289564204
    original_host_telemetry = 'MISSING_NOT_RECONSTRUCTED'
    probes = [ordered]@{}
}
function Probe($Name, [scriptblock]$Operation) {
    try {
        $value = & $Operation
        $report.probes[$Name] = @{ status = 'OBSERVED'; value = $value }
    } catch {
        # Do not serialize arbitrary exception messages, paths or process data.
        $report.probes[$Name] = @{ status = 'UNAVAILABLE'; error_type = $_.Exception.GetType().FullName; hresult = $_.Exception.HResult }
    }
}
Probe 'guest_identity' {
    $cpu = Get-CimInstance Win32_Processor
    $system = Get-CimInstance Win32_ComputerSystem
    @{
        cpu = @($cpu | Select-Object Manufacturer, Architecture, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed, CurrentClockSpeed)
        processor_identifier = $env:PROCESSOR_IDENTIFIER
        guest = $system | Select-Object Manufacturer, Model, HypervisorPresent, NumberOfLogicalProcessors
        physical_host_contention = 'NOT_EXPOSED_BY_GUEST_IDENTITY'
        cim_clock_semantics = 'NOMINAL_OR_PROVIDER_REPORTED_NOT_EFFECTIVE_FREQUENCY'
    }
}
Probe 'pmc_sources' {
    $lines = @(& wpr.exe -pmcsources 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
    @{ exit_code = $code; lines = $lines; semantics = 'ADVERTISED_ONLY_NOT_RECORDING_VERIFIED' }
}
Probe 'hyperv_host_counter_sets' {
    $sets = @(Get-Counter -ListSet 'Hyper-V Hypervisor*' -ErrorAction Stop)
    @{ sets = @($sets.CounterSetName); semantics = 'COUNTER_SET_EXISTENCE_ONLY_NOT_HOST_CONTENTION_PROOF' }
}
Probe 'processor_counter_inventory' {
    $set = Get-Counter -ListSet 'Processor Information'
    @{ paths = @($set.Paths | Where-Object { $_ -match 'Frequency|Performance|Utility|Privileged|Processor Time' }) }
}
Add-Type -TypeDefinition @'
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
public static class CustodiaTelemetryCalibration {
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentThread();
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryThreadCycleTime(IntPtr thread, out ulong cycles);
    public static object Run(int milliseconds) {
        ulong before, after;
        bool a = QueryThreadCycleTime(GetCurrentThread(), out before);
        var watch = Stopwatch.StartNew();
        long iterations = 0;
        while (watch.ElapsedMilliseconds < milliseconds) { iterations++; }
        watch.Stop();
        bool b = QueryThreadCycleTime(GetCurrentThread(), out after);
        return new { available = a && b, delta = a && b ? (double?)(after - before) : null,
            qpc_seconds = watch.Elapsed.TotalSeconds, iterations = iterations,
            semantics = "WINDOWS_SCHEDULER_CYCLE_ACCOUNTING_NOT_RETIRED_INSTRUCTIONS_OR_EFFECTIVE_HZ" };
    }
}
'@
Probe 'thread_cycle_accounting' { [CustodiaTelemetryCalibration]::Run(300) }
$counterPaths = @(
    '\Processor Information(*)\Processor Frequency',
    '\Processor Information(*)\% Processor Performance',
    '\Processor Information(*)\% of Maximum Frequency',
    '\Processor Information(*)\% Processor Utility',
    '\Processor Information(*)\% Processor Time'
)
# Bounded synthetic load on this new guest only. No Core/model/gate execution.
$job = Start-Job { $w = [Diagnostics.Stopwatch]::StartNew(); while ($w.Elapsed.TotalSeconds -lt 8) { [Math]::Sqrt(1234567) | Out-Null } }
try {
    foreach ($path in $counterPaths) {
        Probe $path {
            $samples = @(Get-Counter -Counter $path -SampleInterval 1 -MaxSamples 2 -ErrorAction Stop)
            @{
                semantics = 'GUEST_PDH_REPORTED_VALUES_NEED_CALIBRATION_NOT_PHYSICAL_HOST_TELEMETRY'
                samples = @($samples | ForEach-Object {
                    @{ utc = $_.Timestamp.ToUniversalTime().ToString('o'); counters = @($_.CounterSamples | ForEach-Object {
                        @{ instance = $_.InstanceName; value = $_.CookedValue; status = $_.Status; timestamp_100ns = $_.Timestamp100NS }
                    }) }
                })
            }
        }
    }
} finally {
    Stop-Job $job -ErrorAction SilentlyContinue
    Remove-Job $job -Force -ErrorAction SilentlyContinue
}
Probe 'processor_power_provider' {
    $lines = @(& logman.exe query providers 'Microsoft-Windows-Kernel-Processor-Power' 2>&1 | ForEach-Object { "$_" })
    @{ exit_code = $LASTEXITCODE; lines = $lines; semantics = 'REGISTRATION_ONLY_NOT_EVENT_AVAILABILITY' }
}
$session = 'CustodiaTelemetry-' + [Guid]::NewGuid().ToString('N')
$etl = Join-Path $directory 'processor-power.etl'
$started = $false
try {
    & logman.exe start $session -p 'Microsoft-Windows-Kernel-Processor-Power' 0xffffffffffffffff 5 -o $etl -ets | Out-Null
    $startCode = $LASTEXITCODE
    $started = $startCode -eq 0
    if ($started) {
        $null = [CustodiaTelemetryCalibration]::Run(1000)
        & logman.exe stop $session -ets | Out-Null
        $stopCode = $LASTEXITCODE
        $started = $false
        $xml = Join-Path $directory 'processor-power.xml'
        & tracerpt.exe $etl -o $xml -of XML -y | Out-Null
        $decodeCode = $LASTEXITCODE
        $report.probes['processor_power_recording'] = @{ status = 'RECORDED'; start_exit_code = $startCode; stop_exit_code = $stopCode; decode_exit_code = $decodeCode; semantics = 'EVENT_PAYLOADS_REQUIRE_INSPECTION_BEFORE_FREQUENCY_CLAIM' }
    } else {
        $report.probes['processor_power_recording'] = @{ status = 'UNAVAILABLE'; start_exit_code = $startCode }
    }
} finally {
    if ($started) { & logman.exe stop $session -ets | Out-Null }
    $report | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 $Output
}
