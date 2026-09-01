from __future__ import annotations

import json
from pathlib import Path

import pytest

from provelume.email_contract import (
    EMAIL_ADAPTER_ID,
    EMAIL_ADAPTER_VERSION,
    EMAIL_CAPABILITY_STATES,
    EMAIL_CONTRACT_SCHEMA_VERSION,
    EMAIL_ERROR_CODES,
    EMAIL_LIMIT_CEILINGS,
    EMAIL_PARSER_ID,
    EMAIL_PARSER_VERSION,
    EMAIL_PROFILE_QUALIFIED_TARGETS,
    EMAIL_SOURCE_STATES,
    EMAIL_SUPPORTED_PROFILES,
    EMAIL_UNSUPPORTED_PROFILES,
    EMAIL_WARNING_CODES,
    EmailContractError,
    EmailLimits,
    EmailSourceConfig,
    EmailWarning,
    capability_report,
    mailbox_format_for_profile,
    settings_fingerprint,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "src_" + "1" * 32


def test_limits_are_closed_bounded_and_stably_fingerprinted() -> None:
    limits = EmailLimits()
    assert set(limits.as_record()) == set(EMAIL_LIMIT_CEILINGS)
    assert all(
        1 <= value <= EMAIL_LIMIT_CEILINGS[name]
        for name, value in limits.as_record().items()
    )
    assert EmailLimits.from_mapping(limits.as_record()) == limits
    assert settings_fingerprint(limits) == settings_fingerprint(EmailLimits())

    incomplete = limits.as_record()
    incomplete.pop("max_message_bytes")
    with pytest.raises(EmailContractError) as caught:
        EmailLimits.from_mapping(incomplete)
    assert caught.value.code == "email_internal_error"

    raised = limits.as_record()
    raised["max_message_bytes"] = EMAIL_LIMIT_CEILINGS["max_message_bytes"] + 1
    with pytest.raises(EmailContractError) as caught:
        EmailLimits.from_mapping(raised)
    assert caught.value.code == "email_internal_error"


def test_limit_relationships_fail_closed() -> None:
    values = EmailLimits().as_record()
    values["max_total_read_bytes"] = values["max_message_bytes"] - 1
    with pytest.raises(EmailContractError, match="total read"):
        EmailLimits.from_mapping(values)

    values = EmailLimits().as_record()
    values["max_total_attachment_bytes_per_message"] = (
        values["max_attachment_bytes"] - 1
    )
    with pytest.raises(EmailContractError, match="attachment total"):
        EmailLimits.from_mapping(values)


def test_explicit_source_config_is_path_free_when_public(tmp_path: Path) -> None:
    source = EmailSourceConfig(
        source_id=SOURCE_ID,
        mailbox_format="eml",
        profile="eml-file-v1",
        path=(tmp_path / "mail.eml").resolve(),
    )
    assert source.state == "disabled"
    assert source.public_record() == {
        "schema_version": EMAIL_CONTRACT_SCHEMA_VERSION,
        "source_id": SOURCE_ID,
        "mailbox_format": "eml",
        "profile": "eml-file-v1",
        "state": "disabled",
        "adapter_id": EMAIL_ADAPTER_ID,
        "adapter_version": EMAIL_ADAPTER_VERSION,
        "network_access": "none",
    }
    assert "path" not in source.public_record()
    assert "mail.eml" not in repr(source)


@pytest.mark.parametrize("state", EMAIL_SOURCE_STATES)
def test_source_states_are_closed(tmp_path: Path, state: str) -> None:
    assert (
        EmailSourceConfig(
            source_id=SOURCE_ID,
            mailbox_format="maildir",
            profile="maildir-cur-new-v1",
            path=tmp_path.resolve(),
            state=state,
        ).state
        == state
    )


def test_source_requires_matching_supported_profile_and_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(EmailContractError) as caught:
        EmailSourceConfig(
            source_id=SOURCE_ID,
            mailbox_format="eml",
            profile="maildir-cur-new-v1",  # type: ignore[arg-type]
            path=(tmp_path / "mail.eml").resolve(),
        )
    assert caught.value.code == "email_profile_unsupported"

    with pytest.raises(EmailContractError) as caught:
        EmailSourceConfig(
            source_id=SOURCE_ID,
            mailbox_format="eml",
            profile="eml-file-v1",
            path=Path("relative.eml"),
        )
    assert caught.value.code == "email_source_unsafe"


def test_capability_matrix_is_exact_and_mbox_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "ubuntu-24.04-x86_64-cpython312",
    )
    eml = capability_report("eml", "eml-file-v1")
    maildir = capability_report("maildir", "maildir-cur-new-v1")
    assert eml.available and maildir.available
    assert eml.state == maildir.state == "ready"
    assert eml.parser_id == EMAIL_PARSER_ID
    assert eml.parser_version == EMAIL_PARSER_VERSION
    assert eml.network_access == "none"
    assert eml.runtime_downloads is eml.remote_fallback is False
    assert EMAIL_SUPPORTED_PROFILES == ("eml-file-v1", "maildir-cur-new-v1")
    assert EMAIL_UNSUPPORTED_PROFILES == ("mbox",)
    assert mailbox_format_for_profile("eml-file-v1") == "eml"
    with pytest.raises(EmailContractError) as caught:
        mailbox_format_for_profile("mbox")
    assert caught.value.code == "email_profile_unsupported"


