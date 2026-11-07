"""Optional one-way Git over complete mirror generations; hosted profiles are separate."""

from __future__ import annotations

import os
import re
import stat
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from .maintenance_local_files import directory_binding, open_local_directory, pinned_parent
from .migration_permissions import make_private
from .mirror_contract import (
    HASH,
    MAX_FILES,
    MAX_MANIFEST_BYTES,
    fingerprint,
    inventory,
    parse,
    raw,
    require,
    sha,
)
from .mirror_git_runtime import MAX_OBJECT_BYTES, MAX_OBJECT_FILES, GitSession
from .mirror_git_target import (
    MARKER,
    audit_bare_root,
    exclude_instance_tree,
    local_target,
    target_configuration,
)
from .mirrors import Mirrors
from .paths import native_path
from .storage import InstanceStore


@contextmanager
def git_work(*, descriptors=(), deadline=None):
    with TemporaryDirectory(prefix="provelume-mirror-git-") as temporary:
        work = Path(temporary)
        make_private(work)
        yield GitSession(work, inherited_directories=descriptors, deadline=deadline)


def remote_ref(session, uri, branch):
    ref = "refs/heads/" + branch
    data = session.run(["ls-remote", "--refs", "--", uri, ref])[1]
    if not data.strip():
        return None
    rows = data.decode("ascii").splitlines()
    require(len(rows) == 1 and rows[0].endswith("\t" + ref), "git_ref")
    oid = rows[0].split("\t", 1)[0]
    require(re.fullmatch(r"[0-9a-f]{40}", oid), "git_object_format")
    return oid


def fetch_ref(session, uri, branch, expected):
    if expected is None:
        return {}
    # This is an owned disposable observation ref, never a destination branch.
    # A prior shallow observation cannot establish ancestry for the next fetch.
    session.run(["update-ref", "-d", "refs/provelume/observed"])
    session.run(
        [
            "fetch",
            "--no-tags",
            "--no-write-fetch-head",
            "--depth=1",
            "--",
            uri,
            "refs/heads/" + branch + ":refs/provelume/observed",
        ],
        monitor_storage=True,
    )
    actual = session.run(["rev-parse", "--verify", "refs/provelume/observed^{commit}"])[1]
    require(actual.strip().decode("ascii") == expected, "destination_changed")
    return tree_entries(session, expected)


def tree_entries(session, expected):
    data = session.run(["ls-tree", "-r", "-z", expected], payload_limit=MAX_MANIFEST_BYTES)[1]
    records = {}
    for entry in data.split(b"\0"):
        if not entry:
            continue
        header, name = entry.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split(" ")
        selected = name.decode("utf-8")
        require(
            mode in {"100644", "100755"} and kind == "blob" and re.fullmatch(r"[0-9a-f]{40}", oid),
            "git_tree",
        )
        pure = PurePosixPath(selected)
        require(
            not pure.is_absolute()
            and pure.as_posix() == selected
            and not any(part in {".", "..", ".git"} for part in pure.parts)
            and "\\" not in selected
            and len(selected) <= 512,
            "git_path",
        )
        require(selected not in records and len(records) < MAX_FILES, "limit")
        records[selected] = {"mode": mode, "oid": oid}
    require(len({name.casefold() for name in records}) == len(records), "git_path")
    return records


def active_generation(session, entries, prefix):
    active = prefix + "/active.json"
    if active not in entries:
        require(not any(name.startswith(prefix + "/") for name in entries), "git_active_unknown")
        return None, []
    require(entries[active]["mode"] == "100644", "git_tree")
    pointer = parse(session.blob(entries[active]["oid"], maximum=4096))
    require(
        set(pointer) == {"schema", "generation", "manifest_sha256", "inventory_sha256"}
        and pointer["schema"] == "provelume-git-active/v1",
        "git_active_unknown",
    )
    generation = pointer["generation"]
    require(type(generation) is str and HASH.fullmatch(generation), "git_active_unknown")
    base = prefix + "/generations/" + generation + "/"
    manifest_entry = entries.get(base + "manifest.json")
    require(manifest_entry is not None and manifest_entry["mode"] == "100644", "git_incomplete")
    manifest = parse(session.blob(manifest_entry["oid"], maximum=MAX_MANIFEST_BYTES))
    require(
        fingerprint(manifest) == generation == pointer["manifest_sha256"]
        and manifest.get("schema") == "provelume-mirror-generation/v1"
        and manifest.get("complete") is True
        and manifest.get("canonical") is False,
        "git_incomplete",
    )
    payload = inventory(manifest["inventory"])
    require(pointer["inventory_sha256"] == fingerprint(payload), "git_incomplete")
    expected = {base + row["path"] for row in payload} | {base + "manifest.json"}
    require({name for name in entries if name.startswith(base)} == expected, "git_incomplete")
    blobs = []
    for row in payload:
        entry = entries.get(base + row["path"])
        require(entry is not None and entry["mode"] == "100644", "git_incomplete")
        blobs.append({**row, "oid": entry["oid"]})
    session.verify_blobs(blobs)
    return generation, payload


