from __future__ import annotations

import json
import os
import socket
import subprocess
import tomllib
import urllib.request
from pathlib import Path

import pytest

from provelume import __version__
from provelume.ocr_contract import (
    OCR_CAPABILITY_STATES,
    OCR_CONTRACT_SCHEMA_VERSION,
    OCR_ENGINE_ID,
    OCR_ERROR_CODES,
    OCR_LIMIT_CEILINGS,
    OCR_MODES,
    OCR_OBSERVATION_KINDS,
    OCR_STAGED_PAGE_INPUTS,
    OCR_SUPPORTED_INPUTS,
    OcrAdapterCapability,
    OcrAutomaticPolicy,
    OcrBoundingBox,
    OcrContractError,
    OcrInputDescriptor,
    OcrLanguageDetection,
    OcrLimits,
    OcrObservation,
    OcrPageRequest,
    OcrPageResult,
    OcrPageWarning,
    OcrProvenance,
    OcrRendererCapability,
    OcrSettings,
    OcrSourcePageIdentity,
    OcrTextSpan,
    OcrUnavailableError,
    default_ocr_config,
    isolated_ocr_temp_directory,
    ocr_capability_report,
    ocr_checkpoint_record,
    ocr_derivation_key,
    ocr_settings_from_config,
    require_ocr_available,
    settings_fingerprint,
    should_schedule_ocr,
    validate_ocr_page_result,
)
from provelume.storage import InstanceStore

ROOT = Path(__file__).resolve().parents[1]


class FakeAdapter:
    def __init__(
        self,
        *,
        engine_available: bool = True,
        languages: tuple[str, ...] = ("eng", "ita"),
    ):
        self.calls = 0
        self.engine_available = engine_available
        self.languages = languages

    def capability(self) -> OcrAdapterCapability:
        self.calls += 1
        return OcrAdapterCapability(
            adapter_id="provelume.test-ocr",
            adapter_version="1",
            engine_id=OCR_ENGINE_ID,
            engine_version="5.5.3" if self.engine_available else None,
            engine_available=self.engine_available,
            engine_executable=("/fixtures/tesseract" if self.engine_available else None),
            version_compatible=self.engine_available,
            tessdata_path="/fixtures/tessdata" if self.engine_available else None,
            installed_languages=self.languages,
            input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
            emits_coordinates=True,
            emits_confidence=True,
        )

    def recognise_page(
        self, request: OcrPageRequest, staged_page_path: Path
    ) -> OcrPageResult:
        raise AssertionError(
            f"S01 must not execute OCR: {request}, {staged_page_path}"
        )


class FakeRenderer:
    def __init__(self, *, available: bool = True, compatible: bool = True):
        self.calls = 0
        self.available = available
        self.compatible = compatible

    def capability(self) -> OcrRendererCapability:
        self.calls += 1
        return OcrRendererCapability(
            adapter_id="provelume.test-renderer",
            adapter_version="1",
            renderer_id="pdfium-pillow",
            renderer_version="5.13.0" if self.available else None,
            renderer_available=self.available,
            version_compatible=self.available and self.compatible,
            resolved_path="/fixtures/libpdfium.so" if self.available else None,
            decoder_id="pillow",
            decoder_version="12.3.0" if self.available else None,
            component_versions=(
                (("pdfium", "145.0.7616.0"),) if self.available else ()
            ),
            input_media_types=tuple(sorted(OCR_SUPPORTED_INPUTS)),
        )


def page_provenance(
    page: OcrSourcePageIdentity,
    settings: OcrSettings,
    capability: OcrAdapterCapability | None = None,
    renderer: OcrRendererCapability | None = None,
) -> OcrProvenance:
    selected_capability = capability or FakeAdapter().capability()
    selected_renderer = renderer or FakeRenderer().capability()
    return OcrProvenance(
        engine_id=selected_capability.engine_id,
        engine_version=selected_capability.engine_version or "missing",
        engine_executable=selected_capability.engine_executable or "missing",
        adapter_id=selected_capability.adapter_id,
        adapter_version=selected_capability.adapter_version,
        tessdata_path=selected_capability.tessdata_path,
        renderer_id=selected_renderer.renderer_id,
        renderer_version=selected_renderer.renderer_version or "missing",
        renderer_adapter_id=selected_renderer.adapter_id,
        renderer_adapter_version=selected_renderer.adapter_version,
        renderer_resolved_path=selected_renderer.resolved_path or "missing",
        decoder_id=selected_renderer.decoder_id,
        decoder_version=selected_renderer.decoder_version or "missing",
        render_dpi=settings.render_dpi,
        languages=("eng",),
        settings_sha256=settings_fingerprint(settings),
        source_page=page,
    )


