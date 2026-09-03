from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sys
import textwrap
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from provelume.cli import main
from provelume.derived import materialize_extracted_text
from provelume.extractors import ExtractionResult
from provelume.ocr_contract import (
    OCR_ENGINE_ID,
    OCR_SUPPORTED_INPUTS,
    OcrAdapterCapability,
    OcrBoundingBox,
    OcrContractError,
    OcrPageRequest,
    OcrPageResult,
    OcrProvenance,
    OcrRendererCapability,
    OcrSettings,
    OcrSourcePageIdentity,
    OcrTextSpan,
    OcrUnavailableError,
    ocr_capability_report,
    settings_fingerprint,
)
from provelume.ocr_jobs import OcrJobManager
from provelume.ocr_process import minimal_child_environment, run_bounded_process
from provelume.ocr_renderer import (
    OcrDocumentPlan,
    OcrPlannedPage,
    RenderedOcrPage,
)
from provelume.ocr_tesseract import TesseractCliAdapter
from provelume.scheduler_model import SchedulerError, schedule_payload
from provelume.service import ProvelumeInstance
from provelume.web import create_app

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
ROOT = Path(__file__).resolve().parents[1]


def _renderer_capability() -> OcrRendererCapability:
    return OcrRendererCapability(
        adapter_id="provelume.fixture-renderer",
        adapter_version="1",
        renderer_id="pdfium-pillow",
        renderer_version="5.13.0",
        renderer_available=True,
        version_compatible=True,
        resolved_path="/fixture/libpdfium.so",
        decoder_id="pillow",
        decoder_version="12.3.0",
        component_versions=(
            ("pdfium", "145.0.7616.0"),
            ("pillow", "12.3.0"),
            ("pypdfium2", "5.13.0"),
        ),
        input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
    )


def _adapter_capability() -> OcrAdapterCapability:
    return OcrAdapterCapability(
        adapter_id="provelume.fixture-tesseract",
        adapter_version="1",
        engine_id=OCR_ENGINE_ID,
        engine_version="5.5.3",
        engine_available=True,
        engine_executable="/fixture/tesseract",
        version_compatible=True,
        tessdata_path="/fixture/tessdata",
        installed_languages=("eng", "ita"),
        input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
        emits_coordinates=True,
        emits_confidence=True,
    )


class FakeRenderer:
    def __init__(self, page_count: int = 1):
        self.page_count = page_count
        self.rendered: list[int] = []

    def capability(self) -> OcrRendererCapability:
        return _renderer_capability()

    def inspect(
        self,
        original_path: Path,
        *,
        media_type: str,
        suffix: str,
        signature: bytes,
        input_bytes: int,
        work_directory: Path,
        deadline_seconds: int | None = None,
    ) -> OcrDocumentPlan:
        del original_path, signature, work_directory
        assert input_bytes > 0
        assert deadline_seconds is None or deadline_seconds >= 1
        return OcrDocumentPlan(
            media_type=media_type,
            suffix=suffix,
            input_bytes=input_bytes,
            pages=tuple(
                OcrPlannedPage(number=number, width=1200, height=400)
                for number in range(1, self.page_count + 1)
            ),
        )

    def render(
        self,
        original_path: Path,
        plan: OcrDocumentPlan,
        page_number: int,
        *,
        work_directory: Path,
        cancelled=None,
        deadline_seconds: int | None = None,
    ) -> RenderedOcrPage:
        del original_path, plan
        assert deadline_seconds is None or deadline_seconds >= 1
        if cancelled is not None and cancelled():
            raise OcrContractError("ocr_cancelled", "cancelled fixture")
        data = b"\x89PNG\r\n\x1a\n" + str(page_number).encode("ascii")
        path = work_directory / f"page-{page_number}.png"
        path.write_bytes(data)
        self.rendered.append(page_number)
        return RenderedOcrPage(
            number=page_number,
            path=path,
            width=1200,
            height=400,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
        )


