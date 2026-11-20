"""Acquisition failures remain failures, with useful metadata and no model bytes."""

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).absolute().parents[1] / "scripts"


@pytest.fixture
def acquisition(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("native_acquisition_under_test",
                                                SCRIPTS / "ai_runtime_acquire.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = SimpleNamespace(now=0)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.now))
    return module, clock


def response(acquisition, monkeypatch, blocks, *, elapsed=1):
    module, clock = acquisition

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return "https://us.aws.cdn.hf.co/private-path?signature=DO_NOT_LOG"

        def read(self, length):
            assert length == 1024 * 1024
            if not blocks:
                return b""
            clock.now += elapsed
            block = blocks.pop(0)
            if isinstance(block, BaseException):
                raise block
            return block

    class Opener:
        def open(self, url, *, timeout):
            assert url == "https://huggingface.co/locked" and timeout == 15
            return Reply()

    def build(*handlers):
        assert handlers[0].proxies == {}  # No ambient proxy/cookie/credential adoption.
        return Opener()

    monkeypatch.setattr(module.urllib.request, "build_opener", build)


@pytest.mark.parametrize("kind", ["deadline", "size", "integrity", "network"])
def test_original_refusals_preserve_partial_input_and_closed_failure_metadata(
    acquisition, monkeypatch, tmp_path, kind
):
    module, _clock = acquisition
    data = b"untrusted model data"
    expected_size = len(data) - 1 if kind == "size" else len(data)
    blocks = [TimeoutError("DO_NOT_LOG")] if kind == "network" else [data]
    response(acquisition, monkeypatch, blocks, elapsed=301 if kind == "deadline" else 1)
    target, records = tmp_path / "model.gguf", []
    with pytest.raises((ValueError, TimeoutError)):
        module.acquire("https://huggingface.co/locked", target, expected_size, "0" * 64,
                       observations=records)
    assert not target.exists() and target.with_suffix(".gguf.part").is_file()
    assert records[0]["result"] == "FAIL" and records[0]["deadline_seconds"] == 300
    assert "DO_NOT_LOG" not in json.dumps(records) and "private-path" not in json.dumps(records)
    assert records[0]["final_origin"] == "https://us.aws.cdn.hf.co"
    if kind == "deadline":
        assert records[0]["failure_reason"] == "DEADLINE_EXCEEDED"
        assert records[0]["gate_elapsed_seconds"] == 301
        assert records[0]["received_bytes"] == len(data)
        assert records[0]["write_accepted_bytes"] == 0
    elif kind == "size":
        assert records[0]["failure_reason"] == "DECLARED_SIZE_EXCEEDED"
    elif kind == "integrity":
        assert records[0]["failure_reason"] == "INPUT_INTEGRITY"
        assert target.with_suffix(".gguf.part").read_bytes() == data
    else:
        assert records[0]["exception"] == "TimeoutError"


def test_locked_download_and_existing_input_are_verified_without_redownload(
    acquisition, monkeypatch, tmp_path
):
    module, _clock = acquisition
    data, records = b"locked public synthetic bytes", []
    digest = hashlib.sha256(data).hexdigest()
    response(acquisition, monkeypatch, [data])
    target = tmp_path / "model.gguf"
    module.acquire("https://huggingface.co/locked", target, len(data), digest,
                   observations=records)
    assert target.read_bytes() == data and not target.with_suffix(".gguf.part").exists()
    monkeypatch.setattr(module.urllib.request, "build_opener",
                        lambda *_args: pytest.fail("existing input was downloaded again"))
    module.acquire("https://huggingface.co/locked", target, len(data), digest,
                   observations=records)
    assert [row["mode"] for row in records] == ["DOWNLOADED_LOCKED_INPUT_VERIFIED",
                                                "EXISTING_LOCKED_INPUT_VERIFIED"]
    target.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="existing artifact"):
        module.acquire("https://huggingface.co/locked", target, len(data), digest,
                       observations=records)
    assert target.read_bytes() == b"corrupt"
    assert records[-1]["failure_reason"] == "EXISTING_INPUT_NOT_LOCKED"


@pytest.mark.parametrize("cancelled", [False, True])
def test_receipt_is_exclusive_nonqualifying_and_excludes_exception_text(tmp_path, cancelled):
    spec = importlib.util.spec_from_file_location("acquisition_receipt_under_test",
                                                SCRIPTS / "ai_runtime_acquisition_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "receipt.json"
    failure = KeyboardInterrupt("DO_NOT_LOG") if cancelled else ValueError("DO_NOT_LOG")
    module.save(path, [], failure=failure, source={"commit": "a" * 40, "tree": "b" * 40})
    original = path.read_bytes()
    value = json.loads(original)
    assert value["result"] == ("CANCELLED" if cancelled else "FAIL")
    assert value["native_inference"] == "NOT_RUN_BY_ACQUISITION"
    assert value["qualification_eligible"] is False and value["authority"] == "NOT_GRANTED"
    assert "DO_NOT_LOG" not in original.decode()
    with pytest.raises(FileExistsError):
        module.save(path, [], failure=None, source={})
    assert path.read_bytes() == original
