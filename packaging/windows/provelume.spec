from importlib.util import find_spec
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SOURCE_ROOT = Path(SPECPATH).resolve().parents[1]
ICON = SOURCE_ROOT / "assets" / "windows" / "provelume.ico"
VERSION_INFO = SOURCE_ROOT / "packaging" / "windows" / "version_info.txt"
if not ICON.is_file() or not VERSION_INFO.is_file():
    raise RuntimeError("Versioned Windows icon or executable metadata is missing.")

datas = collect_data_files("provelume") + [(str(ICON), "assets")]
# collect_data_files intentionally omits native extensions. These governed
# optional resources must retain their exact package-relative paths and bytes.
package_root = Path(find_spec("provelume").origin).parent
native_root = package_root / "native-ai"
if native_root.exists():
    from provelume.ai_runtime_contract import runtime_lock

    for platform, inventory in runtime_lock()["platforms"].items():
        root = native_root / platform
        if {path.name for path in root.iterdir()} != set(inventory):
            raise RuntimeError("Native runtime resource inventory is incomplete.")
        datas.extend((str(root / name), "provelume/native-ai/" + platform)
                     for name in sorted(inventory))
hiddenimports = collect_submodules("uvicorn")
pydantic_core_spec = find_spec("pydantic_core._pydantic_core")
if pydantic_core_spec is None or pydantic_core_spec.origin is None:
    raise RuntimeError("The pydantic_core native extension could not be resolved.")
binaries = [(pydantic_core_spec.origin, "pydantic_core")]

analysis = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Provelume",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON),
    version=str(VERSION_INFO),
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Provelume",
)