class FakeAdapter:
    def __init__(
        self,
        renderer: OcrRendererCapability,
        *,
        fail_page_once: int | None = None,
    ):
        self.renderer = renderer
        self.calls: list[int] = []
        self.cancelled = None
        self.fail_page_once = fail_page_once
        self.failed_once = False

    def capability(self) -> OcrAdapterCapability:
        return _adapter_capability()

    def recognise_page(self, request: OcrPageRequest, staged_page_path: Path) -> OcrPageResult:
        assert staged_page_path.is_file()
        self.calls.append(request.source_page.page_number)
        if request.source_page.page_number == self.fail_page_once and not self.failed_once:
            self.failed_once = True
            raise OcrContractError("ocr_adapter_failure", "synthetic adapter crash")
        capability = self.capability()
        page = request.source_page
        text = f"Page {page.page_number} local OCR"
        provenance = OcrProvenance(
            engine_id=capability.engine_id,
            engine_version=capability.engine_version or "missing",
            engine_executable=capability.engine_executable or "missing",
            adapter_id=capability.adapter_id,
            adapter_version=capability.adapter_version,
            tessdata_path=capability.tessdata_path,
            renderer_id=self.renderer.renderer_id,
            renderer_version=self.renderer.renderer_version or "missing",
            renderer_adapter_id=self.renderer.adapter_id,
            renderer_adapter_version=self.renderer.adapter_version,
            renderer_resolved_path=self.renderer.resolved_path or "missing",
            decoder_id=self.renderer.decoder_id,
            decoder_version=self.renderer.decoder_version or "missing",
            render_dpi=300,
            languages=request.languages,
            settings_sha256=request.settings_sha256,
            source_page=page,
        )
        return OcrPageResult(
            source_page=page,
            text=text,
            text_status="machine-unverified",
            spans=(
                OcrTextSpan(
                    text=text,
                    status="machine-unverified",
                    confidence=0.91,
                    box=OcrBoundingBox(
                        left=10,
                        top=10,
                        width=300,
                        height=40,
                        page_width=request.page_width,
                        page_height=request.page_height,
                    ),
                ),
            ),
            warnings=(),
            observations=(),
            provenance=provenance,
        )


def _fixture(
    tmp_path: Path,
    *,
    page_count: int = 1,
    fail_page_once: int | None = None,
) -> tuple[ProvelumeInstance, OcrJobManager, FakeRenderer, FakeAdapter, str]:
    source = tmp_path / "source"
    source.mkdir()
    (source / "scan.png").write_bytes(_PNG)
    instance = ProvelumeInstance.initialise(tmp_path / "instance")
    instance.ingest_run(source)
    version_id = str(instance.store.list_canonical("versions")[0]["id"])
    renderer = FakeRenderer(page_count=page_count)
    adapter = FakeAdapter(_renderer_capability(), fail_page_once=fail_page_once)
    manager = OcrJobManager(
        instance.store,
        renderer_factory=lambda settings, temporary: renderer,
        adapter_factory=lambda settings, capability, temporary: adapter,
    )
    instance.scheduler._ocr_manager_factory = lambda store: manager
    return instance, manager, renderer, adapter, version_id


def test_disabled_default_does_not_probe_or_create_ocr_state(tmp_path: Path) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path)
    assert manager.capability()["state"] == "disabled"
    assert renderer.rendered == []
    assert adapter.calls == []
    with pytest.raises(OcrUnavailableError) as exc_info:
        manager.queue(version_id)
    assert exc_info.value.code == "ocr_disabled"
    assert not manager.root.exists()
    with pytest.raises(SchedulerError):
        instance.create_schedule_policy(
            job_kind="ocr.execute",
            scope={"kind": "instance", "id": instance.instance_summary()["id"]},
            state="disabled",
            schedule={},
        )


