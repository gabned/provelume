"""Compose a closed Windows OCR payload from pinned source-build outputs."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "core"))

from provelume.ocr_kit import (  # noqa: E402
    ENGINE,
    MANIFEST,
    PACKS,
    WORKER,
    InstalledOcrKit,
    build_identity,  # noqa: E402
    payload_identity,  # noqa: E402
    validate_manifest,
)
from provelume.publication import canonical_bytes, file_identity  # noqa: E402

XMLLITE_REFERENCE = (
    "https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ee388577(v=vs.85)"
)

SYSTEM_DLLS = set(
    [
        "advapi32.dll",
        "bcrypt.dll",
        "bcryptprimitives.dll",
        "cabinet.dll",
        "cfgmgr32.dll",
        "comctl32.dll",
        "combase.dll",
        "comdlg32.dll",
        "crypt32.dll",
        "cryptbase.dll",
        "cryptsp.dll",
        "dbghelp.dll",
        "dwrite.dll",
        "dwmapi.dll",
        "gdi32.dll",
        "gdiplus.dll",
        "imm32.dll",
        "iphlpapi.dll",
        "kernel32.dll",
        "kernelbase.dll",
        "mpr.dll",
        "msvcrt.dll",
        "ncrypt.dll",
        "normaliz.dll",
        "ntdll.dll",
        "ole32.dll",
        "oleacc.dll",
        "oleaut32.dll",
        "powrprof.dll",
        "propsys.dll",
        "psapi.dll",
        "rpcrt4.dll",
        "secur32.dll",
        "setupapi.dll",
        "shell32.dll",
        "shlwapi.dll",
        "ucrtbase.dll",
        "user32.dll",
        "userenv.dll",
        "usp10.dll",
        "uxtheme.dll",
        "version.dll",
        "winhttp.dll",
        "wininet.dll",
        "winmm.dll",
        "winspool.drv",
        "wintrust.dll",
        "wldap32.dll",
        "ws2_32.dll",
        "wtsapi32.dll",
        "dhcpcsvc.dll",
        "dnsapi.dll",
        "netapi32.dll",
        "ntasn1.dll",
        "mswsock.dll",
        "hid.dll",
        "shcore.dll",
        "nsi.dll",
        "authz.dll",
        "win32u.dll",
        "xmllite.dll",
    ]
)


@lru_cache(maxsize=256)
def _system_module(name):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint32]
    kernel.LoadLibraryExW.restype = ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetSystemDirectoryW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.FreeLibrary.argtypes = [ctypes.c_void_p]
    handle = kernel.LoadLibraryExW(name, None, 0x800)  # LOAD_LIBRARY_SEARCH_SYSTEM32 only
    if not handle:
        raise ValueError("Required Windows system API is unavailable: " + name)
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        system = ctypes.create_unicode_buffer(32768)
        if not kernel.GetModuleFileNameW(handle, buffer, len(buffer)) or not (
            kernel.GetSystemDirectoryW(system, len(system))
        ):
            raise ValueError("Windows system API ownership cannot be observed")
        path = Path(buffer.value).resolve()
        system_directory = Path(system.value).resolve()
        if not any(
            path.is_relative_to(directory)
            for directory in (system_directory, system_directory.parent / "WinSxS")
        ):
            raise ValueError("Required Windows API resolved outside the operating system")
        return {
            "resolution": "Windows-system-API",
            "resolved_module": path.name,
            "system_file": file_identity(path),
            "windows_build": sys.getwindowsversion().build,
            **({"reference": XMLLITE_REFERENCE} if name == "xmllite.dll" else {}),
        }
    finally:
        kernel.FreeLibrary(handle)


def native_inventory(root):
    import pefile

    paths = {p.relative_to(root).as_posix().casefold(): p for p in root.rglob("*") if p.is_file()}
    result, unresolved = [], []
    for key, path in sorted(paths.items()):
        if path.suffix.lower() not in {".exe", ".dll", ".pyd"}:
            continue
        with pefile.PE(str(path), fast_load=True) as pe:
            if pe.FILE_HEADER.Machine != 0x8664:
                raise ValueError("OCR native file is not AMD64")
            pe.parse_data_directories(directories=[1, 13])
            names = sorted(
                {
                    row.dll.decode("ascii").lower()
                    for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                    for row in getattr(pe, attribute, [])
                }
            )
        imports = []
        for name in names:
            candidates = [path.parent / name]
            if key.startswith("worker/"):
                candidates += [root / "worker/_internal" / name, root / "worker" / name]
            elif key.startswith("engine/"):
                candidates += [root / "engine" / name]
            found = next(
                (
                    paths.get(p.relative_to(root).as_posix().casefold())
                    for p in candidates
                    if p.relative_to(root).as_posix().casefold() in paths
                ),
                None,
            )
            if found is not None:
                imports.append({"name": name, "resolution": found.relative_to(root).as_posix()})
            elif name in SYSTEM_DLLS or name.startswith(("api-ms-win-", "ext-ms-win-")):
                try:
                    imports.append({"name": name, **_system_module(name)})
                except (OSError, ValueError):
                    unresolved.append(name)
            else:
                unresolved.append(name)
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "architecture": "AMD64",
                "sha256": payload_identity(path)["sha256"],
                "imports": imports,
            }
        )
    if unresolved:
        raise ValueError(
            "OCR DLL dependencies are not closed: " + ", ".join(sorted(set(unresolved)))
        )
    if not result:
        raise ValueError("Native OCR inventory is empty")
    return result


def _copy_notices(distribution, root):
    dist = importlib.metadata.distribution(distribution)
    copied = []
    for entry in dist.files or ():
        name = entry.as_posix()
        if ".dist-info/licenses/" not in name and not (
            ".dist-info/" in name and "license" in Path(name).name.lower()
        ):
            continue
        path = Path(dist.locate_file(entry))
        target = root / "licenses" / distribution / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        copied.append(target.relative_to(root).as_posix())
    if not copied:
        raise ValueError("Distribution license inventory is missing: " + distribution)
    return copied


def _acquire(url, output, *, size=None, sha=None):
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = response.read((size or 2 * 1024 * 1024) + 1)
    if (size is not None and len(payload) != size) or (
        sha is not None and hashlib.sha256(payload).hexdigest() != sha
    ):
        raise ValueError("Locked OCR acquisition differs")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)


def native_license(name, version, port, lock, root):
    selected = lock.get("native_license_evidence", {}).get(name)
    if selected is None:
        value = port.get("license")
        if not isinstance(value, str) or not value:
            raise ValueError("Native component license is unspecified: " + name)
        return value, []
    if selected["version"] != version:
        raise ValueError("Native license evidence belongs to a different version: " + name)
    notices = []
    for row in selected["files"]:
        target = root / "licenses/native" / name / "upstream" / row["path"]
        _acquire(row["url"], target, size=row["size_bytes"], sha=row["sha256"])
        notices.append(target.relative_to(root).as_posix())
    return selected["expression"], notices


def compose(worker, vcpkg, identity, output):
    lock = json.loads((SOURCE / "packaging/ocr/windows-py312-x64.json").read_text())
    if sys.platform != "win32" or platform.python_version() != lock["python"]:
        raise ValueError("Native Windows locked interpreter required")
    if (
        subprocess.check_output(["git", "-C", str(vcpkg), "rev-parse", "HEAD"], text=True).strip()
        != lock["vcpkg"]["commit"]
    ):
        raise ValueError("Native source builder identity differs")
    installed = vcpkg / "installed" / lock["vcpkg"]["triplet"]
    build = json.loads(identity.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="provelume-ocr-compose-") as directory:
        root = Path(directory)
        shutil.copytree(worker, root / "worker")
        worker_identity = json.loads(
            subprocess.check_output([str(root / WORKER), "--identity"], text=True, timeout=15)
        )
        if worker_identity != build:
            raise ValueError("Frozen OCR worker source/build identity differs")
        (root / "engine").mkdir()
        shutil.copyfile(installed / "tools/tesseract/tesseract.exe", root / ENGINE)
        version = subprocess.check_output(
            [str(root / ENGINE), "--version"], stderr=subprocess.STDOUT, text=True, timeout=15
        )
        if version.splitlines()[0].strip() != "tesseract 5.5.3":
            raise ValueError("Native engine version differs")
        probe = json.loads(
            subprocess.check_output([str(root / WORKER), "probe"], text=True, timeout=30)
        )
        if (probe["pillow"], probe["pypdfium2"], probe["pdfium"]) != (
            "13.0.0",
            "5.13.0",
            lock["pdfium"],
        ):
            raise ValueError("Frozen renderer/decoder versions differ")
        components = []
        status = (vcpkg / "installed/vcpkg/status").read_text()
        for paragraph in status.strip().split("\n\n"):
            values = dict(line.split(": ", 1) for line in paragraph.splitlines() if ": " in line)
            if "Package" not in values or "Version" not in values:
                continue
            name, version_number = values["Package"], values["Version"]
            port_path = vcpkg / "ports" / name / "vcpkg.json"
            port = json.loads(port_path.read_text())
            share = installed / "share" / name
            if not (share / "copyright").is_file():
                # Host tools are build inputs, not linked runtime components.
                if values.get("Architecture") != lock["vcpkg"]["triplet"]:
                    continue
                raise ValueError("Native component copyright is missing: " + name)
            notices = []
            for filename in ("copyright", "vcpkg.spdx.json", "vcpkg_abi_info.txt"):
                path = share / filename
                if path.is_file():
                    target = root / "licenses/native" / name / filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
                    notices.append(target.relative_to(root).as_posix())
            license_name, extra_notices = native_license(name, version_number, port, lock, root)
            notices.extend(extra_notices)
            components.append(
                {
                    "name": name,
                    "version": version_number,
                    "license": license_name,
                    "notices": notices,
                    "source": "vcpkg:" + lock["vcpkg"]["commit"] + "/ports/" + name,
                    "port_sha256": file_identity(port_path)["sha256"],
                    "linkage": "static; exact source/patch/archive identities in SPDX",
                }
            )
        for distribution, license_name in (
            ("Pillow", "MIT-CMU"),
            ("pypdfium2", "Apache-2.0 OR BSD-3-Clause"),
            ("PyInstaller", "GPL-2.0-or-later WITH Bootloader-exception"),
        ):
            components.append(
                {
                    "name": distribution,
                    "version": importlib.metadata.version(distribution),
                    "license": license_name,
                    "notices": _copy_notices(distribution, root),
                    "source": "reviewed Windows worker lock",
                }
            )
        pdfium_notices = next(c["notices"] for c in components if c["name"] == "pypdfium2")
        components.append(
            {
                "name": "PDFium",
                "version": lock["pdfium"],
                "license": "BSD-3-Clause and attached third-party notices",
                "notices": pdfium_notices,
                "source": "https://pdfium.googlesource.com/pdfium/; exact locked Windows wheel",
            }
        )
        # These include all PDFium dependency licenses from the selected wheel.
        for path in worker.rglob("*LICENSE*"):
            if path.is_file():
                target = root / "licenses/pdfium" / path.relative_to(worker)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
        python_license = Path(sys.base_prefix) / "LICENSE.txt"
        (root / "licenses/python").mkdir(parents=True)
        shutil.copyfile(python_license, root / "licenses/python/LICENSE.txt")
        components.append(
            {
                "name": "CPython",
                "version": platform.python_version(),
                "license": "PSF-2.0",
                "notices": ["licenses/python/LICENSE.txt"],
                "source": "actions/setup-python exact locked patch; frozen DLL inventory",
            }
        )
        for pack in lock["tessdata"]["packs"]:
            url = (
                lock["tessdata"]["repository"].replace(
                    "https://github.com/", "https://raw.githubusercontent.com/"
                )
                + "/"
                + lock["tessdata"]["commit"]
            )
            _acquire(
                url + "/" + pack["id"] + ".traineddata",
                root / PACKS[pack["id"]],
                size=pack["size_bytes"],
                sha=pack["sha256"],
            )
            components.append(
                {
                    "name": "tessdata-fast-" + pack["id"],
                    "version": lock["tessdata"]["commit"],
                    "license": "Apache-2.0",
                    "notices": ["licenses/tessdata/LICENSE"],
                    "source": url,
                }
            )
        _acquire(url + "/LICENSE", root / "licenses/tessdata/LICENSE")
        for filename in ("LICENSE", "COMMERCIAL-LICENSE.md", "THIRD_PARTY_NOTICES.md"):
            shutil.copyfile(SOURCE / filename, root / ("Provelume-" + filename))
        (root / "components.json").write_bytes(
            canonical_bytes(
                {
                    "components": components,
                    "inputs": lock,
                    "engine_version_output": version,
                    "worker_probe": {k: v for k, v in probe.items() if k != "pdfium_library"},
                    "builder": {
                        "python": platform.python_version(),
                        "compiler": platform.python_compiler(),
                    },
                }
            )
        )
        native = native_inventory(root)
        (root / "native-dependencies.json").write_bytes(
            canonical_bytes(
                {
                    "files": native,
                    "system_requirement": "Windows10/11 x64 system APIs",
                    "path_lookup": False,
                    "external_python": False,
                }
            )
        )
        sbom = {
            "bomFormat": "CycloneDX",
            "specVersion": "1.6",
            "version": 1,
            "components": [
                {
                    "type": "library",
                    "name": c["name"],
                    "version": c["version"],
                    "properties": [
                        {"name": "source", "value": c["source"]},
                        {"name": "license", "value": str(c["license"])},
                    ],
                }
                for c in components
            ],
        }
        (root / "ocr-components.cdx.json").write_bytes(canonical_bytes(sbom))
        files = [
            {
                "path": p.relative_to(root).as_posix(),
                **{k: v for k, v in payload_identity(p).items() if k != "name"},
            }
            for p in sorted(root.rglob("*"))
            if p.is_file()
        ]
        manifest = {
            "schema_version": 1,
            "source_repository": "gabned/provelume",
            "version": build["version"],
            "commit": build["commit"],
            "platform": "windows",
            "architecture": "x86_64",
            "python": lock["python"],
            "entrypoints": {"engine": ENGINE, "worker": WORKER, "packs": PACKS},
            "components": components,
            "native_dependencies": native,
            "files": files,
            "trust": {
                "publisher_authentication": "not_established",
                "platform_signature": "unsigned-development",
            },
            "build_identity": build_identity(build),
        }
        (output / "ocr-kit-unqualified-inventory.json").write_bytes(canonical_bytes(manifest))
        validate_manifest(manifest, build)
        raw = canonical_bytes(manifest)
        (root / MANIFEST).write_bytes(raw)
        InstalledOcrKit(root, "0" * 64, hashlib.sha256(raw).hexdigest(), build).verify()
        target = output / f"provelume-{build['version']}-ocr-windows-x64.zip"
        with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_STORED) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0))
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    archive.writestr(info, path.read_bytes())
        report = {
            "build_identity": build_identity(build),
            "kit": file_identity(target),
            "source_commit": build["commit"],
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
            "files": len(files),
            "native_files": len(native),
            "components": components,
            "qualification": "STATIC_AND_PROBE_ONLY",
            "manual_windows": "NOT_RUN",
        }
        (output / "ocr-kit-build.json").write_bytes(canonical_bytes(report))
        print(json.dumps({k: report[k] for k in ("kit", "files", "native_files")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("worker", "vcpkg", "identity", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    compose(args.worker, args.vcpkg, args.identity, args.output)
