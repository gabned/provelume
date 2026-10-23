"""Two artificial observer controls; never ordinary tests or qualification.

The controller imports only the standard library. Each contained worker imports
the shared diagnostic plugin (and therefore pytest), without pytest.main, test
collection or application imports. Only the artificial stdout-holder uses unref.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

KINDS = ("nondetached35", "detached35")
WORK_SECONDS = 90
CLEANUP_SECONDS = 20
RECORD_CAP = 65536
ROOT = Path(__file__).resolve().parents[1]

CONTROL_RECORD_JS = r"""
const __control_cap=65536,__control_persistence_errors=[];
function __control_issue(error){return {name:error?.name,message:String(error?.message),
 code:error?.code,syscall:error?.syscall};}
function __control_publish(path,value){
 const raw=Buffer.from(JSON.stringify(value)+'\n');
 if(raw.length>__control_cap)throw new Error('Admission record cap');
 const temp=path+'.partial-'+process.pid;
 let fd=__control_fs.openSync(temp,'wx');
 try{__control_fs.writeFileSync(fd,raw);__control_fs.fsyncSync(fd);}
 finally{__control_fs.closeSync(fd);}
 __control_fs.linkSync(temp,path);
 try{__control_fs.unlinkSync(temp);}catch(error){
  __control_persistence_errors.push(__control_issue(error));
  try{__control_fs.writeSync(2,JSON.stringify({stage:'PUBLISHED_TEMP_CLEANUP_ERROR',
   path,temp,error:__control_issue(error)})+'\n');}catch{}
 }
}
function __control_read(path){
 const size=__control_fs.statSync(path).size;
 if(size<=0||size>__control_cap)throw new Error('Admission record cap');
 const raw=__control_fs.readFileSync(path);
 if(raw.length!==size||raw.length>__control_cap)throw new Error('Admission record changed');
 return JSON.parse(raw.toString('utf8'));
}
function __control_identity(schema,parent_pid,holder_pid){return {schema,
 control_kind:__control_config.control_kind,run_id:__control_config.run_id,
 run_attempt:__control_config.run_attempt,parent_pid,holder_pid,
 utc:new Date().toISOString(),hrtime_ns:String(process.hrtime.bigint())};}
"""

HOLDER_TEMPLATE = r"""
let __holder_events_fd=null,__holder_events=0,__holder_errors=0;
function __holder_event(stage,extra={}){
 try{
  if(__holder_events_fd===null||__holder_events>=64)throw new Error('Holder event cap');
  const row={stage,ordinal:__holder_events++,pid:process.pid,parent_pid:process.ppid,
   control_kind:__control_config.control_kind,utc:new Date().toISOString(),
   hrtime_ns:String(process.hrtime.bigint()),...extra};
  __control_fs.writeFileSync(__holder_events_fd,JSON.stringify(row)+'\n');
  if(__control_fs.fstatSync(__holder_events_fd).size>65536)throw new Error('Holder byte cap');
  __control_fs.fsyncSync(__holder_events_fd);
 }catch(error){__holder_errors++;
  try{__control_fs.writeSync(2,JSON.stringify({stage:'HOLDER_RECORD_ERROR',
   error:__control_issue(error)})+'\n');}catch{}
 }
}
process.on('uncaughtExceptionMonitor',error=>__holder_event('ERROR',
 {error:__control_issue(error)}));
process.on('disconnect',()=>__holder_event('IPC_DISCONNECT'));
process.on('beforeExit',code=>__holder_event('BEFORE_EXIT',{code}));
process.on('exit',code=>{
 __holder_event('EXIT',{code,holder_errors:__holder_errors});
 try{if(__holder_events_fd!==null)__control_fs.closeSync(__holder_events_fd);}catch{}
});
__holder_events_fd=__control_fs.openSync(__control_config.holder_events_path,'wx');
__control_publish(__control_config.holder_entry_path,
 __control_identity('reader415-holder-entry/v3',process.ppid,process.pid));
__holder_event('MODULE_ENTER');
const __holder_timer=setTimeout(()=>{
 __holder_event('TIMER_EXPIRED');
 const end='HOLDER_END '+__control_config.control_kind+'\n';
 if(__control_fs.writeSync(1,end)!==Buffer.byteLength(end))throw new Error('Partial HOLDER_END');
 __holder_event('END_WRITTEN');
},35000);
__holder_event('TIMER_INSTALLED',{duration_ms:35000});
const __holder_open='HOLDER_OPEN '+__control_config.control_kind+'\n';
if(__control_fs.writeSync(1,__holder_open)!==Buffer.byteLength(__holder_open)){
 throw new Error('Partial HOLDER_OPEN');}
__holder_event('OPEN_WRITTEN');
const __holder_ready={...__control_identity('reader415-holder-ready/v3',
 process.ppid,process.pid),timer_installed:true,timer_duration_ms:35000,
 stdout_open_write_returned:true};
__control_publish(__control_config.holder_ready_path,__holder_ready);
__holder_event('READY_PERSISTED');
if(__control_persistence_errors.length||__holder_errors)throw new Error('Holder persistence error');
if(typeof process.send!=='function'||!process.connected)throw new Error('Holder IPC unavailable');
process.send({...__holder_ready,message_type:'READY'},error=>{
 if(error){__holder_event('ERROR',{control_stage:'READY_IPC',error:__control_issue(error)});
  process.exitCode=1;}else{__holder_event('READY_IPC_SENT');}
});
"""

PARENT_TEMPLATE = r"""
let __control_child=null,__control_timer=null,__control_poll=null;
let __control_ready=null,__control_releasing=false,__control_failed=false,__control_polls=0;
const __control_deadline=process.hrtime.bigint()+5000000000n;
function __control_fail(stage,error){
 if(__control_failed)return;
 __control_failed=true;process.exitCode=1;
 __rd_event('CONTROL_FIXTURE_ERROR',{control_stage:stage,error:__control_issue(error)});
 clearTimeout(__control_timer);clearInterval(__control_poll);
 try{if(__control_child?.connected)__control_child.disconnect();}catch(e){
  __rd_event('CONTROL_FIXTURE_ERROR',{control_stage:'failure_disconnect',error:__control_issue(e)});}
 if(__control_child)__control_child.unref();
}
function __control_match(value){return value&&value.control_kind===__control_config.control_kind&&
 value.run_id===__control_config.run_id&&value.run_attempt===__control_config.run_attempt&&
 value.parent_pid===process.pid&&Number.isSafeInteger(value.holder_pid)&&
 value.holder_pid>0&&value.holder_pid===__control_child.pid;}
