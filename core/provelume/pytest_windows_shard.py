from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest

SHARD_COUNT = 4
DEFAULT_SHARD_TIMEOUT_SECONDS = 540
MIN_SHARD_TIMEOUT_SECONDS = 60
MAX_SHARD_TIMEOUT_SECONDS = 540
MAX_REPLAY_BYTES = 2 * 1024 * 1024
CHILD_ENV = "PROVELUME_WINDOWS_SHARD_CHILD"
FORCE_ENV = "PROVELUME_WINDOWS_SHARD_FORCE"
DISABLE_ENV = "PROVELUME_WINDOWS_SHARD_DISABLE"

# Relative allocation hints: 285 complete non-failing modules from 42855973908/a1
# (eca220c), plus the five newly observable native-subtest modules and the changed
# timing-test module from 42862418198/a1 (74b76b0). Rounded setup/call/teardown
# milliseconds; 290 measured modules. The latter source collects 6,017 node IDs.
# New/count-mismatched modules retain the count fallback. Actual complete/disjoint
# native parent/subtest coverage remains mandatory. These source runs retained
# CANCELLED jobs and are NOT qualified; independent artifact reads remain blocked.
# No failed/interrupted module, execution budget or CPU causal finding is used.
# Exact sources and retained prior data: windows-ci-s23-costs-20261110.md under
# docs/qualification; older literal versions remain in Git history.
_COUNT_COST = 1000
_MODULE_COST_HINTS = (
    ('tests/test_action_center_adapters.py', 43, 14540),
    ('tests/test_action_center_model.py', 37, 3320),
    ('tests/test_action_center_routes.py', 9, 7232),
    ('tests/test_action_notifications.py', 65, 732),
    ('tests/test_agent_protocol_consumer.py', 60, 60222),
    ('tests/test_agent_protocol_consumer_scope.py', 37, 33),
    ('tests/test_agent_protocol_transfer.py', 38, 56062),
    ('tests/test_agent_protocol_v1_2.py', 15, 101278),
    ('tests/test_agent_protocol_v1_2_1.py', 47, 165),
    ('tests/test_agent_protocol_v1_4.py', 21, 8),
    ('tests/test_agent_protocol_v1_4_1.py', 65, 1202),
    ('tests/test_agent_protocol_v1_4_1_slice_issue_transition.py', 16, 73),
    ('tests/test_agent_protocol_v1_4_2_ops.py', 247, 6364),
    ('tests/test_agent_protocol_v1_4_7.py', 63, 473),
    ('tests/test_agent_protocol_v1_4_9.py', 14, 1887),
    ('tests/test_agent_protocol_work_check.py', 36, 7077),
    ('tests/test_agent_protocol_work_recovery.py', 38, 70010),
    ('tests/test_agent_protocol_work_source.py', 37, 6),
    ('tests/test_ai_classification_evaluation.py', 60, 342),
    ('tests/test_ai_classification_proposals.py', 39, 20329),
    ('tests/test_ai_classification_request.py', 22, 4138),
    ('tests/test_ai_classification_targets.py', 33, 5097),
    ('tests/test_ai_context.py', 90, 169),
    ('tests/test_ai_gateway.py', 94, 109),
    ('tests/test_ai_jobs.py', 25, 9018),
    ('tests/test_ai_jobs_boundaries.py', 26, 9142),
    ('tests/test_ai_jobs_controls.py', 29, 3984),
    ('tests/test_ai_llama_prefix.py', 21, 24),
    ('tests/test_ai_llama_wait.py', 5, 2),
    ('tests/test_ai_model_download.py', 42, 83),
    ('tests/test_ai_model_progress_js.py', 1, 667),
    ('tests/test_ai_models.py', 95, 1157),
    ('tests/test_ai_provider.py', 105, 5610),
    ('tests/test_ai_runtime.py', 82, 5501),
    ('tests/test_ai_runtime_cpu.py', 24, 29),
    ('tests/test_ai_runtime_warm_qualification.py', 28, 26),
    ('tests/test_ai_setup.py', 63, 25793),
    ('tests/test_ai_synthesis.py', 69, 32900),
    ('tests/test_ai_synthesis_profile.py', 89, 130),
    ('tests/test_anchored_installation.py', 23, 231),
    ('tests/test_annotation_editor.py', 23, 2417),
    ('tests/test_annotation_route_failures.py', 4, 575),
    ('tests/test_api_browser.py', 6, 2391),
    ('tests/test_api_registration.py', 1, 996),
    ('tests/test_atomic_commit.py', 47, 1418),
    ('tests/test_atomic_digest_bounds.py', 9, 24),
    ('tests/test_atomic_journal_paths.py', 14, 16),
    ('tests/test_atomic_single_io.py', 6, 190),
    ('tests/test_atomic_transaction_pool.py', 8, 338),
    ('tests/test_audio_packaging.py', 2, 3),
    ('tests/test_audio_profiles.py', 24, 1722),
    ('tests/test_audio_real_smoke.py', 1, 1),
    ('tests/test_build_configuration.py', 5, 5),
    ('tests/test_build_info.py', 13, 9),
    ('tests/test_build_input_bundle.py', 5, 40),
    ('tests/test_build_input_lock.py', 6, 75),
    ('tests/test_canonical_brand.py', 8, 2608),
    ('tests/test_capacity_admission.py', 30, 756),
    ('tests/test_capture_adapter.py', 29, 4712),
    ('tests/test_capture_guard_comparison.py', 9, 16),
    ('tests/test_capture_journal.py', 38, 1001),
    ('tests/test_capture_path_guard.py', 13, 24),
    ('tests/test_capture_requests.py', 28, 13),
    ('tests/test_capture_shell_contract.py', 6, 1040),
    ('tests/test_capture_surface.py', 28, 6581),
    ('tests/test_changelog_policy.py', 3, 3),
    ('tests/test_classification_review.py', 32, 20320),
    ('tests/test_cli.py', 9, 88),
    ('tests/test_cli_parser_selection.py', 6, 6885),
    ('tests/test_component_inventory.py', 20, 516),
    ('tests/test_concordia_asana_s13.py', 26, 62553),
    ('tests/test_concordia_capture_marker_fixture.py', 2, 1),
    ('tests/test_concordia_connectors_s10.py', 21, 668),
    ('tests/test_concordia_cpu_topology.py', 13, 276),
    ('tests/test_concordia_folder_s21.py', 19, 15685),
    ('tests/test_concordia_git_admission.py', 3, 1036),
    ('tests/test_concordia_git_s17.py', 37, 51154),
    ('tests/test_concordia_gitea_s20.py', 30, 38605),
    ('tests/test_concordia_github_s18.py', 32, 45456),
    ('tests/test_concordia_gitlab_s19.py', 27, 26242),
    ('tests/test_concordia_gmail_recovery_s23.py', 6, 1310),
    ('tests/test_concordia_google_calendar_s11.py', 11, 20266),
    ('tests/test_concordia_icalendar_s12.py', 30, 7292),
    ('tests/test_concordia_inbox_transit.py', 51, 22668),
    ('tests/test_concordia_integrated_s23.py', 1, 29195),
    ('tests/test_concordia_journal_comparison.py', 8, 5),
    ('tests/test_concordia_kernel_native.py', 8, 56),
    ('tests/test_concordia_kernel_observer.py', 19, 116),
    ('tests/test_concordia_mirror_credential_context.py', 9, 2),
    ('tests/test_concordia_mirrors_s16.py', 46, 15038),
    ('tests/test_concordia_ocr_sources.py', 44, 12526),
    ('tests/test_concordia_personal_s09.py', 2, 28370),
    ('tests/test_concordia_productivity_intake.py', 12, 2993),
    ('tests/test_concordia_rsync_fixture_cleanup.py', 6, 9),
    ('tests/test_concordia_rsync_s22.py', 23, 218),
    ('tests/test_concordia_rsync_state_s22.py', 22, 27),
    ('tests/test_concordia_rsync_windows_diagnostics.py', 13, 33),
    ('tests/test_concordia_search_inputs.py', 97, 50697),
    ('tests/test_concordia_search_s08.py', 54, 12544),
    ('tests/test_concordia_task_writeback_s15.py', 38, 24227),
    ('tests/test_concordia_tududi_s14.py', 28, 67755),
    ('tests/test_concordia_ui_s07.py', 32, 9622),
    ('tests/test_config_decode_reuse.py', 20, 109),
    ('tests/test_config_inspection_reuse.py', 11, 357),
    ('tests/test_connector_foundation.py', 17, 623),
    ('tests/test_connector_lifecycle.py', 6, 1118),
    ('tests/test_cura_ai_completion.py', 20, 8653),
    ('tests/test_cura_document_decisions.py', 6, 2274),
    ('tests/test_cura_icons.py', 37, 753),
    ('tests/test_cura_legacy_maintenance_preview.py', 9, 2860),
    ('tests/test_cura_maintenance_activity.py', 11, 4151),
    ('tests/test_cura_package_resources.py', 54, 1466),
    ('tests/test_cura_preferences.py', 63, 4604),
    ('tests/test_cura_primary_upgrade.py', 9, 46),
    ('tests/test_cura_recovery_capacity_boundary.py', 2, 369),
    ('tests/test_cura_release_identity.py', 20, 5563),
    ('tests/test_cura_retention_recovery.py', 12, 2651),
    ('tests/test_cura_review_runtime.py', 10, 260),
    ('tests/test_cura_s09_preferences.py', 29, 9765),
    ('tests/test_cura_s09_tray.py', 24, 14),
    ('tests/test_cura_shell.py', 12, 8520),
    ('tests/test_cura_shell_js.py', 3, 160),
    ('tests/test_custodia_admission_observations.py', 40, 49),
    ('tests/test_custodia_authority_costs.py', 13, 9),
    ('tests/test_custodia_diagnostics.py', 9, 99),
    ('tests/test_custodia_guided_setup.py', 45, 2350),
    ('tests/test_custodia_language_preferences.py', 20, 8403),
    ('tests/test_custodia_local_file_locality.py', 9, 2),
    ('tests/test_custodia_model_cancellation.py', 17, 206),
    ('tests/test_custodia_native_download.py', 20, 66),
    ('tests/test_custodia_native_packaging.py', 7, 71),
    ('tests/test_custodia_native_sbom.py', 7, 223),
    ('tests/test_custodia_network_lifecycle.py', 9, 1510),
    ('tests/test_custodia_parent_lifetime.py', 2, 1),
    ('tests/test_custodia_pdf_boundary.py', 3, 283),
    ('tests/test_custodia_preview_freshness.py', 13, 2916),
    ('tests/test_custodia_qualification_failures.py', 7, 30106),
    ('tests/test_custodia_recommendation.py', 12, 15),
    ('tests/test_custodia_resource_limits.py', 10, 3),
    ('tests/test_custodia_synthesis_recovery.py', 7, 6089),
    ('tests/test_custodia_windows_package.py', 4, 25),
    ('tests/test_dependency_governance.py', 3, 3),
    ('tests/test_desktop_about.py', 66, 16017),
    ('tests/test_deterministic_build.py', 9, 73),
    ('tests/test_document_bundle_limits.py', 3, 154),
    ('tests/test_document_bundle_validation.py', 2, 836),
    ('tests/test_document_bundles.py', 5, 548),
    ('tests/test_duplicate_assurance.py', 7, 2673),
    ('tests/test_duplicate_conflicts.py', 6, 523),
    ('tests/test_durable_scheduler.py', 19, 2182),
    ('tests/test_email_bundle.py', 2, 2),
    ('tests/test_email_canonical_validation.py', 3, 608),
    ('tests/test_email_containers.py', 17, 18),
    ('tests/test_email_contract.py', 12, 7),
    ('tests/test_email_jobs.py', 13, 1468),
    ('tests/test_email_mime.py', 19, 52),
    ('tests/test_email_packaging.py', 3, 2),
    ('tests/test_email_portability.py', 3, 1629),
    ('tests/test_email_real_smoke.py', 2, 1),
    ('tests/test_email_sources.py', 17, 679),
    ('tests/test_email_surfaces.py', 3, 1633),
    ('tests/test_emendatio_activation.py', 4, 4),
    ('tests/test_entitas_integrated_qualification.py', 10, 18103),
    ('tests/test_external_folder_availability.py', 1, 74),
    ('tests/test_extractor_parity.py', 3, 457),
    ('tests/test_extractor_xlsx_images.py', 2, 424),
    ('tests/test_extractor_zip.py', 6, 348),
    ('tests/test_file_family_profiles.py', 19, 1820),
    ('tests/test_folder_settings.py', 7, 1011),
    ('tests/test_folder_source_enrollment.py', 52, 1165),
    ('tests/test_folder_sources.py', 15, 3492),
    ('tests/test_google_adapter_lifecycle.py', 6, 184),
    ('tests/test_google_connection.py', 54, 6189),
    ('tests/test_google_intake_coordination.py', 7, 5709),
    ('tests/test_google_jobs.py', 13, 2709),
    ('tests/test_governed_catalogs.py', 8, 185),
    ('tests/test_guarded_web_transport.py', 83, 2672),
    ('tests/test_hierarchy_classification.py', 12, 2805),
    ('tests/test_inbox_operations.py', 8, 1159),
    ('tests/test_incremental_search_index.py', 9, 1588),
    ('tests/test_independent_rebuild.py', 5, 50),
    ('tests/test_ingestion_runs.py', 11, 3636),
    ('tests/test_ingestion_security.py', 1, 22),
    ('tests/test_installation_interfaces.py', 6, 1700),
    ('tests/test_installation_verification.py', 87, 282),
    ('tests/test_instance_lifecycle.py', 20, 2854),
    ('tests/test_instance_repair.py', 33, 17216),
    ('tests/test_instance_repair_pending.py', 21, 17078),
    ('tests/test_iudicium_journey.py', 9, 74852),
    ('tests/test_knowledge_object_activity.py', 56, 15030),
    ('tests/test_knowledge_object_contract.py', 69, 125),
    ('tests/test_knowledge_object_review.py', 46, 13270),
    ('tests/test_knowledge_object_review_activity.py', 18, 9780),
    ('tests/test_knowledge_object_services.py', 57, 11603),
    ('tests/test_knowledge_object_storage.py', 43, 14014),
    ('tests/test_local_path_guard.py', 4, 15),
    ('tests/test_maintenance_backup_diagnostics.py', 26, 909),
    ('tests/test_maintenance_catalog.py', 14, 3190),
    ('tests/test_maintenance_queue_contention.py', 15, 6383),
    ('tests/test_maintenance_reviewed_plans.py', 7, 860),
    ('tests/test_manual_web_acquisition.py', 28, 7742),
    ('tests/test_markdown_library_viewer.py', 11, 8023),
    ('tests/test_mobile_retrieval.py', 23, 10050),
    ('tests/test_mobile_shell_contract.py', 5, 874),
    ('tests/test_model_read_buffer.py', 1, 11),
    ('tests/test_network_interfaces.py', 3, 804),
    ('tests/test_network_status.py', 11, 3),
    ('tests/test_node_conformance_lifecycle.py', 1, 58),
    ('tests/test_oauth_authorization.py', 19, 791),
    ('tests/test_object_migration_permissions.py', 20, 5093),
    ('tests/test_ocr_contract.py', 28, 34),
    ('tests/test_ocr_execution.py', 27, 5604),
    ('tests/test_ocr_kit.py', 44, 3169),
    ('tests/test_ocr_kit_release.py', 11, 227),
    ('tests/test_ocr_real_smoke.py', 3, 1),
    ('tests/test_offline_release_verifier.py', 8, 287),
    ('tests/test_operations_maintenance.py', 34, 1021),
    ('tests/test_paths.py', 2, 26),
    ('tests/test_perceptio_integration.py', 6, 5379),
    ('tests/test_photo_profiles.py', 13, 2347),
    ('tests/test_photo_real_smoke.py', 1, 1),
    ('tests/test_portable_transfer.py', 29, 12136),
    ('tests/test_processing_autonomy.py', 54, 20852),
    ('tests/test_public_roadmap.py', 47, 42),
    ('tests/test_publication.py', 24, 626),
    ('tests/test_publication_distribution.py', 24, 2549),
    ('tests/test_publication_updates.py', 5, 776),
    ('tests/test_qualification.py', 24, 8410),
    ('tests/test_qualification_contract.py', 3, 1),
    ('tests/test_qualification_documentation.py', 4, 8),
    ('tests/test_qualification_real_smoke.py', 1, 1),
    ('tests/test_qualification_surfaces.py', 4, 1942),
    ('tests/test_rebuild_coordination.py', 6, 3260),
    ('tests/test_release_assurance.py', 6, 44),
    ('tests/test_release_installed.py', 15, 20),
    ('tests/test_release_manifest.py', 3, 13),
    ('tests/test_representations.py', 27, 2124),
    ('tests/test_resource_statistics.py', 13, 2244),
    ('tests/test_retention_boundaries.py', 16, 13532),
    ('tests/test_review_atomic_removal.py', 12, 151),
    ('tests/test_review_authority_observation.py', 1, 21),
    ('tests/test_review_decision_routes.py', 11, 4005),
    ('tests/test_review_documents_observation.py', 3, 19),
    ('tests/test_review_evidence_reads.py', 7, 19),
    ('tests/test_review_intake_routing.py', 8, 1634),
    ('tests/test_review_origin_observation.py', 4, 30),
    ('tests/test_review_path_observation.py', 22, 80),
    ('tests/test_review_placement_routing.py', 24, 5578),
    ('tests/test_runtime_boundaries.py', 2, 11),
    ('tests/test_s07_documentation.py', 6, 8),
    ('tests/test_scheduler_control.py', 17, 4126),
    ('tests/test_scheduler_cooperative_sources.py', 4, 1339),
    ('tests/test_scheduler_readers.py', 3, 326),
    ('tests/test_setup_activity.py', 4, 12008),
    ('tests/test_setup_coordinator.py', 15, 15123),
    ('tests/test_setup_qualification.py', 1, 9638),
    ('tests/test_setup_source_scope.py', 4, 282),
    ('tests/test_setup_space_name.py', 5, 81),
    ('tests/test_setup_trial_inputs.py', 14, 1292),
    ('tests/test_setup_trials.py', 5, 1605),
    ('tests/test_shell_settings.py', 37, 1351),
    ('tests/test_source_exclusion_contention.py', 12, 3385),
    ('tests/test_source_exclusions.py', 47, 4411),
    ('tests/test_source_reconciliation.py', 17, 3000),
    ('tests/test_startup_diagnostic_copy.py', 21, 2127),
    ('tests/test_startup_process.py', 16, 272),
    ('tests/test_startup_readiness.py', 43, 2560),
    ('tests/test_startup_windows.py', 2, 84),
    ('tests/test_transcript_documentation.py', 3, 1),
    ('tests/test_transcript_jobs.py', 11, 5257),
    ('tests/test_transcript_packaging.py', 4, 4),
    ('tests/test_transcript_parsers.py', 19, 11),
    ('tests/test_transcript_real_smoke.py', 2, 1),
    ('tests/test_transcript_sources.py', 5, 432),
    ('tests/test_transcript_surfaces.py', 6, 1354),
    ('tests/test_updates.py', 28, 1536),
    ('tests/test_verify_release_bundle.py', 7, 165),
    ('tests/test_vertical_slice.py', 4, 397),
    ('tests/test_video_packaging.py', 2, 1),
    ('tests/test_video_profiles.py', 14, 912),
    ('tests/test_video_real_smoke.py', 1, 1),
    ('tests/test_win32_file_api_setup.py', 15, 8),
    ('tests/test_windows_identity.py', 6, 541),
    ('tests/test_windows_json_snapshots.py', 12, 245),
    ('tests/test_windows_package_manifest.py', 2, 4),
    ('tests/test_windows_pdf_lock.py', 9, 6),
    ('tests/test_windows_public_baselines.py', 3, 2),
    ('tests/test_windows_pytest_sharding.py', 6, 3287),
    ('tests/test_windows_shard_costs.py', 18, 15),
    ('tests/test_windows_shard_timings.py', 3, 2511),
)


