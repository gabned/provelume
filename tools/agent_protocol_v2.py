#!/usr/bin/env python3
"""Native dependency verification and routing; credentials belong to the enrolled host."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = ".github/agent-protocol/pin.json"
VENDOR = ROOT / "tools/agent_protocol_core"
REPOSITORY = "gabned/provelume"
REPOSITORY_ID = 1343746770


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlink dependency refused")
    return path.read_bytes()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def verify():
    """Byte proof only: an accepted host independently authenticates source/policy."""
    pin = json.loads(read(ROOT / PIN_PATH))
    require(
        pin["schema"] in {"agent-protocol-consumer-pin/v2", "agent-protocol-consumer-pin/v3"},
        "Unknown consumer pin",
    )
    require(
        (pin["consumer"], pin["consumer_id"]) == (REPOSITORY, REPOSITORY_ID),
        "Consumer identity changed",
    )
    require(
        pin["operational_revision"] == pin["work_revision"] == pin["source_manifest"]["revision"],
        "Work/operational source split",
    )
    manifest = pin["source_manifest"]
    require(
        (manifest["repository"], manifest["repository_id"])
        == ("gabned/agent-protocol", 1393711644),
        "Canonical repository changed",
    )
    require(digest(manifest) == pin["manifest_digest"], "Source inventory changed")
    expected = {}
    for row in manifest["files"]:
        name = row["path"]
        require(
            isinstance(name, str)
            and "\\" not in name
            and ":" not in name
            and not name.startswith("/")
            and all(p not in {"", ".", ".."} for p in name.split("/")),
            "Unsafe source path",
        )
        require(
            name.casefold() not in expected and row["mode"] in {"100644", "100755"},
            "Duplicate path or unsafe mode",
        )
        expected[name.casefold()] = name
        file = VENDOR / name
        data = read(file)
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(
            (hashlib.sha256(data).hexdigest(), blob) == (row["sha256"], row["blob"]),
            "Canonical bytes changed: " + name,
        )
        if os.name != "nt":
            require(
                bool(file.stat().st_mode & 0o111) == (row["mode"] == "100755"),
                "Canonical mode changed: " + name,
            )
    actual = {
        p.relative_to(VENDOR).as_posix()
        for p in VENDOR.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    require(actual == set(expected.values()), "Unmanaged or missing canonical files")
    # Import only after checking every immutable distribution byte.
    sys.path.insert(0, str(VENDOR / "src"))
    from agent_protocol.source import validate_inventory

    validate_inventory(manifest, pin["manifest_digest"])
    if pin["schema"] == "agent-protocol-consumer-pin/v3":
        from agent_protocol.source import validate_git_origin

        configuration = pin["acquisition"]
        require(
            set(configuration) == {"kind", "origin", "artifacts"}
            and configuration["kind"] == "CANONICAL_GIT",
            "Explicit canonical Git acquisition required",
        )
        require(
            "release_url" not in pin and "release_artifacts" not in pin,
            "Ambiguous Git/release selection refused",
        )
        validate_git_origin(configuration["origin"])
        require(
            configuration["origin"]["revision"] == pin["operational_revision"],
            "Source origin/pin mismatch",
        )
    else:
        require("acquisition" not in pin, "Ambiguous Git/release selection refused")
    return pin


def documents(pin, phase, host, workstream):
    from agent_protocol.documents import select

    core_manifest = json.loads(read(VENDOR / ".github/agent-protocol/documents.json"))
    core = select(
        VENDOR,
        core_manifest,
        accepted_digest=pin["documents_digest"],
        phase=phase,
        host=host,
        workstream=workstream,
    )
    local_manifest = json.loads(read(ROOT / ".github/agent-protocol/documents.json"))
    local = select(
        ROOT,
        local_manifest,
        accepted_digest=digest(local_manifest),
        phase=phase,
        host=host,
        workstream=workstream,
    )
    return {
        "source_revision": pin["operational_revision"],
        "core": core,
        "local": local,
        "model_text_bytes": core["model_text_bytes"] + local["model_text_bytes"],
        "authority": "ACCEPTED_CONSUMER_BASE_REQUIRED",
        "tokens": "UNKNOWN",
        "cost": "UNKNOWN",
    }


def acquire_git(pin, *, offline=False, fetch_source=None):
    """Use the canonical Git verifier; the accepted consumer base remains authority."""
    from agent_protocol.source import (
        acquire_git_source,
        authenticate_git_origin,
        verify_installation,
    )

    configuration = pin["acquisition"]
    require(
        isinstance(configuration, dict)
        and set(configuration) == {"kind", "origin", "artifacts"}
        and configuration["kind"] == "CANONICAL_GIT",
        "Unknown or incomplete source acquisition selection",
    )
    revision = pin["operational_revision"]
    origin, artifacts = configuration["origin"], configuration["artifacts"]
    require(origin["revision"] == revision, "Source origin/pin mismatch")
    names = {
        "source.tar.gz",
        "source-manifest.json",
        "git-provenance.json",
        "SHA256SUMS",
        f"agent_protocol_core-{pin['source_manifest']['version']}-py3-none-any.whl",
    }
    require(
        isinstance(artifacts, dict) and set(artifacts) == names,
        "Incomplete Git source artifact inventory",
    )
    for record in artifacts.values():
        require(
            isinstance(record, dict)
            and set(record) == {"sha256", "size"}
            and type(record["size"]) is int
            and 0 < record["size"] < 64 * 1024 * 1024
            and isinstance(record["sha256"], str)
            and len(record["sha256"]) == 64
            and all(c in "0123456789abcdef" for c in record["sha256"]),
            "Invalid Git source artifact record",
        )
    directory = ROOT / ".agent/protocol-artifacts" / revision
    require(
        not any(p.is_symlink() for p in (directory, *directory.parents)), "Cache symlink refused"
    )

    def verify_cache():
        require(directory.is_dir(), "Git source artifact absent from offline cache")
        # Verify known files before inventory completeness so corrupt originals
        # retain their specific diagnostic instead of being hidden by a gap.
        for name, record in artifacts.items():
            target = directory / name
            if target.exists() or target.is_symlink():
                data = read(target)
                require(
                    len(data) == record["size"]
                    and hashlib.sha256(data).hexdigest() == record["sha256"],
                    "Cached artifact differs; preserve it for diagnosis: " + name,
                )
        require(
            {p.name for p in directory.iterdir()} == names,
            "Incomplete or unmanaged Git source cache preserved",
        )

    if directory.exists():
        verify_cache()
    else:
        require(not offline, "Git source artifact absent from offline cache")

    authenticated = None
    if not offline:

        class CanonicalRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                parsed = urllib.parse.urlsplit(newurl)
                require(
                    parsed.scheme == "https"
                    and parsed.hostname == "api.github.com"
                    and not parsed.username
                    and not parsed.password,
                    "Unexpected source authentication redirect",
                )
                return super().redirect_request(req, fp, code, msg, headers, newurl)

        observations = []

        def fetch_json(url):
            require(
                url == "https://api.github.com/repos/gabned/agent-protocol"
                or url.startswith("https://api.github.com/repos/gabned/agent-protocol/"),
                "Unexpected canonical source endpoint",
            )
            if fetch_source is not None:
                require(callable(fetch_source), "Authenticated source read capability required")
                value = fetch_source(url)
            else:
                opener = urllib.request.build_opener(CanonicalRedirect())
                request = urllib.request.Request(
                    url,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "agent-protocol-source",
                    },
                )
                with opener.open(request, timeout=30) as response:
                    data = response.read(4 * 1024 * 1024 + 1)
                require(len(data) <= 4 * 1024 * 1024, "Source observation too large")
                value = json.loads(data)
            observations.append({"url": url, "response": value})
            return value

        authenticated = authenticate_git_origin(origin, fetch_json=fetch_json)
        evidence = ROOT / ".agent/protocol-source-observations" / revision
        require(
            not any(p.is_symlink() for p in (evidence, *evidence.parents)),
            "Source observation symlink refused",
        )
        evidence.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(observations, sort_keys=True) + "\n").encode()
        observation = evidence / (hashlib.sha256(data).hexdigest() + ".json")
        if observation.exists():
            require(read(observation) == data, "Existing source observation differs")
        else:
            with observation.open("xb") as stream:
                stream.write(data)
        if not directory.exists():
            source = ROOT / ".agent/protocol-sources" / revision
            require(
                not any(p.is_symlink() for p in (source, *source.parents)),
                "Canonical source cache symlink refused",
            )
            if not source.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                cloned = subprocess.run(
                    [
                        "git",
                        "-c",
                        "credential.interactive=false",
                        "clone",
                        "--no-checkout",
                        "--no-tags",
                        "https://github.com/gabned/agent-protocol.git",
                        str(source),
                    ],
                    capture_output=True,
                    check=False,
                )
                require(
                    cloned.returncode == 0, "Canonical Git acquisition failed; preserve evidence"
                )
            acquire_git_source(source, directory, origin, authenticate_origin=lambda: authenticated)
            verify_cache()
    require(
        json.loads(read(directory / "source-manifest.json")) == pin["source_manifest"],
        "Canonical Git source inventory differs",
    )
    bundle = {
        "schema": "agent-protocol-source-bundle/v2",
        "kind": "CANONICAL_GIT",
        "archive_path": str(directory / "source.tar.gz"),
        "archive_sha256": pin["archive_sha256"],
        "manifest": pin["source_manifest"],
        "manifest_digest": pin["manifest_digest"],
        "provenance": json.loads(read(directory / "git-provenance.json")),
    }
    proof = verify_installation(
        bundle,
        revision=revision,
        distribution_root=VENDOR,
        source_root=VENDOR / "src",
        authenticate_origin=lambda: authenticated if authenticated is not None else origin,
    )
    return {
        "result": "GIT_SOURCE_BYTES_VERIFIED",
        "revision": revision,
        "artifacts": len(artifacts),
        "source": proof,
        "authority": "ACCEPTED_CONSUMER_BASE_REQUIRED",
    }


def acquire(pin, *, offline=False, fetch_source=None):
    """Acquire the explicitly selected accepted source; a cache is not authority."""
    require("candidate_preview" not in pin, "Preview is not an accepted release")
    if pin["schema"] == "agent-protocol-consumer-pin/v3":
        return acquire_git(pin, offline=offline, fetch_source=fetch_source)
    revision = pin["operational_revision"]
    artifacts = pin["release_artifacts"]
    require(
        set(artifacts)
        == {
            "source.tar.gz",
            "source-manifest.json",
            "SHA256SUMS",
            "conformance.json",
            f"agent_protocol_core-{pin['source_manifest']['version']}-py3-none-any.whl",
        },
        "Incomplete release artifact inventory",
    )
    prefix = (
        "https://github.com/gabned/agent-protocol/releases/download/v"
        + pin["source_manifest"]["version"]
        + "/"
    )
    directory = ROOT / ".agent" / "protocol-artifacts" / revision
    require(
        not any(p.is_symlink() for p in (directory, *directory.parents)), "Cache symlink refused"
    )
    directory.mkdir(parents=True, exist_ok=True)

    class PublicReleaseRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            parsed = urllib.parse.urlsplit(newurl)
            require(
                parsed.scheme == "https"
                and parsed.hostname in {"github.com", "release-assets.githubusercontent.com"}
                and not parsed.username
                and not parsed.password,
                "Unexpected artifact redirect",
            )
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    opener = urllib.request.build_opener(PublicReleaseRedirect())
    for name, record in artifacts.items():
        require(
            set(record) == {"sha256", "size"}
            and isinstance(record["size"], int)
            and 0 < record["size"] < 64 * 1024 * 1024,
            "Invalid artifact record",
        )
        target = directory / name
        if target.exists() or target.is_symlink():
            data = read(target)
        else:
            require(not offline, "Artifact absent from offline cache: " + name)
            with opener.open(prefix + name, timeout=30) as response:
                data = response.read(record["size"] + 1)
            require(
                len(data) == record["size"]
                and hashlib.sha256(data).hexdigest() == record["sha256"],
                "Downloaded artifact differs: " + name,
            )
            # Publish complete verified bytes without overwriting a concurrent cache.
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            try:
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    require(read(target) == data, "Concurrent artifact differs")
            finally:
                temporary.unlink()
        require(
            len(data) == record["size"] and hashlib.sha256(data).hexdigest() == record["sha256"],
            "Cached artifact differs; preserve it for diagnosis: " + name,
        )
    require(
        json.loads(read(directory / "source-manifest.json")) == pin["source_manifest"],
        "Published source inventory differs",
    )
    from agent_protocol.source import verify_installation

    proof = verify_installation(
        {
            "archive_path": str(directory / "source.tar.gz"),
            "archive_sha256": pin["archive_sha256"],
            "manifest": pin["source_manifest"],
            "manifest_digest": pin["manifest_digest"],
        },
        revision=revision,
        distribution_root=VENDOR,
        source_root=VENDOR / "src",
    )
    return {
        "result": "RELEASE_BYTES_VERIFIED",
        "revision": revision,
        "artifacts": len(artifacts),
        "source": proof,
        "authority": "ACCEPTED_CONSUMER_BASE_REQUIRED",
    }


S07_BIND = "042658d5c4c92f37efea0a0830a40431599b8acedb0b74cb7e40835db84a6f9d"
S07_EVALUATOR = "67f72f2e493779daa38a1d97c263e60c5126cb45"
S07_ORIGINAL_RUNS = {
    "19249382a1bb9bfbe5ce7d15d00e2ac70a21c3f2": (41928461608, 126918981396),
    "a713f0141799fea60b7caa1a0e62826f3b373bf9": (42109002130, 127531293383),
    "da25e28564f70fc1bad59f624c5947e9fe2a3924": (42115157949, 127552733141),
    "4cfbec445f7582130802f753b2dc186dc8903142": (42119880008, 127569128458),
}
S07_ADDITIONAL_RUNS = {
    "f2cb84a60f3e5a268d8547285b5a360cbaef8a47": (42368608397, 128391869733),
    "adb276c663007921658fb5dfc4173b7d62ace31d": (42369730479, 128395169479),
    "3790f8afc50ef3a0c7162894e366b7e19b4ddc34": (42378818835, 128421899209),
    "0cf30899fdf2c5b0607dc1ab6c7a5fe97f37f83f": (42382541331, 128433012483),
    "61e8694dd7904de4de8c9295ca8301edf4a358df": (42389259695, 128453164193),
}
S07_COLD_810_APPROVAL_SCHEMA = "provelume-s07-approval/v3"
S07_V2_APPROVAL_COMMENT = "issuecomment-6960833812"
S07_COLD_810_FINDING = f"https://github.com/{REPOSITORY}/actions/runs/42290059975/job/128140838845"
S07_COLD_810_RECORD = {
    "source_commit": "d5b2cc9f06c14be8c51a082d309dbde0358552e8",
    "driver_commit": "358a19468f1e2db58b72212e8e36c102cbf522f6",
    "run_id": 42290059975,
    "attempt": 1,
    "job_id": 128140838845,
    "event": "workflow_dispatch",
    "workflow_path": ".github/workflows/ai-runtime-candidate.yml",
    "job_name": "concordia-capture-guard",
    "job_conclusion": "success",
    "arm": "A",
    "arm_index": 3,
    "phase": "cold",
    "sample": 810,
    "failed_gate": "s08_performance",
    "qualification_eligible": False,
    "result": "FAIL",
    "status": "CURRENT",
    "cause": "NOT_DEMONSTRATED",
    "artifact_id": 13541917919,
    "artifact_sha256": "5248db15078cf441570f114390e8030dc79e4f0065caa6b87172580f00cc7c2a",
    "report_member": "capture-guard-comparison/arm-3/report.json",
    "report_bytes_sha256": "63bc821aec9ad304da7e0fae0b09e57b4cf13d70758a54bd832d44977bd2ef83",
}
S07_WINDOWS_ACQUISITION_REFERENCE = f"https://github.com/{REPOSITORY}/issues/383#issuecomment-7146731122"
S07_WINDOWS_ACQUISITION_COORDINATES = (
    "5f177ac68c1777843f5a97f1292b0848728ef974",
    "3b9242fc6ce655a0f29c91d52a081d8cf6ed06b4",
    "258ef309a75b0ec18c071d2d69d68cc37b890c88",
)
S07_WINDOWS_ACQUISITION_RUNS = {
    "da25e28564f70fc1bad59f624c5947e9fe2a3924": (
        42115157949, 127552732684,
        "92d0fc5e1852bf700ff4553d3aeedb4b994a54735b6a5c865744aa54f6a61c3c",
    ),
    "f2cb84a60f3e5a268d8547285b5a360cbaef8a47": (
        42368608397, 128391870070,
        "d06c2177e225b910ea0ff45b1fee6ec78416e3f55198f0536240bfa7564cb77e",
    ),
    "84826e69742e2a14bc5471a510925677ce9b2888": (
        42387171420, 128446896883,
        "1cd4ab5de5f0bb36843e5d4eddb348e215669122c0917d8b288eea40c8bf0da2",
    ),
}
S07_CPU_GATES = {"deterministic", "s06_governed", "s07_setup", "network"}


def parse_legacy_observations(data):
    """Reject v3 collisions before normalized observations can enter the gate."""
    duplicate_keys = False

    def collect(pairs):
        nonlocal duplicate_keys
        obj = {}
        for key, value in pairs:
            duplicate_keys |= key in obj
            obj[key] = value
        return obj

    observations = json.loads(data, object_pairs_hook=collect)
    if duplicate_keys:
        try:
            schema = observations["s07_qualification"]["approval"]["schema"]
        except (KeyError, TypeError):
            pass
        else:
            require(schema != S07_COLD_810_APPROVAL_SCHEMA,
                    "Duplicate JSON keys in S07 v3 observations")
    return observations


def verify_s07_cpu_jobs(jobs, head):
    require(
        isinstance(jobs, dict) and set(jobs) == {"ubuntu-24.04", "windows-2025"},
        "Both ordinary S07 CPU jobs are required",
    )
    for runner, job in jobs.items():
        require(
            isinstance(job, dict)
            and set(job) == {
                "run_id", "attempt", "job_id", "report", "report_sha256",
                "workflow_path", "event", "job_name", "conclusion",
            }
            and job["workflow_path"] == ".github/workflows/ai-runtime-candidate.yml"
            and job["event"] == "pull_request"
            and job["job_name"] == f"measure ({runner})"
            and job["conclusion"] == "success"
            and all(
                type(job[key]) is int and job[key] > 0
                for key in ("run_id", "attempt", "job_id")
            ),
            "Incomplete or nonpassing ordinary S07 CPU job",
        )
        report = job["report"]
        require(
            isinstance(report, dict)
            and digest(report) == job["report_sha256"]
            and report.get("source_commit") == head
            and report.get("status") == "PASS"
            and isinstance(report.get("gates"), dict)
            and all(report["gates"].get(gate) == "PASS" for gate in S07_CPU_GATES),
            "Missing, altered or nonpassing S07 CPU report on the candidate",
        )
    require(
        len({job["job_id"] for job in jobs.values()}) == len(jobs),
        "S07 platform jobs must be distinct",
    )


def validate_s07_windows_acquisition(approval, snapshot, findings, git, prior_reference, trusted):
    require(
        isinstance(approval, dict) and digest(approval) == trusted,
        "Independently authenticated S07 Windows acquisition approval differs or is missing",
    )
    head, base = snapshot["head_sha"], snapshot["base_sha"]
    coordinates = head, base, git("rev-parse", head + "^{tree}")
    reference = approval.get("reference")
    require(
        isinstance(reference, str) and reference != prior_reference
        and re.fullmatch(rf"https://github\.com/{re.escape(REPOSITORY)}/issues/383#issuecomment-[1-9][0-9]*",
                         reference) is not None,
        "S07 Windows acquisition requires a separate authenticated campaign decision",
    )
    if reference == S07_WINDOWS_ACQUISITION_REFERENCE:
        require(coordinates == S07_WINDOWS_ACQUISITION_COORDINATES,
                "Original S07 Windows acquisition decision is bound to its exact coordinates")

    subjects = []
    historical = {}
    id_fields = ("run_id", "attempt", "job_id")
    for commit, (run, job, log_digest) in S07_WINDOWS_ACQUISITION_RUNS.items():
        url = f"https://github.com/{REPOSITORY}/actions/runs/{run}/job/{job}"
        identity = {"source_commit": commit, "run_id": run, "attempt": 1, "job_id": job}
        subjects.append({"reference": url, **identity})
        historical[url] = {
            **identity,
            "connector_log_capture_sha256": log_digest,
            "result": "FAIL",
            "status": "UNKNOWN",
            "cause": "NOT_DEMONSTRATED",
            "inference": "NOT_RUN",
            "failure_phase": "immutable Windows model acquisition",
        }
    require(
        approval == {
            "schema": "provelume-s07-windows-acquisition-approval/v1",
            "repository": REPOSITORY,
            "owner_pr": "#439",
            "release": "0.15.0",
            "criterion": "QUALIFY_CANDIDATE_AND_MAIN_AT_EXISTING_THRESHOLDS",
            "binding_sha256": S07_BIND,
            "head_sha": coordinates[0],
            "base_sha": coordinates[1],
            "tree_sha": coordinates[2],
            "windows_acquisition_findings": subjects,
            "reference": reference,
        }
        and all(type(subject[key]) is int for subject in approval["windows_acquisition_findings"]
                for key in id_fields),
        "S07 Windows acquisition approval requires exactly three original jobs "
        "and current coordinates",
    )
    require(
        all(findings.get(url) == row and all(type(findings[url][key]) is int for key in id_fields)
            for url, row in historical.items()),
        "The exact three S07 Windows acquisition records and original outcomes are required",
    )
    return historical


def validate_s07_finding_applicability(
    qualification, snapshot, binding, review, git, *, trusted_approval, trusted_evidence,
    trusted_windows_acquisition_approval=None,
):
    """Verify the independently selected approval and authenticated observations offline."""
    require(
        (binding["active_pr"], binding["workstream"], binding["report_sha256"])
        == ("#439", "concordia-s07-cpu-recovery", S07_BIND)
        and review["adapter"] == "V1_3_NATIVE"
        and review["technical_finding"] == "CURRENT",
        "S07 finding applicability requires the original #439 BIND and CURRENT snapshot",
    )
    require(
        isinstance(qualification, dict) and set(qualification) in (
            {"approval", "evidence"}, {"approval", "evidence", "windows_acquisition_approval"},
        ),
        "S07 qualification requires the authenticated approval and evidence",
    )
    windows_approved = "windows_acquisition_approval" in qualification
    require(windows_approved == (trusted_windows_acquisition_approval is not None),
            "S07 Windows acquisition approval and its independent digest are both required")
    approval, evidence = qualification["approval"], qualification["evidence"]
    require(
        isinstance(approval, dict) and digest(approval) == trusted_approval,
        "Independently authenticated S07 approval differs or is missing",
    )
    require(
        isinstance(evidence, dict) and digest(evidence) == trusted_evidence,
        "Independently authenticated S07 evidence differs or is missing",
    )
    original_findings = {
        f"https://github.com/{REPOSITORY}/actions/runs/{run}/job/{job}": {
            "source_commit": commit, "run_id": run, "job_id": job, "result": "FAIL",
            "status": "CURRENT", "cause": "NOT_DEMONSTRATED",
        }
        for commit, (run, job) in S07_ORIGINAL_RUNS.items()
    }
    approval_scope = {
        "schema": "provelume-s07-approval/v1",
        "repository": REPOSITORY,
        "owner_pr": "#439",
        "binding_sha256": S07_BIND,
        "release": "0.15.0",
        "criterion": "QUALIFY_CANDIDATE_AND_MAIN_AT_EXISTING_THRESHOLDS",
        "historical_findings": sorted(original_findings),
    }
    additional_findings = {}
    schema = approval.get("schema")
    cold_810_approved = schema == S07_COLD_810_APPROVAL_SCHEMA
    approval_error = (
        "S07 approval must cover exactly the four original findings and the approved criterion"
    )
    if schema in ("provelume-s07-approval/v2", S07_COLD_810_APPROVAL_SCHEMA):
        additional_findings = {
            f"https://github.com/{REPOSITORY}/actions/runs/{run}/job/{job}": {
                "source_commit": commit, "run_id": run, "job_id": job, "result": "FAIL",
                "status": "CURRENT", "cause": "NOT_DEMONSTRATED",
            }
            for commit, (run, job) in S07_ADDITIONAL_RUNS.items()
        }
        approval_scope = {
            **approval_scope,
            "schema": "provelume-s07-approval/v2",
            "additional_historical_findings": sorted(additional_findings),
        }
        approval_error = (
            "S07 approval must cover exactly the four original and five additional findings "
            "and the approved criterion"
        )
    reference = approval.get("reference")
    if cold_810_approved:
        approval_scope.update(schema=S07_COLD_810_APPROVAL_SCHEMA,
                              cold_810_finding=S07_COLD_810_FINDING)
        approval_error = (
            "S07 v3 approval must cover exactly the nine S07 findings and the cold 810 finding"
        )
    require(
        isinstance(reference, str) and bool(reference.strip())
        and approval == {**approval_scope, "reference": reference},
        approval_error,
    )
    if cold_810_approved:
        decision_comment = re.fullmatch(
            rf"https://github\.com/{re.escape(REPOSITORY)}/(?:issues|pull)/[1-9][0-9]*"
            r"#(issuecomment-[1-9][0-9]*)",
            reference,
        )
        require(
            decision_comment is not None and decision_comment[1] != S07_V2_APPROVAL_COMMENT,
            "S07 v3 requires a separate authenticated cold 810 decision",
        )
    require(
        set(evidence) == {"snapshot_sha256", "findings_complete", "findings", "cpu_jobs", "matrix"}
        and evidence["snapshot_sha256"] == snapshot["report_sha256"]
        and evidence["findings_complete"] is True,
        "S07 evidence must bind the current snapshot and complete finding inventory",
    )
    findings = evidence["findings"]
    require(
        isinstance(findings, dict)
        and all(findings.get(key) == value for key, value in original_findings.items()),
        "All four original S07 findings and their outcomes are required",
    )
    require(
        all(
            findings.get(key) == value
            and type(findings[key]["run_id"]) is int
            and type(findings[key]["job_id"]) is int
            for key, value in additional_findings.items()
        ),
        "All five additional S07 findings and their original outcomes are required",
    )
    if cold_810_approved:
        cold_810 = findings.get(S07_COLD_810_FINDING)
        require(
            cold_810 == S07_COLD_810_RECORD
            and all(
                type(cold_810[key]) is int
                for key in ("run_id", "attempt", "job_id", "arm_index", "sample", "artifact_id")
            )
            and cold_810["qualification_eligible"] is False,
            "The exact S07 cold 810 finding and its original outcome are required",
        )
    windows_findings = {}
    if windows_approved:
        require(cold_810_approved, "S07 Windows acquisition requires the separate v3 approval")
        windows_findings = validate_s07_windows_acquisition(
            qualification["windows_acquisition_approval"], snapshot, findings, git, reference,
            trusted_windows_acquisition_approval,
        )
    remaining_findings = {
        key: value for key, value in findings.items()
        if key not in original_findings and key not in additional_findings
        and (not cold_810_approved or key != S07_COLD_810_FINDING)
        and key not in windows_findings
    }
    require(
        all(
            key.strip() and isinstance(value, dict)
            and value.get("status") in ("CURRENT", "UNKNOWN")
            for key, value in remaining_findings.items()
        ),
        "Invalid open or unresolved S07 finding",
    )
    statuses = {finding["status"] for finding in remaining_findings.values()}
    finding_state = "UNKNOWN" if "UNKNOWN" in statuses else "CURRENT" if statuses else "NONE"

    head = snapshot["head_sha"]
    matrix = evidence["matrix"]
    require(
        isinstance(matrix, dict)
        and set(matrix) == {"report", "sha256"}
        and isinstance(matrix["report"], dict)
        and digest(matrix["report"]) == matrix["sha256"]
        and matrix["report"].get("source_commit") == head
        and matrix["report"].get("automatic") == "PASS"
        and matrix["report"].get("installed_runtime") == "PASS",
        "Verified S07 automatic and installed runtime matrix evidence required",
    )
    require(
        git("rev-parse", head + ":scripts/ai_runtime_report.py") == S07_EVALUATOR,
        "S07 qualification evaluator differs from the original",
    )
    verify_s07_cpu_jobs(evidence["cpu_jobs"], head)
    result = {
        "approval_sha256": trusted_approval,
        "evidence_sha256": trusted_evidence,
        "historical_findings": original_findings,
        "remaining_findings": remaining_findings,
        "candidate_finding": finding_state,
    }
    if additional_findings:
        result["additional_historical_findings"] = additional_findings
    if cold_810_approved:
        result["cold_810_finding"] = {S07_COLD_810_FINDING: findings[S07_COLD_810_FINDING]}
    if windows_approved:
        result["windows_acquisition_approval_sha256"] = trusted_windows_acquisition_approval
        result["windows_acquisition_findings"] = windows_findings
    return result


def legacy_base_preflight(
    snapshot,
    binding,
    effects,
    observations,
    *,
    repository_path,
    expected_head,
    trusted_binding,
    trusted_observations,
    trusted_s07_approval=None,
    trusted_s07_evidence=None,
    trusted_s07_windows_acquisition_approval=None,
    output_path=None,
):
    """Provelume PR-local extension; never projects or edits a historical receipt."""
    spec = importlib.util.spec_from_file_location(
        "legacy_base_native", Path(__file__).with_name("agent_protocol.py")
    )
    native = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native)
    require(binding.get("report_sha256") == trusted_binding, "Original BIND identity changed")
    native.validate_binding(binding, snapshot.get("policy_context"))
    original_authority = binding.get("policy_resolution", {}).get("production_authority")
    current_authority = snapshot["policy_context"]["production_authority"]
    require(
        isinstance(original_authority, dict)
        and set(original_authority) == set(current_authority) == {"production", "deploy", "migrate"}
        and all(type(v) is bool for v in original_authority.values())
        and all(not current_authority[k] or original_authority[k] for k in original_authority),
        "Original authority unavailable or current capabilities increased",
    )
    require(digest(observations) == trusted_observations, "Observed source bytes changed")
    observation_fields = {
        "schema", "observed_at", "repository", "pr", "default", "candidate",
        "test_merge", "files", "files_complete",
    }
    schema = observations.get("schema")
    s07_scope = schema == "provelume-base-observations/v2"
    if s07_scope:
        observation_fields.add("s07_qualification")
    else:
        require(
            trusted_s07_approval is None and trusted_s07_evidence is None
            and trusted_s07_windows_acquisition_approval is None,
            "S07 trust anchors require v2 observations",
        )
    require(
        schema in ("provelume-base-observations/v1", "provelume-base-observations/v2")
        and set(observations) == observation_fields,
        "Unknown base-advance observations",
    )
    native.require_fresh(observations["observed_at"])
    errors = native.validate_snapshot_identity(snapshot)
    require(not errors, "Invalid current snapshot: " + "; ".join(errors))
    native.require_sha(expected_head, "expected_head")
    pr, repository = observations["pr"], observations["repository"]
    base, head = pr["base"]["sha"], pr["head"]["sha"]
    original_base, basis = binding["base_sha"], binding["binding_basis_sha"]
    for sha in (base, head, original_base, basis):
        native.require_sha(sha, "base-advance coordinate")
    require(
        (repository["full_name"], repository["id"], repository["default_branch"])
        == (REPOSITORY, REPOSITORY_ID, "main"),
        "Observed repository identity changed",
    )
    require(
        pr["base"]["repo"]["id"] == pr["head"]["repo"]["id"] == REPOSITORY_ID
        and pr["base"]["repo"]["full_name"] == pr["head"]["repo"]["full_name"] == REPOSITORY,
        "Observed PR repository changed",
    )
    require(
        pr["base"]["ref"] == "main"
        and observations["default"]["ref"] == "refs/heads/main"
        and observations["default"]["object"]["sha"] == base,
        "PR base is not the actual current default",
    )
    require(original_base != base, "No base advancement; use the original preflight")
    comparisons = {
        "owner_pr": f"#{pr['number']}",
        "head_sha": expected_head,
        "base_sha": base,
        "default_sha": base,
        "binding_basis_sha": basis,
        "effect_report_sha256": binding["effect_report_sha256"],
        "pr_state": pr["state"].upper(),
        "draft": str(pr["draft"]).upper(),
        "mergeability": (
            "MERGEABLE"
            if pr["mergeable"] is True
            else "CONFLICTING"
            if pr["mergeable"] is False
            else "UNKNOWN"
        ),
    }
    require(head == expected_head, "Observed PR head moved")
    require(binding["active_pr"] == comparisons["owner_pr"], "Original owner PR changed")
    for key, value in comparisons.items():
        require(snapshot.get(key) == value, "Current snapshot/observation mismatch: " + key)

    # These are fixed, offline Git reads. Ignore ambient Git redirections and
    # credential/config helpers; refuse lazy fetching, replacements and fsmonitor.
    allowed_environment = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR",
        "LANG", "LC_ALL", "LC_CTYPE",
    }
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed_environment}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_NO_LAZY_FETCH="1",
        GIT_ALLOW_PROTOCOL="",
        GIT_TERMINAL_PROMPT="0",
        GIT_OPTIONAL_LOCKS="0",
    )
    proofs = []

    def git(*arguments, record=True, failure=None):
        result = subprocess.run(
            [
                "git",
                "--no-replace-objects",
                "--no-pager",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(repository_path),
                *arguments,
            ],
            env=environment,
            capture_output=True,
            check=False,
            timeout=30,
        )
        require(result.returncode == 0, failure or "Local Git proof failed: " + arguments[0])
        require(len(result.stdout) <= 4 * 1024 * 1024, "Unbounded local Git proof")
        value = result.stdout.decode("utf-8", errors="strict")
        if record:
            proofs.append({"arguments": list(arguments), "stdout": value})
        return value.rstrip("\r\n")

    # Config names can be inspected without loading includes or invoking drivers.
    # Refuse worktree-specific config too: --local alone cannot inventory it.
    names = git("config", "--local", "--no-includes", "--name-only", "--list").splitlines()
    require(
        not any(
            name.casefold().startswith(("filter.", "include.", "includeif."))
            or name.casefold() == "extensions.worktreeconfig"
            for name in names
        ),
        "Executable or included Git configuration refused",
    )
    entries = git("ls-files", "-v", "--stage", "-z").rstrip("\0").split("\0")
    for entry in entries:
        header = entry.split("\t", 1)[0].split()
        require(
            len(header) == 4
            and header[0] == "H"
            and header[1] in {"100644", "100755", "120000"}
            and header[3] == "0",
            "Masked, sparse or non-file index entry refused",
        )
    root = Path(git("rev-parse", "--show-toplevel")).resolve(strict=True)
    require(root == repository_path.resolve(strict=True), "Exact checkout root required")
    if output_path is not None:
        output_path = Path(output_path).absolute()
        require(
            not any(p.is_symlink() or p.is_junction() for p in (output_path, *output_path.parents)),
            "Receipt destination must not traverse links",
        )
        require(not output_path.exists(), "Receipt destination already exists; preserve evidence")
        require(output_path.parent.is_dir(), "Receipt destination parent must exist")
        output_path = output_path.resolve()
        for metadata in (
            git("rev-parse", "--absolute-git-dir"),
            git("rev-parse", "--path-format=absolute", "--git-common-dir"),
        ):
            require(
                not output_path.is_relative_to(Path(metadata).resolve()),
                "Receipt destination must be outside Git metadata",
            )
        if output_path.is_relative_to(root):
            relative = output_path.relative_to(root)
            require(
                len(relative.parts) > 1 and relative.parts[0] == ".agent",
                "Receipt destination must be outside source or in ignored .agent evidence",
            )
            git(
                "check-ignore", "--quiet", "--no-index", "--", relative.as_posix(),
                failure="Receipt destination must be ignored .agent evidence",
            )

    require(git("rev-parse", "--is-shallow-repository") == "false", "Complete history required")
    require(not git("for-each-ref", "refs/replace/"), "Replaced history refused")
    grafts = Path(git("rev-parse", "--path-format=absolute", "--git-path", "info/grafts"))
    require(not grafts.exists(), "Grafted history refused")
    require(
        git("config", "--get", "remote.origin.url") == "https://github.com/gabned/provelume.git",
        "Local repository origin changed",
    )
    require(git("rev-parse", "HEAD") == head, "Local candidate head moved")
    require(git("symbolic-ref", "--short", "HEAD") == pr["head"]["ref"], "PR branch changed")
    require(not git("status", "--porcelain", "--untracked-files=all"), "Dirty candidate refused")
    for ancestor, descendant in (
        (original_base, base),
        (base, head),
        (basis, head),
    ):
        git("merge-base", "--is-ancestor", ancestor, descendant)
    history = git("rev-list", "--topo-order", "--parents", head, "^" + original_base)
    require(bool(history), "Missing candidate ancestry")
    candidate, test_merge = observations["candidate"], observations["test_merge"]
    require(candidate["sha"] == head, "Candidate object identity changed")
    tree = git("rev-parse", head + "^{tree}")
    require(candidate["tree"]["sha"] == tree, "Candidate tree changed")
    require(
        [p["sha"] for p in candidate["parents"]] == git("show", "-s", "--format=%P", head).split(),
        "Candidate parent list changed",
    )
    require(
        test_merge["sha"] == pr["merge_commit_sha"]
        and [p["sha"] for p in test_merge["parents"]] == [base, head]
        and test_merge["tree"]["sha"] == tree,
        "Test merge does not prove the exact current base/head/tree",
    )
    require(
        git("show", "-s", "--format=%P", test_merge["sha"]).split() == [base, head]
        and git("rev-parse", test_merge["sha"] + "^{tree}") == tree,
        "Local test merge differs from the observed object",
    )
    require(observations["files_complete"] is True, "Incomplete observed delta")
    files = observations["files"]
    require(
        isinstance(files, list)
        and len(files) == pr["changed_files"]
        and len({f["filename"] for f in files}) == len(files),
        "Incomplete or duplicate PR file inventory",
    )
    observed_paths = sorted(
        set(
            native.connector_paths(
                [
                    {"filename": row["filename"], "previous_path": row.get("previous_filename")}
                    for row in files
                ]
            )
        )
    )
    local_paths = sorted(
        git(
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            "--no-ext-diff",
            "--no-textconv",
            base,
            head,
        )
        .rstrip("\0")
        .split("\0")
    )
    require(observed_paths == local_paths, "Observed delta differs from the complete Git delta")
    native.verify_effect_report(
        effects,
        base_sha=base,
        head_sha=head,
        policy=binding["effect_policy"],
    )
    require(effects["changed_paths"] == local_paths, "Current effects cover a different delta")
    require(
        effects["effect"] == binding["effect_prediction"],
        "Changed effect prediction requires separate Protocol triage",
    )

    # A distinct current receipt evaluates the gates on the untouched real
    # snapshot. The historical refusal is retained below, never filtered/resealed.
    for key, accepted in {
        "pr_state": "OPEN",
        "draft": "FALSE",
        "checks": "SUCCESS",
        "mergeability": "MERGEABLE",
        "base_ancestry": "TRUE",
        "binding_basis_ancestor": "TRUE",
        "credentials_accessed": False,
        "production_environment_accessed": False,
    }.items():
        if snapshot.get(key) != accepted or type(snapshot.get(key)) is not type(accepted):
            errors.append("Current gate blocks: " + key)
    if type(snapshot.get("unresolved_threads")) is not int or snapshot["unresolved_threads"] != 0:
        errors.append("Current unresolved thread count blocks")
    review = native.normalize_review_snapshot(snapshot)
    candidate_finding = review["technical_finding"]
    if s07_scope:
        s07_receipt = validate_s07_finding_applicability(
            observations["s07_qualification"], snapshot, binding, review, git,
            trusted_approval=trusted_s07_approval, trusted_evidence=trusted_s07_evidence,
            trusted_windows_acquisition_approval=trusted_s07_windows_acquisition_approval,
        )
        candidate_finding = s07_receipt["candidate_finding"]
    review_result = native.evaluate_review_gate(
        source=review["source"],
        codex_state=review["codex_state"],
        repository=REPOSITORY,
        owner_pr=binding["active_pr"],
        current_head=head,
        reviewed_head=review["reviewed_head"],
        repository_review=review["repository_review"],
        technical_finding=candidate_finding,
        withdrawal=review["withdrawal"],
    )
    errors.extend(review_result["errors"])
    historical = native.preflight(snapshot, binding)
    # Recheck mutable local identity at the observation boundary. The host must
    # independently refresh GitHub at the actual authorized action boundary.
    require(git("rev-parse", "HEAD") == head, "Local candidate moved during proof")
    require(not git("status", "--porcelain", "--untracked-files=all"), "Candidate became dirty")
    result = native.seal(
        {
            "schema": (
                "provelume-legacy-base-preflight/v2" if s07_scope
                else "provelume-legacy-base-preflight/v1"
            ),
            **({"s07_qualification": s07_receipt} if s07_scope else {}),
            "mode": "PREFLIGHT_BASE_ADVANCE",
            "repository": REPOSITORY,
            "observed_at": native.now_utc(),
            "owner_pr": binding["active_pr"],
            "workstream": binding["workstream"],
            "binding_sha256": trusted_binding,
            "original_base_sha": original_base,
            "binding_basis_sha": basis,
            "current_base_sha": base,
            "head_sha": head,
            "tree_sha": tree,
            "snapshot_sha256": snapshot["report_sha256"],
            "observations_sha256": trusted_observations,
            "current_effect_report_sha256": effects["report_sha256"],
            "protocol_identity": "BASE_ADVANCE_PROVEN",
            "historical_preflight": historical,
            "review_governance": review_result,
            "git_proofs": proofs,
            "result": "BLOCKED" if errors else "READY",
            "merge_ready": not errors,
            "errors": errors,
            "new_capabilities": [],
            "binding_mutated": False,
            "lifecycle_v2_activated": False,
        }
    )
    if output_path is not None:
        # Exclusive creation preserves earlier receipts. Recheck after the actual
        # write; a concurrent source change leaves a BLOCKED receipt, never READY.
        with output_path.open("x+", encoding="utf-8") as stream:
            json.dump(result, stream, sort_keys=True)
            stream.flush()
            try:
                require(
                    git("rev-parse", "HEAD", record=False) == head,
                    "Candidate moved while publishing receipt",
                )
                require(
                    not git("status", "--porcelain", "--untracked-files=all", record=False),
                    "Candidate became dirty while publishing receipt",
                )
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                result = native.seal(
                    {
                        **{k: v for k, v in result.items() if k != "report_sha256"},
                        "result": "BLOCKED",
                        "merge_ready": False,
                        "errors": [*result["errors"], str(error)],
                    }
                )
                stream.seek(0)
                json.dump(result, stream, sort_keys=True)
                stream.truncate()
    return result


def bind_product_host(
    journal, *, collect_native, native_authority, merge_native, collect_recovery_native
):
    """Bind the repository's accepted PRODUCT host to the canonical journal engine.

    These are authenticated host capabilities, never candidate JSON, executable
    paths or PR-body fields. Native qualification/release/consent stays local.
    """
    pin = verify()
    from agent_protocol.host import ProtocolHost

    identity = journal.read()["identity"]
    require(
        (identity["repository"], identity["repository_id"], identity["workstream_class"])
        == (REPOSITORY, REPOSITORY_ID, "PRODUCT"),
        "Native PRODUCT identity changed",
    )
    require(
        all(
            callable(value)
            for value in (collect_native, native_authority, merge_native, collect_recovery_native)
        ),
        "Complete independently accepted native host capabilities required",
    )

    def authority(state):
        current = native_authority(state)
        require(
            current["identity"] == identity and current["pin"] == pin["operational_revision"],
            "Native authority/source differs from accepted consumer pin",
        )
        require(
            current["policy"]["selected"] == "REPOSITORY_POLICY"
            and current["policy"]["contract"]["routing"] == "PRODUCT/v2",
            "Native PRODUCT policy cannot downgrade to Protocol-only checks",
        )
        require(
            {"CI", "NATIVE", "REVIEWS", "EFFECTS", "ANCESTRY", "SOURCE", "AUTHORIZATION"}
            <= set(current["policy"]["required_gates"]),
            "Complete native PRODUCT gate inventory required",
        )
        return current

    # Fail before exposing a write interface if the accepted route is incomplete.
    authority(journal.read())
    return ProtocolHost(
        journal,
        collect=collect_native,
        authority=authority,
        merge=merge_native,
        collect_recovery=collect_recovery_native,
    )


def workspace(action):
    """Native Provelume profile, invoked only inside the isolated project image."""
    require(REPOSITORY == "gabned/provelume" and os.name == "posix", "Native profile differs")
    wheels = Path("/opt/native-wheels")
    inventory = json.loads(read(wheels / "inventory.json"))
    editable = json.loads(read(wheels / "editable-requirements.json"))
    require(
        isinstance(editable, list)
        and editable
        and all(
            isinstance(item, str)
            and item
            and not any(c in item for c in "/\\:@\n\r")
            and not item.startswith("-")
            for item in editable
        ),
        "Invalid native backend requirements",
    )
    require(
        inventory and set(inventory) == {p.name for p in wheels.glob("*.whl")},
        "Complete native dependency inventory required",
    )
    for name, expected in inventory.items():
        require(Path(name).name == name and name.endswith(".whl"), "Invalid native wheel")
        require(
            hashlib.sha256(read(wheels / name)).hexdigest() == expected,
            "Native dependency cache changed",
        )
    temporary = ROOT / ".agent"
    require(not temporary.is_symlink(), "Native workspace cache symlink refused")
    temporary.mkdir(exist_ok=True)
    environment = temporary / "lab-venv"
    marker = temporary / "lab-environment.json"
    binding = {
        "repository": REPOSITORY,
        "runtime": sys.version,
        "pyproject_sha256": hashlib.sha256(read(ROOT / "pyproject.toml")).hexdigest(),
        "wheels_sha256": digest(inventory),
        "editable_requirements_sha256": digest(editable),
    }
    if marker.exists():
        require(
            json.loads(read(marker)) == binding, "Existing native environment differs; preserve it"
        )
    else:
        require(not environment.exists(), "Unmanaged native environment preserved")
        with marker.open("x", encoding="utf-8") as stream:
            json.dump(binding, stream, sort_keys=True)
    require(not environment.is_symlink(), "Native environment symlink refused")
    if not environment.exists():
        require(action == "prepare", "Prepare the native environment before execution")
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    python = environment / "bin/python"
    require(python.is_file(), "Interrupted native preparation requires reconciliation")
    if action == "prepare":
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheels),
                "--require-hashes",
                "-r",
                str(ROOT / "build-lock/ubuntu-py312-x86_64.requirements.txt"),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(wheels),
                *editable,
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-build-isolation",
                "--find-links",
                str(wheels),
                "-e",
                ".[dev]",
            ],
            cwd=ROOT,
            check=True,
        )
        return {"native_environment": "PREPARED", "gates": "NOT_REPLACED"}
    if action == "check":
        subprocess.run(
            [
                str(python),
                "-m",
                "ruff",
                "check",
                "--cache-dir",
                str(temporary / "ruff-cache"),
                "core",
                "tests",
                "scripts",
                "tools",
                "packaging",
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run([str(python), "-m", "pytest", "-q"], cwd=ROOT, check=True)
        subprocess.run(["git", "diff", "--check"], cwd=ROOT, check=True)
        return {"native_checks": "PASS", "remote_qualification": "REQUIRED"}
    instance = temporary / "lab-synthetic-instance"
    require(not instance.is_symlink(), "Synthetic instance symlink refused")
    if not instance.exists():
        subprocess.run(
            [
                str(python),
                "-m",
                "provelume",
                "init",
                str(instance),
                "--name",
                "Synthetic development instance",
            ],
            cwd=ROOT,
            check=True,
        )
    # Preserve the product's loopback-only serving policy. No public/listen-all
    # override or production endpoint is introduced for convenience.
    subprocess.run(
        [
            str(python),
            "-m",
            "provelume",
            "serve",
            str(instance),
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        cwd=ROOT,
        check=True,
    )
    return {"native_runtime": "STOPPED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    acquisition = sub.add_parser("acquire")
    acquisition.add_argument("--offline", action="store_true")
    docs = sub.add_parser("documents")
    docs.add_argument("--phase", required=True)
    docs.add_argument("--host", required=True)
    docs.add_argument("--workstream", required=True)
    engine = sub.add_parser("engine")
    engine.add_argument("arguments", nargs=argparse.REMAINDER)
    collector = sub.add_parser("collect")
    collector.add_argument("arguments", nargs=argparse.REMAINDER)
    guard = sub.add_parser("event-guard")
    guard.add_argument("--event", type=Path, required=True)
    guard.add_argument("--current-pr", type=Path, required=True)
    guard.add_argument("--name-status", type=Path, required=True)
    guard.add_argument("--expected-base-sha", required=True)
    guard.add_argument("--expected-head-sha", required=True)
    guard.add_argument("--complete", action="store_true")
    guard.add_argument("--output", type=Path)
    legacy = sub.add_parser("legacy-base-preflight")
    for name in ("snapshot", "binding", "effects", "observations", "repository-path"):
        legacy.add_argument("--" + name, type=Path, required=True)
    for name in ("expected-head", "binding-sha256", "observations-sha256"):
        legacy.add_argument("--" + name, required=True)
    legacy.add_argument("--s07-approval-sha256")
    legacy.add_argument("--s07-evidence-sha256")
    legacy.add_argument("--s07-windows-acquisition-approval-sha256")
    legacy.add_argument("--output", type=Path)
    native_workspace = sub.add_parser("workspace")
    native_workspace.add_argument("action", choices=["prepare", "check", "start"])
    args = parser.parse_args(argv)
    try:
        pin = verify()
        if args.command == "verify":
            result = {
                "result": "BYTES_VERIFIED",
                "repository": REPOSITORY,
                "revision": pin["operational_revision"],
                "files": len(pin["source_manifest"]["files"]),
                "authority": "REQUIRES_ACCEPTED_BASE_AND_AUTHENTICATED_SOURCE",
            }
        elif args.command == "documents":
            result = documents(pin, args.phase, args.host, args.workstream)
        elif args.command == "acquire":
            result = acquire(pin, offline=args.offline)
        elif args.command == "workspace":
            result = workspace(args.action)
        elif args.command == "legacy-base-preflight":
            result = legacy_base_preflight(
                json.loads(read(args.snapshot)),
                json.loads(read(args.binding)),
                json.loads(read(args.effects)),
                parse_legacy_observations(read(args.observations)),
                repository_path=args.repository_path,
                expected_head=args.expected_head,
                trusted_binding=args.binding_sha256,
                trusted_observations=args.observations_sha256,
                trusted_s07_approval=args.s07_approval_sha256,
                trusted_s07_evidence=args.s07_evidence_sha256,
                trusted_s07_windows_acquisition_approval=args.s07_windows_acquisition_approval_sha256,
                output_path=args.output,
            )
            print(json.dumps(result, sort_keys=True))
            return 0 if result["merge_ready"] else 1
        elif args.command == "event-guard":
            require(REPOSITORY == "gabned/provelume", "Accepted local event adapter required")
            event = json.loads(read(args.event))
            require(
                (event["repository"]["full_name"], event["repository"]["id"])
                == (REPOSITORY, REPOSITORY_ID),
                "Event repository identity changed",
            )
            spec = importlib.util.spec_from_file_location(
                "native_change_control", ROOT / "tools/agent_protocol.py"
            )
            native = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(native)
            event = native.bind_current_pr_body(event, json.loads(read(args.current_pr)))
            result = native.build_change_control_report(
                event=event,
                changed_paths=native.read_name_status(args.name_status),
                expected_base_sha=args.expected_base_sha,
                expected_head_sha=args.expected_head_sha,
                complete=args.complete,
                credentials_accessed=False,
                production_environment_accessed=False,
            )
            if args.output:
                require(not args.output.exists(), "Preserve existing guard evidence")
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(result, stream, sort_keys=True)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["merge_allowed"] else 1
        elif args.command == "engine":
            from agent_protocol.cli import main as core_main

            return core_main(args.arguments)
        else:
            return subprocess.run(
                ["node", str(VENDOR / "tools/collect.mjs"), *args.arguments], check=False
            ).returncode
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, KeyError, OSError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps({"result": "REFUSED", "reason": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
