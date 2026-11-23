"""Prepare exact-source Linux fixture inputs for the disposable native Windows runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import urlopen

from build_concordia_rsync_fixture import build_prepared
from concordia_windows_fixture_bundle import asset_identity

_RSYNC = "https://github.com/RsyncProject/rsync/releases/download/v3.5.2/rsync-3.5.2.tar.gz"
_RSYNC_BYTES = 1_977_884
_RSYNC_SHA256 = "a10d591825251e070f74c98df3daad195def4ed81b4a2de16169026aea33f6c8"
_DEBIAN = "sha256:7378260c0a098d27ac206225db5e7d92b8c7c84ea7afccc86eeb513756bbd392"
_DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def _required_git(source, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=source, text=True, timeout=15).strip()


def _docker(environment, *arguments, timeout=30, **kwargs):
    return subprocess.run(
        [*_DOCKER, *map(str, arguments)], env=environment, timeout=timeout, check=True, **kwargs
    )


def _check_guest_archive(path):
    with tarfile.open(path, "r:") as archive:
        names = set()
        for member in archive:
            name = member.name.removeprefix("./")
            if (
                name.startswith(("etc/ssh/ssh_host_", "root/.ssh/", "root/.docker/"))
                or name in {"root/.git-credentials", "root/.netrc", "root/.bash_history"}
                or (name == "etc/machine-id" and (not member.isfile() or member.size != 0))
            ):
                raise ValueError("unexpected guest credential or host identity")
            if name in {
                "etc/machine-id",
                "etc/provelume-concordia-fixture",
                "etc/wsl.conf",
                "usr/bin/docker",
            }:
                names.add(name)
        if len(names) != 4:
            raise ValueError("incomplete guest inventory")


def build(bundle, *, work, expected_head):
    source = Path(__file__).absolute().parents[1]
    head = _required_git(source, "rev-parse", "HEAD")
    tree = _required_git(source, "rev-parse", "HEAD^{tree}")
    if (
        os.name != "posix"
        or sys.version_info[:3] != (3, 12, 14)
        or not re.fullmatch(r"[0-9a-f]{40}", head)
        or head != expected_head
        or _required_git(source, "status", "--porcelain")
    ):
        raise ValueError("clean exact Linux fixture source and Python 3.12.14 required")
    work.mkdir(mode=0o700)
    bundle.mkdir(mode=0o700)
    context = work / "context"
    context.mkdir(mode=0o700)
    local_config = work / "docker"
    local_config.mkdir(mode=0o700)
    environment = {
        name: os.environ[name]
        for name in ("PATH", "LANG", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY")
        if name in os.environ
    }
    environment["DOCKER_CONFIG"] = str(local_config)
    environment["DOCKER_BUILDKIT"] = "1"
    archive = context / "rsync-source.tar.gz"
    with urlopen(_RSYNC, timeout=30) as opened:
        data = opened.read(_RSYNC_BYTES + 1)
    archive.write_bytes(data)
    if asset_identity(archive) != {"bytes": _RSYNC_BYTES, "sha256": _RSYNC_SHA256}:
        raise ValueError("Linux rsync public source identity mismatch")
    shutil.copyfile(
        source / "scripts/fixtures/concordia_windows_wsl.Dockerfile", context / "Dockerfile"
    )
    tags = {stage: f"concordia-wsl-{stage}:{head[:12]}" for stage in ("guest", "builder")}
    with (bundle / "guest-build-original.log").open("xb") as log:
        for stage, tag in tags.items():
            _docker(
                environment,
                "build",
                "--platform=linux/amd64",
                "--target",
                stage,
                "--build-arg",
                f"FIXTURE_HEAD={head}",
                "--tag",
                tag,
                context,
                timeout=420,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

    python_root = Path(sys.base_prefix)
    # The preparation container cannot use Docker or the network. It receives
    # only readonly checkout/runtime inputs and one empty private output mount.
    prepared = json.loads(
        _docker(
            environment,
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--mount",
            f"type=bind,source={source},target=/source,readonly",
            "--mount",
            f"type=bind,source={python_root},target={python_root},readonly",
            "--mount",
            f"type=bind,source={work},target=/work",
            "--env",
            "GIT_OPTIONAL_LOCKS=0",
            "--env",
            f"LD_LIBRARY_PATH={python_root}/lib",
            tags["builder"],
            "/usr/bin/python3",
            "/source/scripts/build_concordia_rsync_fixture.py",
            "--work",
            "/work/fixture",
            "--python-root",
            python_root,
            "--rsync-binary",
            "/opt/rsync/rsync",
            "--prepare-only",
            timeout=90,
            capture_output=True,
        ).stdout
    )
    if (prepared["head"], prepared["tree"]) != (head, tree):
        raise ValueError("prepared helper source mismatch")
    fixture = build_prepared(work / "fixture", prepared)
    for path in (work / "fixture").iterdir():
        if path.name.endswith(("-original.log", "-original.json")):
            shutil.copyfile(path, bundle / path.name)
    guest_tar = bundle / "guest-rootfs.tar"
    guest = (
        _docker(
            environment, "create", "--network=none", tags["guest"], "/bin/true", capture_output=True
        )
        .stdout.strip()
        .decode("ascii")
    )
    if not re.fullmatch(r"[0-9a-f]{64}", guest):
        raise ValueError("guest container identity")
    try:
        _docker(environment, "export", "--output", guest_tar, guest, timeout=90)
    finally:
        _docker(environment, "rm", guest, capture_output=True)
    _check_guest_archive(guest_tar)
    _docker(
        environment,
        "save",
        "--output",
        bundle / "fixture-image.tar",
        fixture["image_id"],
        timeout=90,
    )
    manifest = {
        "schema": "concordia-rsync-windows-server-input/v1",
        "head": head,
        "tree": tree,
        "run_id": os.environ["GITHUB_RUN_ID"],
        "run_attempt": os.environ["GITHUB_RUN_ATTEMPT"],
        "image_id": fixture["image_id"],
        "debian_amd64_manifest": _DEBIAN,
        "public_rsync_source": asset_identity(archive),
        "credentials_in_inputs": False,
        "files": {asset.name: asset_identity(asset) for asset in sorted(bundle.iterdir())},
    }
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--bundle", required=True, type=Path)
    arguments.add_argument("--work", required=True, type=Path)
    arguments.add_argument("--expected-head", required=True)
    selected = arguments.parse_args()
    build(
        selected.bundle.absolute(),
        work=selected.work.absolute(),
        expected_head=selected.expected_head,
    )
