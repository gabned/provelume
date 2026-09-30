FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04@sha256:d94c97dd9cacf183d0a6fd12a8e87b526e9e928307674ae9c94139139c0c6eae

# Development dependencies come from native project metadata and its reviewed
# build-input lock. No product source or operator credential enters this build.
RUN apt-get update --snapshot 20260928T000000Z \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       --snapshot 20260928T000000Z python3 python3-venv nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /native/pyproject.toml
COPY build-lock/ubuntu-py312-x86_64.requirements.txt /native/build-requirements.txt
RUN python3 -m venv /opt/dependency-tools \
    && /opt/dependency-tools/bin/python -m pip download --only-binary=:all: \
       --require-hashes -r /native/build-requirements.txt --dest /opt/native-wheels \
    && /opt/dependency-tools/bin/python -m pip install --no-index --find-links /opt/native-wheels \
       --require-hashes -r /native/build-requirements.txt \
    && cd /native \
    && /opt/dependency-tools/bin/python -c 'import hatchling.build,json,pathlib,subprocess,sys,tomllib; p=tomllib.loads(pathlib.Path("pyproject.toml").read_text()); assert p["build-system"]["build-backend"] == "hatchling.build"; requirements=hatchling.build.get_requires_for_build_editable({}); subprocess.run([sys.executable,"-m","pip","download","--only-binary=:all:","--dest","/opt/native-wheels",*requirements],check=True); pathlib.Path("/opt/native-wheels/editable-requirements.json").write_text(json.dumps(requirements))' \
    && /opt/dependency-tools/bin/python -c 'import pathlib, subprocess, sys, tomllib; p=tomllib.loads(pathlib.Path("/native/pyproject.toml").read_text()); requirements=p["project"]["dependencies"]+p["project"]["optional-dependencies"]["dev"]; subprocess.run([sys.executable,"-m","pip","download","--only-binary=:all:","--dest","/opt/native-wheels",*requirements],check=True)' \
    && /opt/dependency-tools/bin/python -c 'import hashlib,json,pathlib; p=pathlib.Path("/opt/native-wheels"); (p/"inventory.json").write_text(json.dumps({f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in p.glob("*.whl")},sort_keys=True))'
WORKDIR /workspace