def test_selected_page_job_is_idempotent_checkpointed_and_removable(
    tmp_path: Path,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path, page_count=3)
    original = instance.store.list_canonical("originals")[0]
    original_before = instance.store.original_bytes(original["id"])
    canonical_before = instance.store.knowledge_fingerprint()

    queued = manager.queue(
        version_id,
        mode="selected-page",
        languages=("eng",),
        pages=(2,),
    )
    duplicate = manager.queue(
        version_id,
        mode="selected-page",
        languages=("eng",),
        pages=(2,),
    )
    assert queued["created"] is True
    assert duplicate["created"] is False
    assert duplicate["job"]["id"] == queued["job"]["id"]

    completed = instance.scheduler.run_one(job_id=queued["job"]["id"])

    assert completed is not None
    assert completed["status"] == "succeeded"
    assert completed["progress"] == {"processed": 1, "skipped": 0, "errors": 0}
    assert completed["checkpoint"]["phase"] == "committed"
    assert renderer.rendered == [2]
    assert adapter.calls == [2]
    bundle = manager.list_bundles(version_id)[0]
    assert bundle["manifest"]["job"] == {
        "id": queued["job"]["id"],
        "state": "succeeded",
    }
    assert [item["page_number"] for item in bundle["manifest"]["pages"]] == [2]
    assert bundle["manifest"]["authoritative"] is False
    assert bundle["manifest"]["text_is_verified"] is False
    assert bundle["manifest"]["network_used"] is False
    bundle_schema = json.loads(
        (ROOT / "core" / "provelume" / "ocr_bundle.schema.json").read_text(encoding="utf-8")
    )
    assert set(bundle["manifest"]) == set(bundle_schema["required"])
    result_ref = bundle["manifest"]["pages"][0]["result_ref"]
    page_record = json.loads((instance.root / result_ref).read_text(encoding="utf-8"))
    assert set(page_record) == set(bundle_schema["$defs"]["pageRecord"]["required"])
    assert page_record["result"]["authoritative"] is False
    assert page_record["result"]["observations"] == {
        "barcode": [],
        "layout": [],
        "qr-code": [],
        "table": [],
    }
    run = manager.get_run(queued["job"]["id"])
    assert run is not None
    assert run["original_sha256_before"] == run["original_sha256_after"]
    assert run["canonical_fingerprint_before"] == run["canonical_fingerprint_after"]
    assert instance.store.original_bytes(original["id"]) == original_before
    assert instance.store.knowledge_fingerprint() == canonical_before

    removed = manager.remove(version_id)
    assert len(removed["removed_artifact_ids"]) == 1
    assert manager.list_bundles(version_id) == []
    assert instance.store.original_bytes(original["id"]) == original_before
    assert instance.store.knowledge_fingerprint() == canonical_before

    rebuilt = manager.rebuild(version_id)
    assert rebuilt["queued"]["created"] is True
    rebuilt_job = rebuilt["queued"]["job"]["id"]
    assert rebuilt_job != queued["job"]["id"]
    rebuilt_result = instance.scheduler.run_one(job_id=rebuilt_job)
    assert rebuilt_result is not None and rebuilt_result["status"] == "succeeded"
    assert (
        manager.list_bundles(version_id)[0]["manifest"]["derivation_key"]
        == (queued["request"]["derivation_key"])
    )


def test_permanent_document_purge_removes_every_ocr_bundle_payload(
    tmp_path: Path,
) -> None:
    instance, manager, _renderer, _adapter, version_id = _fixture(tmp_path)
    queued = manager.queue(version_id, mode="forced")
    completed = instance.scheduler.run_one(job_id=queued["job"]["id"])
    assert completed is not None and completed["status"] == "succeeded"
    bundle = manager.list_bundles(version_id)[0]
    manifest = bundle["manifest"]
    payloads = {
        instance.root / str(bundle["artifact"]["storage_ref"]),
        *(
            instance.root / str(page[key])
            for page in manifest["pages"]
            for key in ("result_ref", "text_ref")
        ),
    }
    assert all(path.is_file() for path in payloads)
    document_id = str(manifest["document_id"])

    instance.trash_document(document_id)
    preview = instance.purge_document_preview(document_id)
    result = instance.purge_document(
        document_id,
        str(preview["confirmation_token"]),
        acknowledge_boundaries=True,
    )

    assert result["status"] == "completed"
    assert all(not path.exists() for path in payloads)
    assert not any(manager.bundles.rglob("*.txt"))
    assert manager.list_bundles(version_id) == []


def test_automatic_mode_skips_reliable_text_without_component_probe(
    tmp_path: Path,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path)
    materialize_extracted_text(
        instance.store,
        version_id,
        ExtractionResult(
            text="This is deterministic reliable embedded text for automatic OCR policy.",
            generator="pypdf",
            generator_version="1",
        ),
    )

    result = manager.queue(version_id, mode="automatic")

    assert result["scheduled"] is False
    assert result["reason"] == "reliable-text-present"
    assert renderer.rendered == []
    assert adapter.calls == []


def test_automatic_mode_does_not_treat_image_metadata_as_reliable_text(
    tmp_path: Path,
) -> None:
    _instance, manager, renderer, adapter, version_id = _fixture(tmp_path)

    queued = manager.queue(version_id, mode="automatic")

    assert queued["scheduled"] is True
    assert queued["request"]["automatic_evidence"] == {
        "reliable_text_characters": 0,
        "printable_ratio": 0.0,
        "reliable_text_generator": "provelume.image-metadata",
    }
    assert renderer.rendered == []
    assert adapter.calls == []


def test_ocr_expired_lease_with_page_checkpoint_is_resumable(tmp_path: Path) -> None:
    instance, manager, _renderer, _adapter, version_id = _fixture(tmp_path)
    queued = manager.queue(version_id, mode="forced")
    start = datetime.fromisoformat(str(queued["job"]["eligible_at"])).astimezone(UTC)
    job = instance.scheduler.journal.claim_next(
        worker_id="fixture",
        job_id=queued["job"]["id"],
        lease_seconds=10,
        now=start,
    )
    assert job is not None
    job = instance.scheduler.journal.checkpoint(
        job["id"],
        job["lease"]["token"],
        sequence=1,
        phase="executing",
        progress={"processed": 1, "skipped": 0, "errors": 0},
        now=start,
    )

    recovery = instance.scheduler.journal.recover(now=start + timedelta(seconds=11))

    assert recovery["expired_leases"] == 1
    recovered = instance.scheduler.journal.get_job(job["id"])
    assert recovered is not None
    assert recovered["status"] == "queued"
    assert recovered["recovery_state"] == "resumable"