def test_only_the_smoke_tested_windows_target_is_advertised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "windows-2025server-x86_64-cpython312",
    )
    assert capability_report("eml", "eml-file-v1").available
    maildir = capability_report("maildir", "maildir-cur-new-v1")
    assert not maildir.available
    assert maildir.state == "runtime-unqualified"
    assert maildir.reason == "email_runtime_unqualified"

    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "windows-11-x86_64-cpython312",
    )
    eml = capability_report("eml", "eml-file-v1")
    assert not eml.available
    assert eml.state == "runtime-unqualified"
    assert eml.reason == "email_runtime_unqualified"


def test_unqualified_or_unknown_capability_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "provelume.email_contract.qualified_runtime_target",
        lambda: "freebsd-14-arm64-cpython312",
    )
    runtime = capability_report("eml", "eml-file-v1")
    assert not runtime.available
    assert runtime.state == "runtime-unqualified"
    assert capability_report("mbox", "mbox").state == "format-unsupported"
    assert capability_report("eml", "maildir-cur-new-v1").state == "profile-unsupported"


def test_warning_and_error_registries_are_closed() -> None:
    for code in EMAIL_WARNING_CODES:
        assert EmailWarning(code).code == code
    with pytest.raises(ValueError, match="closed registry"):
        EmailWarning("invented")
    with pytest.raises(ValueError, match="closed registry"):
        EmailContractError("invented", "not accepted")
    assert {
        "declared_message_id_collision",
        "thread_reference_missing",
        "thread_reference_ambiguous",
        "thread_reference_cycle",
        "thread_reference_cross_source",
    }.issubset(EMAIL_WARNING_CODES)


def test_machine_readable_contract_matches_python_contract() -> None:
    schema = json.loads(
        (ROOT / "core" / "provelume" / "email_contract.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    definitions = schema["$defs"]
    assert definitions["sourceConfig"]["properties"]["schema_version"]["const"] == 1
    assert tuple(definitions["sourceConfig"]["properties"]["state"]["enum"]) == (
        EMAIL_SOURCE_STATES
    )
    assert tuple(definitions["capabilityReport"]["properties"]["state"]["enum"]) == (
        EMAIL_CAPABILITY_STATES
    )
    assert set(definitions["limits"]["required"]) == set(EMAIL_LIMIT_CEILINGS)
    for name, ceiling in EMAIL_LIMIT_CEILINGS.items():
        assert definitions["limits"]["properties"][name]["maximum"] == ceiling
    assert set(definitions["localizedError"]["properties"]["code"]["enum"]) == set(
        EMAIL_ERROR_CODES
    )
    assert set(definitions["warning"]["properties"]["code"]["enum"]) == set(
        EMAIL_WARNING_CODES
    )
    ocr = definitions["attachmentOcrBoundary"]["properties"]
    assert ocr["intake_dependency"] == {"const": False}
    assert ocr["execution_requires_explicit_ocr_job"] == {"const": True}
    assert ocr["execution_started"] == {"const": False}
    assert EMAIL_PROFILE_QUALIFIED_TARGETS == {
        "eml-file-v1": (
            "ubuntu-24.04-x86_64-cpython312",
            "windows-2025server-x86_64-cpython312",
        ),
        "maildir-cur-new-v1": ("ubuntu-24.04-x86_64-cpython312",),
    }

    def assert_local_refs(value: object) -> None:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                assert reference.removeprefix("#/$defs/") in definitions
            for child in value.values():
                assert_local_refs(child)
        elif isinstance(value, list):
            for child in value:
                assert_local_refs(child)

    assert_local_refs(schema)