function __control_proof(value,pid){return value&&value.requested_pid===pid&&
 value.pid_from_handle===pid&&typeof value.creation_filetime_100ns_decimal==='string'&&
 /^[1-9][0-9]*$/.test(value.creation_filetime_100ns_decimal)&&value.exit_filetime_100ns===0&&
 value.is_process_in_exact_outer_job===true&&value.wait_for_single_object_zero===258&&
 value.live_before_release===true&&Array.isArray(value.errors)&&value.errors.length===0;}
__control_timer=setTimeout(()=>__control_fail('READY_RELEASE_DEADLINE',
 new Error('Five-second READY and RELEASE deadline expired')),5000);
let __control_stderr=null;
try{
 __control_stderr=__control_fs.openSync(__control_config.holder_stderr_path,'wx');
 __control_child=__control_spawn(process.execPath,[__control_config.holder_script_path],{
  detached:__control_config.detached,
  stdio:['ignore',process.stdout,__control_stderr,'ipc']});
 __rd_event('CONTROL_HOLDER_SPAWNED',{holder_pid:__control_child.pid,
  detached:__control_config.detached});
 __control_child.on('error',error=>__control_fail('SPAWN_ERROR',error));
 __control_child.on('exit',(code,signal)=>{
  __rd_event('CONTROL_HOLDER_EXIT',{code,signal});
  if(!__control_releasing)__control_fail('HOLDER_EXIT_BEFORE_RELEASE',
   new Error('Holder exited before controller RELEASE'));
 });
 __control_child.on('close',(code,signal)=>__rd_event('CONTROL_HOLDER_CLOSE',{code,signal}));
 __control_child.on('disconnect',()=>{
  __rd_event('CONTROL_HOLDER_DISCONNECT');
  if(__control_releasing&&!__control_failed){
   __control_child.unref();__rd_event('CONTROL_PARENT_BODY_FINISHED');
  }else if(!__control_failed){__control_fail('EARLY_IPC_DISCONNECT',
   new Error('IPC disconnected before controller RELEASE'));}
 });
 __control_child.on('message',value=>{
  if(__control_failed)return;
  if(__control_ready||value?.schema!=='reader415-holder-ready/v3'||
   value.message_type!=='READY'||!__control_match(value)||
   value.timer_installed!==true||value.timer_duration_ms!==35000||
   value.stdout_open_write_returned!==true||process.hrtime.bigint()>__control_deadline){
   __control_fail('INVALID_OR_LATE_READY',new Error('READY identity/truth/deadline mismatch'));
   return;
  }
  __control_ready=value;__rd_event('CONTROL_HOLDER_READY_RECEIVED',{ready:value});
 });
 __control_poll=setInterval(()=>{
  if(__control_failed||__control_releasing)return;
  __control_polls++;
  if(__control_polls>100||process.hrtime.bigint()>__control_deadline){
   __control_fail('READY_RELEASE_DEADLINE',new Error('Five-second admission deadline'));
   return;
  }
  if(!__control_ready||!__control_fs.existsSync(__control_config.release_path))return;
  try{
   const value=__control_read(__control_config.release_path);
   const census=value.census_before_release;
   if(value.schema!=='reader415-controller-release/v3'||!__control_match(value)||
    !__control_proof(value.parent_identity,process.pid)||
    !__control_proof(value.holder_identity,__control_child.pid)||
    !Array.isArray(census?.identities)||
    ![value.parent_identity,value.holder_identity].every(proof=>census.identities.some(
     row=>row.pid===proof.pid_from_handle&&
      row.creation_filetime_100ns_decimal===proof.creation_filetime_100ns_decimal&&
      row.exit_filetime_100ns===0))||process.hrtime.bigint()>__control_deadline){
    throw new Error('Controller RELEASE identity/live/census/deadline mismatch');
   }
   __control_releasing=true;
   __rd_event('CONTROL_CONTROLLER_RELEASE_ACCEPTED',{holder_pid:__control_child.pid});
   clearTimeout(__control_timer);clearInterval(__control_poll);
   if(!__control_child.connected)throw new Error('IPC not connected at RELEASE');
   __control_child.disconnect();
  }catch(error){__control_fail('RELEASE_ERROR',error);}
 },50);
}catch(error){__control_fail('SPAWN_SETUP',error);}
finally{
 if(__control_stderr!==null){try{__control_fs.closeSync(__control_stderr);}catch(error){
  __control_fail('CLOSE_HOLDER_STDERR',error);}}
}
"""


def control_sources(config, node_preamble):
    """Data-only source construction; no imports, filesystem, Win32 or runtime work."""
    prefix = (
        "import * as __control_fs from 'node:fs';\nconst __control_config="
        + json.dumps(config, ensure_ascii=True) + ";\n" + CONTROL_RECORD_JS
    )
    parent = (
        "import {spawn as __control_spawn} from 'node:child_process';\n"
        "import {openSync as __rd_open,writeSync as __rd_write,"
        "closeSync as __rd_close} from 'node:fs';\n"
        + prefix + node_preamble.replace("__MARKER_PATH__", json.dumps(config["node_marker_path"]))
        + PARENT_TEMPLATE
    )
    return {"parent": parent, "holder": prefix + HOLDER_TEMPLATE}


def issue(exc):
    return {
        "type": type(exc).__name__, "message": str(exc)[:2048],
        "winerror": getattr(exc, "winerror", None), "errno": getattr(exc, "errno", None),
    }


def retain(path, data):
    with path.open("xb") as stream:
        stream.write(data)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def document(path, value):
    return retain(path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())


def persisted_file(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Required retained evidence is not a regular file: " + str(path))
    data = path.read_bytes()
    if not data:
        raise RuntimeError("Required retained evidence is empty: " + str(path))
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_record(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Admission record is not a regular file: " + str(path))
    with path.open("rb") as stream:
        raw = stream.read(RECORD_CAP + 1)
    if not raw or len(raw) > RECORD_CAP:
        raise RuntimeError("Admission record exceeds its nonempty 64 KiB cap")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise TypeError("Admission record must be an object")
    return value, {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def atomic_record(path, value):
    """Publish a complete record without replacing anything; retain failures."""
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if len(raw) > RECORD_CAP:
        raise RuntimeError("Admission record exceeds 64 KiB")
    temporary = path.with_name(path.name + ".partial-" + str(os.getpid()))
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, path)
    result = {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        temporary.unlink()
    except BaseException as exc:
        # Publication already happened: never remove or replace that valid final.
        result["temporary_cleanup_error"] = issue(exc)
    return result


def record_identity(value, kind):
    if value.get("control_kind") != kind:
        raise RuntimeError("Wrong control kind in admission record")
    for field, variable in (("run_id", "GITHUB_RUN_ID"), ("run_attempt", "GITHUB_RUN_ATTEMPT")):
        expected = os.environ[variable]
        if not expected.isdecimal() or int(expected) <= 0 or value.get(field) != expected:
            raise RuntimeError("Wrong actual run identity: " + field)
    pids = [value.get(field) for field in ("parent_pid", "holder_pid")]
    if any(type(pid) is not int or pid <= 0 for pid in pids) or pids[0] == pids[1]:
        raise RuntimeError("Positive distinct parent and holder PIDs are required")
    return pids


def ready_records(output, kind):
    entry, entry_ref = read_record(output / "observer" / "holder-entry.json")
    ready, ready_ref = read_record(output / "observer" / "holder-ready.json")
    if entry.get("schema") != "reader415-holder-entry/v3":
        raise RuntimeError("Wrong holder entry schema")
    if ready.get("schema") != "reader415-holder-ready/v3":
        raise RuntimeError("Wrong holder READY schema")
    pids = record_identity(ready, kind)
    if record_identity(entry, kind) != pids:
        raise RuntimeError("Entry and READY process identities disagree")
    for value in (entry, ready):
        if not isinstance(value.get("utc"), str) or not value["utc"]:
            raise RuntimeError("Original UTC observation is missing")
        hrtime = value.get("hrtime_ns")
        if not isinstance(hrtime, str) or not hrtime.isdecimal() or int(hrtime) <= 0:
            raise RuntimeError("Original Node hrtime observation is missing")
    if not (ready.get("timer_installed") is True and ready.get("timer_duration_ms") == 35000
            and ready.get("stdout_open_write_returned") is True):
        raise RuntimeError("Holder READY does not prove the selected fixture")
    return ready, {"entry": entry_ref, "ready": ready_ref}


class Job:
    """One owned process tree. No breakaway, priority or resource overrides."""

    def __init__(self):
        kernel = self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        pointer = ctypes.c_size_t

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", pointer),
                ("MaximumWorkingSetSize", pointer),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", pointer),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
            )]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", pointer), ("JobMemoryLimit", pointer),
                ("PeakProcessMemoryUsed", pointer), ("PeakJobMemoryUsed", pointer),
            ]

        class ProcessList(ctypes.Structure):
            _fields_ = [
                ("NumberOfAssignedProcesses", wintypes.DWORD),
                ("NumberOfProcessIdsInList", wintypes.DWORD),
                ("ProcessIdList", pointer * 64),
            ]

        self.ExtendedLimits, self.ProcessList = ExtendedLimits, ProcessList
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        kernel.SetHandleInformation.restype = wintypes.BOOL
        kernel.GetHandleInformation.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetHandleInformation.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.IsProcessInJob.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL),
        ]
        kernel.IsProcessInJob.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.GetProcessId.argtypes = [wintypes.HANDLE]
        kernel.GetProcessId.restype = wintypes.DWORD
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.handle, self.process_handles = None, {}
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.check(kernel.SetHandleInformation(self.handle, 1, 0))
            flags = wintypes.DWORD()
            self.check(kernel.GetHandleInformation(self.handle, ctypes.byref(flags)))
            if flags.value & 1:
                raise RuntimeError("Job handle unexpectedly inheritable")
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE only.
            self.check(kernel.SetInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            ))
            observed = ExtendedLimits()
            self.check(kernel.QueryInformationJobObject(
                self.handle, 9, ctypes.byref(observed), ctypes.sizeof(observed), None
            ))
            if observed.BasicLimitInformation.LimitFlags != 0x2000:
                raise RuntimeError("Unexpected Job limit flags")
            self.readback = {"handle_inheritable": False, "limit_flags": 0x2000}
        except BaseException:
            kernel.CloseHandle(self.handle)
            self.handle = None
            raise

    @staticmethod
    def check(value):
        if not value:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, worker):
        self.check(self.kernel.AssignProcessToJobObject(
            self.handle, wintypes.HANDLE(int(worker._handle))
        ))
        member = wintypes.BOOL()
        self.check(self.kernel.IsProcessInJob(
            wintypes.HANDLE(int(worker._handle)), self.handle, ctypes.byref(member)
        ))
        if not member.value:
            raise RuntimeError("Worker is not a member of this exact Job")
        return {"worker_pid": worker.pid, "is_process_in_this_exact_job": True}

    def times(self, handle):
        values = [wintypes.FILETIME() for _ in range(4)]
        self.check(self.kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)))
        return dict(zip(
            ("creation_filetime_100ns", "exit_filetime_100ns", "kernel_100ns", "user_100ns"),
            [(value.dwHighDateTime << 32) | value.dwLowDateTime for value in values], strict=True,
        ))

    def census(self):
        started, cpu = time.perf_counter_ns(), time.thread_time_ns()
        rows = self.ProcessList()
        self.check(self.kernel.QueryInformationJobObject(
            self.handle, 3, ctypes.byref(rows), ctypes.sizeof(rows), None
        ))
        if rows.NumberOfProcessIdsInList > 64 or rows.NumberOfAssignedProcesses > 64:
            raise RuntimeError("Job process census exceeded 64 processes")
        pids = list(rows.ProcessIdList[:rows.NumberOfProcessIdsInList])
        identities = []
        for pid in pids:
            row = {"pid": pid}
            try:
                if pid not in self.process_handles:
                    handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
                    self.check(handle)
                    self.process_handles[pid] = handle
                row.update(self.times(self.process_handles[pid]))
                row["creation_filetime_100ns_decimal"] = str(row["creation_filetime_100ns"])
                row["identity_scope"] = (
                    "RETAINED_FIRST_SEEN_HANDLE_NOT_CONTEMPORARY_PID_BIRTH_PROOF"
                    if row["exit_filetime_100ns"] else "RETAINED_FIRST_SEEN_LIVE_HANDLE"
                )
            except BaseException as exc:
                row["identity_error"] = issue(exc)
            identities.append(row)
        return {"perf_counter_ns": started, "assigned_processes": rows.NumberOfAssignedProcesses,
                "listed_processes": rows.NumberOfProcessIdsInList, "identities": identities,
                "observer_perf_elapsed_ns": time.perf_counter_ns() - started,
                "observer_thread_cpu_ns": time.thread_time_ns() - cpu}

    def identity(self, pid, *, before_release=True):
        row = {"requested_pid": pid, "errors": [], "perf_counter_ns": time.perf_counter_ns()}
        if pid not in self.process_handles:
            handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
            self.check(handle)
            self.process_handles[pid] = handle
        handle = self.process_handles[pid]
        try:
            row["pid_from_handle"] = self.kernel.GetProcessId(handle)
            self.check(row["pid_from_handle"])
        except BaseException as exc:
            row["errors"].append({"stage": "GetProcessId", **issue(exc)})
        try:
            row.update(self.times(handle))
            row["creation_filetime_100ns_decimal"] = str(row["creation_filetime_100ns"])
        except BaseException as exc:
            row["errors"].append({"stage": "GetProcessTimes", **issue(exc)})
        try:
            member = wintypes.BOOL()
            self.check(self.kernel.IsProcessInJob(handle, self.handle, ctypes.byref(member)))
            row["is_process_in_exact_outer_job"] = bool(member.value)
        except BaseException as exc:
            row["errors"].append({"stage": "IsProcessInJob", **issue(exc)})
        try:
            value = self.kernel.WaitForSingleObject(handle, 0)
            if value == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            row["wait_for_single_object_zero"] = value
        except BaseException as exc:
            row["errors"].append({"stage": "WaitForSingleObject", **issue(exc)})
        live = (
            not row["errors"] and row.get("pid_from_handle") == pid
            and type(row.get("creation_filetime_100ns")) is int
            and row["creation_filetime_100ns"] > 0 and row.get("exit_filetime_100ns") == 0
            and row.get("is_process_in_exact_outer_job") is True
            and row.get("wait_for_single_object_zero") == 258
        )
        row["query_phase"] = "BEFORE_RELEASE" if before_release else "AFTER_WORK_BEFORE_CLEANUP"
        row["live_before_release" if before_release else "live_at_query"] = live
        return row

    def terminate(self):
        self.check(self.kernel.TerminateJobObject(self.handle, 124))

    def close(self):
        failures = []
        for pid, handle in self.process_handles.items():
            try:
                self.check(self.kernel.CloseHandle(handle))
            except BaseException as exc:
                failures.append({"pid": pid, **issue(exc)})
        if self.handle:
            try:
                self.check(self.kernel.CloseHandle(self.handle))
                self.handle = None
            except BaseException as exc:
                failures.append({"job": True, **issue(exc)})
        return failures


def classify(kind, state):
    """Raw observation category, separate from artificial fixture truth."""
    if kind == "nondetached35":
        return (
            "NODE_RETURNED_CODE_ZERO" if state.get("result", {}).get("returncode") == 0
            else "UNKNOWN_RETURN_OR_TIMEOUT_PATTERN"
        )
    value = state.get("timeout_before_kill")
    if not isinstance(value, dict):
        return "UNKNOWN_NO_PREKILL_SNAPSHOT"
    process = value.get("process_times", {})
    born = process.get("creation_filetime_100ns")
    exited = process.get("exit_filetime_100ns")
    if not process.get("available") or type(born) is not int or born <= 0:
        return "UNKNOWN_POSITIVE_PROCESS_BIRTH_UNAVAILABLE"
    if type(exited) is not int or exited <= 0 or value.get("poll_before_returncode") != 0:
        return "UNKNOWN_PARENT_EXIT_ZERO_UNAVAILABLE_BEFORE_KILL"
    current = [
        row for row in value.get("reader_threads", [])
        if row.get("stream") == "stdout" and row.get("alive")
        and row.get("alive_after_native_query") and row.get("times", {}).get("available")
        and type(row.get("native_id")) is int and row["native_id"] > 0
        and type(row["times"].get("creation_filetime_100ns")) is int
        and row["times"]["creation_filetime_100ns"] > 0
    ]
    for reader in current:
        identity = (reader.get("native_id"), reader["times"].get("creation_filetime_100ns"))
        for sample in state.get("samples", []):
            if (
                sample.get("poll_before_returncode") != 0
                or sample.get("process_times", {}).get("creation_filetime_100ns") != born
                or sample["perf_counter_ns"] >= value["perf_counter_ns"]
            ):
                continue
            for old in sample.get("reader_threads", []):
                if (
                    old.get("stream") == "stdout" and old.get("alive")
                    and old.get("alive_after_native_query")
                    and old.get("times", {}).get("available")
                    and type(old.get("native_id")) is int and old["native_id"] > 0
                    and type(old["times"].get("creation_filetime_100ns")) is int
                    and old["times"]["creation_filetime_100ns"] > 0
                    and (old.get("native_id"), old["times"].get("creation_filetime_100ns"))
                    == identity
                ):
                    return "EXITED_NODE_STDOUT_READER_ALIVE_STABLE_BIRTH"
    return "UNKNOWN_REQUIRED_PATTERN_NOT_OBSERVED"


def holder_lifecycle(path):
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("Holder lifecycle record is missing or nonregular")
    with path.open("rb") as stream:
        raw = stream.read(RECORD_CAP + 1)
    if not raw or len(raw) > RECORD_CAP:
        raise RuntimeError("Holder lifecycle byte cap exceeded")
    rows = [json.loads(line) for line in raw.splitlines()]
    if len(rows) > 64 or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError("Holder lifecycle row cap/type mismatch")
    return rows


def worker(kind, output):
    # Only this contained worker imports pytest indirectly via the shared observer.
    import msvcrt

    import reader415_node_boundary_diagnostic as observer

    if sys.stdin.readline() != "GO\n":
        return 2
    sys.stdin.close()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel.SetStdHandle.restype = wintypes.BOOL
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    with open(os.devnull, "rb") as null_input:
        selected = wintypes.HANDLE(msvcrt.get_osfhandle(null_input.fileno()))
        Job.check(kernel.SetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF), selected))
        if kernel.GetStdHandle(wintypes.DWORD(-10 & 0xFFFFFFFF)) != selected.value:
            raise RuntimeError("Control worker stdin did not rebind to NUL")
        observer.begin_control(output, kind)
        node = shutil.which("node")
        if node is None:
            raise RuntimeError("Node runtime unavailable")
        config = {
            "control_kind": kind, "run_id": os.environ["GITHUB_RUN_ID"],
            "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"], "detached": kind == "detached35",
            "holder_entry_path": str(observer.OUT / "holder-entry.json"),
            "holder_ready_path": str(observer.OUT / "holder-ready.json"),
            "holder_events_path": str(observer.OUT / "holder-events.jsonl"),
            "holder_stderr_path": str(observer.OUT / "holder.stderr"),
            "holder_script_path": str(observer.OUT / "holder.mjs"),
            "node_marker_path": str(observer.OUT / "node-markers.jsonl"),
            "release_path": str(output / "controller-release.json"),
        }
        sources = control_sources(config, observer.NODE_PREAMBLE)
        holder_source = retain(observer.OUT / "holder.mjs", sources["holder"].encode())
        script = observer.OUT / "control.mjs"
        source = retain(script, sources["parent"].encode())
        outcome = {
            "kind": kind, "source": source, "holder_source": holder_source,
            "control_only_stdin": "NUL_AFTER_GO", "original_timeout_seconds": 30,
            "validation_details": [],
        }
        captured_output = None
        try:
            result = observer.observed_run(
                [node, str(script)], cwd=observer.ROOT,
                capture_output=True, text=True, timeout=30,
            )
            captured_output = result.stdout
            outcome.update(actual="RETURNED", returncode=result.returncode,
                           actual_timeout_observed=False)
        except BaseException as exc:
            captured_output = getattr(exc, "stdout", None)
            outcome.update(actual="RAISED", exception=issue(exc),
                           actual_timeout_observed=isinstance(exc, subprocess.TimeoutExpired))
        finally:
            try:
                observer.finish_control(outcome, classify=lambda state: classify(kind, state))
            except BaseException as exc:
                outcome["finalization_error"] = issue(exc)
            outcome.setdefault("observed_category", "UNKNOWN_FINALIZATION_FAILED")
            outcome["raw_observer_status"] = observer.STATE.get("status")
            outcome["raw_observer_error_count"] = observer.STATE.get("error_count")
            outcome["clock_information"] = observer.STATE.get("clock_information")
            outcome["python_version_info"] = list(sys.version_info[:3])
            outcome["python_implementation"] = sys.implementation.name
            outcome["platform"] = sys.platform
            prekill = observer.STATE.get("timeout_before_kill")
            if isinstance(prekill, dict):
                outcome["original_pre_kill_window"] = {
                    name: prekill.get(name) for name in (
                        "perf_counter_ns", "observer_perf_counter_ns",
                        "poll_before_perf_counter_ns", "poll_after_perf_counter_ns", "stage",
                    )
                }
            failures = [row for row in observer.STATE.get("errors", [])
                        if row.get("stage") in {"prekill_checkpoint", "persist_observations"}]
            if failures:
                outcome["finalization_error"] = {
                    "type": "RequiredObserverPersistenceFailed", "errors": failures
                }
            try:
                outcome["durable_observations"] = persisted_file(observer.OUT / "observations.json")
                checkpoint = observer.OUT / "timeout-before-kill.json"
                if checkpoint.exists() or (
                    kind == "detached35" and outcome.get("actual_timeout_observed")
                ):
                    outcome["durable_pre_kill_checkpoint"] = persisted_file(checkpoint)
            except BaseException as exc:
                outcome["finalization_error"] = issue(exc)
        markers = observer.STATE.get("node_markers", [])
        stages = [row.get("stage") for row in markers]
        exits = [row.get("code") for row in markers if row.get("stage") == "EXIT"]
        truth = {
            "parent_exit_marker_zero": exits == [0],
            "ready_message_received": stages.count("CONTROL_HOLDER_READY_RECEIVED") == 1,
            "controller_release_accepted": stages.count("CONTROL_CONTROLLER_RELEASE_ACCEPTED") == 1,
            "parent_body_finished": stages.count("CONTROL_PARENT_BODY_FINISHED") == 1,
            "no_parent_error_markers": not any(stage in {
                "CONTROL_FIXTURE_ERROR", "UNCAUGHT_EXCEPTION_MONITOR"
            } for stage in stages),
        }
        try:
            ready, refs = ready_records(output, kind)
            release, release_ref = read_record(output / "controller-release.json")
            if release.get("schema") != "reader415-controller-release/v3":
                raise RuntimeError("Wrong controller RELEASE schema")
            if record_identity(release, kind) != record_identity(ready, kind):
                raise RuntimeError("READY and RELEASE identities differ")
            for field, pid in (("parent_identity", ready["parent_pid"]),
                               ("holder_identity", ready["holder_pid"])):
                proof = release[field]
                if not (proof["pid_from_handle"] == pid and proof["live_before_release"] is True
                        and proof["is_process_in_exact_outer_job"] is True):
                    raise RuntimeError("Controller RELEASE proof is not live/member bound")
            outcome["admission_files"] = {**refs, "release": release_ref}
            truth["ready_and_release_identity"] = True
            lifecycle = holder_lifecycle(observer.OUT / "holder-events.jsonl")
            outcome["holder_lifecycle"] = lifecycle
            truth["holder_lifecycle_identity"] = all(
                row.get("pid") == ready["holder_pid"]
                and row.get("parent_pid") == ready["parent_pid"]
                and row.get("control_kind") == kind for row in lifecycle
            )
            truth["no_holder_errors"] = not any(
                row.get("stage") == "ERROR" or row.get("holder_errors", 0) for row in lifecycle
            )
            stderr_path = observer.OUT / "holder.stderr"
            raw_stderr = stderr_path.read_bytes()
            outcome["holder_stderr"] = {"path": str(stderr_path), "bytes": len(raw_stderr),
                "sha256": hashlib.sha256(raw_stderr).hexdigest()}
            truth["holder_stderr_empty"] = not raw_stderr
        except BaseException as exc:
            truth["ready_and_release_identity"] = False
            outcome["validation_details"].append({"stage": "admission_and_holder", **issue(exc)})
        expected_open = "HOLDER_OPEN " + kind + "\n"
        truth["holder_open_captured"] = (
            expected_open in captured_output if isinstance(captured_output, str)
            else expected_open.encode() in captured_output
            if isinstance(captured_output, bytes) else False
        )
        if kind == "nondetached35":
            truth["selected_returned_outcome"] = (
                outcome.get("actual") == "RETURNED" and outcome.get("returncode") == 0
                and not outcome.get("actual_timeout_observed")
            )
            expected_category = "NODE_RETURNED_CODE_ZERO"
        else:
            truth["selected_timeout_outcome"] = (
                outcome.get("actual_timeout_observed") is True
                and bool(outcome.get("durable_pre_kill_checkpoint"))
            )
            lifecycle_stages = {row.get("stage") for row in outcome.get("holder_lifecycle", [])}
            truth["holder_timer_and_end_recorded"] = {
                "TIMER_EXPIRED", "END_WRITTEN"
            }.issubset(lifecycle_stages)
            expected_category = "EXITED_NODE_STDOUT_READER_ALIVE_STABLE_BIRTH"
        outcome["control_fixture_truth_checks"] = truth
        outcome["control_validation_errors"] = [name for name, valid in truth.items() if not valid]
        matched = (
            outcome["observed_category"] == expected_category
            and not outcome.get("finalization_error") and not outcome["control_validation_errors"]
        )
        outcome["category_pattern_observed"] = bool(matched)
        outcome["pattern_evaluation"] = (
            "CATEGORY_PATTERN_OBSERVED_WITH_RAW_OBSERVER_STATUS_RETAINED"
            if matched else "CATEGORY_PATTERN_NOT_OBSERVED_OR_UNKNOWN"
        )
        document(observer.OUT / "worker-result.json", outcome)
        return 0 if matched else 1


def admit_holder(job, output, kind, record):
    ready, refs = ready_records(output, kind)
    parent_pid, holder_pid = record_identity(ready, kind)
    before = {"parent": job.identity(parent_pid), "holder": job.identity(holder_pid)}
    record["admission_identity_before_census"] = before
    census = job.census()
    record["admission_census"] = census
    parent, holder = job.identity(parent_pid), job.identity(holder_pid)
    record["admission_identity_after_census"] = {"parent": parent, "holder": holder}
    for proof in (parent, holder):
        if not proof["live_before_release"] or not any(
            row.get("pid") == proof["pid_from_handle"]
            and row.get("creation_filetime_100ns") == proof["creation_filetime_100ns"]
            and row.get("exit_filetime_100ns") == 0 for row in census["identities"]
        ):
            raise RuntimeError("Both actual live Job members must occur in the pre-release census")
    release = {
        "schema": "reader415-controller-release/v3", "control_kind": kind,
        "run_id": os.environ["GITHUB_RUN_ID"], "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "parent_pid": parent_pid, "holder_pid": holder_pid,
        "parent_identity": parent, "holder_identity": holder,
        "census_before_release": census, "perf_counter_ns": time.perf_counter_ns(),
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    record["holder_admission_records"] = refs
    record["controller_release"] = release
    ref = atomic_record(output / "controller-release.json", release)
    record["controller_release_file"] = ref
    record["controller_release_published"] = True
    if ref.get("temporary_cleanup_error"):
        record["errors"].append({"stage": "release_temp_cleanup", **ref["temporary_cleanup_error"]})


def detached_pre_kill_witness(record, worker_result):
    """Project already retained system-wide Windows QPC observations only."""
    result = {
        "status": "UNKNOWN", "comparison_basis": (
            "CPYTHON_WINDOWS_3_12_SYSTEM_WIDE_QUERY_PERFORMANCE_COUNTER_SAME_HOST; "
            "NO_NODE_HRTIME_OR_FILETIME_EPOCH_COMPARISON"
        ),
    }
    own = record.get("clock_information", {}).get("perf_counter", {})
    other = (worker_result.get("clock_information") or {}).get("perf_counter", {})
    result["controller_clock"] = own
    result["worker_clock"] = other
    supported = (
        sys.platform == "win32" and sys.implementation.name == "cpython"
        and sys.version_info[:2] == (3, 12)
        and worker_result.get("platform") == "win32"
        and worker_result.get("python_implementation") == "cpython"
        and worker_result.get("python_version_info", [])[:2] == [3, 12]
        and own.get("implementation") == other.get("implementation")
        and "QueryPerformanceCounter" in own.get("implementation", "")
        and own.get("monotonic") is True and other.get("monotonic") is True
        and own.get("adjustable") is False and other.get("adjustable") is False
    )
    if not supported:
        result["reason"] = "SAME_HOST_WINDOWS_CPYTHON_3_12_QPC_SUPPORT_NOT_PROVEN"
        return result
    window = worker_result.get("original_pre_kill_window") or {}
    result["original_pre_kill_window"] = window
    fields = [window.get(name) for name in (
        "perf_counter_ns", "observer_perf_counter_ns",
        "poll_before_perf_counter_ns", "poll_after_perf_counter_ns",
    )]
    if not all(type(value) is int and value > 0 for value in fields):
        result["reason"] = "ORIGINAL_PREKILL_WINDOW_RAW_CLOCKS_UNAVAILABLE"
        return result
    start, elapsed, poll_before, poll_after = fields
    end = start + elapsed
    if not start <= poll_before <= poll_after <= end:
        result["reason"] = "ORIGINAL_PREKILL_RAW_CLOCK_ORDER_INVALID"
        return result
    release = record.get("controller_release", {})
    proof = release.get("holder_identity", {})
    pid, born = release.get("holder_pid"), proof.get("creation_filetime_100ns")
    if type(pid) is not int or pid <= 0 or type(born) is not int or born <= 0:
        result["reason"] = "ADMITTED_HOLDER_IDENTITY_UNAVAILABLE"
        return result
    before, after = [], []
    for index, census in enumerate(record.get("job_census", [])):
        stamp, cost = census.get("perf_counter_ns"), census.get("observer_perf_elapsed_ns")
        if not (type(stamp) is int and stamp > 0 and type(cost) is int and cost >= 0):
            continue
        present = any(
            row.get("pid") == pid and row.get("creation_filetime_100ns") == born
            and row.get("exit_filetime_100ns") == 0 and not row.get("identity_error")
            for row in census.get("identities", [])
        )
        if not present:
            continue
        item = {"job_census_index": index, "start_perf_counter_ns": stamp,
                "end_perf_counter_ns": stamp + cost, "raw_census": census}
        if stamp + cost < start:
            before.append(item)
        if stamp > end:
            after.append(item)
    if not before or not after:
        result["reason"] = "SAME_BORN_LIVE_HOLDER_EXACT_JOB_CENSUS_BRACKET_MISSING"
        return result
    result.update(
        status="OBSERVED", holder_pid=pid, holder_creation_filetime_100ns=born,
        pre_kill_start_perf_counter_ns=start, pre_kill_end_perf_counter_ns=end,
        before=max(before, key=lambda value: value["end_perf_counter_ns"]),
        after=min(after, key=lambda value: value["start_perf_counter_ns"]),
        membership_scope="ACTUAL_QUERY_INFORMATION_OF_THIS_EXACT_OWNED_JOB_PID_LIST",
        inference="SAME_RETAINED_PROCESS_LIVE_AND_JOB_MEMBER_BEFORE_AND_AFTER_PREKILL_WINDOW",
    )
    return result


def control(kind, output):
    output.mkdir(parents=True, exist_ok=False)
    record = {
        "kind": kind, "scope": "ARTIFICIAL_OBSERVER_CONTROL_NOT_QUALIFICATION",
        "errors": [], "job_census": [], "work_seconds": WORK_SECONDS,
        "cleanup_seconds": CLEANUP_SECONDS, "go_attempted": False, "go_sent": False,
        "cleanup_census": [], "retained_process_final_times": [],
    }
    job = process = None
    started = time.perf_counter_ns()
    record["started_perf_counter_ns"] = started
    out_path, err_path = output / "worker.stdout", output / "worker.stderr"
    with out_path.open("xb") as stdout, err_path.open("xb") as stderr:
        try:
            clock = time.get_clock_info("perf_counter")
            record["clock_information"] = {"perf_counter": {
                "implementation": clock.implementation, "resolution_seconds": clock.resolution,
                "monotonic": clock.monotonic, "adjustable": clock.adjustable,
            }}
            job = Job()
            record["job_readback"] = job.readback
            argv = [
                sys.executable, "-B", str(Path(__file__).resolve()),
                "--worker", kind, "--output", str(output),
            ]
            record["argv"] = argv
            spawn_started = time.perf_counter_ns()
            record["worker_popen_before_perf_counter_ns"] = spawn_started
            deadline = spawn_started + WORK_SECONDS * 1_000_000_000
            record["worker_work_deadline_perf_counter_ns"] = deadline
            process = subprocess.Popen(
                argv, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                close_fds=True, cwd=ROOT,
            )
            record["worker_popen_after_perf_counter_ns"] = time.perf_counter_ns()
            record["worker_pid"] = process.pid
            record["membership"] = job.assign(process)
            record["job_census"].append(job.census())
            record["go_admission_perf_counter_ns"] = time.perf_counter_ns()
            if record["go_admission_perf_counter_ns"] >= deadline:
                record["outer_work_timeout"] = True
                record["status"] = "NOT_ADMITTED_BEFORE_NODE_WORKLOAD"
                raise TimeoutError("90-second control work budget exhausted before GO")
            record["go_attempted"] = True
            process.stdin.write(b"GO\n")
            process.stdin.flush()
            record["go_sent"] = True
            process.stdin.close()
            while process.poll() is None and time.perf_counter_ns() < deadline:
                if len(record["job_census"]) < 512:
                    record["job_census"].append(job.census())
                else:
                    raise RuntimeError("512 bounded Job census records exhausted")
                ready_path = output / "observer" / "holder-ready.json"
                if not record.get("controller_release_attempted") and ready_path.exists():
                    record["controller_release_attempted"] = True
                    admit_holder(job, output, kind, record)
                time.sleep(min(0.25, max(0, (deadline - time.perf_counter_ns()) / 1e9)))
            record["worker_returncode_before_cleanup"] = process.poll()
            if process.poll() is None:
                record["outer_work_timeout"] = True
                raise TimeoutError("Control outer 90-second deadline expired")
        except BaseException as exc:
            record["errors"].append({"stage": "work", **issue(exc)})
            if not record["go_attempted"]:
                record.setdefault("status", "UNSUPPORTED_BEFORE_NODE_WORKLOAD")
            elif not record["go_sent"]:
                record["admission"] = "UNKNOWN_GO_WRITE_OR_FLUSH_DID_NOT_COMPLETE"
        finally:
            # Independent operations: an API/clock/close failure cannot skip the rest.
            cleanup_started = None
            try:
                cleanup_started = time.perf_counter_ns()
            except BaseException as exc:
                record["errors"].append({"stage": "cleanup_start_clock", **issue(exc)})
            cleanup_deadline = (
                cleanup_started + CLEANUP_SECONDS * 1_000_000_000
                if cleanup_started is not None else None
            )

            def remaining():
                if cleanup_deadline is None:
                    return 0
                try:
                    return max(0, (cleanup_deadline - time.perf_counter_ns()) / 1e9)
                except BaseException as exc:
                    record["errors"].append({"stage": "cleanup_admission_clock", **issue(exc)})
                    return 0
            if process is not None and process.stdin is not None and not process.stdin.closed:
                try:
                    process.stdin.close()
                except BaseException as exc:
                    record["errors"].append({"stage": "stdin_close", **issue(exc)})
            if job is not None:
                if record.get("controller_release_published"):
                    record["released_processes_before_cleanup"] = {}
                    for name in ("parent", "holder"):
                        pid = record["controller_release"][name + "_pid"]
                        try:
                            row = job.identity(pid, before_release=False)
                        except BaseException as exc:
                            row = {"requested_pid": pid, "identity_error": issue(exc)}
                        record["released_processes_before_cleanup"][name] = row
                try:
                    record["before_cleanup_census"] = job.census()
                except BaseException as exc:
                    record["errors"].append({"stage": "before_cleanup_census", **issue(exc)})
                try:
                    job.terminate()
                    record["owned_job_termination_requested"] = True
                except BaseException as exc:
                    record["errors"].append({"stage": "terminate_owned_job", **issue(exc)})
            if process is not None and not record["go_attempted"]:
                try:
                    if process.poll() is None:
                        process.terminate()  # Still GO-blocked; no Node workload was admitted.
                except BaseException as exc:
                    record["errors"].append({"stage": "terminate_blocked_worker", **issue(exc)})
            if process is not None:
                try:
                    record["worker_returncode"] = process.wait(
                        timeout=remaining()
                    )
                except BaseException as exc:
                    record["errors"].append({"stage": "wait_worker", **issue(exc)})
            if job is not None:
                try:
                    while True:
                        census = job.census()
                        if len(record["cleanup_census"]) >= 512:
                            raise RuntimeError("512 bounded cleanup census records exhausted")
                        record["cleanup_census"].append(census)
                        record["after_cleanup_census"] = census
                        if (
                            census["listed_processes"] == 0
                            and census["assigned_processes"] == 0
                        ):
                            record["job_quiescent"] = True
                            break
                        if remaining() <= 0:
                            raise TimeoutError("Job quiescence unproven within cleanup budget")
                        time.sleep(0.05)
                except BaseException as exc:
                    record["errors"].append({"stage": "verify_job_quiescence", **issue(exc)})
                for pid, handle in job.process_handles.items():
                    row = {"pid": pid, "identity_scope": "RETAINED_FIRST_SEEN_HANDLE"}
                    try:
                        row.update(job.times(handle))
                    except BaseException as exc:
                        row["identity_error"] = issue(exc)
                        record["errors"].append({"stage": "final_handle_times", **row})
                    record["retained_process_final_times"].append(row)
                try:
                    record["errors"].extend(
                        {"stage": "close_job_handles", **entry} for entry in job.close()
                    )
                except BaseException as exc:
                    record["errors"].append({"stage": "close_job_handles", **issue(exc)})
            record["cleanup_started_perf_counter_ns"] = cleanup_started
            try:
                record["cleanup_completed_perf_counter_ns"] = time.perf_counter_ns()
            except BaseException as exc:
                record["cleanup_completed_perf_counter_ns"] = None
                record["errors"].append({"stage": "cleanup_end_clock", **issue(exc)})
    record["streams"] = []
    for path in (out_path, err_path):
        try:
            data = path.read_bytes()
            record["streams"].append({
                "path": str(path), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "representation": "EXACT_WORKER_OUTPUT_FILE_BYTES",
            })
        except BaseException as exc:
            record["errors"].append({"stage": "stream_hash", "path": str(path), **issue(exc)})
    try:
        record["completed_perf_counter_ns"] = time.perf_counter_ns()
    except BaseException as exc:
        record["completed_perf_counter_ns"] = None
        record["errors"].append({"stage": "completion_clock", **issue(exc)})
    try:
        result_path = output / "observer" / "worker-result.json"
        record["worker_result_file"] = persisted_file(result_path)
        worker_result = json.loads(result_path.read_text(encoding="utf-8"))
        record["raw_observer_status"] = worker_result["raw_observer_status"]
        record["raw_observer_error_count"] = worker_result["raw_observer_error_count"]
        record["category_pattern_observed"] = worker_result["category_pattern_observed"]
        record["pattern_evaluation"] = worker_result["pattern_evaluation"]
        if kind == "detached35":
            witness = detached_pre_kill_witness(record, worker_result)
            record["holder_original_pre_kill_witness"] = witness
            if witness["status"] != "OBSERVED":
                record["category_pattern_observed"] = False
                record["errors"].append({
                    "stage": "control_fixture_truth", "type": "PreKillHolderWitnessUnavailable",
                    "message": witness.get("reason", "UNKNOWN"),
                })
        if kind == "nondetached35" and record["category_pattern_observed"]:
            release = record.get("controller_release", {})
            post_work = record.get("released_processes_before_cleanup", {})
            observed_exits = all(
                post_work.get(name, {}).get("pid_from_handle") == release.get(name + "_pid")
                and post_work[name].get("creation_filetime_100ns")
                == release.get(name + "_identity", {}).get("creation_filetime_100ns")
                and type(post_work[name].get("exit_filetime_100ns")) is int
                and post_work[name]["exit_filetime_100ns"] > 0
                and not post_work[name].get("errors") for name in ("parent", "holder")
            )
            record["nondetached_native_exits_observed_before_cleanup"] = observed_exits
            if not observed_exits:
                record["category_pattern_observed"] = False
                record["errors"].append({
                    "stage": "control_fixture_truth", "type": "NativeExitProofUnavailable",
                    "message": "Both admitted process exits were not proven before owned cleanup",
                })
        if worker_result.get("finalization_error"):
            record["errors"].append({
                "stage": "worker_finalization", **worker_result["finalization_error"]
            })
    except BaseException as exc:
        record["errors"].append({"stage": "worker_outcome_read", **issue(exc)})
    record["controller_completion"] = (
        "COMPLETE" if not record["errors"] and record.get("job_quiescent")
        and record.get("worker_returncode") is not None else "INCOMPLETE"
    )
    complete = (
        not record["errors"] and record.get("worker_returncode") == 0
        and record.get("job_quiescent") and record.get("category_pattern_observed")
    )
    record["status_scope"] = "CONTROLLER_AND_CATEGORY_NOT_RAW_OBSERVER_COMPLETENESS"
    record.setdefault("status", "COMPLETE" if complete else "INCOMPLETE_OR_UNEXPECTED")
    try:
        document(output / "control-record.json", record)
    except BaseException as exc:
        record["errors"].append({"stage": "persist_control_record", **issue(exc)})
        record["controller_completion"] = "INCOMPLETE"
        record["status"] = "INCOMPLETE_OR_UNEXPECTED"
        try:
            print("CONTROL_RECORD_PERSISTENCE_FALLBACK=" + json.dumps(record), file=sys.stderr)
        except BaseException as fallback:
            record["fallback_stderr_error"] = issue(fallback)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", choices=KINDS)
    arguments = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("These artificial controls require Windows")
    if arguments.worker:
        return worker(arguments.worker, arguments.output.resolve())
    output = arguments.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "reader415-node-boundary-controls/v3",
        "scope": "ARTIFICIAL_OBSERVER_CONTROLS_ONLY_NOT_QUALIFICATION",
        "controls": [], "errors": [], "ordinary_verdict_modified": False,
    }
    for kind in KINDS:
        try:
            result["controls"].append(control(kind, output / ("control-" + kind)))
        except BaseException as exc:
            result["errors"].append({"kind": kind, **issue(exc)})
    complete = (
        not result["errors"] and len(result["controls"]) == 2
        and all(row["status"] == "COMPLETE" for row in result["controls"])
    )
    result["controller_completion"] = (
        "COMPLETE" if not result["errors"] and len(result["controls"]) == 2
        and all(row["controller_completion"] == "COMPLETE" for row in result["controls"])
        else "INCOMPLETE"
    )
    result["raw_observer_status_by_control"] = {
        row["kind"]: row.get("raw_observer_status", "UNKNOWN") for row in result["controls"]
    }
    result["result"] = (
        "ALL_CATEGORY_PATTERNS_OBSERVED_RAW_STATUS_RETAINED"
        if complete else "INCOMPLETE_OR_UNEXPECTED"
    )
    try:
        document(output / "controls-summary.json", result)
    except BaseException as exc:
        result["errors"].append({"stage": "persist_controls_summary", **issue(exc)})
        result["controller_completion"] = "INCOMPLETE"
        result["result"] = "INCOMPLETE_OR_UNEXPECTED"
        complete = False
        try:
            print("CONTROLS_SUMMARY_PERSISTENCE_FALLBACK=" + json.dumps(result), file=sys.stderr)
        except BaseException as fallback:
            result["fallback_stderr_error"] = issue(fallback)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
