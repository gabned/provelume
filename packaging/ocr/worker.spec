from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

datas, binaries, hiddenimports = [], [], []
datas += collect_data_files("provelume", includes=["build_info.json"])
for package in ("PIL", "pypdfium2", "pypdfium2_raw"):
    data, binary, hidden = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += hidden
for distribution in ("Pillow", "pypdfium2"):
    datas += copy_metadata(distribution)
unused = {"_imagingtk", "_imagingft", "_imagingcms", "_avif", "_webp", "_imagingmorph"}
binaries = [(path, target) for path, target in binaries
            if __import__("pathlib").Path(path).name.split(".")[0] not in unused]
hiddenimports = [name for name in hiddenimports if name.rsplit(".", 1)[-1] not in unused]
analysis = Analysis(["worker_entry.py"], pathex=[], binaries=binaries, datas=datas,
                    hiddenimports=hiddenimports, hookspath=[], hooksconfig={},
                    runtime_hooks=[], excludes=["tkinter", "PIL.ImageTk",
                                                *["PIL." + name for name in sorted(unused)]],
                    noarchive=False, optimize=0)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
                 name="ProvelumeOcrWorker", console=True, debug=False,
                 strip=False, upx=False)
collection = COLLECT(executable, analysis.binaries, analysis.datas,
                     strip=False, upx=False, name="ProvelumeOcrWorker")