def source_page(page_number: int = 1) -> OcrSourcePageIdentity:
    return OcrSourcePageIdentity(
        original_sha256="a" * 64,
        version_id="ver_public_fixture",
        page_number=page_number,
        page_image_sha256=f"{page_number:064x}",
        source_media_type="application/pdf",
    )


def test_default_configuration_is_disabled_local_and_bounded(tmp_path: Path) -> None:
    settings = OcrSettings()
    assert settings.mode == "disabled"
    assert settings.engine == "tesseract-cli"
    assert settings.languages == ("eng",)
    assert settings.language_detection == OcrLanguageDetection()
    assert settings.limits.as_record() == OCR_LIMIT_CEILINGS
    assert default_ocr_config() == settings.as_record()

    store = InstanceStore.initialise(tmp_path / "instance")
    config = store.read_config()
    assert config["ocr"] == default_ocr_config()
    assert ocr_settings_from_config(config) == settings


def test_existing_configuration_without_ocr_remains_valid() -> None:
    assert ocr_settings_from_config({"schema_version": 2}) == OcrSettings()


def test_configuration_is_closed_and_cannot_raise_resource_ceilings() -> None:
    config = default_ocr_config()
    config["unexpected"] = True
    with pytest.raises(OcrContractError, match="incomplete or unsupported"):
        ocr_settings_from_config({"ocr": config})

    for name, ceiling in OCR_LIMIT_CEILINGS.items():
        limits = default_ocr_config()["limits"]
        limits[name] = ceiling + 1
        with pytest.raises(OcrContractError, match=name):
            ocr_settings_from_config(
                {"ocr": {**default_ocr_config(), "limits": limits}}
            )

    assert OcrSettings(engine="fixture-local-adapter").engine == "fixture-local-adapter"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_ratios_reject_non_finite_configuration_and_confidence(value: float) -> None:
    with pytest.raises(OcrContractError, match="between 0 and 1"):
        OcrAutomaticPolicy(min_printable_ratio=value)
    with pytest.raises(OcrContractError, match="between 0 and 1"):
        OcrTextSpan(
            text="uncertain",
            status="machine-unverified",
            confidence=value,
        )


@pytest.mark.parametrize("mode", OCR_MODES)
def test_declared_modes_are_closed(mode: str) -> None:
    settings = OcrSettings(mode=mode)
    assert settings.mode == mode
    with pytest.raises(OcrContractError, match="unsupported OCR mode"):
        OcrSettings(mode=f"{mode}-remote")


def test_automatic_mode_runs_only_without_reliable_text() -> None:
    settings = OcrSettings(
        mode="automatic",
        automatic=OcrAutomaticPolicy(
            min_reliable_characters=32,
            min_printable_ratio=0.85,
        ),
    )
    assert should_schedule_ocr(
        settings, reliable_text_characters=0, printable_ratio=1.0
    )
    assert should_schedule_ocr(
        settings, reliable_text_characters=100, printable_ratio=0.5
    )
    assert not should_schedule_ocr(
        settings, reliable_text_characters=100, printable_ratio=0.95
    )
    assert not should_schedule_ocr(OcrSettings(), reliable_text_characters=0)


def test_selected_page_mode_requires_a_bounded_exact_selection() -> None:
    settings = OcrSettings(mode="selected-page")
    assert should_schedule_ocr(
        settings,
        selected_pages=(1, 3),
        document_page_count=3,
    )
    for selected in ((), (2, 2), (2, 1), (4,)):
        with pytest.raises(OcrContractError) as exc_info:
            should_schedule_ocr(
                settings,
                selected_pages=selected,
                document_page_count=3,
            )
        assert exc_info.value.code == "ocr_invalid_selection"


