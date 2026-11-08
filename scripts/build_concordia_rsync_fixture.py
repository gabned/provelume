"""Build an offline, credential-free Linux SSH helper fixture from exact local inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path


def build(work, python_root, rsync):
    source = Path(__file__).absolute().parents[1]
    if os.name != "posix" or work.exists():
        raise ValueError("fresh native Linux fixture required")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    tree = subprocess.check_output(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True
    ).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=source):
        raise ValueError("clean exact source required")
    environment = dict(os.environ)
    for name in (
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_TLS",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        environment.pop(name, None)
    environment["DOCKER_BUILDKIT"] = "0"
    docker = ["docker", "--host=unix:///var/run/docker.sock"]
    work.mkdir(parents=True, mode=0o700)
    root = work / "rootfs"
    records = []

    def copy(path, destination, *, executable=False):
        if not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
            raise ValueError("bounded regular fixture input required")
        target = root / destination.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(0o755 if executable else 0o644)
        records.append(
            {
                "path": destination,
                "bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )

    # No host home, registry configuration, credentials or Instance enters a layer.
    for path in sorted((source / "core/provelume").rglob("*.py")):
        if "__pycache__" not in path.parts:
            copy(path, "/opt/product/core/" + path.relative_to(source / "core").as_posix())
    copy(source / "scripts/fixtures/concordia_rsync_site.py", "/opt/fixture_hooks/sitecustomize.py")
    interpreter = python_root / "bin/python3.12"
    copy(interpreter, "/opt/python/bin/python3.12", executable=True)
    native = [
        interpreter,
        rsync,
        *map(
            Path, ("/usr/sbin/sshd", "/usr/lib/openssh/sshd-session", "/usr/lib/openssh/sshd-auth")
        ),
    ]
    for name in ("sh", "sleep"):
        path = Path("/bin") / name
        copy(path, "/bin/" + name, executable=True)
        native.append(path)
    library = python_root / "lib/python3.12"
    for path in sorted(library.rglob("*")):
        relative = path.relative_to(library)
        if any(
            part
            in {
                "__pycache__",
                "site-packages",
                "test",
                "tests",
                "idlelib",
                "tkinter",
                "turtledemo",
                "ensurepip",
            }
            or part.startswith("config-")
            for part in relative.parts
        ):
            continue
        if (
            path.is_file()
            and path.suffix in {".py", ".so"}
            and not path.name.startswith(("_test", "_tkinter"))
        ):
            copy(path, "/opt/python/lib/python3.12/" + relative.as_posix())
            if path.suffix == ".so":
                native.append(path)
    for path in (python_root / "lib").glob("libpython3.12.so*"):
        copy(path, "/opt/python/lib/" + path.name)
    copy(rsync, "/opt/rsync/rsync", executable=True)
    for path in native[2:5]:
        copy(path, str(path), executable=True)
    dependencies = set()
    for path in native:
        output = subprocess.check_output(["ldd", str(path)], text=True, stderr=subprocess.STDOUT)
        if "not found" in output:
            raise ValueError("missing native fixture dependency")
        for name in re.findall(r"(/[^\s()]+)", output):
            selected = Path(name)
            if selected.is_relative_to(python_root):
                continue
            dependencies.add(selected)
    for name in ("libnss_files.so.2", "libnss_dns.so.2", "libresolv.so.2"):
        dependencies.add(Path("/lib/x86_64-linux-gnu") / name)
    for path in sorted(dependencies):
        # The ELF interpreter itself needs execute permission for a non-root
        # caller; ordinary shared libraries retain the input's public mode.
        copy(path, str(path), executable=os.access(path, os.X_OK))
    for path in [root, *root.rglob("*")]:
        if path.is_dir():
            path.chmod(0o755)
    for name, data in {
        "passwd": (
            "root:x:0:0:root:/root:/bin/sh\n"
            "synthetic:x:1000:1000:Synthetic mirror fixture:/fixture:/bin/sh\n"
            "sshd:x:102:65534:Privilege separation:/run/sshd:/usr/sbin/nologin\n"
        ),
        "group": "root:x:0:\nsynthetic:x:1000:\nnogroup:x:65534:\n",
        "nsswitch.conf": "passwd: files\ngroup: files\nshadow: files\nhosts: files dns\n",
    }.items():
        path = work / name
        path.write_text(data)
        path.chmod(0o644)
    tag = "concordia-s22-helper:" + head[:12]
    (work / "Dockerfile").write_text(
        "FROM scratch\nCOPY rootfs/ /\nCOPY passwd /etc/passwd\nCOPY group /etc/group\n"
        "COPY nsswitch.conf /etc/nsswitch.conf\n"
        "ENV LD_LIBRARY_PATH=/opt/python/lib PATH=/opt/python/bin:/opt/rsync:/usr/bin:/bin\n"
        "LABEL org.provelume.fixture=concordia-rsync-ssh-v1 org.provelume.source.commit="
        + head
        + " org.provelume.source.tree="
        + tree
        + '\nENTRYPOINT ["/bin/sleep", "180"]\n'
    )
    with (work / "docker-build-original.log").open("xb") as log:
        subprocess.run(
            docker + ["build", "--pull=false", "--network=none", "--tag", tag, str(work)],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=300,
        )
    image_id = json.loads(
        subprocess.check_output(docker + ["image", "inspect", tag], env=environment)
    )[0]["Id"]
    probes = []
    for phase, binary, arguments in (
        ("python", "/opt/python/bin/python3.12", ["--version"]),
        ("rsync", "/opt/rsync/rsync", ["--version"]),
        ("sshd", "/usr/sbin/sshd", ["-V"]),
        (
            "helper-import",
            "/opt/python/bin/python3.12",
            [
                "-c",
                "from provelume.mirror_rsync_remote_main import enroll_helper; print('IMPORT_OK')",
            ],
        ),
    ):
        probe = subprocess.run(
            docker
            + [
                "run",
                "--rm",
                "--network=none",
                "--read-only",
                "--user=1000:1000",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "-e",
                "PYTHONPATH=/opt/product/core",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "--entrypoint=" + binary,
                image_id,
                *arguments,
            ],
            env=environment,
            capture_output=True,
            timeout=15,
        )
        (work / (phase + "-stdout-original.log")).write_bytes(probe.stdout)
        (work / (phase + "-stderr-original.log")).write_bytes(probe.stderr)
        probes.append({"phase": phase, "exit": probe.returncode})
        if probe.returncode != 0:
            raise ValueError("native fixture prerequisite failed: " + phase)
    result = {
        "schema": "concordia-rsync-fixture-build/v1",
        "head": head,
        "tree": tree,
        "image_id": image_id,
        "base": "SCRATCH_NO_HOST_CREDENTIALS_OR_ACCOUNT_DATABASE",
        "inputs": records,
        "credentials_in_image": False,
        "application_distribution": False,
        "build_network": "NONE",
        "native_prerequisites": probes,
    }
    (work / "fixture-build-original.json").write_text(json.dumps(result, indent=2) + "\n")
    return {
        key: result[key]
        for key in ("schema", "head", "tree", "image_id", "credentials_in_image", "build_network")
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--python-root", type=Path, required=True)
    parser.add_argument("--rsync-binary", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.work.absolute(),
                args.python_root.absolute(),
                args.rsync_binary.absolute(),
            ),
            sort_keys=True,
        )
    )
