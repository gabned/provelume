"""Reduce the predefined new-host observation; no qualification or original-host attribution."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
source = Path(sys.argv[2])
spec = importlib.util.spec_from_file_location('scheduler_reducer', source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
report = json.loads(next(root.rglob('diagnostic.json')).read_text(encoding='utf-8-sig'))
sampler = json.loads(next(root.rglob('custodia-frequency-diagnosis/sampler-status.json')).read_text(encoding='utf-8-sig'))
frequency_rows = [json.loads(s) for s in next(root.rglob('custodia-frequency-diagnosis/guest-frequency.jsonl')).read_text(encoding='utf-8-sig').splitlines()]
samples = [r for r in frequency_rows if r.get('kind') == 'sample']
clock = report['clock_identity']
qpc_ns = clock['windows_qpc'] * 1000000000 // clock['qpc_frequency']
clock_valid = clock['python_before_ns'] <= qpc_ns <= clock['python_after_ns']
anchors = []
for row in samples:
    after = dt.datetime.fromisoformat(row['utc_after_collect'].replace('Z', '+00:00'))
    measured = dt.datetime.fromisoformat(row['sample_utc'].replace('Z', '+00:00'))
    row['sample_qpc_ns'] = row['qpc_after_collect'] * 1000000000 // row['qpc_frequency'] + round((measured-after).total_seconds()*1e9)
    anchors.append(after.timestamp() - row['qpc_after_collect']/row['qpc_frequency'])
clock_valid = clock_valid and all(r['qpc_frequency'] == clock['qpc_frequency'] for r in samples)
clock_valid = clock_valid and max(anchors)-min(anchors) < 0.05
clock_valid = clock_valid and all(0 < (b['sample_qpc_ns']-a['sample_qpc_ns'])/1e9 < 2.5 for a,b in zip(samples,samples[1:]))
sessions = json.loads(next(root.rglob('sessions.json')).read_text())
workers = [json.loads(s) for f in root.rglob('worker-*.jsonl') for s in f.read_text().splitlines()]
rows = []
for observed in report['samples']:
    if observed['id'] != 'en04':
        continue
    request, pid = observed['prefill']['request'], observed['prefill']['pid']
    spans = [r for r in workers if r['phase'] == 'native.prefill_decode' and r['request'] == request and r['start']['pid'] == pid]
    windows = [(r['start']['performance_ns'], r['end']['performance_ns']) for r in spans]
    session = next(s for s in sessions if s['run'] == observed['run'])
    metadata = json.loads(next(root.rglob(session['trace']+'.metadata.json')).read_text())
    events = [json.loads(s) for s in next(root.rglob(session['trace']+'.events.jsonl')).read_text().splitlines()]
    affinity = observed['load']['limits']['cpu_topology']['selected_logical_cpus']
    reduced = module.reduce_events(events, metadata, session, pid, windows, affinity)
    in_window = [s for s in samples if any(a <= s['sample_qpc_ns'] <= b for a,b in windows)]
    frequencies = {}
    for sample in in_window:
        for counter in sample['counters']:
            if counter['counter'].casefold() == 'actual frequency':
                frequencies.setdefault(counter['instance'], []).append(counter['value'])
    reduced.update(run=observed['run'], request=request, first_wall_seconds=observed['first_wall_seconds'],
        phases=observed['phases'], decode_pdh_sample_count=len(in_window),
        guest_frequency_mhz={k: {'min': min(v), 'max': max(v)} for k,v in frequencies.items()},
        slow_decode_discriminable=len(in_window)>=2 and clock_valid and reduced['status']=='OBSERVED')
    rows.append(reduced)
result = {'purpose':'DIAGNOSTIC_ONLY','qualification':'NOT_EVALUATED', 'original_cause':'NON_DIMOSTRATA',
    'clock_identity': clock, 'clock_verified': clock_valid, 'anchor_offset_spread_seconds':max(anchors)-min(anchors),
    'sampler':sampler, 'environment':report['environment'], 'sample_count':len(report['samples']),
    'first_wall_over_5s':[{'id':s['id'],'run':s['run'],'seconds':s['first_wall_seconds']} for s in report['samples'] if s['first_wall_seconds']>5],
    'worker_absent':report['worker_absent'], 'rows':rows,
    'physical_host_contention':'UNOBSERVED','hardware_pmc':'UNOBSERVED'}
(root.parent/'frequency-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
