"""Actual Linux process/thread lifetime and containment; no native model needed."""

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux pidfd containment")

WORKER = '''
import sys,os,time,json
sys.path.insert(0,sys.argv[1])
from provelume.ai_runtime_limits import contain
job,limits=contain()
from provelume.ai_runtime_parent import watch_parent
watch_parent(int(sys.argv[2]))
print(json.dumps({'ready':True,'network':limits['network_control']}),flush=True)
time.sleep(60)
'''


def test_worker_survives_creator_thread_but_not_parent_process(tmp_path):
    root = str(Path(__file__).resolve().parents[1] / "core")
    helper = f'''
import os,subprocess,sys,threading,json,time
descriptor=os.pidfd_open(os.getpid())
workers=[]
def launch():
    workers.append(subprocess.Popen([sys.executable,'-I','-c',{WORKER!r},
                   sys.argv[1],str(descriptor)],pass_fds=(descriptor,),
                   stdout=subprocess.PIPE,stderr=subprocess.PIPE))
thread=threading.Thread(target=launch)
thread.start();thread.join()
os.close(descriptor)
child=workers[0]
ready=json.loads(child.stdout.readline())
print(json.dumps({{'pid':child.pid,**ready}}),flush=True)
time.sleep(60)
'''
    parent = subprocess.Popen([sys.executable, "-I", "-c", helper, root],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child_fd = None
    try:
        assert select.select([parent.stdout], [], [], 8)[0], "worker startup exceeded bound"
        raw = parent.stdout.readline()
        assert raw, parent.stderr.read(4096)
        row = json.loads(raw)
        assert row["ready"] and row["network"] == "seccomp:socket-syscalls-EPERM"
        child_fd = os.pidfd_open(row["pid"])
        assert not select.select([child_fd], [], [], 0.2)[0]
        # The lifetime guard, created after contain(), must inherit seccomp too.
        statuses = [p.read_text() for p in Path(f"/proc/{row['pid']}/task").glob("*/status")]
        assert len(statuses) == 2
        assert all("Seccomp:\t2\n" in status for status in statuses)
        started = time.monotonic()
        parent.kill()
        parent.wait(timeout=2)
        assert select.select([child_fd], [], [], 2)[0]
        assert time.monotonic() - started < 2
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        if child_fd is not None:
            if not select.select([child_fd], [], [], 0)[0]:
                signal.pidfd_send_signal(child_fd, signal.SIGKILL)
            assert select.select([child_fd], [], [], 2)[0]
            os.close(child_fd)
        parent.communicate(timeout=2)


def test_parent_guard_refuses_an_unrelated_inherited_file(tmp_path):
    root = str(Path(__file__).resolve().parents[1] / "core")
    path = tmp_path / "ordinary-public-file"
    path.write_text("not a process identity")
    with path.open("rb") as handle:
        process = subprocess.run([sys.executable, "-I", "-c", WORKER, root,
                                  str(handle.fileno())], pass_fds=(handle.fileno(),),
                                 capture_output=True, timeout=8)
    assert process.returncode != 0 and not process.stdout
    assert b"model_compatibility" in process.stderr
