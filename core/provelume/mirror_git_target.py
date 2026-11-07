"""Known private local bare Git targets; no arbitrary tree or backup destination."""

from __future__ import annotations

import configparser
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from .maintenance_local_files import directory_binding, open_local_directory, pinned_parent
from .migration_permissions import private_directory
from .mirror_contract import MAX_MANIFEST_BYTES, MAX_RECORDS, fingerprint, parse, require
from .mirror_git_runtime import MAX_OBJECT_BYTES, MAX_OBJECT_FILES

MARKER = "provelume-mirror-target.json"
_ROOTS = {
    "HEAD",
    "config",
    "description",
    "packed-refs",
    "objects",
    "refs",
    "hooks",
    "info",
    "logs",
    MARKER,
}


def target_configuration(value):
    require(
        type(value) is dict
        and set(value)
        == {"transport", "repository", "branch", "path", "commit_name", "commit_email"}
    )
    require(value["transport"] == "local", "git_profile_not_qualified")
    repository = Path(value["repository"])
    require(
        type(value["repository"]) is str
        and repository.is_absolute()
        and not any(ord(char) < 32 for char in value["repository"]),
        "unsafe_git_target",
    )
    branch = value["branch"]
    require(
        type(branch) is str
        and 0 < len(branch) <= 120
        and all(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,59}", part) for part in branch.split("/"))
        and not any(part.endswith((".", ".lock")) or ".." in part for part in branch.split("/")),
        "git_branch",
    )
    for part in branch.split("/"):
        require(
            part.split(".", 1)[0]
            not in {
                "con",
                "prn",
                "aux",
                "nul",
                "com1",
                "com2",
                "com3",
                "com4",
                "com5",
                "com6",
                "com7",
                "com8",
                "com9",
                "lpt1",
                "lpt2",
                "lpt3",
                "lpt4",
                "lpt5",
                "lpt6",
                "lpt7",
                "lpt8",
                "lpt9",
            },
            "git_branch",
        )
    prefix = value["path"]
    require(
        type(prefix) is str
        and 0 < len(prefix) <= 80
        and all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,39}", part) for part in prefix.split("/")),
        "git_path",
    )
    require(
        type(value["commit_name"]) is str
        and 0 < len(value["commit_name"].strip()) <= 100
        and not any(ord(char) < 32 or char in "<>" for char in value["commit_name"]),
        "git_identity",
    )
    require(
        type(value["commit_email"]) is str
        and len(value["commit_email"]) <= 240
        and re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", value["commit_email"]),
        "git_identity",
    )
    return value


def _reference_path(value):
    text = str(value)
    if os.name == "nt" and text.startswith("\\\\?\\UNC\\"):
        text = "\\\\" + text[8:]
    elif os.name == "nt" and text.startswith("\\\\?\\"):
        text = text[4:]
    return Path(os.path.abspath(text))


def exclude_instance_tree(repository, store):
    # Caller has admitted locality and pinned the physical parent/root first.
    root = _reference_path(store.paths.root.resolve())
    selected = _reference_path(repository)
    require(
        not selected.is_relative_to(root) and not root.is_relative_to(selected), "unsafe_git_target"
    )
    control = root.parent / ("." + root.name + ".provelume")
    require(not selected.is_relative_to(control), "unsafe_git_target")
    sources = store.read_config().get("sources") or {}
    require(type(sources) is dict and len(sources) <= MAX_RECORDS, "limit")
    for source in sources.values():
        require(type(source) is dict, "invalid")
        configured = source.get("path")
        if configured is not None:
            require(type(configured) is str and configured and "\x00" not in configured, "invalid")
            # Registered Source paths are already canonicalized at enrollment.
            # Normalize portable references lexically; never resolve/probe an
            # offline or remote Source just to prepare a local mirror.
            observed = _reference_path(root / configured)
            require(
                not selected.is_relative_to(observed) and not observed.is_relative_to(selected),
                "unsafe_git_target",
            )
    # Initial admission requires an absent root. Subsequent admission additionally
    # requires the exact known Git marker and closed bare-tree shape below.
    for parent in (selected, *selected.parents):
        require(not parent.is_symlink() and not parent.is_junction(), "unsafe_git_target")


