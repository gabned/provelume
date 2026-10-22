param([Parameter(Mandatory=$true)][string]$Artifacts, [switch]$Diagnostic,
      [switch]$GovernedDiagnostic)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
    throw 'This network observation changes only disposable GitHub Windows runners.'
}
New-Item -ItemType Directory -Force -Path .agent | Out-Null
$workerPython = & .venv/Scripts/python.exe -c 'import sys; print(sys._base_executable)'
$ruleName = 'Provelume-S05-' + [guid]::NewGuid().ToString()
$reportPrefix = if ($Diagnostic) { 's06-diagnostic' } else { 's05' }
$reportPath = if ($Diagnostic) { '.agent/s06-diagnostic.json' } else { '.agent/s05-real.json' }
$wfpPath = if ($Diagnostic) { '.agent/s06-diagnostic-wfp.json' } else { '.agent/s05-wfp.json' }
if ($GovernedDiagnostic) {
    if ($Diagnostic) { throw 'Select one diagnostic experiment.' }
    $reportPrefix = 's06-governed-diagnostic'
    $reportPath = '.agent/s06-governed-diagnostic.json'
    $wfpPath = '.agent/s06-governed-diagnostic-wfp.json'
}
$auditFile = Join-Path (Resolve-Path .agent) ($reportPrefix + '-audit-before.csv')
$started = Get-Date
$subCategory = '{0CCE9226-69AE-11D9-BED3-505054503030}'
$measurementExit = 1
& auditpol /backup "/file:$auditFile" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Cannot preserve audit policy; no measurement performed.' }
try {
    & auditpol /set "/subcategory:$subCategory" /success:enable /failure:enable | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'WFP observer unavailable; NOT_RUN.' }
    New-NetFirewallRule -Name $ruleName -DisplayName $ruleName -Direction Outbound `
        -Action Block -Program $workerPython -Profile Any | Out-Null
    # The documentation-range destination is only an observer calibration probe.
    # Both the deny rule and its corresponding 5157 audit event must be observed.
    $probeCode = @'
import socket
s = socket.socket()
s.settimeout(1)
try:
    s.connect(("198.51.100.1", 9))
except OSError:
    pass
'@
    & $workerPython -I -c $probeCode
    $appliedRule = Get-NetFirewallRule -Name $ruleName
    $appliedProgram = $appliedRule | Get-NetFirewallApplicationFilter
    if ($appliedRule.Enabled -ne 'True' -or $appliedRule.Action -ne 'Block' -or
        $appliedRule.Direction -ne 'Outbound' -or $appliedProgram.Program -ne $workerPython) {
        throw 'S06 requires the independently observed exact-interpreter WFP control.'
    }
    $env:S06_WFP_VERIFIED = '1'
    if ($GovernedDiagnostic) {
        & .venv/Scripts/python.exe scripts/diagnose_ai_governed_control.py --artifacts $Artifacts `
            --output $reportPath
    } elseif ($Diagnostic) {
        & .venv/Scripts/python.exe scripts/diagnose_ai_governed.py --artifacts $Artifacts `
            --output $reportPath
    } else {
        & .venv/Scripts/python.exe scripts/qualify_ai_runtime.py --artifacts $Artifacts `
            --output $reportPath
    }
    $measurementExit = $LASTEXITCODE
    $pythonName = [IO.Path]::GetFileName($workerPython)
    $events = @(Get-WinEvent -FilterHashtable @{LogName='Security'; Id=5156,5157; StartTime=$started} `
        -ErrorAction SilentlyContinue | ForEach-Object {
        $eventId = $_.Id
        $fields = @{}
        ([xml]$_.ToXml()).Event.EventData.Data | ForEach-Object { $fields[$_.Name] = $_.'#text' }
        if ($fields['Application'] -and $fields['Application'].EndsWith($pythonName)) {
            @{id=$eventId; pid=[int]$fields['ProcessID']; destination=$fields['DestAddress']}
        }
    })
    $probe = @($events | Where-Object { $_.id -eq 5157 -and $_.destination -eq '198.51.100.1' })
    @{audit_enabled=$true; probe_denied=($probe.Count -gt 0); events=$events} |
        ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $wfpPath
} finally {
    Remove-Item Env:S06_WFP_VERIFIED -ErrorAction SilentlyContinue
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    & auditpol /restore "/file:$auditFile" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Audit policy restoration failed.' }
}
if (-not (Test-Path $reportPath)) { exit $measurementExit }
if ($GovernedDiagnostic) {
    & .venv/Scripts/python.exe scripts/diagnose_ai_governed_control.py --audit $wfpPath `
        --output $reportPath
    if ($measurementExit -ne 0) { exit $measurementExit }
    exit $LASTEXITCODE
}
if ($Diagnostic) {
    & .venv/Scripts/python.exe scripts/diagnose_ai_governed.py --audit $wfpPath `
        --output $reportPath
    if ($measurementExit -ne 0) { exit $measurementExit }
    exit $LASTEXITCODE
}
& .venv/Scripts/python.exe scripts/ai_runtime_network.py --report .agent/s05-real.json `
    --events .agent/s05-wfp.json
exit $LASTEXITCODE