def test_running_job_cancellation_is_cooperative_sanitized_and_immutable(
    tmp_path: Path,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path)
    original = instance.store.list_canonical("originals")[0]
    original_before = instance.store.original_bytes(original["id"])
    canonical_before = instance.store.knowledge_fingerprint()
    queued = manager.queue(version_id, mode="forced")
    claimed = instance.scheduler.journal.claim_next(
        worker_id="fixture",
        job_id=queued["job"]["id"],
        lease_seconds=60,
    )
    assert claimed is not None

    cancellation = instance.cancel_ocr_job(claimed["id"])

    assert cancellation["cancellation_requested"] is True
    assert cancellation["job"]["lease"]["token_present"] is True
    assert "token" not in cancellation["job"]["lease"]
    with pytest.raises(OcrContractError) as exc_info:
        manager.execute(claimed, checkpoint=lambda progress: progress)
    assert exc_info.value.code == "ocr_cancelled"
    run = manager.get_run(claimed["id"])
    assert run is not None and run["state"] == "cancelled"
    assert run["original_sha256_before"] == run["original_sha256_after"]
    assert run["canonical_fingerprint_before"] == run["canonical_fingerprint_after"]
    assert instance.store.original_bytes(original["id"]) == original_before
    assert instance.store.knowledge_fingerprint() == canonical_before
    assert renderer.rendered == []
    assert adapter.calls == []