def test_language_selection_is_explicit_or_bounded() -> None:
    settings = OcrSettings(
        mode="forced",
        languages=("eng", "ita"),
        language_detection=OcrLanguageDetection(
            mode="bounded",
            candidates=("eng", "ita"),
        ),
    )
    assert settings.language_detection.candidates == ("eng", "ita")
    with pytest.raises(OcrContractError, match="selected language packs"):
        OcrSettings(
            languages=("eng",),
            language_detection=OcrLanguageDetection(
                mode="bounded",
                candidates=("eng", "ita"),
            ),
        )


def test_supported_input_contract_is_explicit() -> None:
    assert OCR_SUPPORTED_INPUTS == {
        "application/pdf": (".pdf",),
        "image/tiff": (".tif", ".tiff"),
        "image/png": (".png",),
        "image/jpeg": (".jpg", ".jpeg"),
        "image/bmp": (".bmp",),
    }
    descriptor = OcrInputDescriptor(
        media_type="image/png",
        suffix=".PNG",
        signature=b"\x89PNG\r\n\x1a\n",
        input_bytes=1024,
        page_count=1,
        max_page_pixels=1_000_000,
        total_pixels=1_000_000,
        max_decompressed_page_bytes=4_000_000,
        max_decompression_ratio=4,
    )
    assert descriptor.validate(OcrLimits())["suffix"] == ".png"


def test_hostile_and_boundary_fixtures_fail_with_closed_codes() -> None:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "ocr-boundaries.json").read_text(
            encoding="utf-8"
        )
    )
    assert fixture["schema_version"] == 1
    for case in fixture["cases"]:
        value = dict(case["descriptor"])
        value["signature"] = bytes.fromhex(value.pop("signature_hex"))
        descriptor = OcrInputDescriptor(**value)
        with pytest.raises(OcrContractError) as exc_info:
            descriptor.validate(OcrLimits())
        assert exc_info.value.code == case["expected_code"], case["name"]
        assert exc_info.value.code in OCR_ERROR_CODES


def test_disabled_reporting_does_not_probe_adapter_or_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"unexpected external effect: {args!r} {kwargs!r}")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    report = ocr_capability_report(OcrSettings(), adapter)
    assert adapter.calls == 0
    assert report["state"] == "disabled"
    assert report["error"]["code"] == "ocr_disabled"
    assert report["network_required"] is False
    assert report["runtime_downloads"] is False
    assert report["remote_fallback"] is False
    assert report["original_mutation"] is False
    assert report["canonical_mutation"] is False


def test_enabled_reporting_fails_closed_when_components_are_absent() -> None:
    settings = OcrSettings(mode="forced", languages=("eng", "ita"))

    report = ocr_capability_report(settings)
    assert report["state"] == "adapter-unavailable"
    with pytest.raises(OcrUnavailableError) as exc_info:
        require_ocr_available(report)
    assert exc_info.value.code == "ocr_adapter_unavailable"
    assert set(exc_info.value.messages) == {"en", "it"}

    engine_missing = ocr_capability_report(
        settings,
        FakeAdapter(engine_available=False, languages=()),
        FakeRenderer(),
    )
    assert engine_missing["state"] == "engine-unavailable"

    renderer_missing = ocr_capability_report(
        settings, FakeAdapter(), FakeRenderer(available=False)
    )
    assert renderer_missing["state"] == "renderer-unavailable"

    incompatible = ocr_capability_report(
        settings, FakeAdapter(), FakeRenderer(compatible=False)
    )
    assert incompatible["state"] == "version-incompatible"

    pack_missing = ocr_capability_report(
        settings, FakeAdapter(languages=("eng",)), FakeRenderer()
    )
    assert pack_missing["state"] == "language-pack-missing"
    assert pack_missing["missing_languages"] == ["ita"]


