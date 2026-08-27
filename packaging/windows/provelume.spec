from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("provelume")
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