def build_commit(session, *, mirrors, plan, git_plan, target, entries):
    manifest = mirrors.snapshots.verify(plan["generation"])
    base = target["path"] + "/generations/" + plan["generation"] + "/"
    additions = {}
    for entry in manifest["inventory"]:
        source = mirrors.snapshots.root() / plan["generation"] / entry["path"]
        data = native_path(source).read_bytes()
        require(len(data) == entry["size_bytes"] and sha(data) == entry["sha256"], "integrity")
        additions[base + entry["path"]] = data
    additions[base + "manifest.json"] = raw(manifest)
    pointer = {
        "schema": "provelume-git-active/v1",
        "generation": plan["generation"],
        "manifest_sha256": fingerprint(manifest),
        "inventory_sha256": fingerprint(manifest["inventory"]),
    }
    additions[target["path"] + "/active.json"] = raw(pointer)
    require(len(set(entries) | set(additions)) <= MAX_FILES, "limit")
    if git_plan["head"] is None:
        session.run(["read-tree", "--empty"])
    else:
        session.run(["read-tree", git_plan["head"]])
    names = sorted(additions)
    object_ids = {}
    existing_blobs = []
    for name, data in additions.items():
        selected = session.work / "payload" / name
        native_path(selected.parent).mkdir(parents=True, exist_ok=True)
        native_path(selected).write_bytes(data)
        if name in entries and name.startswith(base):
            require(entries[name]["mode"] == "100644", "git_generation_changed")
            existing_blobs.append(
                {"oid": entries[name]["oid"], "size_bytes": len(data), "sha256": sha(data)}
            )
    session.verify_blobs(existing_blobs)
    for offset in range(0, len(names), 1000):
        batch = names[offset : offset + 1000]
        paths = "".join("payload/" + name + "\n" for name in batch).encode()
        output = session.run(
            ["hash-object", "-w", "--stdin-paths", "--no-filters"],
            input_bytes=paths,
            monitor_storage=True,
        )[1]
        hashes = output.decode("ascii").splitlines()
        require(
            len(hashes) == len(batch) and all(re.fullmatch(r"[0-9a-f]{40}", oid) for oid in hashes),
            "git_object_format",
        )
        object_ids.update(zip(batch, hashes, strict=True))
    index = b"".join(("100644 " + object_ids[name] + "\t" + name + "\0").encode() for name in names)
    session.run(["update-index", "--add", "-z", "--index-info"], input_bytes=index)
    tree = session.run(["write-tree"])[1].strip().decode("ascii")
    require(re.fullmatch(r"[0-9a-f]{40}", tree), "git_object_format")
    timestamp = "@" + str(int(datetime.fromisoformat(plan["created_at"]).timestamp())) + " +0000"
    session.environment.update(
        {
            "GIT_AUTHOR_NAME": target["commit_name"],
            "GIT_AUTHOR_EMAIL": target["commit_email"],
            "GIT_COMMITTER_NAME": target["commit_name"],
            "GIT_COMMITTER_EMAIL": target["commit_email"],
            "GIT_AUTHOR_DATE": timestamp,
            "GIT_COMMITTER_DATE": timestamp,
        }
    )
    parents = [] if git_plan["head"] is None else ["-p", git_plan["head"]]
    candidate = (
        session.run(
            ["commit-tree", tree, *parents],
            input_bytes=(
                "Provelume mirror " + plan["generation"] + "\n\nOperation " + plan["id"] + "\n"
            ).encode(),
        )[1]
        .strip()
        .decode("ascii")
    )
    require(re.fullmatch(r"[0-9a-f]{40}", candidate), "git_object_format")
    # This independent parent proof limits the explicit ref lease to fast-forward.
    commit = session.run(["cat-file", "-p", candidate])[1].decode("utf-8")
    actual_parents = [
        line[7:] for line in commit.split("\n\n", 1)[0].splitlines() if line.startswith("parent ")
    ]
    require(
        actual_parents == ([] if git_plan["head"] is None else [git_plan["head"]]),
        "git_not_fast_forward",
    )
    return candidate


