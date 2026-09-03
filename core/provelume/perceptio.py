from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

from .audio_profiles import AUDIO_PROFILE_ID, AUDIO_RECIPE_ID, AudioProfileManager
from .build_info import current_build_info
from .component_inventory import ComponentInventory
from .file_family_profiles import (
    FILE_FAMILY_PROFILE_IDS,
    FILE_FAMILY_RECIPE_ID,
    FileFamilyProfileManager,
)
from .photo_profiles import PHOTO_PROFILE_ID, PHOTO_RECIPE_ID, PhotoProfileManager
from .representations import RepresentationBundleManager, RepresentationReadModel
from .storage import InstanceStore
from .video_profiles import VIDEO_PROFILE_ID, VIDEO_RECIPE_ID, VideoProfileManager

PERCEPTIO_MODEL_VERSION = 1
PERCEPTIO_TARGET_VERSION = "0.10.0"
PERCEPTIO_MAX_RESULTS = 500
PERCEPTIO_MAX_QUALIFICATION_BYTES = 256 * 1024
PERCEPTIO_STATES = (
    "happy",
    "empty",
    "loading",
    "degraded",
    "unavailable",
    "interrupted",
    "recovery",
)
PERCEPTIO_PROFILE_IDS = (
    "universal-original-v1",
    "lectio-document-extraction-v1",
    "lectio-local-ocr-v1",
    "lectio-email-intake-v1",
    "lectio-google-readonly-v1",
    "lectio-transcript-srt-v1",
    "lectio-transcript-webvtt-v1",
    "perceptio-photo-v1",
    "perceptio-audio-v1",
    "perceptio-video-v1",
    "perceptio-csv-cell-v1",
    "perceptio-xlsx-sheet-cell-v1",
    "perceptio-zip-member-v1",
    "lectio-cross-source-findings-v1",
)
PERCEPTIO_ERROR_CODES = frozenset({"perceptio_limit_invalid", "perceptio_qualification_invalid"})

_FAMILIES: tuple[dict[str, Any], ...] = (
    {
        "id": "photo",
        "recipe_id": PHOTO_RECIPE_ID,
        "profile_ids": (PHOTO_PROFILE_ID,),
        "surface": "gallery_metadata",
        "browser_path": "/photos",
    },
    {
        "id": "audio",
        "recipe_id": AUDIO_RECIPE_ID,
        "profile_ids": (AUDIO_PROFILE_ID,),
        "surface": "player_waveform_transcript",
        "browser_path": "/audio",
    },
    {
        "id": "video",
        "recipe_id": VIDEO_RECIPE_ID,
        "profile_ids": (VIDEO_PROFILE_ID,),
        "surface": "player_keyframe_subtitle_transcript",
        "browser_path": "/video",
    },
    {
        "id": "file_family",
        "recipe_id": FILE_FAMILY_RECIPE_ID,
        "profile_ids": FILE_FAMILY_PROFILE_IDS,
        "surface": "table_archive_metadata",
        "browser_path": "/file-families",
    },
)
_FAMILY_BY_RECIPE = {str(item["recipe_id"]): item for item in _FAMILIES}


class PerceptioError(ValueError):
    """Closed failure for the integrated Perceptio read model."""

    def __init__(self, code: str, message: str):
        if code not in PERCEPTIO_ERROR_CODES:
            raise ValueError("Perceptio error code is outside the closed registry")
        super().__init__(message)
        self.code = code


