"""Ordinary installed Linux image, non-root and entirely offline at execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import suppress
from pathlib import Path

from custodia_ordinary import document_jobs, model_action, public_documents, restart_off

from provelume.ai_native_inventory import inventory
from provelume.ai_runtime import native_selection
from provelume.ai_runtime_contract import hardware
from provelume.build_info import current_build_info
from provelume.service import ProvelumeInstance


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class Response:
    def __init__(self, status, raw):
        self.status_code, self.text = status, raw.decode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise ValueError("http_status")

    def json(self):
        return json.loads(self.text)


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, path, data=None):
        data = urllib.parse.urlencode(data).encode() if data is not None else None
        request = urllib.request.Request(self.base + path, data=data)
        try:
            response = self.opener.open(request, timeout=70)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            raw = response.read(2 * 1024**2 + 1)
            if len(raw) > 2 * 1024**2:
                raise ValueError("http_limit")
            return Response(response.code, raw)

    get = request
    post = request


def run(args):
    report = {"schema_version": 1, "source_commit": args.commit,
              "status": "NOT_RUN", "phase": "admission", "checks": {},
              "private_content_logged": False, "model_weights_in_artifact": False,
              "network": "Docker --network=none; ordinary in-container loopback HTTP",
              "configuration_sha256": hashlib.sha256(native_selection().configuration).hexdigest()}
    process, observed = None, {}

    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)

    try:
        save()
        if os.getuid() != 10001:
            raise ValueError("nonroot_identity")
        report["hardware"] = hardware()
        if current_build_info()["commit"] != args.commit:
            raise ValueError("installed_identity")
        components, _ = inventory(required=True)
        if len(components) != 12:
            raise ValueError("native_inventory")
        report["checks"]["installed_native_resources"] = "PASS"
        if args.restart:
            instance = ProvelumeInstance(args.instance)
            before = instance.scheduler.journal.list_jobs(limit=100)
            process = subprocess.Popen([
                "provelume", "serve", str(args.instance), "--host", "127.0.0.1", "--port", "8079"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            client, end = Client(8079), time.monotonic() + 30
            while True:
                try:
                    response = client.get("/settings/ai?lang=en")
                    response.raise_for_status()
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= end or process.poll() is not None:
                        raise ValueError("service_start") from None
                    time.sleep(.1)
            if ('data-ai-session="off"' not in response.text
                    or instance.scheduler.journal.list_jobs(limit=100) != before):
                raise ValueError("restart_authority")
            process.terminate()
            process.wait(timeout=10)
            report["restart"] = restart_off(args.instance)
            if report["restart"]["model_present"] is None:
                raise ValueError("model_persistence")
            report["checks"]["separate_volume_persistence_and_restart_off"] = "PASS"
        else:
            instance = ProvelumeInstance.initialise(args.instance, name="Custodia public container")
            cases = public_documents(instance, args.corpus, Path("/tmp/public-corpus"))
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            process = subprocess.Popen([
                "provelume", "serve", str(args.instance), "--host", "127.0.0.1", "--port", str(port)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            client = Client(port)
            end = time.monotonic() + 30
            while True:
                try:
                    client.get("/settings/ai").raise_for_status()
                    break
                except urllib.error.URLError:
                    if time.monotonic() >= end or process.poll() is not None:
                        raise ValueError("service_start") from None
                    time.sleep(.1)
            if client.get("/api/v1/security/network").json()["policy"]["external_access"]:
                raise ValueError("network_default")

            def observe():
                # Read all task child lists: the AI owner is an application worker
                # thread, not necessarily the process's original main thread.
                pids = set()
                for task in Path(f"/proc/{process.pid}/task").iterdir():
                    with suppress(FileNotFoundError):
                        pids.update(map(int, (task / "children").read_text().split()))
                if len(pids) > 1:
                    raise ValueError("worker_count")
                for pid in pids:
                    if pid in observed:
                        continue
                    try:
                        fd = os.pidfd_open(pid)
                        status = Path(f"/proc/{pid}/status").read_text()
                    except ProcessLookupError:
                        continue
                    observed[pid] = fd
                    fields = {line.split(":", 1)[0]: line.split(":", 1)[1].strip()
                              for line in status.splitlines() if ":" in line}
                    if fields["Seccomp"] != "2" or fields["NoNewPrivs"] != "1":
                        raise ValueError("worker_containment")

            report["phase"] = "offline_import"
            model_action(client, "import", report, path=str(args.model), observe=observe, save=save)
            report["checks"]["ordinary_offline_import"] = "PASS"
            report["phase"] = "guided_enablement"
            model_action(client, "enable_local", report, observe=observe, save=save)
            report["checks"]["ordinary_guided_enablement"] = "PASS"
            report["phase"] = "document_synthesis"
            document_jobs(client, instance, cases, report, observe=observe, save=save)
            report["phase"] = "parent_death"
            model_action(client, "self_test", report, observe=observe, save=save)
            live = [fd for fd in observed.values() if not select.select([fd], [], [], 0)[0]]
            if not live:
                raise ValueError("unobserved_live_worker")
            process.kill()
            process.wait(timeout=5)
            started = time.monotonic()
            for fd in live:
                if not select.select([fd], [], [], max(0, 2 - (time.monotonic() - started)))[0]:
                    raise ValueError("orphan_worker")
            report["parent_death_seconds"] = time.monotonic() - started
            report["checks"]["pidfd_parent_lifetime"] = "PASS"
            report["workers_observed"] = len(observed)
            report["restart"] = restart_off(args.instance)
            report["checks"]["restart_session_off"] = "PASS"
        report["status"], report["phase"] = "PASS", "completed"
    except Exception as exc:
        report["status"], report["failure_type"] = "FAIL", type(exc).__name__
        code = str(exc) if type(exc) is ValueError else getattr(exc, "code", None)
        report["failure_code"] = code if code in {
            "nonroot_identity", "installed_identity", "native_inventory", "model_persistence",
            "service_start", "network_default", "worker_count", "worker_containment",
            "unobserved_live_worker", "orphan_worker", "corpus_identity", "synthesis_preview",
            "synthesis_consent", "synthesis_job_identity", "synthesis_quality", "restart_authority",
            "model_operation", "model_action_http", "operation_timeout", "http_status",
            "http_limit",
            "model_limit", "model_compatibility",
        } else "qualification_failed"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for fd in observed.values():
            os.close(fd)
        save()
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("instance", "model", "corpus"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restart", action="store_true")
    raise SystemExit(run(parser.parse_args()))
