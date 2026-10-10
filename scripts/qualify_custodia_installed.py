"""Observe the ordinary installed Windows AI path through its existing HTTP forms.

Only a disposable public fixture is used. This harness adds no executable role,
qualification API, model substitution or alternate worker to the product.
"""

from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from custodia_ordinary import (
    Page,
    acquisition,
    document_jobs,
    model_action,
    public_documents,
    restart_off,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))

from provelume.ai_runtime import native_selection  # noqa: E402
from provelume.ai_runtime_contract import hardware  # noqa: E402
from provelume.ai_windows_api import D, H, P, bind, libraries, verify_token  # noqa: E402
from provelume.service import ProvelumeInstance  # noqa: E402


def children(parent):
    """An external process-table observation, not a PID reported by the app."""
    class Entry(c.Structure):
        _fields_ = [("size", D), ("usage", D), ("pid", D), ("heap", c.c_size_t),
                    ("module", D), ("threads", D), ("parent", D), ("priority", c.c_int32),
                    ("flags", D), ("exe", c.c_wchar * 260)]

    kernel, _, _, _ = libraries()
    snapshot = bind(kernel, "CreateToolhelp32Snapshot", H, D, D)(2, 0)
    if snapshot == P(-1).value:
        raise ValueError("process_observation")
    try:
        first = bind(kernel, "Process32FirstW", c.c_int32, H, P)
        following = bind(kernel, "Process32NextW", c.c_int32, H, P)
        row = Entry()
        row.size = c.sizeof(row)
        found, values = first(snapshot, c.byref(row)), []
        while found:
            if row.parent == parent:
                if row.exe != "Provelume.exe":
                    raise ValueError("unexpected_child")
                values.append(row.pid)
            found = following(snapshot, c.byref(row))
        if len(values) > 1:
            raise ValueError("worker_count")
        return values
    finally:
        kernel.CloseHandle(snapshot)


