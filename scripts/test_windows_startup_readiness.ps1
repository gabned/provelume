param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string]$InstanceDirectory,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$ExpectedCommit
)

# Called only after the parent installer smoke independently verifies executable
# identity. This tests frozen stdin/proof transport, not the managed Panel UI.
$ErrorActionPreference = "Stop"
$Report = [ordered]@{
    schema = "provelume-frozen-readiness-smoke/v1"
    status = "RUNNING"
    failure_code = "bootstrap_failed"
    expected_commit = $ExpectedCommit
    surface = "frozen_private_stdin_transport"
    executable_sha256 = $null
    readiness_deadline_seconds = 30
    response_bound_bytes = 2048
    probes = 0
    proof_verified = $false
    opened_root_binding_verified = $false
    cleanup_confirmed = $false
    cooperative_stop_confirmed = $false
    managed_panel_ui_qualified = $false
    windows11_qualified = $false
    private_content_logged = $false
    key_written_to_file_or_environment = $false
}
$Child = $null
$RootHandle = $null
$Client = $null
$StopEvent = $null
$Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

function Get-RandomHex {
    param([int]$Size)
    $Bytes = [byte[]]::new($Size)
    $Rng.GetBytes($Bytes)
    return [Convert]::ToHexString($Bytes).ToLowerInvariant()
}

function Get-FramedBytes {
    param([string[]]$Values)
    $Buffer = [System.IO.MemoryStream]::new()
    try {
        foreach ($Value in $Values) {
            $Bytes = [Text.Encoding]::UTF8.GetBytes($Value)
            $Length = [BitConverter]::GetBytes([uint32]$Bytes.Length)
            if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($Length) }
            $Buffer.Write($Length, 0, 4)
            $Buffer.Write($Bytes, 0, $Bytes.Length)
        }
        return ,$Buffer.ToArray()
    }
    finally { $Buffer.Dispose() }
}

function Get-Mac {
    param([byte[]]$Key, [string[]]$Values)
    $Mac = [Security.Cryptography.HMACSHA256]::new($Key)
    try {
        return [Convert]::ToHexString($Mac.ComputeHash((Get-FramedBytes $Values))).ToLowerInvariant()
    }
    finally { $Mac.Dispose() }
}

