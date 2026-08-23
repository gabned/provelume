from __future__ import annotations

from typing import Any

import pytest

from provelume import build_info
from provelume.build_info import BuildInfoError


@pytest.fixture(autouse=True)
def clear_build_info_cache():
    build_info._loaded_build_info.cache_clear()
    yield
    build_info._loaded_build_info.cache_clear()


def _official_payload(**changes: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "version": "0.1.0",
        "source_repository": "gabned/provelume",
        "tag": "v0.1.0",
        "commit": "a" * 40,
        "channel": "preview",
        "source_date_epoch": 1787443200,
        "source_date_utc": "2026-08-23T00:00:00+00:00",
        "official": True,
    }
    payload.update(changes)
    return payload


def test_tracked_metadata_identifies_development_build_offline() -> None:
    result = build_info.current_build_info()
    assert result["identity_status"] == "development_build"
    assert result["metadata_present"] is True
    assert result["source_repository"] == "gabned/provelume"
    assert result["official"] is False
    assert result["verification"] == {
        "status": "not_performed",
        "installation_integrity": "not_verified",
        "artifact_provenance": "not_verified_locally",
        "signature": "not_verified",
        "network_used": False,
    }


def test_official_metadata_is_descriptive_not_locally_verified() -> None:
    result = build_info.parse_build_info(_official_payload())
    assert result["identity_status"] == "official_metadata_present"
    assert result["metadata_present"] is True
    assert result["official"] is True
    assert result["tag"] == "v0.1.0"
    assert result["commit"] == "a" * 40
    assert result["verification"]["status"] == "not_performed"
    assert result["verification"]["network_used"] is False


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"schema_version": True}, "schema version"),
        ({"tag": "v0.2.0"}, "tag must match"),
        ({"commit": None}, "requires a commit"),
        ({"channel": "development"}, "preview or stable"),
        ({"source_date_epoch": None, "source_date_utc": None}, "source timestamp"),
        ({"source_repository": "private/reference"}, "not canonical"),
        ({"version": "0.2.0", "tag": "v0.2.0"}, "does not match package"),
        ({"source_date_epoch": 10**100}, "supported range"),
    ],
)
def test_official_metadata_fails_closed(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(BuildInfoError, match=message):
        build_info.parse_build_info(_official_payload(**changes))


def test_metadata_rejects_unknown_fields_and_wrong_types() -> None:
    with pytest.raises(BuildInfoError, match="unknown fields"):
        build_info.parse_build_info(_official_payload(extra="not allowed"))
    with pytest.raises(BuildInfoError, match="version must"):
        build_info.create_build_info(
            version=1,  # type: ignore[arg-type]
            commit=None,
            tag=None,
            channel="development",
            source_date_epoch=None,
            official=False,
        )
    with pytest.raises(BuildInfoError, match="channel"):
        build_info.create_build_info(
            version="0.1.0",
            commit=None,
            tag=None,
            channel=None,  # type: ignore[arg-type]
            source_date_epoch=None,
            official=False,
        )


def test_cached_identity_cannot_be_mutated_by_a_caller() -> None:
    first = build_info.current_build_info()
    first["identity_status"] = "tampered"
    first["verification"]["network_used"] = True

    second = build_info.current_build_info()
    assert second["identity_status"] == "development_build"
    assert second["verification"]["network_used"] is False


def test_missing_embedded_metadata_reports_sanitized_unavailable_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingResource:
        def joinpath(self, *_parts: str):
            return self

        def read_text(self, **_kwargs: Any) -> str:
            raise OSError("/private/local/site-packages/provelume/build_info.json")

    monkeypatch.setattr(build_info, "files", lambda _package: MissingResource())
    result = build_info.current_build_info()

    assert result["identity_status"] == "identity_unavailable"
    assert result["metadata_present"] is False
    assert result["source_repository"] is None
    assert result["metadata_error"] == "embedded build metadata cannot be read"
    assert "/private/" not in result["metadata_error"]
    assert result["verification"]["network_used"] is False
