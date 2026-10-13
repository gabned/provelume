"""Request/PID-correlated ETW reduction; never a qualification evaluator."""
from pathlib import Path
import argparse
import json

def overlap(a,b,windows):
 return sum(max(0,min(b,end)-max(a,start)) for start,end in windows)/1e9

def reduce_events(events,metadata,session,worker_pid,windows,affinity):
 frequency=metadata['qpc_frequency']
 events=sorted(events,key=lambda e:e['qpc'])
 owners={}
 for row in session['threads_before']+session['threads_after']:
  if row['tid'] in owners and owners[row['tid']]!=row['pid']:
   raise ValueError('PID/TID ownership changed inside the observed window')
  owners[row['tid']]=row['pid']
 worker_tids={tid for tid,pid in owners.items() if pid==worker_pid}
 if not worker_tids: raise ValueError('Worker thread ownership is missing')
 def point(e): return e['qpc']*1000000000//frequency
 def fields(e): return {k.casefold():v for k,v in e['payload'].items()}
 active={}
 ready={}
 running={}
 ready_time={}
 other_cpu={}
 continuity_breaks=0
 ready_count=0
 switches=0
 disk=[]
 for e in events:
  now=point(e);values=fields(e);name=e['name'].casefold()
  if 'readythread' in name:
   ready_count+=1
   tid=values.get('awakenedthreadid')
   if tid is not None: ready.setdefault(tid,now)
  if 'cswitch' in name:
   switches+=1
   old,new=values.get('oldthreadid'),values.get('newthreadid')
   if old is None or new is None: raise ValueError('Context switch thread IDs missing')
   cpu=e['cpu']
   if cpu in active:
    since,previous=active[cpu]
    if previous!=old: continuity_breaks+=1
    seconds=overlap(since,now,windows)
    if previous in worker_tids:
     running[previous]=running.get(previous,0)+seconds
    elif cpu in affinity and previous!=0:
     other_cpu[cpu]=other_cpu.get(cpu,0)+seconds
   active[cpu]=(now,new)
   if values.get('oldthreadstate')==1: ready.setdefault(old,now)
   if new in ready:
    seconds=overlap(ready.pop(new),now,windows)
    if new in worker_tids: ready_time[new]=ready_time.get(new,0)+seconds
  if name.startswith('diskio/') or 'hardfault' in name:
   tid=values.get('issuingthreadid',values.get('threadid',values.get('tthreadid',e['tid'])))
   if tid in worker_tids and any(a<=now<=b for a,b in windows):
    disk.append({'name':e['name'],'tid':tid,'qpc_ns':now,'payload':e['payload']})
 if events:
  end=point(events[-1])
  for cpu,(since,tid) in active.items():
   seconds=overlap(since,end,windows)
   if tid in worker_tids: running[tid]=running.get(tid,0)+seconds
   elif cpu in affinity and tid!=0: other_cpu[cpu]=other_cpu.get(cpu,0)+seconds
  for tid,since in ready.items():
   if tid in worker_tids: ready_time[tid]=ready_time.get(tid,0)+overlap(since,end,windows)
 window_seconds=sum(b-a for a,b in windows)/1e9
 covered=(events and point(events[0])<=min(a for a,b in windows)
          and point(events[-1])>=max(b for a,b in windows))
 complete=metadata.get('events_lost')==0 and covered and continuity_breaks==0
 return {'status':'OBSERVED' if complete else 'INCOMPLETE',
  'qualification':'NOT_EVALUATED','events_lost':metadata.get('events_lost'),
  'continuity_breaks':continuity_breaks,'bounds_covered':bool(covered),
  'window_seconds':window_seconds,'worker_pid':worker_pid,'worker_tids':sorted(worker_tids),
  'worker_running_seconds':sum(running.values()),'worker_running_by_tid':running,
  'worker_ready_wait_seconds':sum(ready_time.values()),'worker_ready_by_tid':ready_time,
  'other_nonidle_running_on_affinity_seconds':sum(other_cpu.values()),
  'other_nonidle_by_cpu':other_cpu,'context_switch_count':switches,
  'ready_event_count':ready_count,'worker_io_events':disk,
  'dynamic_cpu_frequency':'NOT_OBSERVED',
  'interpretation':'Aggregate thread time is not additive wall latency; original run has no ETW trace'}

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('root',type=Path)
 args=parser.parse_args();root=args.root
 report=json.loads(next(root.rglob('diagnostic.json')).read_text())
 sessions=json.loads(next(root.rglob('sessions.json')).read_text())
 workers=[json.loads(line) for f in root.rglob('worker-*.jsonl') for line in f.read_text().splitlines()]
 rows=[]
 for sample in report['samples']:
  if sample['id']!='en04': continue
  request=sample['prefill']['request'];pid=sample['prefill']['pid']
  spans=[r for r in workers if r['phase']=='native.prefill_decode' and r['request']==request
         and r['start']['pid']==pid]
  assert spans
  windows=[(r['start']['performance_ns'],r['end']['performance_ns']) for r in spans]
  session=next(s for s in sessions if s['run']==sample['run'])
  assert session['request']==request
  file=next(root.rglob(session['trace']+'.events.jsonl'))
  metadata=json.loads(next(root.rglob(session['trace']+'.metadata.json')).read_text())
  events=[json.loads(line) for line in file.read_text().splitlines()]
  affinity=sample['load']['limits']['cpu_topology']['selected_logical_cpus']
  row=reduce_events(events,metadata,session,pid,windows,affinity)
  row.update(case=sample['id'],run=sample['run'],request=request,cold=sample['cold'],
    first_wall_seconds=sample['first_wall_seconds'],
    native_prefill_cpu_seconds=sample['phases']['prefill_cpu_seconds'],
    original_spike_cause='NOT_DEMONSTRATED')
  rows.append(row)
 output=root.parent/'scheduler-analysis.json'
 output.write_text(json.dumps({'purpose':'DIAGNOSTIC_ONLY','rows':rows},indent=2)+'\n')
 print(json.dumps(rows,indent=2))
if __name__=='__main__': main()