def test_explicit_adapter_can_report_ready_without_remote_fallback() -> None:
    adapter = FakeAdapter()
    report = ocr_capability_report(
        OcrSettings(mode="forced", languages=("eng", "ita")),
        adapter,
        FakeRenderer(),
    )
    assert adapter.calls == 1
    assert report["state"] == "ready"
    assert report["available"] is True
    assert report["error"] is None
    assert report["adapter"]["engine_version"] == "5.5.3"
    assert report["adapter"]["outputs"] == {
        "coordinates": True,
        "confidence": True,
        "layout": False,
        "tables": False,
        "barcodes": False,
        "qr_codes": False,
    }
    require_ocr_available(report)
    assert tuple(OCR_CAPABILITY_STATES) == (
        "disabled",
        "adapter-unavailable",
        "engine-unavailable",
        "renderer-unavailable",
        "version-incompatible",
        "language-pack-missing",
        "ready",
    )


def test_provenance_idempotency_and_page_checkpoint_are_exact() -> None:
    settings = OcrSettings(mode="forced", languages=("eng", "ita"))
    capability = FakeAdapter().capability()
    renderer = FakeRenderer().capability()
    first = ocr_derivation_key(source_page(1), settings, capability, renderer)
    assert first == ocr_derivation_key(
        source_page(1), settings, capability, renderer
    )
    assert first != ocr_derivation_key(
        source_page(2), settings, capability, renderer
    )

    changed = OcrSettings(mode="forced", languages=("eng",))
    assert first != ocr_derivation_key(
        source_page(1), changed, capability, renderer
    )

    checkpoint = ocr_checkpoint_record(first, (1, 2), total_pages=3)
    assert checkpoint == {
        "schema_version": 1,
        "derivation_key": first,
        "phase": "ocr.page.committed",
        "sequence": 2,
        "committed_pages": [1, 2],
        "next_page": 3,
        "terminal": False,
    }
    assert ocr_checkpoint_record(first, (1, 2, 3), total_pages=3)["terminal"]


def test_page_result_keeps_uncertainty_and_nontext_observations_separate() -> None:
    page = source_page()
    settings = OcrSettings(mode="forced")
    provenance = page_provenance(page, settings)
    span = OcrTextSpan(
        text="uncertain",
        status="needs-review",
        confidence=0.42,
        box=OcrBoundingBox(
            left=10,
            top=20,
            width=100,
            height=30,
            page_width=1000,
            page_height=1400,
        ),
    )
    observations = tuple(
        OcrObservation(
            kind=kind,
            adapter_id="fixture.observer",
            adapter_version="1",
            schema_id=f"{kind}.v1",
            payload={"source": "synthetic"},
        )
        for kind in OCR_OBSERVATION_KINDS
    )
    result = OcrPageResult(
        source_page=page,
        text="uncertain",
        text_status="needs-review",
        spans=(span,),
        warnings=(OcrPageWarning(code="low-confidence", message="Review this page."),),
        observations=observations,
        provenance=provenance,
    ).as_record()

    assert result["text_status"] == "needs-review"
    assert result["spans"][0]["confidence"] == 0.42
    assert set(result["observations"]) == set(OCR_OBSERVATION_KINDS)
    assert all(len(result["observations"][kind]) == 1 for kind in OCR_OBSERVATION_KINDS)
    assert result["authoritative"] is False
    assert result["derived"] is True
    assert result["removable"] is True
    assert result["rebuildable"] is True

    with pytest.raises(OcrContractError, match="cannot be marked as verified"):
        OcrTextSpan(text="claim", status="verified")


def test_page_request_binds_page_settings_languages_and_deadline() -> None:
    settings = OcrSettings(mode="forced")
    request = OcrPageRequest(
        source_page=source_page(),
        staged_media_type="image/png",
        page_width=1000,
        page_height=1400,
        settings_sha256=settings_fingerprint(settings),
        languages=("eng",),
        deadline_seconds=settings.limits.max_seconds_per_page,
        max_output_chars=settings.limits.max_output_chars_per_page,
    )
    assert request.source_page.page_number == 1
    assert request.languages == ("eng",)
    assert request.staged_media_type in OCR_STAGED_PAGE_INPUTS
    assert request.as_record()["max_output_chars"] == 500_000

    with pytest.raises(OcrContractError, match="raster media type"):
        OcrPageRequest(
            source_page=source_page(),
            staged_media_type="application/pdf",
            page_width=1000,
            page_height=1400,
            settings_sha256=settings_fingerprint(settings),
            languages=("eng",),
            deadline_seconds=60,
            max_output_chars=500_000,
        )