def _read(root, name, *, maximum=MAX_MANIFEST_BYTES):
    item = root / name
    require(not item.is_symlink() and not item.is_junction(), "unsafe_git_target")
    info = item.stat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= maximum,
        "unsafe_git_target",
    )
    with item.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, "limit")
    return data


def audit_bare_root(root, *, instance_id, device, binding):
    marker = parse(_read(root, MARKER, maximum=4096))
    require(
        marker
        == {
            "schema": "provelume-local-git-target/v1",
            "instance_id": instance_id,
            "device_sha256": device,
            "root_sha256": fingerprint(binding),
        },
        "unknown_git_target",
    )
    configuration = configparser.ConfigParser(interpolation=None, strict=True)
    configuration.read_string(_read(root, "config", maximum=16384).decode("utf-8"))
    require(configuration.sections() == ["core"], "unsafe_git_config")
    core = dict(configuration["core"])
    require(
        core.get("repositoryformatversion") == "0" and core.get("bare") == "true",
        "unsafe_git_config",
    )
    require(
        set(core)
        <= {
            "repositoryformatversion",
            "bare",
            "filemode",
            "ignorecase",
            "symlinks",
            "precomposeunicode",
            "protecthfs",
            "protectntfs",
            "longpaths",
        }
        and all(
            item in {"true", "false"}
            for key, item in core.items()
            if key not in {"repositoryformatversion", "bare"}
        ),
        "unsafe_git_config",
    )
    require(
        not any(
            (root / name).exists()
            for name in (
                "objects/info/alternates",
                "objects/info/http-alternates",
                "info/grafts",
                "shallow",
            )
        ),
        "unsafe_git_target",
    )
    replace_refs = root / "refs/replace"
    require(not replace_refs.exists() or not any(replace_refs.iterdir()), "unsafe_git_target")
    count, size = 0, 0
    for child in root.rglob("*"):
        require(not child.is_symlink() and not child.is_junction(), "unsafe_git_target")
        relative = child.relative_to(root)
        require(relative.parts[0] in _ROOTS, "unknown_git_target")
        info = child.stat()
        if stat.S_ISDIR(info.st_mode):
            continue
        count += 1
        size += info.st_size
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and count <= MAX_OBJECT_FILES
            and size <= MAX_OBJECT_BYTES,
            "git_storage_limit",
        )
        if relative.parts[0] == "hooks":
            require(child.name.endswith(".sample"), "unsafe_git_hook")
    return marker


@contextmanager
def local_target(target, *, store, device):
    target_configuration(target)
    selected = Path(target["repository"])
    if os.name == "posix":
        with pinned_parent(selected) as (path, parent):
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
            )
            try:
                info = os.fstat(descriptor)
                require(
                    info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "git_target_privacy",
                )
                binding = directory_binding(descriptor)
                pinned = Path("/proc/self/fd") / str(descriptor)
                require(pinned.is_dir(), "git_containment")
                exclude_instance_tree(pinned.resolve(), store)
                marker = audit_bare_root(
                    pinned,
                    instance_id=store.read_config()["instance"]["id"],
                    device=device,
                    binding=binding,
                )
                yield {
                    "directory": pinned,
                    "uri": pinned.as_uri(),
                    "binding": binding,
                    "descriptors": (descriptor,),
                    "marker": marker,
                }
                current = os.stat(path, follow_symlinks=False)
                require(
                    (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino),
                    "git_target_changed",
                )
            finally:
                os.close(descriptor)
    else:
        with open_local_directory(selected) as (path, binding):
            exclude_instance_tree(path.resolve(), store)
            private_directory(path)
            marker = audit_bare_root(
                path,
                instance_id=store.read_config()["instance"]["id"],
                device=device,
                binding=binding,
            )
            yield {
                "directory": path,
                "uri": path.as_uri(),
                "binding": binding,
                "descriptors": (),
                "marker": marker,
            }