def _qualification(registry_profile_ids: list[str]) -> dict[str, Any]:
    try:
        raw = files("provelume").joinpath("perceptio_qualification.json").read_bytes()
        if len(raw) > PERCEPTIO_MAX_QUALIFICATION_BYTES:
            raise ValueError("qualification evidence exceeds its byte limit")
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise PerceptioError(
            "perceptio_qualification_invalid", "Perceptio qualification evidence is unreadable"
        ) from exc
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "qualification_id",
            "target_version",
            "publication_state",
            "registry_profile_ids",
            "families",
            "surfaces",
            "scenarios",
            "platforms",
            "accessibility",
            "privacy",
            "recovery",
            "resource_policy",
            "exit_gates",
            "adoption",
        }
        or value["schema_version"] != 1
        or value["qualification_id"] != "provelume.perceptio-s07.v1"
        or value["target_version"] != PERCEPTIO_TARGET_VERSION
        or value["publication_state"] != "candidate"
        or value["registry_profile_ids"] != registry_profile_ids
        or registry_profile_ids != list(PERCEPTIO_PROFILE_IDS)
        or value["families"] != [str(item["id"]) for item in _FAMILIES]
        or value["surfaces"] != {str(item["id"]): str(item["surface"]) for item in _FAMILIES}
        or value["scenarios"] != list(PERCEPTIO_STATES)
        or value["platforms"]
        != {
            "ubuntu_24_04": "permanent_ci_required",
            "windows_2025": "permanent_ci_required",
            "codec_claims": "profile_matrix_only",
        }
        or value["accessibility"]
        != {
            "languages": ["en", "it"],
            "keyboard": "native_controls",
            "screen_reader": "exact_artifact_release_gate",
            "contrast_reflow_reduced_motion": ("permanent_regression_and_exact_artifact_gate"),
        }
        or value["privacy"]
        != {
            "offline": True,
            "source_writeback": False,
            "gps_default_export": "excluded",
            "active_content": "inert",
            "identity_inference": False,
        }
        or value["recovery"]
        != {
            "remove_rebuild": "required",
            "backup_restore": "required",
            "portable_transfer": "required",
            "n_minus_one": "0.9.0",
            "rollback": "explicit_no_silent_schema_downgrade",
        }
        or value["resource_policy"]
        != {
            "bounded_profiles_only": True,
            "limits_fail_closed": True,
            "network_required": False,
            "publication_gate": "verified_release_boundary",
        }
        or value["adoption"]
        != {
            "audience": "controlled_personal_multimedia_pilot",
            "available_before_publication": False,
            "next_product_gate": "0.11.0",
        }
        or not isinstance(value["exit_gates"], list)
        or len(value["exit_gates"]) != 10
        or [item.get("id") for item in value["exit_gates"] if isinstance(item, Mapping)]
        != [f"release-exit-{index:02d}" for index in range(1, 11)]
        or any(
            set(item) != {"id", "evidence"}
            or not isinstance(item["evidence"], str)
            or not item["evidence"]
            for item in value["exit_gates"]
        )
    ):
        raise PerceptioError(
            "perceptio_qualification_invalid", "Perceptio qualification evidence is invalid"
        )
    return value


def _limit(value: int) -> int:
    if type(value) is not int or not 1 <= value <= PERCEPTIO_MAX_RESULTS:
        raise PerceptioError(
            "perceptio_limit_invalid", "Perceptio limit must be an integer from 1 through 500"
        )
    return value