def test_ocr_retry_resumes_page_checkpoint_without_duplicate_artifact(
    tmp_path: Path,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(
        tmp_path,
        page_count=2,
        fail_page_once=2,
    )
    queued = manager.queue(version_id, mode="forced")
    first_now = datetime.fromisoformat(str(queued["job"]["eligible_at"])).astimezone(UTC)

    first = instance.scheduler.run_one(job_id=queued["job"]["id"], now=first_now)

    assert first is not None
    assert first["status"] == "retry_wait"
    assert first["progress"] == {"processed": 1, "skipped": 0, "errors": 1}
    assert manager.list_bundles(version_id) == []
    retry_at = datetime.fromisoformat(str(first["retry_not_before"]))
    instance.scheduler.recover(now=retry_at)

    second = instance.scheduler.run_one(job_id=queued["job"]["id"], now=retry_at)

    assert second is not None and second["status"] == "succeeded"
    assert second["attempt"] == 2
    assert renderer.rendered == [1, 2, 2]
    assert adapter.calls == [1, 2, 2]
    bundles = manager.list_bundles(version_id)
    assert len(bundles) == 1
    assert [page["page_number"] for page in bundles[0]["manifest"]["pages"]] == [
        1,
        2,
    ]


def test_ocr_job_enforces_the_total_deadline_without_publishing(
    tmp_path: Path,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path)
    settings = OcrSettings(mode="forced")
    settings = replace(
        settings,
        limits=replace(
            settings.limits,
            max_seconds_per_page=1,
            max_total_seconds=1,
        ),
    )
    manager.configure(settings)
    calls = 0

    def advancing_clock() -> float:
        nonlocal calls
        calls += 1
        return 2.0 if calls >= 7 else 0.0

    timed = OcrJobManager(
        instance.store,
        renderer_factory=manager.renderer_factory,
        adapter_factory=manager.adapter_factory,
        clock=advancing_clock,
    )
    instance.scheduler._ocr_manager_factory = lambda store: timed
    queued = timed.queue(version_id)

    result = instance.scheduler.run_one(job_id=queued["job"]["id"])

    assert result is not None and result["status"] == "retry_wait"
    assert result["attempts"][-1]["error_code"] == "ocr_deadline_exceeded"
    assert timed.list_bundles(version_id) == []
    run = timed.get_run(queued["job"]["id"])
    assert run is not None and run["error"]["code"] == "ocr_deadline_exceeded"
    assert run["original_sha256_before"] == run["original_sha256_after"]
    assert run["canonical_fingerprint_before"] == run["canonical_fingerprint_after"]


def test_ocr_deadline_covers_bundle_and_registration_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, manager, _renderer, _adapter, version_id = _fixture(tmp_path)
    settings = OcrSettings(mode="forced")
    settings = replace(
        settings,
        limits=replace(
            settings.limits,
            max_seconds_per_page=1,
            max_total_seconds=1,
        ),
    )
    manager.configure(settings)
    now = [0.0]
    timed = OcrJobManager(
        instance.store,
        renderer_factory=manager.renderer_factory,
        adapter_factory=manager.adapter_factory,
        clock=lambda: now[0],
    )
    instance.scheduler._ocr_manager_factory = lambda store: timed
    original_promote = timed._promote_bundle

    def promote_then_expire(*args, **kwargs):
        result = original_promote(*args, **kwargs)
        now[0] = 2.0
        return result

    monkeypatch.setattr(timed, "_promote_bundle", promote_then_expire)
    queued = timed.queue(version_id)

    result = instance.scheduler.run_one(job_id=queued["job"]["id"])

    assert result is not None and result["status"] == "retry_wait"
    assert result["attempts"][-1]["error_code"] == "ocr_deadline_exceeded"
    assert timed.list_bundles(version_id) == []
    assert not any(timed.bundles.rglob("manifest.json"))


def test_ocr_cumulative_work_and_promotion_respect_temporary_budget(
    tmp_path: Path,
) -> None:
    _instance, manager, _renderer, _adapter, _version_id = _fixture(tmp_path)
    manager._ensure_directories()
    derivation = f"ocr_{'a' * 64}"
    request = {"derivation_key": derivation, "version_id": "ver_fixture"}
    work = manager.work / derivation
    work.mkdir()
    record = {"payload": "x" * 1024}
    first = manager._checkpoint_work_page(
        work,
        request,
        1,
        record,
        max_temp_bytes=1024 * 1024,
    )
    committed_bytes = sum(path.stat().st_size for path in work.rglob("*") if path.is_file())
    cumulative_limit = committed_bytes + 1
    assert len(first) < cumulative_limit

    with pytest.raises(OcrContractError) as checkpoint_error:
        manager._checkpoint_work_page(
            work,
            request,
            2,
            record,
            max_temp_bytes=cumulative_limit,
        )
    assert checkpoint_error.value.code == "ocr_temporary_space_exceeded"
    assert not (work / "pages" / "000002.json").exists()

    with pytest.raises(OcrContractError) as promotion_error:
        manager._promote_bundle(
            {"id": "job_fixture"},
            request,
            {1: first},
            work_directory=work,
            max_temp_bytes=committed_bytes + len(first) - 1,
            check_deadline=lambda: 1,
        )
    assert promotion_error.value.code == "ocr_temporary_space_exceeded"
    assert not (manager.bundles / "ver_fixture" / derivation).exists()


def test_ocr_run_rejects_non_ocr_scheduler_job_without_executing(
    tmp_path: Path,
) -> None:
    instance, _manager, _renderer, _adapter, _version_id = _fixture(tmp_path)
    policy = instance.scheduler.journal.create_policy(
        job_kind="maintenance.validate",
        scope={"kind": "instance", "id": instance.instance_summary()["id"]},
        state="disabled",
        schedule=schedule_payload(mode="manual", timezone="UTC"),
    )
    queued = instance.scheduler.journal.run_now(policy["id"], request_key="not-an-ocr-job")["job"]

    with pytest.raises(OcrContractError) as exc_info:
        instance.run_ocr_job(str(queued["id"]))

    assert exc_info.value.code == "ocr_contract_violation"
    unchanged = instance.scheduler.journal.get_job(str(queued["id"]))
    assert unchanged is not None and unchanged["status"] == "queued"


def test_failed_bundle_registration_rolls_back_publication_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance, manager, renderer, adapter, version_id = _fixture(tmp_path)
    queued = manager.queue(version_id, mode="forced")
    original_write = instance.store.write_derived_provenance
    failed = False

    def fail_once(edge: object) -> None:
        nonlocal failed
        if not failed and getattr(edge, "relation", None) == "ocr_derived_to":
            failed = True
            raise OSError("synthetic derived provenance failure")
        original_write(edge)  # type: ignore[arg-type]

    monkeypatch.setattr(instance.store, "write_derived_provenance", fail_once)

    first = instance.scheduler.run_one(job_id=queued["job"]["id"])

    assert first is not None and first["status"] == "retry_wait"
    assert manager.list_bundles(version_id) == []
    assert not any(manager.bundles.rglob("manifest.json"))
    retry_at = datetime.fromisoformat(str(first["retry_not_before"]))
    instance.scheduler.recover(now=retry_at)
    second = instance.scheduler.run_one(job_id=queued["job"]["id"], now=retry_at)
    assert second is not None and second["status"] == "succeeded"
    assert renderer.rendered == [1]
    assert adapter.calls == [1]
    assert len(manager.list_bundles(version_id)) == 1


def test_bounded_process_has_minimal_environment_limits_and_cancellation(
    tmp_path: Path,
) -> None:
    environment = minimal_child_environment(tmp_path)
    assert "HOME" not in environment
    assert "PATH" not in environment
    assert "HTTP_PROXY" not in environment
    assert set(environment) >= {"LANG", "LC_ALL", "TMP", "TEMP", "TMPDIR"}

    safe_argument = "literal;touch should-not-exist"
    result = run_bounded_process(
        [sys.executable, "-c", "import sys;print(sys.argv[1])", safe_argument],
        temporary_directory=tmp_path,
        timeout_seconds=5,
        stdout_limit=1024,
        stderr_limit=1024,
    )
    assert result.returncode == 0
    assert result.stdout.strip().decode() == safe_argument
    assert not (tmp_path / "should-not-exist").exists()
    assert list(tmp_path.glob(".process-*")) == []

    with pytest.raises(OcrContractError) as output_error:
        run_bounded_process(
            [sys.executable, "-c", "print('x' * 10000)"],
            temporary_directory=tmp_path,
            timeout_seconds=5,
            stdout_limit=100,
            stderr_limit=100,
        )
    assert output_error.value.code == "ocr_output_limit_exceeded"

    with pytest.raises(OcrContractError) as timeout_error:
        run_bounded_process(
            [sys.executable, "-c", "import time;time.sleep(5)"],
            temporary_directory=tmp_path,
            timeout_seconds=1,
            stdout_limit=100,
            stderr_limit=100,
        )
    assert timeout_error.value.code == "ocr_deadline_exceeded"

    with pytest.raises(OcrContractError) as cancel_error:
        run_bounded_process(
            [sys.executable, "-c", "import time;time.sleep(5)"],
            temporary_directory=tmp_path,
            timeout_seconds=5,
            stdout_limit=100,
            stderr_limit=100,
            cancelled=lambda: True,
        )
    assert cancel_error.value.code == "ocr_cancelled"
    assert list(tmp_path.glob(".process-*")) == []

    produced = tmp_path / "produced.bin"
    with pytest.raises(OcrContractError) as produced_error:
        run_bounded_process(
            [
                sys.executable,
                "-c",
                (
                    "import pathlib,time; p=pathlib.Path('produced.bin'); "
                    "p.write_bytes(b'x'*10000); time.sleep(5)"
                ),
            ],
            temporary_directory=tmp_path,
            timeout_seconds=5,
            stdout_limit=100,
            stderr_limit=100,
            produced_file_limits={produced: 100},
        )
    assert produced_error.value.code == "ocr_output_limit_exceeded"


def test_bounded_process_retries_delayed_capture_handle_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_unlink = Path.unlink
    attempts: dict[Path, int] = {}

    def delayed_unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path.name.startswith(".process-"):
            attempts[path] = attempts.get(path, 0) + 1
            if attempts[path] == 1:
                raise PermissionError("synthetic delayed capture handle release")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", delayed_unlink)
    result = run_bounded_process(
        [sys.executable, "-c", "print('bounded')"],
        temporary_directory=tmp_path,
        timeout_seconds=5,
        stdout_limit=100,
        stderr_limit=100,
    )

    assert result.stdout.strip() == b"bounded"
    assert attempts and all(count == 2 for count in attempts.values())
    assert list(tmp_path.glob(".process-*")) == []


def _fake_tesseract(tmp_path: Path, mode: str) -> Path:
    if os.name == "nt":
        pytest.skip("the shebang fake CLI is POSIX-only; Windows process cleanup is separate")
    executable = tmp_path / f"fake-tesseract-{mode}"
    executable.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import pathlib
            import sys
            import time

            mode = {mode!r}
            if sys.argv[1:] == ["--version"]:
                print("tesseract 5.5.3")
                raise SystemExit(0)
            if sys.argv[1:] == ["--list-langs"]:
                print('List of available languages in "/fixture/tessdata/" (2):')
                print("eng")
                print("ita")
                raise SystemExit(0)
            output = pathlib.Path(sys.argv[2] + ".tsv")
            header = (
                "level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\t"
                "left\\ttop\\twidth\\theight\\tconf\\ttext\\n"
            )
            row = "5\\t1\\t1\\t1\\t1\\t1\\t10\\t20\\t100\\t30\\t42.0\\tuncertain\\n"
            if mode == "valid":
                output.write_text(header + row, encoding="utf-8")
            elif mode == "malformed":
                output.write_text("not-tsv\\n", encoding="utf-8")
            elif mode == "incomplete":
                output.write_text(
                    header + row.rsplit("\\t", 1)[0] + "\\n", encoding="utf-8"
                )
            elif mode == "huge":
                output.write_bytes(b"x" * (32 * 1024 * 1024 + 1))
            elif mode == "nonzero":
                raise SystemExit(7)
            elif mode == "hang":
                time.sleep(5)
            elif mode == "missing":
                pass
            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable


def _tesseract_request(settings: OcrSettings, image: Path) -> OcrPageRequest:
    return OcrPageRequest(
        source_page=OcrSourcePageIdentity(
            original_sha256="a" * 64,
            version_id="ver_fixture",
            page_number=1,
            page_image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
            source_media_type="image/png",
        ),
        staged_media_type="image/png",
        page_width=1000,
        page_height=1000,
        settings_sha256=settings_fingerprint(settings),
        languages=settings.languages,
        deadline_seconds=settings.limits.max_seconds_per_page,
        max_output_chars=settings.limits.max_output_chars_per_page,
    )


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("malformed", "ocr_engine_output_invalid"),
        ("incomplete", "ocr_engine_output_invalid"),
        ("huge", "ocr_output_limit_exceeded"),
        ("nonzero", "ocr_adapter_failure"),
        ("missing", "ocr_engine_output_invalid"),
    ],
)
def test_fake_tesseract_cli_rejects_invalid_outputs(tmp_path: Path, mode: str, code: str) -> None:
    executable = _fake_tesseract(tmp_path, mode)
    settings = OcrSettings(
        mode="forced",
        engine_executable=str(executable),
        languages=("eng",),
    )
    image = tmp_path / "page;not-a-command.png"
    image.write_bytes(_PNG)
    adapter = TesseractCliAdapter(settings, _renderer_capability(), tmp_path)

    with pytest.raises(OcrContractError) as exc_info:
        adapter.recognise_page(_tesseract_request(settings, image), image)

    assert exc_info.value.code == code
    assert not (tmp_path / "not-a-command.png").exists()