try {
    if ($ExpectedCommit -cnotmatch '^[0-9a-f]{40}$' -or $Port -lt 1024 -or $Port -gt 65535) {
        throw "Invalid synthetic test coordinates."
    }
    $Report.executable_sha256 = (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not ("ConcordiaReadinessNative" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class ConcordiaReadinessNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct FileIdInfo {
        public UInt64 Volume;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst=16)] public byte[] Id;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share,
        IntPtr security, uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool GetFileInformationByHandleEx(SafeFileHandle handle,
        int kind, out FileIdInfo info, uint size);
    public static SafeFileHandle Open(string path) {
        var handle=CreateFileW(path, 0x81, 3, IntPtr.Zero, 3, 0x02200000, IntPtr.Zero);
        if(handle.IsInvalid) throw new Win32Exception();
        return handle;
    }
    public static byte[] Identity(SafeFileHandle handle) {
        FileIdInfo info;
        if(!GetFileInformationByHandleEx(handle,18,out info,(uint)Marshal.SizeOf(typeof(FileIdInfo))))
            throw new Win32Exception();
        var volume=BitConverter.GetBytes(info.Volume);
        if(BitConverter.IsLittleEndian) Array.Reverse(volume);
        var data=new byte[24]; Array.Copy(volume,0,data,0,8); Array.Copy(info.Id,0,data,8,16);
        return data;
    }
    public static bool Equal(byte[] left, byte[] right) {
        if(left.Length != right.Length) return false;
        int difference=0;
        for(int i=0;i<left.Length;i++) difference |= left[i] ^ right[i];
        return difference==0;
    }
}
'@
    }
    $RootHandle = [ConcordiaReadinessNative]::Open($InstanceDirectory)
    $RootBinding = "win32.file-id.v1:" + [Convert]::ToHexString(
        [ConcordiaReadinessNative]::Identity($RootHandle)
    ).ToLowerInvariant()
    $Manifest = Get-Content -LiteralPath (Join-Path $InstanceDirectory "instance-manifest.json") -Raw | ConvertFrom-Json
    $InstanceId = [string]$Manifest.instance.id
    if (-not $InstanceId.StartsWith("inst_")) { throw "Invalid synthetic Instance." }
    $StartupId = Get-RandomHex 16
    $Key = [byte[]]::new(32)
    $Rng.GetBytes($Key)
    $StopName = "Local\Provelume.Startup.Stop." + (Get-Mac -Key $Key -Values @(
        "provelume.startup-stop.v1", $StartupId
    ))
    $CreatedNew = $false
    $StopEvent = [Threading.EventWaitHandle]::new(
        $false, [Threading.EventResetMode]::ManualReset, $StopName, [ref]$CreatedNew
    )
    if (-not $CreatedNew) { throw "Synthetic stop event already exists." }
    $PortText = $Port.ToString([Globalization.CultureInfo]::InvariantCulture)
    $Binding = Get-Mac -Key $Key -Values @(
        "provelume.instance-binding.v1", $StartupId, $InstanceId, $RootBinding, "127.0.0.1", $PortText
    )
    $Bootstrap = [ordered]@{ version=1; startup_id=$StartupId; key=[Convert]::ToHexString($Key).ToLowerInvariant() }
    $Frame = [Text.Encoding]::UTF8.GetBytes(($Bootstrap | ConvertTo-Json -Compress))
    if ($Frame.Length -gt 256) { throw "Bootstrap bound exceeded." }
    $Length = [BitConverter]::GetBytes([uint32]$Frame.Length)
    if ([BitConverter]::IsLittleEndian) { [Array]::Reverse($Length) }
    $Start = [Diagnostics.ProcessStartInfo]::new()
    $Start.FileName = $Executable
    $Start.UseShellExecute = $false
    $Start.CreateNoWindow = $true
    $Start.RedirectStandardInput = $true
    $Start.StandardInputEncoding = [Text.UTF8Encoding]::new($false)
    foreach ($Argument in @("--serve", $InstanceDirectory, "--port", $PortText, "--startup-bootstrap-stdin")) {
        $Start.ArgumentList.Add($Argument)
    }
    $Child = [Diagnostics.Process]::new()
    $Child.StartInfo = $Start
    $Child.Start() | Out-Null
    $Child.StandardInput.BaseStream.Write($Length, 0, 4)
    $Child.StandardInput.BaseStream.Write($Frame, 0, $Frame.Length)
    $Child.StandardInput.BaseStream.Flush()
    $Child.StandardInput.Close()
    $Bootstrap = $null
    $Frame = $null

    $Handler = [Net.Http.HttpClientHandler]::new()
    $Handler.UseProxy = $false
    $Handler.AllowAutoRedirect = $false
    $Client = [Net.Http.HttpClient]::new($Handler)
    $Client.Timeout = [Threading.Timeout]::InfiniteTimeSpan
    $Clock = [Diagnostics.Stopwatch]::StartNew()
    $Report.failure_code = "readiness_timeout"
    while ($Clock.ElapsedMilliseconds -lt 30000 -and -not $Report.proof_verified) {
        if ($Child.HasExited) { throw "Owned child exited before readiness." }
        $Remaining = 30000 - $Clock.ElapsedMilliseconds
        $Cts = [Threading.CancellationTokenSource]::new([int][Math]::Min(1000, $Remaining))
        $Request = [Net.Http.HttpRequestMessage]::new(
            [Net.Http.HttpMethod]::Get, "http://127.0.0.1:$Port/internal/startup-readiness"
        )
        $Challenge = Get-RandomHex 32
        $Request.Headers.Add("X-Provelume-Readiness-Challenge", $Challenge)
        $Response = $null
        $Report.probes++
        try {
            try {
                $Response = $Client.SendAsync(
                    $Request, [Net.Http.HttpCompletionOption]::ResponseHeadersRead, $Cts.Token
                ).GetAwaiter().GetResult()
            }
            catch [Net.Http.HttpRequestException] { continue }
            catch [Threading.Tasks.TaskCanceledException] { continue }
            $Report.failure_code = "readiness_response_invalid"
            $Size = $Response.Content.Headers.ContentLength
            if ($null -eq $Size -or $Size -lt 1 -or $Size -gt 2048 -or
                $Response.Content.Headers.ContentType.MediaType -ne "application/json") {
                throw "Invalid bounded JSON response."
            }
            $Buffer = [byte[]]::new([int]$Size)
            $Stream = $Response.Content.ReadAsStream()
            $Offset = 0
            while ($Offset -lt $Buffer.Length) {
                $Count = $Stream.ReadAsync($Buffer, $Offset, $Buffer.Length-$Offset, $Cts.Token).GetAwaiter().GetResult()
                if ($Count -eq 0) { throw "Truncated response." }
                $Offset += $Count
            }
            $Document = [Text.Json.JsonDocument]::Parse([Text.UTF8Encoding]::new($false,$true).GetString($Buffer))
            try {
                $Json = $Document.RootElement
                $Fields = @("contract","version","startup_id","challenge","instance_binding","port",
                            "backend_state","reason","diagnostics_state","proof")
                $Names = @($Json.EnumerateObject() | ForEach-Object { $_.Name })
                if ($Names.Count -ne 10 -or @($Names | Sort-Object -Unique).Count -ne 10 -or
                    @(Compare-Object ($Names | Sort-Object) ($Fields | Sort-Object)).Count -ne 0) {
                    throw "Unknown or duplicate response fields."
                }
                $Version = $Json.GetProperty("version").GetInt32()
                $ObservedPort = $Json.GetProperty("port").GetInt32()
                $Values = @{}
                foreach ($Field in ($Fields | Where-Object { $_ -notin @("version","port") })) {
                    $Values[$Field] = $Json.GetProperty($Field).GetString()
                }
                if ($Version -ne 1 -or $Values.contract -cne "provelume.startup-readiness" -or
                    $ObservedPort -ne $Port -or $Values.startup_id -cne $StartupId -or
                    $Values.challenge -cne $Challenge -or $Values.instance_binding -cne $Binding -or
                    $Values.proof -cnotmatch '^[0-9a-f]{64}$' -or
                    $Values.diagnostics_state -cnotin @("not_requested","pending","complete","failed","unavailable") -or
                    $Values.backend_state -cnotin @("starting","ready","failed")) {
                    throw "Startup identity or schema mismatch."
                }
                $AllowedReasons = @{
                    starting=@("initializing"); ready=@("operational")
                    failed=@("configuration_invalid","integrity_failed","initialization_failed")
                }
                $Status = [int]$Response.StatusCode
                if (-not $AllowedReasons.ContainsKey($Values.backend_state) -or
                    $Values.reason -cnotin $AllowedReasons[$Values.backend_state] -or
                    $Status -ne $(if ($Values.backend_state -ceq "ready") {200} else {503})) {
                    throw "Incoherent startup state."
                }
                $ExpectedProof = Get-Mac -Key $Key -Values @(
                    "provelume.startup-readiness.proof.v1", $Values.contract, "1", $StartupId,
                    $Challenge, $Binding, $PortText, $Values.backend_state, $Values.reason,
                    $Values.diagnostics_state
                )
                if (-not [ConcordiaReadinessNative]::Equal(
                    [Convert]::FromHexString($Values.proof), [Convert]::FromHexString($ExpectedProof)
                )) { throw "Invalid startup proof." }
                if ($Values.backend_state -ceq "failed") { throw "Mandatory initialization failed." }
                if ($Values.backend_state -ceq "ready") {
                    if ($Child.HasExited -or $Clock.ElapsedMilliseconds -ge 30000) {
                        throw "Late or exited startup result."
                    }
                    $Report.proof_verified = $true
                    $Report.opened_root_binding_verified = $true
                }
            }
            finally { $Document.Dispose() }
            $Report.failure_code = "readiness_timeout"
        }
        finally {
            if ($null -ne $Response) { $Response.Dispose() }
            $Request.Dispose()
            $Cts.Dispose()
            if (-not $Report.proof_verified) {
                $Gap = [int][Math]::Min(250, [Math]::Max(0, 30000-$Clock.ElapsedMilliseconds))
                if ($Gap -gt 0) { Start-Sleep -Milliseconds $Gap }
            }
        }
    }
    if (-not $Report.proof_verified) { throw "Startup deadline exceeded." }
    $Report.status = "PASS"
    $Report.failure_code = $null
}
catch { $Report.status = "FAIL" }
finally {
    if ($null -ne $Child) {
        try {
            if (-not $Child.HasExited -and $null -ne $StopEvent) {
                $StopEvent.Set() | Out-Null
                $Report.cooperative_stop_confirmed = $Child.WaitForExit(4000)
            }
            if (-not $Child.HasExited) { $Child.Kill($true) }
            $Report.cleanup_confirmed = $Child.WaitForExit(2000)
        }
        catch { $Report.cleanup_confirmed = $Child.HasExited }
        finally { $Child.Dispose() }
    }
    if (-not $Report.cleanup_confirmed) {
        $Report.status = "FAIL"
        if ($null -eq $Report.failure_code) { $Report.failure_code = "stop_unconfirmed" }
    }
    if ($null -ne $RootHandle) { $RootHandle.Dispose() }
    if ($null -ne $Client) { $Client.Dispose() }
    if ($null -ne $StopEvent) { $StopEvent.Dispose() }
    $Rng.Dispose()
    $Key = $null
}
[pscustomobject]$Report
