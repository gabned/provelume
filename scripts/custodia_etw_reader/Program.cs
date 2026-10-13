// Diagnostic reader only. No dependency enters the product or installation kit.
using System.Diagnostics;
using System.Globalization;
using System.Text.Json;
using Microsoft.Diagnostics.Tracing;

if (args.Length != 3) throw new ArgumentException("trace.etl events.jsonl metadata.json required");
using var output = new StreamWriter(args[1]);
using var source = new ETWTraceEventSource(args[0]);
var counts = new Dictionary<string, long>();
long first = long.MaxValue, last = 0, rows = 0;
var allowed = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
    "OldThreadID", "NewThreadID", "ThreadID", "TThreadID", "AwakenedThreadID",
    "OldThreadState", "OldThreadWaitReason", "OldThreadWaitMode",
    "NewThreadPriority", "OldThreadPriority", "NewThreadWaitTime",
    "ProcessID", "IssuingThreadID", "DiskNumber", "TransferSize", "IOSize",
    "ByteCount", "ElapsedTime", "HighResResponseTime", "ResponseTime", "IOFlags"
};
source.Kernel.All += data => {
    var name = data.EventName;
    if (!(name.Contains("CSwitch", StringComparison.OrdinalIgnoreCase) ||
          name.Contains("ReadyThread", StringComparison.OrdinalIgnoreCase) ||
          name.StartsWith("PerfInfo/", StringComparison.OrdinalIgnoreCase) ||
          name.StartsWith("DiskIO/", StringComparison.OrdinalIgnoreCase) ||
          name.Contains("HardFault", StringComparison.OrdinalIgnoreCase))) return;
    var values = new Dictionary<string, object>();
    for (var i = 0; i < data.PayloadNames.Length; i++) {
        var key = data.PayloadNames[i];
        if (!allowed.Contains(key)) continue;
        var value = data.PayloadValue(i);
        if (value is Enum) values[key] = Convert.ToInt64(value, CultureInfo.InvariantCulture);
        else if (value is byte or sbyte or short or ushort or int or uint or long or ulong or
                 float or double or bool) values[key] = value;
    }
    first = Math.Min(first, data.TimeStampQPC);
    last = Math.Max(last, data.TimeStampQPC);
    counts[name] = counts.GetValueOrDefault(name) + 1;
    rows++;
    output.WriteLine(JsonSerializer.Serialize(new {
        name, qpc = data.TimeStampQPC, cpu = data.ProcessorNumber,
        pid = data.ProcessID, tid = data.ThreadID, payload = values
    }));
};
source.Process();
output.Flush();
// Unknown loss reporting stays unknown; it can never certify a complete trace.
var lostProperty = source.GetType().GetProperty("EventsLost");
var lost = lostProperty?.GetValue(source);
File.WriteAllText(args[2], JsonSerializer.Serialize(new {
    purpose = "DIAGNOSTIC_ONLY", qualification = "NOT_EVALUATED",
    qpc_frequency = Stopwatch.Frequency, first_qpc = first, last_qpc = last,
    rows, events_lost = lost, event_counts = counts,
    strings_excluded = new[] { "process arguments", "paths", "file names", "memory contents" }
}, new JsonSerializerOptions { WriteIndented = true }));