def test_fake_tesseract_cli_reports_identity_languages_confidence_and_warnings(
    tmp_path: Path,
) -> None:
    executable = _fake_tesseract(tmp_path, "valid")
    settings = OcrSettings(
        mode="forced",
        engine_executable=str(executable),
        languages=("eng",),
    )
    image = tmp_path / "page.png"
    image.write_bytes(_PNG)
    adapter = TesseractCliAdapter(settings, _renderer_capability(), tmp_path)

    capability = adapter.capability()
    result = adapter.recognise_page(_tesseract_request(settings, image), image)

    assert capability.engine_version == "5.5.3"
    assert capability.engine_executable == str(executable.resolve())
    assert capability.installed_languages == ("eng", "ita")
    assert capability.tessdata_path == "/fixture/tessdata"
    assert result.text == "uncertain"
    assert result.text_status == "needs-review"
    assert result.spans[0].confidence == 0.42
    assert result.warnings[0].code == "low-confidence"
    assert result.observations == ()
    assert result.provenance.engine_executable == str(executable.resolve())


def test_fake_tesseract_cli_timeout_and_cooperative_cancellation(
    tmp_path: Path,
) -> None:
    executable = _fake_tesseract(tmp_path, "hang")
    settings = OcrSettings(
        mode="forced",
        engine_executable=str(executable),
        languages=("eng",),
    )
    settings = replace(
        settings,
        limits=replace(settings.limits, max_seconds_per_page=1),
    )
    image = tmp_path / "page.png"
    image.write_bytes(_PNG)
    timed = TesseractCliAdapter(settings, _renderer_capability(), tmp_path)

    with pytest.raises(OcrContractError) as timeout_error:
        timed.recognise_page(_tesseract_request(settings, image), image)
    assert timeout_error.value.code == "ocr_deadline_exceeded"

    cancellable = TesseractCliAdapter(
        settings,
        _renderer_capability(),
        tmp_path,
        cancelled=lambda: True,
    )
    with pytest.raises(OcrContractError) as cancel_error:
        cancellable.recognise_page(_tesseract_request(settings, image), image)
    assert cancel_error.value.code == "ocr_cancelled"