def _validated_cost_hints() -> dict[str, tuple[int, int]]:
    if type(_MODULE_COST_HINTS) is not tuple:
        raise ValueError("invalid Provelume pytest allocation hints")
    hints: dict[str, tuple[int, int]] = {}
    for row in _MODULE_COST_HINTS:
        if type(row) is not tuple or len(row) != 3:
            raise ValueError("invalid Provelume pytest allocation hint")
        source, count, cost = row
        if (
            type(source) is not str
            or not source.startswith("tests/")
            or not source.endswith(".py")
            or "\\" in source
            or ":" in source
            or any(part in {"", ".", ".."} for part in source.split("/"))
            or any(character.isspace() or ord(character) < 32 for character in source)
            or source in hints
            or type(count) is not int
            or count < 1
            or type(cost) is not int
            or cost < 1
        ):
            raise ValueError("invalid Provelume pytest allocation hint")
        hints[source] = (count, cost)
    return hints


def pytest_addoption(parser) -> None:
    group = parser.getgroup("provelume-windows-shard")
    group.addoption("--provelume-shard-index", type=int, default=None)
    group.addoption("--provelume-shard-count", type=int, default=None)


def _source_for_nodeid(nodeid: str) -> str:
    return nodeid.split("::", 1)[0].replace("\\", "/")


