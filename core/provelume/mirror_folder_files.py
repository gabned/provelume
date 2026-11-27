"""Owned local generation trees. No-follow handles, finite I/O and atomic pointers."""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import stat
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from uuid import uuid4

from .maintenance_local_files import (
    _windows_open,
    directory_binding,
    open_local_directory,
    pinned_parent,
)
from .migration_permissions import make_private, private_directory
from .mirror_contract import (
    HASH,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_GENERATIONS,
    MAX_MANIFEST_BYTES,
    MAX_RECORDS,
    MAX_SECONDS,
    MAX_TOTAL_BYTES,
    MirrorError,
    fingerprint,
    inventory,
    parse,
    raw,
    require,
)
from .mirror_git_target import exclude_instance_tree

MARKER = "provelume-folder-target.json"
MAX_TARGET_BYTES = 512 * 1024 * 1024
MAX_TARGET_FILES = 10_000


def validate_transport_proof(value, observation):
    require(
        type(value) is dict
        and set(value)
        == {
            "profile",
            "root_sha256",
            "namespace",
            "active_pointer_sha256",
            "activation_written",
            "filesystem_profile",
            "evidence_mode",
            "publication_time",
        },
        "folder_proof",
    )
    require(
        value["profile"] == "folder-local/v1"
        and observation["visibility"] == "private"
        and type(value["activation_written"]) is bool
        and value["evidence_mode"] in {"direct_verified", "reconciled_current_state"}
        and value["filesystem_profile"]
        in {"linux-local-renameat2/v1", "windows-local-ntfs-movefileex/v1"}
        and value["publication_time"] is None
        and type(value["namespace"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["namespace"]),
        "folder_proof",
    )
    for key in ("root_sha256", "active_pointer_sha256"):
        require(type(value[key]) is str and HASH.fullmatch(value[key]), "folder_proof")


def configuration(value):
    require(type(value) is dict and set(value) == {"transport", "path"}, "folder_target")
    require(value["transport"] == "folder" and type(value["path"]) is str, "folder_target")
    require(0 < len(value["path"]) <= 4096 and Path(value["path"]).is_absolute(), "folder_target")
    require(not any(ord(char) < 32 for char in value["path"]), "folder_target")
    return value


def parts(value):
    require(type(value) is str and len(value) <= 512, "folder_path")
    if not value:
        return ()
    path = PurePosixPath(value)
    require(
        path.as_posix() == value
        and not path.is_absolute()
        and len(path.parts) <= 10
        and all(
            re.fullmatch(r"[a-z0-9_.-]{1,240}", item) and item not in {".", ".."}
            for item in path.parts
        ),
        "folder_path",
    )
    return path.parts


def filesystem_profile(path):
    if os.name != "nt":
        return "linux-local-renameat2/v1"
    from ctypes import wintypes as w

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    kernel.GetVolumePathNameW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
    kernel.GetVolumePathNameW.restype = w.BOOL
    require(kernel.GetVolumePathNameW(str(path), volume, len(volume)), "folder_filesystem")
    name = ctypes.create_unicode_buffer(64)
    kernel.GetVolumeInformationW.argtypes = [
        w.LPCWSTR,
        w.LPWSTR,
        w.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        w.LPWSTR,
        w.DWORD,
    ]
    kernel.GetVolumeInformationW.restype = w.BOOL
    require(
        kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, name, len(name))
        and name.value == "NTFS",
        "folder_filesystem",
    )
    return "windows-local-ntfs-movefileex/v1"