def run(args):
    report = {"schema_version": 1, "source_commit": args.commit, "status": "NOT_RUN",
              "phase": "installation", "checks": {}, "observations": {},
              "configuration_sha256": hashlib.sha256(native_selection().configuration).hexdigest(),
              "private_content_logged": False, "model_weights_in_artifact": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    process, observed = None, {}
    kernel, _, _, _ = libraries()
    open_process = bind(kernel, "OpenProcess", H, D, c.c_int32, D)

    def save():
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def observe():
        for pid in children(process.pid):
            if pid in observed:
                continue
            handle = open_process(0x100000 | 0x1000, False, pid)
            if not handle:
                raise ValueError("worker_observation")
            observed[pid] = handle
            report["observations"][str(pid)] = verify_token(handle)
        save()

    def settings(client):
        response = client.get("/settings/ai?lang=en")
        response.raise_for_status()
        return Page(response.text)

    def action(client, name, **values):
        return model_action(client, name, report, observe=observe, save=save, **values)

    try:
        save()
        if os.name != "nt" or args.executable.name != "Provelume.exe":
            raise ValueError("native_windows_required")
        diagnostic = args.output.parent / "installed-identity.json"
        subprocess.run([str(args.executable), "--diagnostics-file", str(diagnostic)],
                       check=True, timeout=30)
        identity = json.loads(diagnostic.read_text(encoding="utf-8"))
        if not identity["frozen"] or identity["about"]["commit"] != args.commit:
            raise ValueError("installed_identity")
        report["checks"]["installed_exact_source"] = "PASS"
        report["hardware"] = hardware()
        subprocess.run([str(args.executable), "--bootstrap-instance", str(args.instance),
                        "--instance-name", "Custodia public synthetic lifecycle"],
                       check=True, timeout=30)
        instance = ProvelumeInstance(args.instance)
        cases = public_documents(instance, args.corpus, args.output.parent.parent / "public-corpus")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        process = subprocess.Popen([str(args.executable), "--serve", str(args.instance),
                                    "--port", str(port)])
        report["phase"] = "service_start"
        client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=70, trust_env=False)
        with client:
            end = time.monotonic() + 30
            while time.monotonic() < end:
                try:
                    settings(client)
                    break
                except httpx.ConnectError:
                    if process.poll() is not None:
                        raise ValueError("service_exit") from None
                    time.sleep(.1)
            else:
                raise ValueError("service_timeout")
            network = client.get("/api/v1/security/network").json()
            if network["policy"]["external_access"]:
                raise ValueError("network_default")
            report["phase"] = "ordinary_network_acquisition"
            acquisition(client, report, save=save)
            report["phase"] = "offline_import"
            action(client, "import", path=str(args.model))
            report["checks"]["ordinary_offline_import"] = "PASS"
            report["phase"] = "ordinary_self_test"
            action(client, "self_test")
            if not observed:
                raise ValueError("unobserved_worker")
            report["checks"]["ordinary_self_test"] = "PASS"
            report["checks"]["external_appcontainer_token_observation"] = "PASS"
            report["phase"] = "activation"
            action(client, "activate")
            report["checks"]["ordinary_activation"] = "PASS"
            action(client, "enable_local")
            report["checks"]["ordinary_guided_enablement"] = "PASS"
            report["phase"] = "ordinary_document_synthesis"
            document_jobs(client, instance, cases, report, observe=observe, save=save)
            # Keep the already-observed worker warm, then kill the actual parent.
            # Handle waits observe process identity, with no PID-reuse ambiguity.
            report["phase"] = "parent_death"
            action(client, "self_test")
            if not any(kernel.WaitForSingleObject(h, 0) == 258 for h in observed.values()):
                raise ValueError("unobserved_live_worker")
            process.kill()
            process.wait(timeout=5)
            started = time.monotonic()
            if any(kernel.WaitForSingleObject(h, 2000) != 0 for h in observed.values()):
                raise ValueError("orphan_worker")
            elapsed = time.monotonic() - started
            report["parent_death_seconds"] = elapsed
            if elapsed > 2:
                raise ValueError("parent_death_bound")
            report["checks"]["kill_on_parent_death"] = "PASS"
            before = instance.scheduler.journal.list_jobs(limit=100)
            report["phase"] = "ordinary_restart"
            process = subprocess.Popen([str(args.executable), "--serve", str(args.instance),
                                        "--port", str(port)])
            end = time.monotonic() + 30
            while True:
                try:
                    response = client.get("/settings/ai?lang=en")
                    response.raise_for_status()
                    break
                except httpx.ConnectError:
                    if time.monotonic() >= end or process.poll() is not None:
                        raise ValueError("service_timeout") from None
                    time.sleep(.1)
            if ('data-ai-session="off"' not in response.text or children(process.pid)
                    or instance.scheduler.journal.list_jobs(limit=100) != before):
                raise ValueError("restart_authority")
            report["checks"]["ordinary_installed_restart_off_without_replay"] = "PASS"
            process.terminate()
            process.wait(timeout=5)
            report["restart"] = restart_off(args.instance)
            report["checks"]["restart_session_off"] = "PASS"
        report["status"], report["phase"] = "PASS", "completed"
    except Exception as exc:
        report["status"] = "FAIL"
        # Do not put arbitrary subprocess, HTTP, filesystem or model text in evidence.
        report["failure_type"] = type(exc).__name__
        if type(exc) is ValueError and str(exc) in {
            "process_observation", "unexpected_child", "worker_count", "worker_observation",
            "model_action_http", "model_operation", "operation_timeout", "native_windows_required",
            "installed_identity", "service_exit", "service_timeout", "network_default",
            "unobserved_worker", "orphan_worker", "parent_death_bound",
            "unobserved_live_worker", "corpus_identity", "synthesis_preview",
            "synthesis_consent", "synthesis_job_identity", "synthesis_quality", "restart_authority",
            "acquisition_form", "acquisition_network_state", "acquisition_network_consent",
            "acquisition_denial", "acquisition_cancel", "acquisition_unobserved_transfer",
            "acquisition_size",
            "acquisition_cancellation_bound",
        }:
            report["failure_code"] = str(exc)
        else:
            report["failure_code"] = getattr(exc, "code", "qualification_failed")
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for handle in observed.values():
            kernel.CloseHandle(handle)
        save()
    print(json.dumps({key: report[key] for key in ("status", "phase", "checks")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "model", "instance", "output", "corpus"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--commit", required=True)
    raise SystemExit(run(parser.parse_args()))
