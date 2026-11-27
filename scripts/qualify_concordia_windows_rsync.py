"""Run the exact S22 synthetic journey from source or the installed Windows executable."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from concordia_windows_fixture_bundle import asset_identity, verify

from provelume.mirror_rsync_windows_fixture import DOCKER_SOCKET

_GUEST_ROOT = "/run/provelume-concordia"
_LINUX_DOCKER = ["/usr/bin/docker", "--host=" + DOCKER_SOCKET]
_CASES = ("Complete generation", "before", "after", "disconnect", "disk-full", "replaced-root")


def _write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def _distribution_names(output):
    return set(
        output.decode("utf-16-le" if b"\x00" in output else "utf-8-sig")
        .removeprefix("\ufeff")
        .replace("\r", "")
        .splitlines()
    )


@contextmanager
def _server(wsl, *, bundle, work, output, manifest, environment):
    distribution = "Provelume-Concordia-" + uuid4().hex[:12]
    guest = ["--distribution", distribution, "--user", "root", "--exec"]

    def run(*arguments, timeout=15, **kwargs):
        return subprocess.run(
            [wsl, *arguments], env=environment, timeout=timeout, capture_output=True, **kwargs
        )

    def names():
        result = run("--list", "--quiet", "--all")
        if result.returncode:
            diagnostic = b"\n".join((result.stdout, result.stderr)).replace(b"\x00", b"")
            if (
                b"WSL_E_NO_DISTRO" not in diagnostic
                and b"has no installed distributions" not in diagnostic
            ):
                raise ValueError("WSL distribution inventory unavailable")
            return set()
        return _distribution_names(result.stdout)

    def own_marker():
        result = run(*guest, "/bin/cat", "/etc/provelume-concordia-fixture")
        return result.returncode == 0 and result.stdout == manifest["head"].encode() + b"\n"

    initial = names()
    if distribution in initial:
        raise ValueError("foreign fixture distribution")
    observed = {"distribution": distribution, "setup": "NOT_RUN", "cleanup": "UNKNOWN"}
    storage = work / "guest"
    storage.mkdir()
    daemon = None
    try:
        imported = run(
            "--import",
            distribution,
            str(storage),
            str(bundle / "guest-rootfs.tar"),
            "--version",
            "2",
            timeout=90,
        )
        if imported.returncode or distribution not in names() or not own_marker():
            raise ValueError("owned WSL2 guest import was not proven")
        guest_os = run(*guest, "/bin/uname", "-r")
        kernel = guest_os.stdout.strip().decode("ascii")
        if guest_os.returncode or not re.fullmatch(r"[0-9A-Za-z.-]*WSL2[0-9A-Za-z.-]*", kernel):
            raise ValueError("native Linux kernel required for server fixture")
        if run(*guest, "/bin/mkdir", "-p", "-m", "0700", _GUEST_ROOT).returncode:
            raise ValueError("WSL runtime directory unavailable")
        with (output / "linux-docker-original.log").open("xb") as journal:
            daemon = subprocess.Popen(
                [
                    wsl,
                    *guest,
                    "/usr/sbin/dockerd",
                    "--host=" + DOCKER_SOCKET,
                    "--pidfile=" + _GUEST_ROOT + "/dockerd.pid",
                    "--exec-root=" + _GUEST_ROOT + "/exec",
                    "--data-root=/var/lib/provelume-concordia/docker",
                    "--bridge=none",
                    "--ip-forward=false",
                    "--storage-driver=overlay2",
                ],
                env=environment,
                stdout=journal,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            )
        deadline = time.monotonic() + 20
        while True:
            state = run(*guest, *_LINUX_DOCKER, "info", "--format", "{{.OSType}}", timeout=5)
            if state.returncode == 0 and state.stdout.strip() == b"linux":
                break
            if daemon.poll() is not None or time.monotonic() >= deadline:
                raise ValueError("owned Linux Docker did not become ready")
            time.sleep(0.2)
        with (bundle / "fixture-image.tar").open("rb") as image:
            load = run(*guest, *_LINUX_DOCKER, "load", timeout=60, stdin=image)
        labels = run(
            *guest,
            *_LINUX_DOCKER,
            "image",
            "inspect",
            manifest["image_id"],
            "--format",
            "{{json .Config.Labels}}",
        )
        if (
            load.returncode
            or labels.returncode
            or json.loads(labels.stdout)
            != {
                "org.provelume.fixture": "concordia-rsync-ssh-v1",
                "org.provelume.source.commit": manifest["head"],
                "org.provelume.source.tree": manifest["tree"],
            }
        ):
            raise ValueError("Linux fixture image source was not proven")
        observed.update(setup="PASS", kernel=kernel, image=manifest["image_id"])
        yield distribution
    finally:
        try:
            if distribution not in names():
                observed["cleanup"] = "DISTRIBUTION_ABSENCE_CONFIRMED"
            elif not own_marker():
                observed["cleanup"] = "OWNERSHIP_REFUSED"
                raise ValueError("fixture distribution ownership uncertain")
            else:
                terminate = run("--terminate", distribution)
                unregister = run("--unregister", distribution, timeout=30)
                observed.update(
                    terminate_exit=terminate.returncode, unregister_exit=unregister.returncode
                )
                if terminate.returncode or unregister.returncode or distribution in names():
                    raise ValueError("fixture distribution cleanup unconfirmed")
                if storage.exists():
                    storage.rmdir()
                observed["cleanup"] = "OWNED_REMOVAL_CONFIRMED"
        finally:
            if daemon is not None:
                if daemon.poll() is None:
                    daemon.kill()
                daemon.wait(timeout=5)
            _write(output / "wsl-fixture-original.json", observed)


def qualify(
    bundle, components, ssh_components, work, output, head, executable=None, installer=None
):
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise ValueError("disposable native Windows Actions runner required")
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], text=True, timeout=15
    ).strip()
    if head != subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=15).strip():
        raise ValueError("source checkout does not match qualification head")
    artifact_id = os.environ["RSYNC_ARTIFACT_ID"]
    producer_attempt = os.environ["RSYNC_PRODUCER_ATTEMPT"]
    if not re.fullmatch(r"[1-9][0-9]*", artifact_id):
        raise ValueError("exact same-run fixture artifact ID required")
    manifest = verify(
        bundle,
        head=head,
        tree=tree,
        run_id=os.environ["GITHUB_RUN_ID"],
        run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
        producer_attempt=producer_attempt,
    )
    output.mkdir()
    work.mkdir()
    windows = Path(os.environ["SYSTEMROOT"])
    wsl = windows / "System32/wsl.exe"
    if not wsl.is_file():
        raise ValueError("WSL2 capability absent on the native runner")
    environment = {
        name: os.environ[name]
        for name in ("SYSTEMROOT", "WINDIR", "PROGRAMDATA", "TEMP", "TMP", "USERPROFILE", "APPDATA")
        if name in os.environ
    }
    environment.update(LOCALAPPDATA=str(work / "Host"), PATH="")
    manifest_identity = asset_identity(bundle / "manifest.json")
    _write(
        output / "fixture-source.json",
        {
            "head": head,
            "tree": tree,
            "input_manifest": manifest_identity,
            "input_artifact_id": artifact_id,
            "input_run_id": manifest["run_id"],
            "input_run_attempt": manifest["run_attempt"],
            "candidate_run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
            "installer": asset_identity(installer) if installer else None,
            "installed_executable": asset_identity(executable) if executable else None,
        },
    )
    source = work / "Native Windows wire"
    result = output / "native-windows-rsync.json"
    with _server(
        wsl, bundle=bundle, work=work, output=output, manifest=manifest, environment=environment
    ) as distribution:
        options = [
            "rsync-windows-transport-qualify",
            str(source),
            "--fixture-directory",
            str(components),
            "--ssh-fixture-directory",
            str(ssh_components),
            "--fixture-image",
            manifest["image_id"],
            "--expected-source-commit",
            head,
            "--fixture-distribution",
            distribution,
        ]
        if executable is None:
            command = [
                sys.executable,
                "-c",
                "import sys; from pathlib import Path; "
                "from provelume.ocr_desktop import run_ocr_command; "
                "sys.exit(run_ocr_command(sys.argv[2:], Path(sys.argv[1])))",
                str(result),
                *options,
            ]
        else:
            command = [executable, "--ocr-result-file", str(result), "--ocr-command", *options]
        try:
            subprocess.run(command, env=environment, timeout=180, check=True)
            report = json.loads(result.read_text(encoding="utf-8"))
            if (
                report.get("result") != "PASS"
                or report.get("declared_expected_source_commit") != head
            ):
                raise ValueError("native Windows wire result is incomplete")
        finally:
            for name in ("case-results-original.jsonl", "qualification-original.json"):
                if (source / name).is_file():
                    shutil.copyfile(source / name, output / name)
            for case in _CASES:
                observed = source / case / "Fixture/cleanup-original.json"
                if observed.is_file():
                    shutil.copyfile(observed, output / (case + "-cleanup-original.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("bundle", "components", "ssh-components", "work", "output"):
        parser.add_argument("--" + option, required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--installer", type=Path)
    args = parser.parse_args()
    if (args.executable is None) != (args.installer is None):
        parser.error("installed qualification requires executable and installer identities")
    qualify(
        args.bundle.absolute(),
        args.components.absolute(),
        args.ssh_components.absolute(),
        args.work.absolute(),
        args.output.absolute(),
        args.head,
        args.executable,
        args.installer,
    )