def test_capability_distinguishes_missing_engine_renderer_version_and_language(
    tmp_path: Path,
) -> None:
    missing_engine = TesseractCliAdapter(
        OcrSettings(mode="forced", engine_executable=str(tmp_path / "absent")),
        _renderer_capability(),
        tmp_path,
    )
    renderer_missing = OcrRendererCapability(
        adapter_id="provelume.fixture-renderer",
        adapter_version="1",
        renderer_id="pdfium-pillow",
        renderer_version=None,
        renderer_available=False,
        version_compatible=False,
        resolved_path=None,
        decoder_id="pillow",
        decoder_version=None,
        component_versions=(),
        input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
    )

    class Renderer:
        def __init__(self, capability: OcrRendererCapability):
            self._capability = capability

        def capability(self) -> OcrRendererCapability:
            return self._capability

    assert (
        ocr_capability_report(
            OcrSettings(mode="forced"), missing_engine, Renderer(_renderer_capability())
        )["state"]
        == "engine-unavailable"
    )
    assert (
        ocr_capability_report(
            OcrSettings(mode="forced"),
            FakeAdapter(_renderer_capability()),
            Renderer(renderer_missing),
        )["state"]
        == "renderer-unavailable"
    )

    executable = _fake_tesseract(tmp_path, "valid")
    language_adapter = TesseractCliAdapter(
        OcrSettings(
            mode="forced",
            engine_executable=str(executable),
            languages=("deu",),
        ),
        _renderer_capability(),
        tmp_path,
    )
    language_report = ocr_capability_report(
        language_adapter.settings,
        language_adapter,
        Renderer(_renderer_capability()),
    )
    assert language_report["state"] == "language-pack-missing"
    assert language_report["missing_languages"] == ["deu"]