def test_adapter_result_must_match_request_limits_and_provenance() -> None:
    settings = OcrSettings(mode="forced")
    capability = FakeAdapter().capability()
    renderer = FakeRenderer().capability()
    request = OcrPageRequest(
        source_page=source_page(),
        staged_media_type="image/png",
        page_width=1000,
        page_height=1400,
        settings_sha256=settings_fingerprint(settings),
        languages=("eng",),
        deadline_seconds=60,
        max_output_chars=5,
    )
    provenance = page_provenance(
        request.source_page, settings, capability, renderer
    )
    result = OcrPageResult(
        source_page=request.source_page,
        text="short",
        text_status="machine-unverified",
        spans=(),
        warnings=(),
        observations=(),
        provenance=provenance,
    )
    validate_ocr_page_result(request, result, capability, renderer)

    too_long = OcrPageResult(
        source_page=request.source_page,
        text="longer",
        text_status="machine-unverified",
        spans=(),
        warnings=(),
        observations=(),
        provenance=provenance,
    )
    with pytest.raises(OcrContractError, match="requested text limit"):
        validate_ocr_page_result(request, too_long, capability, renderer)


def test_temporary_files_are_private_and_cleaned_after_failure(tmp_path: Path) -> None:
    base = tmp_path / "instance-state" / "tmp" / "ocr"
    created: Path | None = None
    with (
        pytest.raises(RuntimeError, match="synthetic failure"),
        isolated_ocr_temp_directory(base) as selected,
    ):
        created = selected
        assert selected.parent == base
        assert selected.name.startswith("ocr-job-")
        assert not selected.is_symlink()
        if os.name == "posix":
            assert selected.stat().st_mode & 0o777 == 0o700
        (selected / "page.bin").write_bytes(b"synthetic")
        raise RuntimeError("synthetic failure")
    assert created is not None
    assert not created.exists()
    assert list(base.iterdir()) == []


