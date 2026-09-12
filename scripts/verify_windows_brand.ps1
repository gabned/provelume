param(
    [Parameter(Mandatory = $true)][string]$Artifact,
    [Parameter(Mandatory = $true)][string]$CanonicalIcon
)

$ErrorActionPreference = "Stop"
if (-not ("ProvelumeBrandResources" -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ProvelumeBrandResources {
    private delegate bool ResourceName(IntPtr module, IntPtr type, IntPtr name, IntPtr parameter);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern IntPtr LoadLibraryExW(string file, IntPtr reserved, uint flags);
    [DllImport("kernel32")] private static extern bool FreeLibrary(IntPtr module);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool EnumResourceNamesW(IntPtr module, IntPtr type, ResourceName callback, IntPtr parameter);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern IntPtr FindResourceW(IntPtr module, IntPtr name, IntPtr type);
    [DllImport("kernel32")] private static extern uint SizeofResource(IntPtr module, IntPtr resource);
    [DllImport("kernel32")] private static extern IntPtr LoadResource(IntPtr module, IntPtr resource);
    [DllImport("kernel32")] private static extern IntPtr LockResource(IntPtr resource);
    private static byte[] Read(IntPtr module, IntPtr name, int type) {
        IntPtr resource=FindResourceW(module,name,new IntPtr(type));
        uint size=SizeofResource(module,resource);
        if(resource==IntPtr.Zero || size==0 || size>1048576) throw new InvalidOperationException("Invalid bounded icon resource");
        IntPtr address=LockResource(LoadResource(module,resource));
        if(address==IntPtr.Zero) throw new InvalidOperationException("Unreadable icon resource");
        byte[] bytes=new byte[size]; Marshal.Copy(address,bytes,0,bytes.Length); return bytes;
    }
    public static List<byte[][]> Groups(string file) {
        // Data-only mapping never executes the candidate executable.
        IntPtr module=LoadLibraryExW(file,IntPtr.Zero,0x22);
        if(module==IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        try {
            var result=new List<byte[][]>(); Exception failure=null;
            ResourceName callback=delegate(IntPtr ignored, IntPtr type, IntPtr name, IntPtr parameter) {
                try {
                    byte[] group=Read(module,name,14);
                    int count=BitConverter.ToUInt16(group,4);
                    if(count<1 || count>64 || group.Length!=6+14*count) throw new InvalidOperationException("Invalid icon group");
                    var frames=new byte[count][];
                    for(int i=0;i<count;i++) frames[i]=Read(module,new IntPtr(BitConverter.ToUInt16(group,6+14*i+12)),3);
                    result.Add(frames);return true;
                } catch(Exception error) { failure=error;return false; }
            };
            bool ok=EnumResourceNamesW(module,new IntPtr(14),callback,IntPtr.Zero);
            GC.KeepAlive(callback);
            if(failure!=null) throw failure;
            if(!ok || result.Count==0) throw new InvalidOperationException("No readable icon groups");
            return result;
        } finally { FreeLibrary(module); }
    }
}
'@
}
$IconBytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $CanonicalIcon).Path)
if ($IconBytes.Length -lt 6 -or [BitConverter]::ToUInt16($IconBytes, 2) -ne 1) {
    throw "Canonical file is not an ICO."
}
$Count = [BitConverter]::ToUInt16($IconBytes, 4)
if ($Count -ne 9) { throw "Canonical ICO must contain all nine reviewed sizes." }
$Hasher = [Security.Cryptography.SHA256]::Create()
try {
    $Expected = @()
    for ($Index = 0; $Index -lt $Count; $Index++) {
        $Length = [BitConverter]::ToUInt32($IconBytes, 6 + 16 * $Index + 8)
        $Offset = [BitConverter]::ToUInt32($IconBytes, 6 + 16 * $Index + 12)
        if ($Offset + $Length -gt $IconBytes.Length) { throw "Truncated canonical ICO." }
        $Frame = [byte[]]::new($Length)
        [Array]::Copy($IconBytes, $Offset, $Frame, 0, $Length)
        $Expected += [BitConverter]::ToString($Hasher.ComputeHash($Frame))
    }
    $Matched = $false
    foreach ($Group in [ProvelumeBrandResources]::Groups((Resolve-Path -LiteralPath $Artifact).Path)) {
        $Actual = @($Group | ForEach-Object { [BitConverter]::ToString($Hasher.ComputeHash($_)) })
        if ($Actual.Count -eq $Count -and ($Actual -join ',') -ceq ($Expected -join ',')) {
            $Matched = $true
        }
    }
    if (-not $Matched) { throw "Executable resources do not contain the complete canonical brand." }
    [ordered]@{ status = "PASS"; canonical_sizes = $Count; canonical_sha256 = (Get-FileHash -LiteralPath $CanonicalIcon -Algorithm SHA256).Hash.ToLowerInvariant(); artifact_sha256 = (Get-FileHash -LiteralPath $Artifact -Algorithm SHA256).Hash.ToLowerInvariant(); executed = $false }
}
finally { $Hasher.Dispose() }