def balanced_shard_assignments(nodeids: list[str], count: int) -> dict[str, int]:
    """Assign all collected modules using cost hints with a test-count fallback."""
    if type(count) is not int or count < 1:
        raise ValueError("invalid Provelume pytest shard count")
    hints = _validated_cost_hints()
    source_sizes: dict[str, int] = {}
    for nodeid in nodeids:
        source = _source_for_nodeid(nodeid)
        source_sizes[source] = source_sizes.get(source, 0) + 1

    costs = {
        source: hints[source][1]
        if source in hints and hints[source][0] == size
        else size * _COUNT_COST
        for source, size in source_sizes.items()
    }
    loads = [0] * count
    test_counts = [0] * count
    assignments: dict[str, int] = {}
    for source, size in sorted(
        source_sizes.items(), key=lambda value: (-costs[value[0]], -value[1], value[0])
    ):
        index = min(
            range(count),
            key=lambda candidate: (loads[candidate], test_counts[candidate], candidate),
        )
        assignments[source] = index
        loads[index] += costs[source]
        test_counts[index] += size
    return assignments


def pytest_collection_modifyitems(config, items) -> None:
    index = config.getoption("--provelume-shard-index")
    count = config.getoption("--provelume-shard-count")
    if index is None and count is None:
        return
    if (
        type(index) is not int
        or type(count) is not int
        or count < 1
        or not 0 <= index < count
    ):
        raise ValueError("invalid Provelume pytest shard selection")
    assignments = balanced_shard_assignments([item.nodeid for item in items], count)
    selected = [
        item for item in items if assignments[_source_for_nodeid(item.nodeid)] == index
    ]
    deselected = [
        item for item in items if assignments[_source_for_nodeid(item.nodeid)] != index
    ]
    items[:] = selected
    config.hook.pytest_deselected(items=deselected)
    config._provelume_shard_count = len(selected)