def test_machine_readable_schema_matches_python_contract() -> None:
    schema = json.loads(
        (ROOT / "core" / "provelume" / "ocr_contract.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$defs"]["settings"]["properties"]["schema_version"]["const"] == (
        OCR_CONTRACT_SCHEMA_VERSION
    )
    assert tuple(schema["$defs"]["settings"]["properties"]["mode"]["enum"]) == OCR_MODES
    assert (
        tuple(schema["$defs"]["capabilityReport"]["properties"]["state"]["enum"])
        == OCR_CAPABILITY_STATES
    )
    assert set(
        schema["$defs"]["localizedError"]["properties"]["code"]["enum"]
    ) == set(OCR_ERROR_CODES)
    assert schema["$defs"]["pageResult"]["properties"]["authoritative"]["const"] is False
    assert schema["$defs"]["settings"]["properties"]["engine"] == {
        "$ref": "#/$defs/componentId"
    }
    assert set(
        schema["$defs"]["pageRequest"]["properties"]["staged_media_type"]["enum"]
    ) == set(OCR_STAGED_PAGE_INPUTS)
    assert "missing_languages" in schema["$defs"]["capabilityReport"]["required"]

    def assert_local_references_resolve(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                assert reference.removeprefix("#/$defs/") in schema["$defs"]
            for child in value.values():
                assert_local_references_resolve(child)
        elif isinstance(value, list):
            for child in value:
                assert_local_references_resolve(child)

    assert_local_references_resolve(schema)


def test_packaging_manifest_is_optional_offline_and_license_complete() -> None:
    manifest = json.loads(
        (ROOT / "packaging" / "ocr" / "tesseract-5.5.3.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["slice"] == "0.9/S02"
    assert manifest["status"] == "local-execution-qualified"
    assert manifest["selected_engine"] == {
        "id": "tesseract-cli",
        "qualified_baseline_version": "5.5.3",
        "source": "https://github.com/tesseract-ocr/tesseract/releases/tag/5.5.3",
        "license": "Apache-2.0",
        "bundled": False,
        "runtime_download": False,
        "remote_fallback": False,
    }
    distribution = manifest["distribution"]
    assert distribution["base_wheel"]["python_runtime_dependencies_added"] == []
    assert distribution["base_wheel"]["engine_bundled"] is False
    assert distribution["sdist"]["engine_bundled"] is False
    assert distribution["windows_installer"]["engine_bundled"] is False
    assert distribution["windows_installer"]["silent_runtime_download"] is False
    assert manifest["size_and_supply_chain"]["base_wheel_ocr_engine_bytes"] == 0
    assert manifest["size_and_supply_chain"]["base_windows_installer_ocr_engine_bytes"] == 0
    assert manifest["execution_baseline"]["qualified_matrix"] == [
        {
            "platform": "ubuntu-24.04",
            "architecture": "x86_64",
            "python": "3.12",
            "engine": (
                "distribution-provided Tesseract 5.x (5.3.4 observed locally; "
                "exact CI version recorded by the workflow)"
            ),
            "renderer": "pypdfium2 5.13.0 / PDFium 153.0.7999.0",
            "decoder": "Pillow 12.3.0",
            "language_packs": ["eng"],
            "formats": ["PDF", "TIFF", "PNG", "JPEG", "BMP"],
            "workflow": ".github/workflows/ocr-smoke.yml",
        }
    ]
    assert all(
        component["bundled_by_provelume"] is False
        for component in manifest["renderer_and_decoder"]["components"]
    )
    assert manifest["language_pack_source"]["license"] == "Apache-2.0"
    assert manifest["language_pack_source"]["commit"] == (
        "87416418657359cb625c412a48b6e1d6d41c29bd"
    )
    assert {item["id"]: item["license"] for item in manifest["upstream_components"]} == {
        "tesseract": "Apache-2.0",
        "leptonica": "BSD-2-Clause",
        "image-codecs": "component-specific",
    }
    assert manifest["redistribution"]["agpl_component_selected"] is False


def test_lectio_release_identity_adds_no_ocr_dependencies() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == "0.9.0"
    assert __version__ == "0.9.0"
    dependencies = pyproject["project"]["dependencies"]
    assert all(
        token not in dependency.casefold()
        for dependency in dependencies
        for token in (
            "tesseract",
            "ocrmypdf",
            "paddleocr",
            "easyocr",
            "torch",
            "pypdfium2",
            "pillow",
        )
    )
    embedded = json.loads(
        (ROOT / "core" / "provelume" / "build_info.json").read_text(encoding="utf-8")
    )
    assert embedded["version"] == "0.9.0"


def test_notices_distinguish_selected_but_unbundled_components() -> None:
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "Tesseract" in notices
    assert "Leptonica" in notices
    assert "tessdata_fast" in notices
    assert "pypdfium2" in notices
    assert "PDFium" in notices
    assert "Pillow" in notices
    assert "not bundled" in notices.casefold()


def test_qualified_external_component_bom_is_not_a_release_sbom() -> None:
    bom = json.loads(
        (
            ROOT / "packaging" / "ocr" / "qualified-local-components.cdx.json"
        ).read_text(encoding="utf-8")
    )
    assert bom["bomFormat"] == "CycloneDX"
    assert bom["specVersion"] == "1.6"
    assert bom["metadata"]["component"]["name"] == (
        "Provelume local OCR execution baseline"
    )
    assert {component["name"] for component in bom["components"]} == {
        "Tesseract OCR",
        "tessdata_fast eng.traineddata",
        "pypdfium2",
        "PDFium",
        "Pillow",
    }
    assert all(
        property_["value"] == "false"
        for component in bom["components"]
        for property_ in component.get("properties", [])
        if property_["name"] == "provelume:bundled"
    )
