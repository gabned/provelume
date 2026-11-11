# S23 Windows allocation observations, R10, 11 November 2026

On `db63ea2fe156c6ad7da259512782f862e492ab22`, [group 0](https://github.com/gabned/provelume/actions/runs/43013073932/job/130497243840)
PASS includes all32 Gitea cases. [Group 1](https://github.com/gabned/provelume/actions/runs/43013073932/job/130497243908)
retains CANCELLED at10m and the actual SSH-agent completion-proof failure; both
shards had finished in438.58/510.88s. Completed test output never overrides a
cancelled job. The aggregator130502394598 remains BLOCKED.

The existing observer reports292 complete modules/6028 selected parents. Only291
non-failing modules provide new timing hints. The failed `test_concordia_rsync_s22.py`
is excluded and keeps its prior hint. Costs are rounded actual setup/call/teardown
milliseconds; no multiplier or fabricated runtime. All raw observations, the
failed module and original outcomes are preserved in the local R10 observation.
Previous records remain in [the earlier 11 November record](windows-ci-s23-costs-20261111.md)
and [10 November](windows-ci-s23-costs-20261110.md), without rewritten results.

The allocator AST is identical after removing only the hint assignment. All test
membership/count fallback, four workers/two runner groups, native540s/job10m,
upload/cleanup, recorder/verifier, pin/Protocol source and every workflow remain
unchanged. Replaying these same non-failing module timings yields:

| Shard | Observed work sum | Same costs, refreshed allocation |
| --- | ---: | ---: |
| 0 | 337.740s | 407.436s |
| 1 | 352.560s | 407.623s |
| 2 | 433.533s | 407.625s |
| 3 | 506.479s | 407.628s |

This is a distribution check using placeholder labels for module counts, not
native identity/coverage proof, a runtime prediction or qualification. Collection,
reporting, cleanup and host variation remain outside these sums. Exact-head CI
and its original verifier must still succeed. The separate completion-I/O
correction and its closed diagnostics do not dispose of the original Gitea cause.
Independent Actions artifact verification stays BLOCKED_BY_MAINTAINER/NOT_WAIVED;
decoded logs/API metadata only, no artifact ZIP or unchanged manual rerun.
All prior R4–R9, BIND S07 and original findings remain unchanged. No publication,
merge or intermediate PC installation follows.

## Exact new observations used as hints

| Module | Selected/completed parents | Rounded milliseconds |
| --- | ---: | ---: |
| `tests/test_action_center_adapters.py` | 43 | 15239 |
| `tests/test_action_center_model.py` | 37 | 3062 |
| `tests/test_action_center_routes.py` | 9 | 7594 |
| `tests/test_action_notifications.py` | 65 | 917 |
| `tests/test_agent_protocol_consumer.py` | 60 | 86850 |
| `tests/test_agent_protocol_consumer_scope.py` | 37 | 43 |
| `tests/test_agent_protocol_transfer.py` | 38 | 64038 |
| `tests/test_agent_protocol_v1_2.py` | 15 | 114775 |
| `tests/test_agent_protocol_v1_2_1.py` | 47 | 271 |
| `tests/test_agent_protocol_v1_4.py` | 21 | 12 |
| `tests/test_agent_protocol_v1_4_1.py` | 65 | 1301 |
| `tests/test_agent_protocol_v1_4_1_slice_issue_transition.py` | 16 | 140 |
| `tests/test_agent_protocol_v1_4_2_ops.py` | 247 | 10193 |
| `tests/test_agent_protocol_v1_4_7.py` | 63 | 795 |
| `tests/test_agent_protocol_v1_4_9.py` | 14 | 1696 |
| `tests/test_agent_protocol_work_check.py` | 36 | 6355 |
| `tests/test_agent_protocol_work_recovery.py` | 38 | 74218 |
| `tests/test_agent_protocol_work_source.py` | 37 | 10 |
| `tests/test_ai_classification_evaluation.py` | 60 | 468 |
| `tests/test_ai_classification_proposals.py` | 39 | 13244 |
| `tests/test_ai_classification_request.py` | 22 | 6526 |
| `tests/test_ai_classification_targets.py` | 33 | 4520 |
| `tests/test_ai_context.py` | 90 | 236 |
| `tests/test_ai_gateway.py` | 94 | 172 |
| `tests/test_ai_jobs.py` | 25 | 6863 |
| `tests/test_ai_jobs_boundaries.py` | 26 | 9556 |
| `tests/test_ai_jobs_controls.py` | 29 | 3102 |
| `tests/test_ai_llama_prefix.py` | 21 | 20 |
| `tests/test_ai_llama_wait.py` | 5 | 3 |
| `tests/test_ai_model_download.py` | 42 | 95 |
| `tests/test_ai_model_progress_js.py` | 1 | 576 |
| `tests/test_ai_models.py` | 95 | 1541 |
| `tests/test_ai_provider.py` | 105 | 4801 |
| `tests/test_ai_runtime.py` | 82 | 5439 |
| `tests/test_ai_runtime_cpu.py` | 24 | 20 |
| `tests/test_ai_runtime_warm_qualification.py` | 28 | 23 |
| `tests/test_ai_setup.py` | 63 | 19798 |
| `tests/test_ai_synthesis.py` | 69 | 25472 |
| `tests/test_ai_synthesis_profile.py` | 89 | 100 |
| `tests/test_anchored_installation.py` | 23 | 178 |
| `tests/test_annotation_editor.py` | 23 | 2072 |
| `tests/test_annotation_route_failures.py` | 4 | 849 |
| `tests/test_api_browser.py` | 6 | 3577 |
| `tests/test_api_registration.py` | 1 | 657 |
| `tests/test_api_shared_routes.py` | 3 | 352 |
| `tests/test_atomic_commit.py` | 47 | 834 |
| `tests/test_atomic_digest_bounds.py` | 9 | 26 |
| `tests/test_atomic_journal_paths.py` | 14 | 24 |
| `tests/test_atomic_single_io.py` | 6 | 92 |
| `tests/test_atomic_transaction_pool.py` | 8 | 196 |
| `tests/test_audio_packaging.py` | 2 | 2 |
| `tests/test_audio_profiles.py` | 24 | 2426 |
| `tests/test_audio_real_smoke.py` | 1 | 1 |
| `tests/test_build_configuration.py` | 5 | 7 |
| `tests/test_build_info.py` | 13 | 10 |
| `tests/test_build_input_bundle.py` | 5 | 32 |
| `tests/test_build_input_lock.py` | 6 | 80 |
| `tests/test_canonical_brand.py` | 8 | 2556 |
| `tests/test_capacity_admission.py` | 30 | 527 |
| `tests/test_capture_adapter.py` | 29 | 3891 |
| `tests/test_capture_guard_comparison.py` | 9 | 16 |
| `tests/test_capture_journal.py` | 38 | 1450 |
| `tests/test_capture_path_guard.py` | 13 | 23 |
| `tests/test_capture_requests.py` | 28 | 20 |
| `tests/test_capture_shell_contract.py` | 6 | 798 |
| `tests/test_capture_surface.py` | 28 | 4082 |
| `tests/test_changelog_policy.py` | 3 | 3 |
| `tests/test_classification_review.py` | 32 | 13857 |
| `tests/test_cli.py` | 9 | 129 |
| `tests/test_cli_parser_selection.py` | 6 | 5228 |
| `tests/test_component_inventory.py` | 20 | 1159 |
| `tests/test_concordia_asana_s13.py` | 26 | 48926 |
| `tests/test_concordia_capture_marker_fixture.py` | 2 | 1 |
| `tests/test_concordia_connectors_s10.py` | 21 | 980 |
| `tests/test_concordia_cpu_topology.py` | 13 | 208 |
| `tests/test_concordia_folder_s21.py` | 19 | 9716 |
| `tests/test_concordia_git_admission.py` | 3 | 859 |
| `tests/test_concordia_git_s17.py` | 37 | 43780 |
| `tests/test_concordia_gitea_s20.py` | 32 | 30291 |
| `tests/test_concordia_github_s18.py` | 32 | 38108 |
| `tests/test_concordia_gitlab_s19.py` | 27 | 32688 |
| `tests/test_concordia_gmail_recovery_s23.py` | 6 | 2544 |
| `tests/test_concordia_google_calendar_s11.py` | 11 | 12933 |
| `tests/test_concordia_icalendar_s12.py` | 30 | 12159 |
| `tests/test_concordia_inbox_transit.py` | 51 | 16463 |
| `tests/test_concordia_integrated_s23.py` | 1 | 49144 |
| `tests/test_concordia_journal_comparison.py` | 8 | 4 |
| `tests/test_concordia_kernel_native.py` | 8 | 44 |
| `tests/test_concordia_kernel_observer.py` | 19 | 80 |
| `tests/test_concordia_mirror_credential_context.py` | 9 | 4 |
| `tests/test_concordia_mirrors_s16.py` | 46 | 9174 |
| `tests/test_concordia_ocr_sources.py` | 44 | 18869 |
| `tests/test_concordia_personal_s09.py` | 2 | 22078 |
| `tests/test_concordia_productivity_intake.py` | 12 | 4461 |
| `tests/test_concordia_rsync_fixture_cleanup.py` | 6 | 13 |
| `tests/test_concordia_rsync_state_s22.py` | 22 | 23 |
| `tests/test_concordia_rsync_windows_diagnostics.py` | 13 | 28 |
| `tests/test_concordia_search_inputs.py` | 97 | 25474 |
| `tests/test_concordia_search_s08.py` | 54 | 12683 |
| `tests/test_concordia_task_writeback_s15.py` | 38 | 14355 |
| `tests/test_concordia_tududi_s14.py` | 28 | 51961 |
| `tests/test_concordia_ui_s07.py` | 32 | 6989 |
| `tests/test_config_decode_reuse.py` | 20 | 90 |
| `tests/test_config_inspection_reuse.py` | 11 | 357 |
| `tests/test_connector_foundation.py` | 17 | 832 |
| `tests/test_connector_lifecycle.py` | 6 | 1029 |
| `tests/test_cura_ai_completion.py` | 20 | 10026 |
| `tests/test_cura_document_decisions.py` | 6 | 4030 |
| `tests/test_cura_icons.py` | 37 | 515 |
| `tests/test_cura_legacy_maintenance_preview.py` | 9 | 2907 |
| `tests/test_cura_maintenance_activity.py` | 11 | 4229 |
| `tests/test_cura_package_resources.py` | 54 | 2348 |
| `tests/test_cura_preferences.py` | 63 | 4568 |
| `tests/test_cura_primary_upgrade.py` | 9 | 36 |
| `tests/test_cura_recovery_capacity_boundary.py` | 2 | 483 |
| `tests/test_cura_release_identity.py` | 20 | 5827 |
| `tests/test_cura_retention_recovery.py` | 12 | 3803 |
| `tests/test_cura_review_runtime.py` | 10 | 440 |
| `tests/test_cura_s09_preferences.py` | 29 | 5294 |
| `tests/test_cura_s09_tray.py` | 24 | 20 |
| `tests/test_cura_shell.py` | 12 | 11663 |
| `tests/test_cura_shell_js.py` | 3 | 221 |
| `tests/test_custodia_admission_observations.py` | 40 | 80 |
| `tests/test_custodia_authority_costs.py` | 13 | 7 |
| `tests/test_custodia_diagnostics.py` | 9 | 96 |
| `tests/test_custodia_guided_setup.py` | 45 | 1938 |
| `tests/test_custodia_language_preferences.py` | 20 | 8788 |
| `tests/test_custodia_local_file_locality.py` | 9 | 2 |
| `tests/test_custodia_model_cancellation.py` | 17 | 339 |
| `tests/test_custodia_native_download.py` | 20 | 61 |
| `tests/test_custodia_native_packaging.py` | 7 | 60 |
| `tests/test_custodia_native_sbom.py` | 7 | 89 |
| `tests/test_custodia_network_lifecycle.py` | 9 | 777 |
| `tests/test_custodia_parent_lifetime.py` | 2 | 1 |
| `tests/test_custodia_pdf_boundary.py` | 3 | 186 |
| `tests/test_custodia_preview_freshness.py` | 13 | 2516 |
| `tests/test_custodia_qualification_failures.py` | 7 | 34044 |
| `tests/test_custodia_recommendation.py` | 12 | 28 |
| `tests/test_custodia_resource_limits.py` | 10 | 2 |
| `tests/test_custodia_synthesis_recovery.py` | 7 | 8304 |
| `tests/test_custodia_windows_package.py` | 4 | 19 |
| `tests/test_dependency_governance.py` | 3 | 2 |
| `tests/test_desktop_about.py` | 66 | 13493 |
| `tests/test_deterministic_build.py` | 9 | 96 |
| `tests/test_document_bundle_limits.py` | 3 | 93 |
| `tests/test_document_bundle_validation.py` | 2 | 280 |
| `tests/test_document_bundles.py` | 5 | 1308 |
| `tests/test_duplicate_assurance.py` | 7 | 1898 |
| `tests/test_duplicate_conflicts.py` | 6 | 257 |
| `tests/test_durable_scheduler.py` | 19 | 3332 |
| `tests/test_email_bundle.py` | 2 | 3 |
| `tests/test_email_canonical_validation.py` | 3 | 782 |
| `tests/test_email_containers.py` | 17 | 29 |
| `tests/test_email_contract.py` | 12 | 11 |
| `tests/test_email_jobs.py` | 13 | 1761 |
| `tests/test_email_mime.py` | 19 | 45 |
| `tests/test_email_packaging.py` | 3 | 2 |
| `tests/test_email_portability.py` | 3 | 2911 |
| `tests/test_email_real_smoke.py` | 2 | 1 |
| `tests/test_email_sources.py` | 17 | 619 |
| `tests/test_email_surfaces.py` | 3 | 705 |
| `tests/test_emendatio_activation.py` | 4 | 5 |
| `tests/test_entitas_integrated_qualification.py` | 10 | 33186 |
| `tests/test_external_folder_availability.py` | 1 | 68 |
| `tests/test_extractor_parity.py` | 3 | 227 |
| `tests/test_extractor_xlsx_images.py` | 2 | 283 |
| `tests/test_extractor_zip.py` | 6 | 235 |
| `tests/test_file_family_profiles.py` | 19 | 2707 |
| `tests/test_folder_settings.py` | 7 | 599 |
| `tests/test_folder_source_enrollment.py` | 52 | 1974 |
| `tests/test_folder_sources.py` | 15 | 2623 |
| `tests/test_google_adapter_lifecycle.py` | 6 | 225 |
| `tests/test_google_connection.py` | 54 | 9850 |
| `tests/test_google_intake_coordination.py` | 7 | 4105 |
| `tests/test_google_jobs.py` | 13 | 3069 |
| `tests/test_governed_catalogs.py` | 8 | 224 |
| `tests/test_guarded_web_transport.py` | 83 | 4401 |
| `tests/test_hierarchy_classification.py` | 12 | 2090 |
| `tests/test_inbox_operations.py` | 8 | 915 |
| `tests/test_incremental_search_index.py` | 9 | 1853 |
| `tests/test_independent_rebuild.py` | 5 | 48 |
| `tests/test_ingestion_runs.py` | 11 | 3297 |
| `tests/test_ingestion_security.py` | 1 | 31 |
| `tests/test_installation_interfaces.py` | 6 | 1081 |
| `tests/test_installation_verification.py` | 87 | 439 |
| `tests/test_instance_lifecycle.py` | 20 | 5415 |
| `tests/test_instance_repair.py` | 33 | 18811 |
| `tests/test_instance_repair_pending.py` | 21 | 11857 |
| `tests/test_iudicium_journey.py` | 9 | 62103 |
| `tests/test_knowledge_object_activity.py` | 56 | 18304 |
| `tests/test_knowledge_object_contract.py` | 69 | 121 |
| `tests/test_knowledge_object_review.py` | 46 | 19617 |
| `tests/test_knowledge_object_review_activity.py` | 18 | 13569 |
| `tests/test_knowledge_object_services.py` | 57 | 10118 |
| `tests/test_knowledge_object_storage.py` | 43 | 22837 |
| `tests/test_local_path_guard.py` | 4 | 21 |
| `tests/test_maintenance_backup_diagnostics.py` | 26 | 1384 |
| `tests/test_maintenance_catalog.py` | 14 | 4787 |
| `tests/test_maintenance_queue_contention.py` | 15 | 5796 |
| `tests/test_maintenance_reviewed_plans.py` | 7 | 676 |
| `tests/test_manual_web_acquisition.py` | 28 | 4673 |
| `tests/test_markdown_library_viewer.py` | 11 | 4915 |
| `tests/test_mobile_retrieval.py` | 23 | 6979 |
| `tests/test_mobile_shell_contract.py` | 5 | 583 |
| `tests/test_model_read_buffer.py` | 1 | 14 |
| `tests/test_network_interfaces.py` | 3 | 1024 |
| `tests/test_network_status.py` | 11 | 4 |
| `tests/test_node_conformance_lifecycle.py` | 1 | 119 |
| `tests/test_oauth_authorization.py` | 19 | 1442 |
| `tests/test_object_migration_permissions.py` | 20 | 7160 |
| `tests/test_ocr_contract.py` | 28 | 30 |
| `tests/test_ocr_execution.py` | 27 | 4636 |
| `tests/test_ocr_kit.py` | 44 | 2889 |
| `tests/test_ocr_kit_release.py` | 11 | 528 |
| `tests/test_ocr_real_smoke.py` | 3 | 1 |
| `tests/test_offline_release_verifier.py` | 8 | 283 |
| `tests/test_operations_maintenance.py` | 34 | 1243 |
| `tests/test_paths.py` | 2 | 21 |
| `tests/test_perceptio_integration.py` | 6 | 4225 |
| `tests/test_photo_profiles.py` | 13 | 3208 |
| `tests/test_photo_real_smoke.py` | 1 | 1 |
| `tests/test_portable_transfer.py` | 29 | 21516 |
| `tests/test_processing_autonomy.py` | 54 | 13236 |
| `tests/test_public_roadmap.py` | 47 | 76 |
| `tests/test_publication.py` | 24 | 703 |
| `tests/test_publication_distribution.py` | 24 | 3181 |
| `tests/test_publication_updates.py` | 5 | 1380 |
| `tests/test_qualification.py` | 24 | 8365 |
| `tests/test_qualification_contract.py` | 3 | 2 |
| `tests/test_qualification_documentation.py` | 4 | 8 |
| `tests/test_qualification_real_smoke.py` | 1 | 1 |
| `tests/test_qualification_surfaces.py` | 4 | 1346 |
| `tests/test_rebuild_coordination.py` | 6 | 2114 |
| `tests/test_release_assurance.py` | 6 | 82 |
| `tests/test_release_installed.py` | 15 | 26 |
| `tests/test_release_manifest.py` | 3 | 9 |
| `tests/test_representations.py` | 27 | 2622 |
| `tests/test_resource_statistics.py` | 13 | 1865 |
| `tests/test_retention_boundaries.py` | 16 | 10778 |
| `tests/test_review_atomic_removal.py` | 12 | 254 |
| `tests/test_review_authority_observation.py` | 1 | 29 |
| `tests/test_review_decision_routes.py` | 11 | 4349 |
| `tests/test_review_documents_observation.py` | 3 | 31 |
| `tests/test_review_evidence_reads.py` | 7 | 14 |
| `tests/test_review_intake_routing.py` | 8 | 2727 |
| `tests/test_review_origin_observation.py` | 4 | 46 |
| `tests/test_review_path_observation.py` | 22 | 132 |
| `tests/test_review_placement_routing.py` | 24 | 5112 |
| `tests/test_runtime_boundaries.py` | 2 | 16 |
| `tests/test_s07_documentation.py` | 6 | 6 |
| `tests/test_scheduler_control.py` | 17 | 2981 |
| `tests/test_scheduler_cooperative_sources.py` | 4 | 1004 |
| `tests/test_scheduler_readers.py` | 3 | 278 |
| `tests/test_setup_activity.py` | 4 | 17607 |
| `tests/test_setup_coordinator.py` | 15 | 21686 |
| `tests/test_setup_qualification.py` | 1 | 7934 |
| `tests/test_setup_source_scope.py` | 4 | 603 |
| `tests/test_setup_space_name.py` | 5 | 36 |
| `tests/test_setup_trial_inputs.py` | 14 | 948 |
| `tests/test_setup_trials.py` | 5 | 2710 |
| `tests/test_shell_settings.py` | 37 | 1561 |
| `tests/test_source_exclusion_contention.py` | 12 | 3555 |
| `tests/test_source_exclusions.py` | 47 | 3824 |
| `tests/test_source_reconciliation.py` | 17 | 5983 |
| `tests/test_ssh_agent_report_commit.py` | 6 | 31 |
| `tests/test_startup_diagnostic_copy.py` | 21 | 2805 |
| `tests/test_startup_process.py` | 16 | 286 |
| `tests/test_startup_readiness.py` | 43 | 2370 |
| `tests/test_startup_windows.py` | 2 | 110 |
| `tests/test_transcript_documentation.py` | 3 | 3 |
| `tests/test_transcript_jobs.py` | 11 | 4394 |
| `tests/test_transcript_packaging.py` | 4 | 3 |
| `tests/test_transcript_parsers.py` | 19 | 10 |
| `tests/test_transcript_real_smoke.py` | 2 | 1 |
| `tests/test_transcript_sources.py` | 5 | 703 |
| `tests/test_transcript_surfaces.py` | 6 | 1986 |
| `tests/test_updates.py` | 28 | 1027 |
| `tests/test_verify_release_bundle.py` | 7 | 206 |
| `tests/test_vertical_slice.py` | 4 | 361 |
| `tests/test_video_packaging.py` | 2 | 2 |
| `tests/test_video_profiles.py` | 14 | 1607 |
| `tests/test_video_real_smoke.py` | 1 | 1 |
| `tests/test_win32_file_api_setup.py` | 15 | 11 |
| `tests/test_windows_identity.py` | 6 | 975 |
| `tests/test_windows_json_snapshots.py` | 12 | 275 |
| `tests/test_windows_package_manifest.py` | 2 | 4 |
| `tests/test_windows_pdf_lock.py` | 9 | 8 |
| `tests/test_windows_public_baselines.py` | 3 | 4 |
| `tests/test_windows_pytest_sharding.py` | 6 | 2005 |
| `tests/test_windows_shard_costs.py` | 18 | 9 |
| `tests/test_windows_shard_timings.py` | 3 | 3496 |