class _ModuleTimings:
    """Observe completed selected modules without changing pytest outcomes."""

    def __init__(self, session, index: int, count: int) -> None:
        self.reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        self.index, self.count = index, count
        self.nodes: dict[str, str] = {}
        self.modules: dict[str, dict] = {}
        for item in session.items:
            try:
                source = item.path.relative_to(session.config.rootpath).as_posix()
            except ValueError:
                continue
            self.nodes[item.nodeid] = source
            module = self.modules.setdefault(source, {
                "selected": 0, "completed": set(), "seen": {}, "invalid": False,
                "durations": dict.fromkeys(("setup", "call", "teardown"), 0.0),
                "outcomes": {phase: dict.fromkeys(("passed", "failed", "skipped"), 0)
                             for phase in ("setup", "call", "teardown")},
            })
            module["selected"] += 1

    def pytest_runtest_logreport(self, report) -> None:
        source = self.nodes.get(report.nodeid)
        if source is None:
            return
        module = self.modules[source]
        key = (report.nodeid, report.when)
        setup = module["seen"].get((report.nodeid, "setup"))
        if (type(report).__module__ == "_pytest.subtests"
                and type(report).__name__ in {"SubtestReport", "SubTestReport"}):
            # The outer call duration includes its subtests. Recognize the same
            # native reports as the unchanged CI recorder, without counting a
            # child as a second parent phase or using failed children as costs.
            if (report.when != "call" or setup != "passed"
                    or (report.nodeid, "call") in module["seen"]
                    or (report.nodeid, "teardown") in module["seen"]
                    or report.outcome not in {"passed", "skipped"}
                    or not math.isfinite(report.duration) or report.duration < 0):
                module["invalid"] = True
            return
        if (
            module["invalid"] or key in module["seen"]
            or report.when not in module["durations"]
            or report.outcome not in ("passed", "failed", "skipped")
            or not math.isfinite(report.duration) or report.duration < 0
            or (report.when != "setup" and setup is None)
            or (report.when == "call" and setup != "passed")
            or (report.when == "teardown" and setup == "passed"
                and (report.nodeid, "call") not in module["seen"])
        ):
            module["invalid"] = True
            return
        module["seen"][key] = report.outcome
        module["durations"][report.when] += report.duration
        module["outcomes"][report.when][report.outcome] += 1
        if report.when != "teardown":
            return
        module["completed"].add(report.nodeid)
        if len(module["completed"]) != module["selected"]:
            return
        durations = dict(module["durations"])
        durations["total"] = sum(durations.values())
        record = {
            "schema": 1, "shard_index": self.index, "shard_count": self.count,
            "module": source, "selected": module["selected"],
            "completed": len(module["completed"]), "complete": True,
            "duration_seconds": durations, "phase_outcomes": module["outcomes"],
        }
        self.reporter.write_line(
            "provelume-windows-module " + json.dumps(record, ensure_ascii=True)
        )
        self.reporter.flush()