class PerceptioReadModel:
    """One offline, non-mutating multimedia pilot projection for every public surface."""

    def __init__(
        self,
        store: InstanceStore,
        *,
        photos: PhotoProfileManager | None = None,
        audio: AudioProfileManager | None = None,
        video: VideoProfileManager | None = None,
        file_families: FileFamilyProfileManager | None = None,
        components: ComponentInventory | None = None,
        representations: RepresentationReadModel | None = None,
    ):
        self.store = store
        self.bundles = RepresentationBundleManager(store)
        self.photos = photos or PhotoProfileManager(store)
        self.audio = audio or AudioProfileManager(store)
        self.video = video or VideoProfileManager(store)
        self.file_families = file_families or FileFamilyProfileManager(store)
        self.components = components or ComponentInventory()
        self.representations = representations or RepresentationReadModel(store)

    def _source_models(
        self,
        *,
        version_id: str | None,
        limit: int,
        registry: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        managers = (self.photos, self.audio, self.video, self.file_families)
        result: list[dict[str, Any]] = []
        registry_records = list(registry["records"])
        for family, manager in zip(_FAMILIES, managers, strict=True):
            profiles: list[dict[str, Any]] = []
            for bundle in self.bundles.list(recipe_id=str(family["recipe_id"]), limit=500):
                profile = manager.get(str(bundle["representation_id"]))
                if profile is None:
                    continue
                record = profile["record"]
                if version_id is not None and record["version_id"] != version_id:
                    continue
                profiles.append(profile)
                if len(profiles) >= limit:
                    break
            jobs = [
                copy.deepcopy(job)
                for job in manager.list_jobs(limit=500)
                if version_id is None or job.get("version_id") == version_id
            ][:limit]
            profile_ids = set(family["profile_ids"])
            result.append(
                {
                    **family,
                    "model": {
                        "support": {
                            "registry_id": registry["registry_id"],
                            "profile_ids": list(family["profile_ids"]),
                            "records": [
                                copy.deepcopy(record)
                                for record in registry_records
                                if record["profile_id"] in profile_ids
                            ],
                            "capability_probe": "not_performed",
                            "network_used": False,
                            "mutated": False,
                        },
                        "profiles": profiles,
                        "jobs": jobs,
                    },
                }
            )
        return result

    @staticmethod
    def _profile_id(family: Mapping[str, Any], record: Mapping[str, Any]) -> str:
        selected = record.get("profile_id")
        if isinstance(selected, str) and selected in family["profile_ids"]:
            return selected
        return str(family["profile_ids"][0])

    @staticmethod
    def _item(
        family: Mapping[str, Any], profile: Mapping[str, Any], bundle: Mapping[str, Any]
    ) -> dict[str, Any]:
        representation_id = str(bundle["representation_id"])
        record = copy.deepcopy(dict(profile["record"]))
        anchors = copy.deepcopy(list(bundle["anchors"]))
        corrections = copy.deepcopy(list(bundle["corrections"]))
        warnings = copy.deepcopy(list(bundle["warnings"]))
        profile_id = PerceptioReadModel._profile_id(family, record)
        return {
            "family": family["id"],
            "profile_id": profile_id,
            "surface": family["surface"],
            "representation_id": representation_id,
            "version_id": bundle["version"]["id"],
            "availability": copy.deepcopy(dict(bundle["availability"])),
            "record": record,
            "outputs": copy.deepcopy(list(bundle["outputs"])),
            "implementation": copy.deepcopy(dict(bundle["implementation"])),
            "provenance": copy.deepcopy(dict(bundle["provenance"])),
            "uncertainty": {"count": len(warnings), "warnings": warnings},
            "corrections": {
                "count": len(corrections),
                "all_reversible": all(item["reversible"] is True for item in corrections),
                "annotations": corrections,
            },
            "anchors": {
                "count": len(anchors),
                "kinds": sorted({str(item["kind"]) for item in anchors}),
                "items": anchors,
            },
            "links": {
                "browser": str(family["browser_path"]),
                "api": f"/api/v1/perceptio/representations/{representation_id}",
                "universal_representation": f"/api/v1/representations/{representation_id}",
            },
        }

    def read(self, *, version_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        selected_limit = _limit(limit)
        registry = self.representations.support.read(resolve_components=False)
        source_models = self._source_models(
            version_id=version_id,
            limit=selected_limit,
            registry=registry,
        )
        items: list[dict[str, Any]] = []
        support: list[dict[str, Any]] = []
        jobs: list[dict[str, Any]] = []
        for source in source_models:
            family = str(source["id"])
            model = source["model"]
            support.append(
                {
                    "family": family,
                    "profile_ids": list(source["profile_ids"]),
                    "surface": source["surface"],
                    "browser_path": source["browser_path"],
                    "representation_count": len(model["profiles"]),
                    "job_count": len(model["jobs"]),
                    "evidence": copy.deepcopy(model["support"]),
                }
            )
            jobs.extend({"family": family, "record": copy.deepcopy(job)} for job in model["jobs"])
            for profile in model["profiles"]:
                if len(items) >= selected_limit:
                    break
                bundle = self.bundles.get(str(profile["representation_id"]), deep=True)
                if bundle is None or bundle["recipe"]["id"] != source["recipe_id"]:
                    continue
                items.append(self._item(source, profile, bundle))

        components = self.components.read()
        registry_profile_ids = list(
            dict.fromkeys(str(record["profile_id"]) for record in registry["records"])
        )
        build = current_build_info()
        published = (
            build["official"] is True
            and build["identity_status"] == "official_metadata_present"
            and build["version"] == PERCEPTIO_TARGET_VERSION
            and build["tag"] == f"v{PERCEPTIO_TARGET_VERSION}"
            and isinstance(build["commit"], str)
        )
        return {
            "schema_version": PERCEPTIO_MODEL_VERSION,
            "model_id": "provelume.perceptio-read-model.v1",
            "target_version": PERCEPTIO_TARGET_VERSION,
            "publication": {
                "state": "published" if published else "candidate",
                "availability": (
                    "available_in_verified_release"
                    if published
                    else "unavailable_until_verified_publication"
                ),
                "current_package_version": build["version"],
                "official_build": build["official"],
            },
            "journey": {
                "read_only": True,
                "sequence": ["gallery", "player", "evidence", "correction", "reopen"],
                "states": list(PERCEPTIO_STATES),
            },
            "registry": {
                "support": registry,
                "compatibility": self.representations.compatibility(),
                "profile_ids": registry_profile_ids,
            },
            "support": support,
            "items": items,
            "jobs": jobs[:selected_limit],
            "components": components,
            "qualification": _qualification(registry_profile_ids),
            "privacy": {
                "local_only": True,
                "network_used": False,
                "source_writeback": False,
                "gps_default_export": "excluded",
                "active_content": "never_executed",
                "identity_inference": False,
            },
            "invariants": {
                "mutated": False,
                "original_immutable": True,
                "canonical_records_immutable": True,
                "provider_data_immutable": True,
                "corrections_are_annotations": True,
            },
        }

    def get(self, representation_id: str) -> dict[str, Any] | None:
        bundle = self.bundles.get(representation_id, deep=True)
        if bundle is None:
            return None
        family = _FAMILY_BY_RECIPE.get(str(bundle["recipe"]["id"]))
        if family is None:
            return None
        manager = {
            "photo": self.photos,
            "audio": self.audio,
            "video": self.video,
            "file_family": self.file_families,
        }[str(family["id"])]
        profile = manager.get(representation_id)
        if profile is None:
            return None
        return {
            "schema_version": PERCEPTIO_MODEL_VERSION,
            "model_id": "provelume.perceptio-read-model.v1",
            "item": self._item(family, profile, bundle),
            "network_used": False,
            "mutated": False,
        }

    def get_anchor(self, representation_id: str, anchor_id: str) -> dict[str, Any] | None:
        selected = self.get(representation_id)
        if selected is None:
            return None
        return next(
            (
                copy.deepcopy(anchor)
                for anchor in selected["item"]["anchors"]["items"]
                if anchor["id"] == anchor_id
            ),
            None,
        )


__all__ = [
    "PERCEPTIO_ERROR_CODES",
    "PERCEPTIO_MAX_RESULTS",
    "PERCEPTIO_MODEL_VERSION",
    "PERCEPTIO_PROFILE_IDS",
    "PERCEPTIO_STATES",
    "PERCEPTIO_TARGET_VERSION",
    "PerceptioError",
    "PerceptioReadModel",
]
