"""Tiny inert fixtures; these are NOT model/runtime qualification evidence."""

import io
import zipfile

LICENSE = b"CC0-1.0\nSynthetic lifecycle fixture; not an inference model.\n"


def package(version="1", *, entries=None, compression=zipfile.ZIP_STORED):
    target = io.BytesIO()
    if entries is None:
        entries = [("model.bin", f"PROVELUME-SYNTHETIC-MODEL/1\nversion={version}\n".encode()),
                   ("LICENSE.txt", LICENSE)]
    with zipfile.ZipFile(target, "w") as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            info.compress_type = compression
            archive.writestr(info, data)
    return target.getvalue()


class Download:
    def __init__(self, raw=None, *, failure=None, hook=None):
        self.raw = raw if raw is not None else package()
        self.calls = 0
        self.failure = failure
        self.hook = hook

    def fetch(self, entry, *, cancel, deadline):
        self.calls += 1
        if self.hook:
            self.hook()
        for index in range(0, len(self.raw), 64):
            yield self.raw[index:index + 64]
        if self.failure:
            raise self.failure


def runner(model, runtime, cancel):
    assert model.model.startswith(b"PROVELUME-SYNTHETIC-MODEL/1\n")
    return "PASSED"