def pytest_collection_finish(session) -> None:
    count = getattr(session.config, "_provelume_shard_count", None)
    index = session.config.getoption("--provelume-shard-index")
    total = session.config.getoption("--provelume-shard-count")
    if count is not None:
        session.config.pluginmanager.get_plugin("terminalreporter").write_line(
            f"provelume-windows-shard index={index}/{total} selected={count}"
        )
        if os.environ.get(CHILD_ENV) == "1" and index is not None and total is not None:
            session.config.pluginmanager.register(_ModuleTimings(session, index, total))


def pytest_sessionfinish(session, exitstatus) -> None:
    count = getattr(session.config, "_provelume_shard_count", None)
    if count == 0 and exitstatus == pytest.ExitCode.NO_TESTS_COLLECTED:
        session.exitstatus = pytest.ExitCode.OK


def _should_orchestrate(args: tuple[str, ...]) -> bool:
    if os.environ.get(CHILD_ENV) == "1" or os.environ.get(DISABLE_ENV) == "1":
        return False
    if os.environ.get(FORCE_ENV) == "1":
        return True
    if os.name != "nt":
        return False
    harmless = {"-q", "--quiet"}
    return all(argument in harmless for argument in args)


def _timeout_seconds() -> int:
    raw = os.environ.get("PROVELUME_WINDOWS_SHARD_TIMEOUT_SECONDS", "")
    try:
        value = int(raw) if raw else DEFAULT_SHARD_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_SHARD_TIMEOUT_SECONDS
    return max(MIN_SHARD_TIMEOUT_SECONDS, min(MAX_SHARD_TIMEOUT_SECONDS, value))