def test_ocr_cli_and_guarded_browser_control_surfaces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    instance, manager, _renderer, _adapter, version_id = _fixture(tmp_path)
    assert main(["ocr-configure", str(instance.root), "--mode", "disabled"]) == 0
    configured = json.loads(capsys.readouterr().out)
    assert configured["mode"] == "disabled"
    assert main(["ocr-capability", str(instance.root)]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "disabled"

    app = create_app(instance.root)
    web_instance = app.state.provelume
    web_manager = OcrJobManager(
        web_instance.store,
        renderer_factory=manager.renderer_factory,
        adapter_factory=manager.adapter_factory,
    )
    web_instance.ocr = web_manager
    web_instance.scheduler._ocr_manager_factory = lambda store: web_manager
    client = TestClient(app)
    page = client.get("/ocr")
    assert page.status_code == 200
    token_match = re.search(r'name="csrf_token" value="([^"]+)"', page.text)
    assert token_match is not None
    token = token_match.group(1)
    assert (
        client.post(
            "/ocr",
            data={"csrf_token": "wrong", "action": "configure"},
        ).status_code
        == 403
    )
    configured_page = client.post(
        "/ocr",
        data={
            "csrf_token": token,
            "action": "configure",
            "mode": "forced",
            "languages": "eng",
            "engine_executable": "/fixture/tesseract",
            "tessdata_path": "/fixture/tessdata",
            "render_dpi": "300",
        },
    )
    assert configured_page.status_code == 200
    assert "configured" in configured_page.text
    queued_page = client.post(
        "/ocr",
        data={
            "csrf_token": token,
            "action": "queue",
            "version_id": version_id,
            "mode": "forced",
            "languages": "eng",
            "pages": "",
        },
    )
    assert queued_page.status_code == 200
    assert "queued:" in queued_page.text
    capability = client.get("/api/v1/ocr/capability").json()
    assert capability["state"] == "ready"
    assert capability["network_required"] is False
    jobs = client.get("/api/v1/ocr/jobs").json()
    assert len(jobs) == 1
    assert jobs[0]["job"]["job_kind"] == "ocr.execute"
    cancelled = web_instance.cancel_ocr_job(jobs[0]["job"]["id"])
    assert cancelled["job"].get("lease") is None
    assert client.post("/api/v1/ocr/jobs").status_code == 405


def test_bundle_schema_reuses_the_public_contract_definitions() -> None:
    bundle_schema = json.loads(
        (ROOT / "core" / "provelume" / "ocr_bundle.schema.json").read_text(encoding="utf-8")
    )
    contract_schema = json.loads(
        (ROOT / "core" / "provelume" / "ocr_contract.schema.json").read_text(encoding="utf-8")
    )
    assert bundle_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert bundle_schema["properties"]["schema_version"]["const"] == 1
    assert bundle_schema["properties"]["settings"] == {
        "$ref": "ocr_contract.schema.json#/$defs/settings"
    }

    def assert_references(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str):
                if reference.startswith("#/$defs/"):
                    assert reference.removeprefix("#/$defs/") in bundle_schema["$defs"]
                elif reference.startswith("ocr_contract.schema.json#/$defs/"):
                    assert (
                        reference.removeprefix("ocr_contract.schema.json#/$defs/")
                        in contract_schema["$defs"]
                    )
                else:
                    pytest.fail(f"unsupported OCR bundle schema reference: {reference}")
            for child in value.values():
                assert_references(child)
        elif isinstance(value, list):
            for child in value:
                assert_references(child)

    assert_references(bundle_schema)
