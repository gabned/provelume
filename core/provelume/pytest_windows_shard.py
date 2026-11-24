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

# Relative allocation hints in rounded observed milliseconds. Where both
# recent exact-source runs completed a module, use the higher parent-phase
# total for the unchanged test inventory:
# - 50452424 / 20ce241, run 45289172398 attempt 1, artifacts 14873422756 and 14873862484.
# - 4f7497af / f05571b, run 45292862680 attempt 1, artifacts 14876216085 and 14876315602.
# For a module without two recent complete records, take the higher of the
# prior same-count hint and any complete new observation. Exact history for
# the prior hints remains in 4f7497af and the existing qualification records.
# The cancelled and timed-out groups retain their recorded status.
# All 298 modules and 6203 collected parent cases are retained.
# Native PASS never overrides cancelled jobs or a BLOCKED aggregator. No runtime
# prediction, multiplier or omitted failure. Rounded observed milliseconds only.
# Allocator/count fallback, four workers/two groups and every budget are unchanged.
# Source-specific records: docs/qualification/windows-ci-s23-maximum-costs-20261111.md
# and the preceding R10/11November/10November records, all retained unchanged.
_COUNT_COST = 1000
_MODULE_COST_HINTS = (
    ('tests/test_action_center_adapters.py', 43, 15935),
    ('tests/test_action_center_model.py', 37, 3508),
    ('tests/test_action_center_routes.py', 9, 10935),
    ('tests/test_action_notifications.py', 65, 1348),
    ('tests/test_agent_protocol_consumer.py', 156, 271583),
    ('tests/test_agent_protocol_consumer_scope.py', 37, 68),
    ('tests/test_agent_protocol_transfer.py', 38, 81870),
    ('tests/test_agent_protocol_v1_2.py', 15, 145502),
    ('tests/test_agent_protocol_v1_2_1.py', 47, 284),
    ('tests/test_agent_protocol_v1_4.py', 21, 15),
    ('tests/test_agent_protocol_v1_4_1.py', 65, 1355),
    ('tests/test_agent_protocol_v1_4_1_slice_issue_transition.py', 16, 121),
    ('tests/test_agent_protocol_v1_4_2_ops.py', 247, 9940),
    ('tests/test_agent_protocol_v1_4_7.py', 63, 849),
    ('tests/test_agent_protocol_v1_4_9.py', 14, 1653),
    ('tests/test_agent_protocol_work_check.py', 36, 7093),
    ('tests/test_agent_protocol_work_recovery.py', 38, 80122),
    ('tests/test_agent_protocol_work_source.py', 37, 17),
    ('tests/test_ai_classification_evaluation.py', 60, 603),
    ('tests/test_ai_classification_proposals.py', 39, 14625),
    ('tests/test_ai_classification_request.py', 22, 5600),
    ('tests/test_ai_classification_targets.py', 33, 5114),
    ('tests/test_ai_context.py', 90, 355),
    ('tests/test_ai_gateway.py', 94, 312),
    ('tests/test_ai_jobs.py', 25, 8803),
    ('tests/test_ai_jobs_boundaries.py', 26, 10433),
    ('tests/test_ai_jobs_controls.py', 29, 3872),
    ('tests/test_ai_llama_prefix.py', 21, 19),
    ('tests/test_ai_llama_wait.py', 5, 3),
    ('tests/test_ai_model_download.py', 42, 162),
    ('tests/test_ai_model_progress_js.py', 1, 663),
    ('tests/test_ai_models.py', 95, 2402),
    ('tests/test_ai_provider.py', 105, 5795),
    ('tests/test_ai_runtime.py', 83, 5472),
    ('tests/test_ai_runtime_cpu.py', 24, 31),
    ('tests/test_ai_runtime_warm_qualification.py', 28, 254),
    ('tests/test_ai_setup.py', 63, 23214),
    ('tests/test_ai_synthesis.py', 69, 34683),
    ('tests/test_ai_synthesis_profile.py', 89, 148),
    ('tests/test_anchored_installation.py', 23, 163),
    ('tests/test_annotation_editor.py', 23, 2554),
    ('tests/test_annotation_route_failures.py', 4, 746),
    ('tests/test_api_browser.py', 6, 3711),
    ('tests/test_api_registration.py', 1, 548),
    ('tests/test_api_shared_routes.py', 3, 745),
    ('tests/test_atomic_commit.py', 47, 1288),
    ('tests/test_atomic_digest_bounds.py', 9, 29),
    ('tests/test_atomic_journal_paths.py', 14, 59),
    ('tests/test_atomic_single_io.py', 6, 102),
    ('tests/test_atomic_transaction_pool.py', 8, 304),
    ('tests/test_audio_packaging.py', 2, 3),
    ('tests/test_audio_profiles.py', 24, 2973),
    ('tests/test_audio_real_smoke.py', 1, 1),
    ('tests/test_build_configuration.py', 5, 8),
    ('tests/test_build_info.py', 13, 9),
    ('tests/test_build_input_bundle.py', 5, 43),
    ('tests/test_build_input_lock.py', 6, 98),
    ('tests/test_canonical_brand.py', 8, 2877),
    ('tests/test_capacity_admission.py', 30, 973),
    ('tests/test_capture_adapter.py', 29, 4551),
    ('tests/test_capture_guard_comparison.py', 9, 113),
    ('tests/test_capture_journal.py', 39, 1799),
    ('tests/test_capture_path_guard.py', 13, 22),
    ('tests/test_capture_requests.py', 28, 24),
    ('tests/test_capture_shell_contract.py', 6, 1132),
    ('tests/test_capture_surface.py', 28, 6179),
    ('tests/test_changelog_policy.py', 3, 3),
    ('tests/test_classification_review.py', 32, 16594),
    ('tests/test_cli.py', 9, 193),
    ('tests/test_cli_parser_selection.py', 6, 7431),
    ('tests/test_component_inventory.py', 20, 1294),
    ('tests/test_concordia_asana_s13.py', 26, 42030),
    ('tests/test_concordia_capture_marker_fixture.py', 2, 1),
    ('tests/test_concordia_connectors_s10.py', 21, 1714),
    ('tests/test_concordia_cpu_topology.py', 13, 278),
    ('tests/test_concordia_folder_s21.py', 19, 15337),
    ('tests/test_concordia_git_admission.py', 3, 823),
    ('tests/test_concordia_git_s17.py', 44, 45904),
    ('tests/test_concordia_gitea_s20.py', 32, 41115),
    ('tests/test_concordia_github_s18.py', 32, 43080),
    ('tests/test_concordia_gitlab_s19.py', 27, 36354),
    ('tests/test_concordia_gmail_recovery_s23.py', 6, 2303),
    ('tests/test_concordia_google_calendar_s11.py', 11, 20489),
    ('tests/test_concordia_icalendar_s12.py', 35, 11734),
    ('tests/test_concordia_inbox_transit.py', 51, 21006),
    ('tests/test_concordia_integrated_s23.py', 1, 61210),
    ('tests/test_concordia_journal_comparison.py', 8, 4),
    ('tests/test_concordia_kernel_native.py', 9, 94),
    ('tests/test_concordia_kernel_observer.py', 19, 103),
    ('tests/test_concordia_mirror_credential_context.py', 9, 4),
    ('tests/test_concordia_mirrors_s16.py', 48, 15584),
    ('tests/test_concordia_ocr_sources.py', 44, 20097),
    ('tests/test_concordia_personal_s09.py', 2, 24327),
    ('tests/test_concordia_productivity_intake.py', 12, 5656),
    ('tests/test_concordia_rsync_fixture_cleanup.py', 6, 19),
    ('tests/test_concordia_rsync_rsh.py', 5, 4),
    ('tests/test_concordia_rsync_s22.py', 34, 238),
    ('tests/test_concordia_rsync_state_s22.py', 22, 204),
    ('tests/test_concordia_rsync_windows_diagnostics.py', 15, 37),
    ('tests/test_concordia_search_inputs.py', 97, 37903),
    ('tests/test_concordia_search_s08.py', 54, 13760),
    ('tests/test_concordia_task_writeback_s15.py', 38, 22823),
    ('tests/test_concordia_tududi_s14.py', 28, 64992),
    ('tests/test_concordia_ui_s07.py', 32, 8140),
    ('tests/test_config_decode_reuse.py', 20, 110),
    ('tests/test_config_inspection_reuse.py', 11, 312),
    ('tests/test_connector_foundation.py', 17, 998),
    ('tests/test_connector_lifecycle.py', 6, 982),
    ('tests/test_cura_ai_completion.py', 20, 9566),
    ('tests/test_cura_document_decisions.py', 6, 4094),
    ('tests/test_cura_icons.py', 37, 695),
    ('tests/test_cura_legacy_maintenance_preview.py', 9, 3323),
    ('tests/test_cura_maintenance_activity.py', 11, 6037),
    ('tests/test_cura_package_resources.py', 54, 2194),
    ('tests/test_cura_preferences.py', 63, 5387),
    ('tests/test_cura_primary_upgrade.py', 9, 62),
    ('tests/test_cura_recovery_capacity_boundary.py', 2, 718),
    ('tests/test_cura_release_identity.py', 20, 6904),
    ('tests/test_cura_retention_recovery.py', 12, 4106),
    ('tests/test_cura_review_runtime.py', 10, 427),
    ('tests/test_cura_s09_preferences.py', 29, 7192),
    ('tests/test_cura_s09_tray.py', 24, 30),
    ('tests/test_cura_shell.py', 12, 14606),
    ('tests/test_cura_shell_js.py', 3, 238),
    ('tests/test_custodia_admission_observations.py', 40, 98),
    ('tests/test_custodia_authority_costs.py', 13, 10),
    ('tests/test_custodia_diagnostics.py', 9, 99),
    ('tests/test_custodia_guided_setup.py', 45, 2401),
    ('tests/test_custodia_language_preferences.py', 20, 10266),
    ('tests/test_custodia_local_file_locality.py', 9, 2),
    ('tests/test_custodia_model_cancellation.py', 17, 320),
    ('tests/test_custodia_native_download.py', 20, 74),
    ('tests/test_custodia_native_packaging.py', 7, 56),
    ('tests/test_custodia_native_sbom.py', 7, 115),
    ('tests/test_custodia_network_lifecycle.py', 9, 1447),
    ('tests/test_custodia_parent_lifetime.py', 2, 1),
    ('tests/test_custodia_pdf_boundary.py', 3, 298),
    ('tests/test_custodia_preview_freshness.py', 13, 3017),
    # S07 5f177ac, Public CI 45407113533/a1, artifact 14927395465, complete 9/9.
    ('tests/test_custodia_qualification_failures.py', 9, 42689),
    ('tests/test_custodia_recommendation.py', 12, 40),
    ('tests/test_custodia_resource_limits.py', 10, 3),
    ('tests/test_custodia_synthesis_recovery.py', 7, 10668),
    ('tests/test_custodia_windows_package.py', 4, 21),
    ('tests/test_dependency_governance.py', 3, 4),
    ('tests/test_desktop_about.py', 66, 16164),
    ('tests/test_deterministic_build.py', 9, 118),
    ('tests/test_document_bundle_limits.py', 3, 129),
    ('tests/test_document_bundle_validation.py', 2, 794),
    ('tests/test_document_bundles.py', 5, 1208),
    ('tests/test_duplicate_assurance.py', 7, 2269),
    ('tests/test_duplicate_conflicts.py', 6, 362),
    ('tests/test_durable_scheduler.py', 19, 3826),
    ('tests/test_email_bundle.py', 2, 4),
    ('tests/test_email_canonical_validation.py', 3, 1375),
    ('tests/test_email_containers.py', 17, 29),
    ('tests/test_email_contract.py', 12, 15),
    ('tests/test_email_jobs.py', 13, 4262),
    ('tests/test_email_mime.py', 19, 52),
    ('tests/test_email_packaging.py', 3, 3),
    ('tests/test_email_portability.py', 3, 2845),
    ('tests/test_email_real_smoke.py', 2, 1),
    ('tests/test_email_sources.py', 17, 686),
    ('tests/test_email_surfaces.py', 3, 1092),
    ('tests/test_emendatio_activation.py', 4, 8),
    ('tests/test_entitas_integrated_qualification.py', 10, 30943),
    ('tests/test_external_folder_availability.py', 1, 92),
    ('tests/test_extractor_parity.py', 3, 275),
    ('tests/test_extractor_xlsx_images.py', 2, 541),
    ('tests/test_extractor_zip.py', 6, 289),
    ('tests/test_file_family_profiles.py', 19, 2919),
    ('tests/test_folder_settings.py', 7, 910),
    ('tests/test_folder_source_enrollment.py', 52, 2910),
    ('tests/test_folder_sources.py', 15, 3159),
    ('tests/test_git_failure_diagnostics.py', 12, 59),
    ('tests/test_git_process_wakeup.py', 12, 46),
    ('tests/test_gitea_interruption_diagnostics.py', 4, 9),
    ('tests/test_google_adapter_lifecycle.py', 6, 290),
    ('tests/test_google_connection.py', 54, 12302),
    ('tests/test_google_intake_coordination.py', 7, 5025),
    ('tests/test_google_jobs.py', 13, 4584),
    ('tests/test_governed_catalogs.py', 8, 319),
    ('tests/test_guarded_web_transport.py', 83, 5529),
    ('tests/test_hierarchy_classification.py', 12, 2230),
    ('tests/test_inbox_operations.py', 8, 1488),
    ('tests/test_incremental_search_index.py', 9, 1463),
    ('tests/test_independent_rebuild.py', 5, 58),
    ('tests/test_ingestion_runs.py', 11, 3306),
    ('tests/test_ingestion_security.py', 1, 41),
    ('tests/test_installation_interfaces.py', 6, 1221),
    ('tests/test_installation_verification.py', 87, 478),
    ('tests/test_instance_lifecycle.py', 22, 5605),
    ('tests/test_instance_repair.py', 33, 17939),
    ('tests/test_instance_repair_pending.py', 21, 15563),
    ('tests/test_iudicium_journey.py', 9, 63694),
    ('tests/test_knowledge_object_activity.py', 56, 18518),
    ('tests/test_knowledge_object_contract.py', 69, 137),
    ('tests/test_knowledge_object_review.py', 46, 26818),
    ('tests/test_knowledge_object_review_activity.py', 18, 14552),
    ('tests/test_knowledge_object_services.py', 57, 13152),
    ('tests/test_knowledge_object_storage.py', 43, 27926),
    ('tests/test_local_path_guard.py', 4, 33),
    ('tests/test_maintenance_backup_diagnostics.py', 26, 1920),
    ('tests/test_maintenance_catalog.py', 14, 7201),
    ('tests/test_maintenance_queue_contention.py', 15, 5767),
    ('tests/test_maintenance_reviewed_plans.py', 7, 1037),
    ('tests/test_manual_web_acquisition.py', 28, 5821),
    ('tests/test_markdown_library_viewer.py', 12, 8258),
    ('tests/test_mobile_retrieval.py', 23, 10084),
    ('tests/test_mobile_shell_contract.py', 5, 1187),
    ('tests/test_model_read_buffer.py', 1, 16),
    ('tests/test_network_interfaces.py', 3, 998),
    ('tests/test_network_status.py', 11, 6),
    ('tests/test_node_conformance_lifecycle.py', 1, 115),
    ('tests/test_oauth_authorization.py', 19, 1315),
    ('tests/test_object_migration_permissions.py', 20, 8380),
    ('tests/test_ocr_contract.py', 28, 34),
    ('tests/test_ocr_execution.py', 27, 4133),
    ('tests/test_ocr_kit.py', 44, 3154),
    ('tests/test_ocr_kit_release.py', 11, 360),
    ('tests/test_ocr_real_smoke.py', 3, 1),
    ('tests/test_offline_release_verifier.py', 8, 302),
    ('tests/test_operations_maintenance.py', 34, 1881),
    ('tests/test_paths.py', 2, 28),
    ('tests/test_perceptio_integration.py', 6, 5311),
    ('tests/test_photo_profiles.py', 13, 3944),
    ('tests/test_photo_real_smoke.py', 1, 1),
    ('tests/test_portable_transfer.py', 29, 19114),
    ('tests/test_processing_autonomy.py', 54, 16187),
    ('tests/test_public_roadmap.py', 47, 76),
    ('tests/test_publication.py', 24, 675),
    ('tests/test_publication_distribution.py', 24, 3958),
    ('tests/test_publication_updates.py', 5, 1287),
    ('tests/test_qualification.py', 24, 9150),
    ('tests/test_qualification_contract.py', 3, 3),
    ('tests/test_qualification_documentation.py', 4, 8),
    ('tests/test_qualification_real_smoke.py', 1, 1),
    ('tests/test_qualification_surfaces.py', 4, 1911),
    ('tests/test_rebuild_coordination.py', 6, 3363),
    ('tests/test_release_assurance.py', 6, 76),
    ('tests/test_release_installed.py', 15, 37),
    ('tests/test_release_manifest.py', 3, 12),
    ('tests/test_representations.py', 27, 4231),
    ('tests/test_resource_statistics.py', 13, 2503),
    ('tests/test_retention_boundaries.py', 16, 10317),
    ('tests/test_review_atomic_removal.py', 12, 326),
    ('tests/test_review_authority_observation.py', 1, 60),
    ('tests/test_review_decision_routes.py', 11, 5594),
    ('tests/test_review_documents_observation.py', 3, 33),
    ('tests/test_review_evidence_reads.py', 8, 23),
    ('tests/test_review_intake_routing.py', 8, 3549),
    ('tests/test_review_origin_observation.py', 4, 68),
    ('tests/test_review_path_observation.py', 22, 143),
    ('tests/test_review_placement_routing.py', 24, 6093),
    ('tests/test_runtime_boundaries.py', 2, 20),
    ('tests/test_s07_documentation.py', 6, 11),
    ('tests/test_scheduler_control.py', 17, 4838),
    ('tests/test_scheduler_cooperative_sources.py', 4, 1417),
    ('tests/test_scheduler_readers.py', 3, 306),
    ('tests/test_setup_activity.py', 4, 18957),
    ('tests/test_setup_coordinator.py', 16, 26596),
    ('tests/test_setup_qualification.py', 1, 9391),
    ('tests/test_setup_source_scope.py', 4, 709),
    ('tests/test_setup_space_name.py', 5, 38),
    ('tests/test_setup_trial_inputs.py', 14, 1555),
    ('tests/test_setup_trials.py', 5, 3353),
    ('tests/test_shell_settings.py', 37, 2168),
    ('tests/test_source_exclusion_contention.py', 12, 7534),
    ('tests/test_source_exclusions.py', 47, 3927),
    ('tests/test_source_reconciliation.py', 17, 8686),
    ('tests/test_ssh_agent_completion_diagnostics.py', 6, 9),
    ('tests/test_ssh_agent_report_commit.py', 6, 34),
    ('tests/test_ssh_agent_windows_io_completion.py', 5, 4),
    ('tests/test_startup_diagnostic_copy.py', 21, 3798),
    ('tests/test_startup_process.py', 16, 289),
    ('tests/test_startup_readiness.py', 43, 3156),
    ('tests/test_startup_windows.py', 2, 113),
    ('tests/test_transcript_documentation.py', 3, 3),
    ('tests/test_transcript_jobs.py', 11, 6092),
    ('tests/test_transcript_packaging.py', 4, 4),
    ('tests/test_transcript_parsers.py', 19, 14),
    ('tests/test_transcript_real_smoke.py', 2, 1),
    ('tests/test_transcript_sources.py', 5, 967),
    ('tests/test_transcript_surfaces.py', 6, 3673),
    ('tests/test_updates.py', 28, 1586),
    ('tests/test_verify_release_bundle.py', 7, 191),
    ('tests/test_vertical_slice.py', 4, 544),
    ('tests/test_video_packaging.py', 2, 3),
    ('tests/test_video_profiles.py', 14, 1598),
    ('tests/test_video_real_smoke.py', 1, 1),
    ('tests/test_win32_file_api_setup.py', 15, 16),
    ('tests/test_windows_identity.py', 6, 996),
    ('tests/test_windows_json_snapshots.py', 12, 286),
    ('tests/test_windows_package_manifest.py', 2, 6),
    ('tests/test_windows_pdf_lock.py', 9, 11),
    ('tests/test_windows_public_baselines.py', 3, 4),
    ('tests/test_windows_pytest_sharding.py', 6, 3464),
    ('tests/test_windows_shard_costs.py', 18, 15),
    ('tests/test_windows_shard_timings.py', 3, 5023),
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