def _terminate_process_tree(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        process.kill()
        process.wait(timeout=5)


def _replay(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_REPLAY_BYTES:
        data = data[-MAX_REPLAY_BYTES:]
        prefix = b"[bounded output: earlier shard output omitted]\n"
    else:
        prefix = b""
    return (prefix + data).decode("utf-8", errors="replace")


def _child_working_directory(config) -> Path:
    inipath = config.inipath
    return (
        Path(inipath).resolve().parent
        if inipath is not None
        else Path(config.rootpath).resolve()
    )


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config) -> int | None:
    args = tuple(str(value) for value in config.invocation_params.args)
    if not _should_orchestrate(args):
        return None
    started = time.monotonic()
    timeout = _timeout_seconds()
    # An explicit test target may live on another Windows drive (pytest's
    # ``tmp_path`` commonly does).  In that case pytest can derive a volume
    # root as ``rootpath`` even though ``-c`` points at the repository config.
    # Starting child collection there makes pytest encounter protected junctions
    # such as ``C:\\Documents and Settings``.  Anchor children to the versioned
    # configuration directory instead; fall back to rootpath only when no
    # configuration file exists.
    root = _child_working_directory(config)
    with tempfile.TemporaryDirectory(prefix="provelume-windows-shards-") as temporary:
        temporary_root = Path(temporary)
        processes: list[subprocess.Popen[Any]] = []
        logs = []
        handles = []
        shard_started = []
        try:
            for index in range(SHARD_COUNT):
                log = temporary_root / f"shard-{index}.log"
                handle = log.open("wb")
                environment = os.environ.copy()
                environment[CHILD_ENV] = "1"
                # Shard logs are decoded as UTF-8 regardless of the host console.
                environment["PYTHONIOENCODING"] = "utf-8"
                environment.pop(FORCE_ENV, None)
                state = temporary_root / f"state-{index}"
                state.mkdir()
                if os.name == "nt":
                    environment["LOCALAPPDATA"] = str(state)
                else:
                    environment["XDG_STATE_HOME"] = str(state)
                command = [
                    sys.executable,
                    "-m",
                    "pytest",
                    f"--rootdir={root}",
                    "-o",
                    f"cache_dir={state / 'pytest-cache'}",
                    *args,
                    # Retain the active test and slowest completed cases when
                    # the bounded aggregate deadline interrupts a quiet run.
                    # Full collection, partitioning and output bounds are unchanged.
                    "-vv",
                    "--durations=10",
                    f"--provelume-shard-index={index}",
                    f"--provelume-shard-count={SHARD_COUNT}",
                ]
                process = subprocess.Popen(
                    command,
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=handle,
                    stderr=subprocess.STDOUT,
                    env=environment,
                    start_new_session=os.name != "nt",
                    creationflags=(
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )
                processes.append(process)
                logs.append(log)
                handles.append(handle)
                shard_started.append(time.monotonic())

            deadline = started + timeout
            while any(process.poll() is None for process in processes):
                if time.monotonic() >= deadline:
                    for process in processes:
                        _terminate_process_tree(process)
                    break
                time.sleep(0.1)
        finally:
            for process in processes:
                _terminate_process_tree(process)
            for handle in handles:
                handle.close()

        timed_out = time.monotonic() >= started + timeout
        return_codes = []
        for index, (process, log) in enumerate(zip(processes, logs, strict=True)):
            code = process.returncode if process.returncode is not None else 1
            return_codes.append(code)
            duration = time.monotonic() - shard_started[index]
            print(
                f"windows-shard index={index}/{SHARD_COUNT} "
                f"duration_seconds={duration:.2f} exit_code={code}"
            )
            output = _replay(log)
            if output:
                # A redirected Windows parent may still use cp1252. Preserve
                # unrepresentable diagnostics as escapes without hiding failure
                # or aborting replay of the remaining shards.
                encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
                output = output.encode(encoding, errors="backslashreplace").decode(encoding)
                print(output, end="" if output.endswith("\n") else "\n")
        total = time.monotonic() - started
        print(
            f"windows-shards completed={not timed_out} count={SHARD_COUNT} "
            f"duration_seconds={total:.2f} timeout_seconds={timeout}"
        )
        if timed_out:
            return 124
        return 0 if all(code == 0 for code in return_codes) else 1