def admit_target_growth(directory, manifest):
    # Conservative pre-send bound: even copying the complete new payload plus
    # pack/index overhead must fit the already fixed destination admission cap.
    sizes = [item.stat().st_size for item in directory.rglob("*") if item.is_file()]
    require(
        sum(sizes) + manifest["total_bytes"] + MAX_MANIFEST_BYTES + 32 * 1024 * 1024
        <= MAX_OBJECT_BYTES,
        "git_storage_limit",
    )
    require(len(sizes) + len(manifest["inventory"]) + 16 <= MAX_OBJECT_FILES, "git_storage_limit")


class GitMirrors:
    def __init__(self, store, *, mirrors=None):
        self.store = store
        self.mirrors = mirrors or Mirrors(store)

    def context(self, destination_id, *, inspection_operation=None, scheduled=False):
        with self.mirrors.guard():
            row, authority = self.mirrors.authority(
                destination_id, _inspection_operation=inspection_operation, scheduled=scheduled
            )
            identity = authority["identity"]
            require(identity["profile"] == "git", "git_profile_not_qualified")
            grant = self.mirrors._grant(identity)
            require(grant["credential"] == {"reference": ""}, "git_local_credentials")
            target = grant["destinations"][destination_id]["target"]
            target_configuration(target)
            exclude_instance_tree(Path(target["repository"]), self.store)
            return row, authority, target

    def status(self):
        return {
            "git": "OPTIONAL_NOT_PROBED",
            "network_used": False,
            "process_used": False,
            "hosted_profiles": "NOT_QUALIFIED",
            "publication": "LOCAL_PRIVATE_MANUAL_OR_SCHEDULED",
        }

    def initialize_local(self, destination_id, *, expected_destination_sha256, confirmed):
        require(confirmed is True, "consent_required")
        row, authority, target = self.context(destination_id)
        require(row["destination_sha256"] == expected_destination_sha256, "stale")
        selected = Path(target["repository"])
        with pinned_parent(selected) as (path, parent), git_work() as session:
            require(not path.exists() and not path.is_symlink(), "git_target_exists")
            version = session.probe()
            require(self.mirrors.authority(destination_id)[1] == authority, "stale")
            if os.name == "posix":
                os.mkdir(path.name, 0o700, dir_fd=parent)
                descriptor = os.open(
                    path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                try:
                    info = os.fstat(descriptor)
                    require(
                        stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700,
                        "git_target_privacy",
                    )
                    pinned = Path("/proc/self/fd") / str(descriptor)
                    binding = directory_binding(descriptor)
                    session.directories = (descriptor,)
                    self._initialize_pinned(session, pinned, binding)
                finally:
                    os.close(descriptor)
            else:
                path.mkdir()
                with open_local_directory(path) as (pinned, binding):
                    make_private(pinned)
                    self._initialize_pinned(session, pinned, binding)
            return {
                "status": "initialized",
                "destination_sha256": row["destination_sha256"],
                "root_sha256": fingerprint(binding),
                "git_version": version,
                "network_used": False,
                "canonical_mutation": False,
            }

    def _initialize_pinned(self, session, pinned, binding):
        session.run(["init", "--bare", "--object-format=sha1"], git_directory=pinned)
        marker = {
            "schema": "provelume-local-git-target/v1",
            "instance_id": self.store.read_config()["instance"]["id"],
            "device_sha256": self.mirrors.device(),
            "root_sha256": fingerprint(binding),
        }
        InstanceStore._atomic_bytes(pinned / MARKER, raw(marker))
        audit_bare_root(
            pinned, instance_id=marker["instance_id"], device=self.mirrors.device(), binding=binding
        )

    def prepare(
        self, destination_id, *, expected_revision, confirmed, scheduled=False, _deadline=None
    ):
        require(confirmed is True, "consent_required")
        row, authority, target = self.context(destination_id, scheduled=scheduled)
        require(row["revision"] == expected_revision, "stale")
        with (
            local_target(target, store=self.store, device=self.mirrors.device()) as pinned,
            git_work(descriptors=pinned["descriptors"], deadline=_deadline) as session,
        ):
            version = session.probe()
            session.initialize_work()
            head = remote_ref(session, pinned["uri"], target["branch"])
            entries = fetch_ref(session, pinned["uri"], target["branch"], head)
            generation, payload = active_generation(session, entries, target["path"])
            require(
                remote_ref(session, pinned["uri"], target["branch"]) == head,
                "destination_changed",
            )
            observation = {
                "destination_sha256": row["destination_sha256"],
                "visibility": "private",
                "writable": True,
                "inventory": payload,
                "revision": fingerprint([head, pinned["binding"], pinned["marker"]]),
            }
            with self.mirrors.guard():
                require(self.mirrors.authority(destination_id)[1] == authority, "stale")
                plan = self.mirrors._preview_locked(
                    destination_id,
                    observation,
                    expected_revision=expected_revision,
                    scheduled=scheduled,
                    _deadline=_deadline,
                )
                git_plan = {
                    "schema": "provelume-git-plan/v1",
                    "plan_id": plan["id"],
                    "original_plan_sha256": plan["plan_sha256"],
                    "head": head,
                    "active_generation": generation,
                    "root_sha256": fingerprint(pinned["binding"]),
                    "branch": target["branch"],
                    "path": target["path"],
                    "commit_identity": {
                        "name": target["commit_name"],
                        "email": target["commit_email"],
                    },
                    "git_version": version,
                }
                self.mirrors._save("git/plans/" + plan["id"] + ".json", git_plan)
            return {
                **plan,
                "git_plan": git_plan,
                "git_plan_sha256": fingerprint(git_plan),
                "publication": "PREVIEW_ONLY",
            }

    def git_plan(self, plan_id):
        plan = self.mirrors.plan(plan_id)
        selected = self.mirrors._load("git/plans/" + plan_id + ".json")
        require(
            selected is not None
            and selected.get("schema") == "provelume-git-plan/v1"
            and selected.get("plan_id") == plan_id,
            "git_plan",
        )
        require(
            selected["original_plan_sha256"] == fingerprint({**plan, "state": "prepared"}), "stale"
        )
        return plan, selected

    def reconcile(self, plan_id, *, confirmed):
        """Read-only native proof; absence/old values never authorize a resend."""
        require(confirmed is True, "consent_required")
        require(self.mirrors.access()["enabled"], "local_only")
        plan, git_plan = self.git_plan(plan_id)
        with self.mirrors.guard():
            historical = self.mirrors._recover_terminal_locked(plan_id)
        if historical is not None:
            return {
                "receipt": historical,
                "historical": True,
                "process_used": False,
                "live_destination_checked": False,
            }
        row, authority, target = self.context(plan["destination_id"], inspection_operation=plan_id)
        require(
            {**authority, "operation_serial": plan["authority"]["operation_serial"]}
            == plan["authority"]
            and authority["operation_serial"] == plan["authority"]["operation_serial"] + 1,
            "stale",
        )
        operations = self.mirrors.operation_ledger(
            plan["destination_id"], epoch=authority["grant_epoch"]
        )
        require(operations["inflight"]["plan_sha256"] == git_plan["original_plan_sha256"], "stale")
        with (
            local_target(target, store=self.store, device=self.mirrors.device()) as pinned,
            git_work(descriptors=pinned["descriptors"]) as session,
        ):
            version = session.probe()
            require(
                version == git_plan["git_version"]
                and fingerprint(pinned["binding"]) == git_plan["root_sha256"],
                "stale",
            )
            session.initialize_work()
            observed = remote_ref(session, pinned["uri"], target["branch"])
            if observed is None:
                return {
                    "outcome": "UNKNOWN",
                    "process_used": True,
                    "live_destination_checked": True,
                    "resend_allowed": False,
                }
            entries = fetch_ref(session, pinned["uri"], target["branch"], observed)
            generation, payload = active_generation(session, entries, target["path"])
            if generation != plan["generation"]:
                return {
                    "outcome": "UNKNOWN",
                    "process_used": True,
                    "live_destination_checked": True,
                    "resend_allowed": False,
                }
            noop = git_plan["active_generation"] == plan["generation"]
            if noop:
                candidate = git_plan["head"]
            else:
                original_entries = {}
                if git_plan["head"] is not None:
                    # Fetch the one predeclared original commit, not unbounded history.
                    session.run(
                        [
                            "fetch",
                            "--no-tags",
                            "--no-write-fetch-head",
                            "--depth=1",
                            "--",
                            pinned["uri"],
                            git_plan["head"] + ":refs/provelume/original",
                        ],
                        monitor_storage=True,
                    )
                    original_entries = tree_entries(session, git_plan["head"])
                    active_generation(session, original_entries, target["path"])
                candidate = build_commit(
                    session,
                    mirrors=self.mirrors,
                    plan=plan,
                    git_plan=git_plan,
                    target=target,
                    entries=original_entries,
                )
            if (
                observed != candidate
                or remote_ref(session, pinned["uri"], target["branch"]) != candidate
            ):
                return {
                    "outcome": "UNKNOWN",
                    "process_used": True,
                    "live_destination_checked": True,
                    "resend_allowed": False,
                }
            with self.mirrors.guard():
                # Recheck revocation/global policy after all native reads.
                require(
                    self.mirrors.authority(plan["destination_id"], _inspection_operation=plan_id)[1]
                    == authority,
                    "stale",
                )
                receipt = self.mirrors._complete_locked(
                    plan_id,
                    operation_id=plan_id,
                    observation={
                        "destination_sha256": row["destination_sha256"],
                        "visibility": "private",
                        "writable": True,
                        "inventory": payload,
                        "revision": fingerprint([candidate, pinned["binding"], pinned["marker"]]),
                    },
                    transport_proof={
                        "profile": "git-local/v1",
                        "commit_sha": candidate,
                        "observed_head": observed,
                        "commit_written": not noop,
                        "git_version": version,
                        "evidence_mode": "reconciled_current_state",
                        "publication_time": None,
                    },
                )
            return {
                "receipt": receipt,
                "historical": False,
                "process_used": True,
                "live_destination_checked": True,
                "resend_allowed": False,
            }

    def publish(
        self, plan_id, *, expected_plan_sha256, expected_git_plan_sha256, confirmed, _deadline=None
    ):
        require(confirmed is True, "consent_required")
        plan, git_plan = self.git_plan(plan_id)
        require(
            git_plan["original_plan_sha256"] == expected_plan_sha256
            and fingerprint(git_plan) == expected_git_plan_sha256,
            "stale",
        )
        require(self.mirrors.access()["enabled"], "local_only")
        with self.mirrors.guard():
            historical = self.mirrors._recover_terminal_locked(plan_id)
        if historical is not None:
            return {
                "receipt": historical,
                "historical": True,
                "process_used": False,
                "live_destination_checked": False,
            }
        require(plan["state"] == "prepared", "outcome_unknown")
        row, authority, target = self.context(plan["destination_id"])
        require(
            authority == plan["authority"]
            and target["branch"] == git_plan["branch"]
            and target["path"] == git_plan["path"]
            and git_plan["commit_identity"]
            == {"name": target["commit_name"], "email": target["commit_email"]},
            "stale",
        )
        with (
            local_target(target, store=self.store, device=self.mirrors.device()) as pinned,
            git_work(descriptors=pinned["descriptors"], deadline=_deadline) as session,
        ):
            version = session.probe()
            require(version == git_plan["git_version"], "git_version_changed")
            session.initialize_work()
            head = remote_ref(session, pinned["uri"], target["branch"])
            require(
                head == git_plan["head"]
                and fingerprint(pinned["binding"]) == git_plan["root_sha256"],
                "destination_changed",
            )
            entries = fetch_ref(session, pinned["uri"], target["branch"], head)
            active, payload = active_generation(session, entries, target["path"])
            observation = {
                "destination_sha256": row["destination_sha256"],
                "visibility": "private",
                "writable": True,
                "inventory": payload,
                "revision": fingerprint([head, pinned["binding"], pinned["marker"]]),
            }
            require(observation == plan["observation"], "destination_changed")
            noop = active == plan["generation"]
            if not noop:
                admit_target_growth(
                    pinned["directory"], self.mirrors.snapshots.verify(plan["generation"])
                )
            candidate = (
                head
                if noop
                else build_commit(
                    session,
                    mirrors=self.mirrors,
                    plan=plan,
                    git_plan=git_plan,
                    target=target,
                    entries=entries,
                )
            )
            # Verify every candidate blob before its ref can become visible.
            candidate_generation, candidate_inventory = active_generation(
                session, tree_entries(session, candidate), target["path"]
            )
            require(
                candidate_generation == plan["generation"]
                and candidate_inventory
                == self.mirrors.snapshots.verify(plan["generation"])["inventory"],
                "git_incomplete",
            )
            operation = {
                "schema": "provelume-git-operation/v1",
                "plan_id": plan_id,
                "generation": plan["generation"],
                "expected_ref": head,
                "candidate_sha": candidate,
                "git_plan_sha256": expected_git_plan_sha256,
                "noop": noop,
                "state": "prepared",
            }
            with self.mirrors.guard():
                self.mirrors._save("git/operations/" + plan_id + ".json", operation)
                self.mirrors._claim_locked(
                    plan_id,
                    expected_plan_sha256=expected_plan_sha256,
                    observation=observation,
                    confirmed=True,
                )
            try:
                operation["state"] = "send_started" if not noop else "inspecting_noop"
                self.mirrors._save("git/operations/" + plan_id + ".json", operation)
                if not noop:
                    ref = "refs/heads/" + target["branch"]
                    code, output = session.run(
                        [
                            "push",
                            "--porcelain",
                            "--force-with-lease=" + ref + ":" + (head or ""),
                            "--",
                            pinned["uri"],
                            candidate + ":" + ref,
                        ],
                        check=False,
                    )
                    if code != 0:
                        # This exact native lease rejection is a definitive no-update
                        # response. Other errors and missing/malformed output stay UNKNOWN.
                        records = [line for line in output.splitlines() if line.startswith(b"!\t")]
                        rejected = (
                            len(records) == 1
                            and b"[rejected] (stale info)" in records[0]
                            and records[0].split(b"\t")[1].endswith((":" + ref).encode())
                        )
                        if rejected:
                            with self.mirrors.guard():
                                receipt = self.mirrors._not_applied_locked(
                                    plan_id, reason="conflict", proof_sha256=sha(output)
                                )
                            operation["state"] = "not_applied"
                            self.mirrors._save("git/operations/" + plan_id + ".json", operation)
                            return {
                                "receipt": receipt,
                                "historical": False,
                                "process_used": True,
                                "live_destination_checked": False,
                            }
                        require(False, "outcome_unknown")
                    records = [
                        line for line in output.splitlines() if line[:2] in {b"*\t", b" \t", b"=\t"}
                    ]
                    require(
                        len(records) == 1
                        and records[0].split(b"\t")[1].endswith((":" + ref).encode()),
                        "outcome_unknown",
                    )
                observed_head = remote_ref(session, pinned["uri"], target["branch"])
                require(observed_head == candidate, "outcome_unknown")
                fresh = fetch_ref(session, pinned["uri"], target["branch"], candidate)
                generation, inventory_after = active_generation(session, fresh, target["path"])
                require(
                    generation == plan["generation"]
                    and remote_ref(session, pinned["uri"], target["branch"]) == candidate,
                    "outcome_unknown",
                )
                final = {
                    **observation,
                    "inventory": inventory_after,
                    "revision": fingerprint([candidate, pinned["binding"], pinned["marker"]]),
                }
                with self.mirrors.guard():
                    receipt = self.mirrors._complete_locked(
                        plan_id,
                        operation_id=plan_id,
                        observation=final,
                        transport_proof={
                            "profile": "git-local/v1",
                            "commit_sha": candidate,
                            "observed_head": observed_head,
                            "commit_written": not noop,
                            "git_version": version,
                            "evidence_mode": "direct_verified",
                            "publication_time": None,
                        },
                    )
                operation["state"] = "completed"
                self.mirrors._save("git/operations/" + plan_id + ".json", operation)
                return {
                    "receipt": receipt,
                    "historical": False,
                    "process_used": True,
                    "live_destination_checked": True,
                }
            except BaseException:
                operation["state"] = "unknown"
                self.mirrors._save("git/operations/" + plan_id + ".json", operation)
                with self.mirrors.guard():
                    if self.mirrors.plan(plan_id)["state"] in {"dispatched", "unknown"}:
                        self.mirrors._unknown_locked(plan_id)
                raise