class FolderTree:
    def __init__(self, root, descriptor, binding, *, deadline=None):
        self.root, self.descriptor, self.binding = root, descriptor, binding
        self.deadline = min(deadline or float("inf"), time.monotonic() + MAX_SECONDS)
        self.device = os.fstat(descriptor).st_dev if descriptor is not None else root.stat().st_dev
        self.profile = filesystem_profile(root)

    def check(self):
        require(time.monotonic() <= self.deadline, "deadline")
        if self.descriptor is not None:
            try:
                current = self.root.stat(follow_symlinks=False)
                opened = os.fstat(self.descriptor)
            except OSError:
                raise MirrorError("folder_target_changed") from None
            require(
                stat.S_ISDIR(current.st_mode)
                and (current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino),
                "folder_target_changed",
            )

    @contextmanager
    def directory(self, relative="", *, create=False):
        self.check()
        names = parts(relative)
        if os.name == "nt":
            with ExitStack() as stack:
                selected = self.root
                for name in names:
                    selected = selected / name
                    if create and not selected.exists():
                        selected.mkdir()
                        make_private(selected)
                    selected, _binding = stack.enter_context(open_local_directory(selected))
                    require(selected.stat().st_dev == self.device, "folder_filesystem")
                    private_directory(selected)
                yield selected
        else:
            descriptor = os.dup(self.descriptor)
            try:
                for name in names:
                    self.check()
                    try:
                        opened = os.open(
                            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                        )
                    except FileNotFoundError:
                        require(create, "folder_missing")
                        os.mkdir(name, 0o700, dir_fd=descriptor)
                        opened = os.open(
                            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                        )
                    os.close(descriptor)
                    descriptor = opened
                    info = os.fstat(descriptor)
                    require(
                        info.st_dev == self.device
                        and info.st_uid == os.geteuid()
                        and stat.S_IMODE(info.st_mode) == 0o700,
                        "folder_privacy",
                    )
                yield descriptor
            finally:
                os.close(descriptor)
        self.check()

    def names(self, relative=""):
        with self.directory(relative) as directory:
            names = os.listdir(directory)
            require(len(names) <= MAX_TARGET_FILES, "limit")
            for name in names:
                parts(name)
            return sorted(names)

    def info(self, relative, *, missing_leaf=False):
        names = parts(relative)
        require(names, "folder_path")
        with self.directory("/".join(names[:-1])) as directory:
            # Interpret only an absent selected leaf while its parent guards are
            # still held. Windows parent contexts deliberately normalize escaped
            # FileNotFoundError; a vanished ancestor must remain a refusal.
            try:
                if os.name == "nt":
                    selected = directory / names[-1]
                    require(
                        not selected.is_symlink() and not selected.is_junction(), "folder_alias"
                    )
                    return selected.stat(follow_symlinks=False)
                return os.stat(names[-1], dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                if missing_leaf:
                    return None
                raise

    def exists(self, relative):
        return self.info(relative, missing_leaf=True) is not None

    @contextmanager
    def file(self, relative, *, create=False):
        names = parts(relative)
        require(names, "folder_path")
        with self.directory("/".join(names[:-1]), create=create) as directory:
            descriptor = (
                _windows_open(directory / names[-1], directory=False, create=create)
                if os.name == "nt"
                else os.open(
                    names[-1],
                    (os.O_RDWR | os.O_CREAT | os.O_EXCL if create else os.O_RDONLY)
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK,
                    0o600,
                    dir_fd=directory,
                )
            )
            with os.fdopen(descriptor, "wb" if create else "rb") as stream:
                info = os.fstat(stream.fileno())
                require(
                    stat.S_ISREG(info.st_mode)
                    and info.st_nlink == 1
                    and info.st_dev == self.device,
                    "folder_alias",
                )
                yield stream
            if create and os.name == "nt":
                make_private(directory / names[-1])
        self.check()

    def read(self, relative, *, maximum=MAX_MANIFEST_BYTES):
        with self.file(relative) as stream:
            data = stream.read(maximum + 1)
            require(len(data) <= maximum, "limit")
            return data

    def write(self, relative, data):
        require(type(data) is bytes and len(data) <= MAX_FILE_BYTES, "limit")
        with self.file(relative, create=True) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def mkdir(self, relative):
        require(not self.exists(relative), "folder_exists")
        with self.directory(relative, create=True):
            pass

    def rename(self, source, destination, *, replace=False):
        source_parts, destination_parts = parts(source), parts(destination)
        with (
            self.directory("/".join(source_parts[:-1])) as source_directory,
            self.directory("/".join(destination_parts[:-1])) as destination_directory,
        ):
            if os.name == "nt":
                from ctypes import wintypes as w

                move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
                move.argtypes, move.restype = [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.BOOL
                require(
                    move(
                        str(source_directory / source_parts[-1]),
                        str(destination_directory / destination_parts[-1]),
                        8 | (1 if replace else 0),
                    ),
                    "folder_atomic_activation",
                )
            elif replace:
                os.replace(
                    source_parts[-1],
                    destination_parts[-1],
                    src_dir_fd=source_directory,
                    dst_dir_fd=destination_directory,
                )
            else:
                library = ctypes.CDLL(None, use_errno=True)
                rename = getattr(library, "renameat2", None)
                require(rename is not None, "folder_atomic_activation")
                rename.argtypes = [
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_int,
                    ctypes.c_char_p,
                    ctypes.c_uint,
                ]
                rename.restype = ctypes.c_int
                require(
                    rename(
                        source_directory,
                        os.fsencode(source_parts[-1]),
                        destination_directory,
                        os.fsencode(destination_parts[-1]),
                        1,
                    )
                    == 0,
                    "folder_atomic_activation",
                )
            if os.name != "nt":
                os.fsync(source_directory)
                os.fsync(destination_directory)
        self.check()

    def sync_directories(self, relative):
        """Persist the completed local staging directory entries before promotion."""
        if os.name == "nt":
            # Files were flushed; promotion uses the qualified NTFS write-through
            # primitive. This is no attestation of a whole-system power failure.
            return
        for name in self.names(relative):
            child = relative + "/" + name
            if stat.S_ISDIR(self.info(child).st_mode):
                self.sync_directories(child)
        with self.directory(relative) as descriptor:
            os.fsync(descriptor)

    def files(self, relative):
        result = []
        visited = 0

        def visit(prefix):
            nonlocal visited
            for name in self.names(prefix):
                visited += 1
                require(visited <= MAX_RECORDS, "limit")
                self.check()
                item = prefix + "/" + name if prefix else name
                info = self.info(item)
                require(info.st_dev == self.device, "folder_filesystem")
                if stat.S_ISDIR(info.st_mode):
                    visit(item)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "folder_alias")
                    result.append((item, info.st_size))
                    require(len(result) <= MAX_TARGET_FILES, "limit")

        visit(relative)
        return result

    def generation(self, prefix, expected):
        manifest = parse(self.read(prefix + "/manifest.json"))
        require(
            manifest.get("schema") == "provelume-mirror-generation/v1"
            and manifest.get("complete") is True
            and manifest.get("canonical") is False
            and fingerprint(manifest) == expected,
            "folder_incomplete",
        )
        payload = inventory(manifest["inventory"])
        actual = self.files(prefix)
        require(
            len(actual) <= MAX_FILES + 1
            and {name[len(prefix) + 1 :] for name, _ in actual}
            == {item["path"] for item in payload} | {"manifest.json"},
            "folder_incomplete",
        )
        for item in payload:
            digest, count = hashlib.sha256(), 0
            with self.file(prefix + "/" + item["path"]) as stream:
                while chunk := stream.read(1024 * 1024):
                    self.check()
                    count += len(chunk)
                    require(count <= item["size_bytes"] <= MAX_FILE_BYTES, "limit")
                    digest.update(chunk)
            require(
                count == item["size_bytes"] and digest.hexdigest() == item["sha256"],
                "folder_incomplete",
            )
        require(sum(item["size_bytes"] for item in payload) <= MAX_TOTAL_BYTES, "limit")
        return manifest

    def active(self):
        if not self.exists("active.json"):
            return None, []
        pointer = parse(self.read("active.json", maximum=4096))
        require(
            set(pointer)
            == {
                "schema",
                "generation",
                "manifest_sha256",
                "inventory_sha256",
                "operation_id",
                "previous_pointer_sha256",
            }
            and pointer["schema"] == "provelume-folder-active/v1"
            and type(pointer["generation"]) is str
            and HASH.fullmatch(pointer["generation"])
            and pointer["manifest_sha256"] == pointer["generation"]
            and type(pointer["operation_id"]) is str
            and re.fullmatch(r"mirplan_[0-9a-f]{32}", pointer["operation_id"])
            and type(pointer["previous_pointer_sha256"]) is str
            and HASH.fullmatch(pointer["previous_pointer_sha256"]),
            "folder_incomplete",
        )
        manifest = self.generation("generations/" + pointer["generation"], pointer["generation"])
        require(
            pointer["inventory_sha256"] == fingerprint(manifest["inventory"]), "folder_incomplete"
        )
        return pointer, manifest["inventory"]

    def audit(self):
        names = set(self.names())
        require(
            names <= {MARKER, "transfer.lock", "staging", "generations", "active.json"}
            and {MARKER, "transfer.lock", "staging", "generations"} <= names,
            "folder_unknown_content",
        )
        entries = self.files("")
        require(
            len(entries) <= MAX_TARGET_FILES
            and sum(size for _, size in entries) <= MAX_TARGET_BYTES,
            "folder_storage_limit",
        )
        generations, stages = self.names("generations"), self.names("staging")
        require(len(generations) + len(stages) <= MAX_GENERATIONS, "folder_storage_limit")
        for generation in generations:
            require(HASH.fullmatch(generation), "folder_unknown_content")
            self.generation("generations/" + generation, generation)
        return {
            "generations": generations,
            "staging": stages,
            "files": len(entries),
            "bytes": sum(size for _, size in entries),
        }


@contextmanager
def folder_root(target, *, store, device, destination_sha256, deadline=None, fresh=False):
    configuration(target)
    expected = {
        "instance_id": store.read_config()["instance"]["id"],
        "device_sha256": device,
        "destination_sha256": destination_sha256,
    }
    with owned_folder_root(
        target["path"],
        expected=expected,
        admit=lambda selected: exclude_instance_tree(selected, store),
        deadline=deadline,
        fresh=fresh,
    ) as tree:
        yield tree


@contextmanager
def owned_folder_root(value, *, expected, admit, deadline=None, fresh=False, namespace=None):
    """Shared native primitive; each caller supplies its real namespace authority.

    Local mirrors use their actual Instance. A forced-command remote helper uses
    independently installed namespace configuration, never a pretend Store.
    """
    require(
        type(expected) is dict
        and set(expected) == {"instance_id", "device_sha256", "destination_sha256"}
        and callable(admit),
        "folder_unknown_target",
    )
    require(
        namespace is None or type(namespace) is str and re.fullmatch(r"[0-9a-f]{32}", namespace),
        "folder_unknown_target",
    )
    selected = Path(value)
    with pinned_parent(selected) as (path, parent):
        admit(path.parent.resolve() / path.name)
        if fresh:
            require(
                not path.exists() and not path.is_symlink() and not path.is_junction(),
                "folder_exists",
            )
            if os.name == "nt":
                path.mkdir()
                make_private(path)
            else:
                os.mkdir(path.name, 0o700, dir_fd=parent)
        with ExitStack() as stack:
            if os.name == "nt":
                root, binding = stack.enter_context(open_local_directory(path))
                private_directory(root)
                descriptor = None
            else:
                descriptor = os.open(
                    path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                stack.callback(os.close, descriptor)
                info = os.fstat(descriptor)
                require(
                    info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700,
                    "folder_privacy",
                )
                root, binding = path, directory_binding(descriptor)
            tree = FolderTree(root, descriptor, binding, deadline=deadline)
            expected = {
                "schema": "provelume-folder-target/v1",
                **expected,
                "root_sha256": fingerprint(binding),
            }
            if fresh:
                require(not tree.names(), "folder_unknown_content")
                tree.write(MARKER, raw({**expected, "namespace": namespace or uuid4().hex}))
                tree.write("transfer.lock", b"\0")
                tree.mkdir("staging")
                tree.mkdir("generations")
            marker = parse(tree.read(MARKER, maximum=4096))
            require(
                set(marker) == set(expected) | {"namespace"}
                and {key: value for key, value in marker.items() if key != "namespace"} == expected
                and type(marker["namespace"]) is str
                and re.fullmatch(r"[0-9a-f]{32}", marker["namespace"])
                and (namespace is None or marker["namespace"] == namespace),
                "folder_unknown_target",
            )
            tree.marker = marker
            # The lock belongs to this physical namespace, never a global lock.
            with tree.directory() as directory:
                lock = (
                    _windows_open(directory / "transfer.lock", directory=False, lock=True)
                    if os.name == "nt"
                    else os.open("transfer.lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory)
                )
                try:
                    info = os.fstat(lock)
                    require(
                        stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 1,
                        "folder_alias",
                    )
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(lock, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    tree.audit()
                    yield tree
                finally:
                    os.close(lock)
            with open_local_directory(path) as (_root, current):
                require(current == binding, "folder_target_changed")
