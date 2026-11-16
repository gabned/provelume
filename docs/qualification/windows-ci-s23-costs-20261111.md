# S23 Windows allocation observations, 11 November 2026

Ubuntu completes on source `ea54a02094f8ad3d053852fe3fab4e295cbc3268`:
[130421465123](https://github.com/gabned/provelume/actions/runs/42990361706/job/130421465123)
reports 6,034 PASS / 66 SKIP / 419 subtests in 556.20 seconds with the original
15-minute job cap. This result belongs to that source only.

Windows group 0
[130421465642](https://github.com/gabned/provelume/actions/runs/42990361706/job/130421465642)
retains CANCELLED with the ten-minute-cap annotation. Its native execution step
and artifact upload both succeeded before final cleanup; the complete shards
report 516.53 and 484.13 seconds. Group 1
[130421465169](https://github.com/gabned/provelume/actions/runs/42990361706/job/130421465169)
succeeds; its shards report 275.78 and 252.36 seconds. The unchanged aggregator
[130426554091](https://github.com/gabned/provelume/actions/runs/42990361706/job/130426554091)
remains BLOCKED because both runner jobs did not succeed. Completed test output
never overrides a cancelled job.

The PRODUCT allocation inputs now use all 291 complete, non-failing module
records emitted by the existing observer in those decoded logs. Selected and
completed counts match for every module, totaling 6,020 selected parents. Costs
are rounded observed setup/call/teardown milliseconds, with no invented cost,
failed/interrupted module, multiplier or inferred CPU cause. The two hosts have
different observed speeds; a replay cannot isolate source/host causes or predict
future runtime. Earlier observations remain in
[the 10 November record](windows-ci-s23-costs-20261110.md) and Git history.

The Python AST is identical after removing the relative-hint assignment. The
allocator, count fallback, test membership, four workers, two runner groups,
native 540-second deadline, ten-minute job cap, cleanup, upload, native recorder,
verifier, Protocol source/pin and every workflow are unchanged. Replaying exactly
the same observed module costs changes sums from
512.388, 480.034, 273.269, 249.956 seconds to
378.909, 378.913, 378.914, 378.911 seconds. Collection, cleanup, reporting and host variation
remain outside these sums. This is a distribution check, not a qualified run.

Only authenticated API metadata and decoded logs were read. Independent Actions
artifact verification remains BLOCKED_BY_MAINTAINER / NOT_WAIVED. No artifact ZIP
was downloaded, no rerun of unchanged source was requested and no native gate is
replaced by this analysis. Actual case identity, disjointness, subtest outcomes
and complete coverage remain the unchanged CI verifier's responsibility. The new
head requires its own complete qualification; no Ubuntu/Windows PASS transfers.
All R4–R8 records, BIND receipts and original/current findings remain unchanged.
S07 experiments are not reopened; ordinary CPU checks cannot close their findings.
No merge, release, publication or intermediate PC installation follows.

## Exact observed allocation inputs

| Module | Selected/completed parents | Rounded observed milliseconds |
| --- | ---: | ---: |
| `tests/test_action_center_adapters.py` | 43 | 9485 |
| `tests/test_action_center_model.py` | 37 | 2087 |
| `tests/test_action_center_routes.py` | 9 | 6102 |
| `tests/test_action_notifications.py` | 65 | 1192 |
| `tests/test_agent_protocol_consumer.py` | 60 | 56935 |
| `tests/test_agent_protocol_consumer_scope.py` | 37 | 30 |
| `tests/test_agent_protocol_transfer.py` | 38 | 86388 |
| `tests/test_agent_protocol_v1_2.py` | 15 | 174289 |
| `tests/test_agent_protocol_v1_2_1.py` | 47 | 153 |
| `tests/test_agent_protocol_v1_4.py` | 21 | 8 |
| `tests/test_agent_protocol_v1_4_1.py` | 65 | 618 |
| `tests/test_agent_protocol_v1_4_1_slice_issue_transition.py` | 16 | 146 |
| `tests/test_agent_protocol_v1_4_2_ops.py` | 247 | 10966 |
| `tests/test_agent_protocol_v1_4_7.py` | 63 | 491 |
| `tests/test_agent_protocol_v1_4_9.py` | 14 | 1122 |
| `tests/test_agent_protocol_work_check.py` | 36 | 7449 |
| `tests/test_agent_protocol_work_recovery.py` | 38 | 49511 |
| `tests/test_agent_protocol_work_source.py` | 37 | 11 |
| `tests/test_ai_classification_evaluation.py` | 60 | 595 |
| `tests/test_ai_classification_proposals.py` | 39 | 16214 |
| `tests/test_ai_classification_request.py` | 22 | 6022 |
| `tests/test_ai_classification_targets.py` | 33 | 3157 |
| `tests/test_ai_context.py` | 90 | 179 |
| `tests/test_ai_gateway.py` | 94 | 113 |
| `tests/test_ai_jobs.py` | 25 | 4998 |
| `tests/test_ai_jobs_boundaries.py` | 26 | 10165 |
| `tests/test_ai_jobs_controls.py` | 29 | 3262 |
| `tests/test_ai_llama_prefix.py` | 21 | 19 |
| `tests/test_ai_llama_wait.py` | 5 | 3 |
| `tests/test_ai_model_download.py` | 42 | 66 |
| `tests/test_ai_model_progress_js.py` | 1 | 619 |
| `tests/test_ai_models.py` | 95 | 1267 |
| `tests/test_ai_provider.py` | 105 | 4275 |
| `tests/test_ai_runtime.py` | 82 | 5608 |
| `tests/test_ai_runtime_cpu.py` | 24 | 18 |
| `tests/test_ai_runtime_warm_qualification.py` | 28 | 19 |
| `tests/test_ai_setup.py` | 63 | 20443 |
| `tests/test_ai_synthesis.py` | 69 | 28627 |
| `tests/test_ai_synthesis_profile.py` | 89 | 66 |
| `tests/test_anchored_installation.py` | 23 | 165 |
| `tests/test_annotation_editor.py` | 23 | 1198 |
| `tests/test_annotation_route_failures.py` | 4 | 602 |
| `tests/test_api_browser.py` | 6 | 2139 |
| `tests/test_api_registration.py` | 1 | 242 |
| `tests/test_api_shared_routes.py` | 3 | 428 |
| `tests/test_atomic_commit.py` | 47 | 1060 |
| `tests/test_atomic_digest_bounds.py` | 9 | 18 |
| `tests/test_atomic_journal_paths.py` | 14 | 29 |
| `tests/test_atomic_single_io.py` | 6 | 114 |
| `tests/test_atomic_transaction_pool.py` | 8 | 136 |
| `tests/test_audio_packaging.py` | 2 | 2 |
| `tests/test_audio_profiles.py` | 24 | 2808 |
| `tests/test_audio_real_smoke.py` | 1 | 1 |
| `tests/test_build_configuration.py` | 5 | 7 |
| `tests/test_build_info.py` | 13 | 4 |
| `tests/test_build_input_bundle.py` | 5 | 53 |
| `tests/test_build_input_lock.py` | 6 | 85 |
| `tests/test_canonical_brand.py` | 8 | 3385 |
| `tests/test_capacity_admission.py` | 30 | 803 |
| `tests/test_capture_adapter.py` | 29 | 2147 |
| `tests/test_capture_guard_comparison.py` | 9 | 20 |
| `tests/test_capture_journal.py` | 38 | 1065 |
| `tests/test_capture_path_guard.py` | 13 | 29 |
| `tests/test_capture_requests.py` | 28 | 30 |
| `tests/test_capture_shell_contract.py` | 6 | 884 |
| `tests/test_capture_surface.py` | 28 | 2999 |
| `tests/test_changelog_policy.py` | 3 | 3 |
| `tests/test_classification_review.py` | 32 | 10114 |
| `tests/test_cli.py` | 9 | 123 |
| `tests/test_cli_parser_selection.py` | 6 | 6895 |
| `tests/test_component_inventory.py` | 20 | 566 |
| `tests/test_concordia_asana_s13.py` | 26 | 28691 |
| `tests/test_concordia_capture_marker_fixture.py` | 2 | 1 |
| `tests/test_concordia_connectors_s10.py` | 21 | 2311 |
| `tests/test_concordia_cpu_topology.py` | 13 | 275 |
| `tests/test_concordia_folder_s21.py` | 19 | 7744 |
| `tests/test_concordia_git_admission.py` | 3 | 536 |
| `tests/test_concordia_git_s17.py` | 37 | 46562 |
| `tests/test_concordia_gitea_s20.py` | 30 | 40064 |
| `tests/test_concordia_github_s18.py` | 32 | 26261 |
| `tests/test_concordia_gitlab_s19.py` | 27 | 41970 |
| `tests/test_concordia_gmail_recovery_s23.py` | 6 | 1670 |
| `tests/test_concordia_google_calendar_s11.py` | 11 | 9117 |
| `tests/test_concordia_icalendar_s12.py` | 30 | 7364 |
| `tests/test_concordia_inbox_transit.py` | 51 | 10230 |
| `tests/test_concordia_integrated_s23.py` | 1 | 28204 |
| `tests/test_concordia_journal_comparison.py` | 8 | 3 |
| `tests/test_concordia_kernel_native.py` | 8 | 37 |
| `tests/test_concordia_kernel_observer.py` | 19 | 119 |
| `tests/test_concordia_mirror_credential_context.py` | 9 | 4 |
| `tests/test_concordia_mirrors_s16.py` | 46 | 10715 |
| `tests/test_concordia_ocr_sources.py` | 44 | 20006 |
| `tests/test_concordia_personal_s09.py` | 2 | 18679 |
| `tests/test_concordia_productivity_intake.py` | 12 | 4573 |
| `tests/test_concordia_rsync_fixture_cleanup.py` | 6 | 12 |
| `tests/test_concordia_rsync_s22.py` | 23 | 188 |
| `tests/test_concordia_rsync_state_s22.py` | 22 | 22 |
| `tests/test_concordia_rsync_windows_diagnostics.py` | 13 | 30 |
| `tests/test_concordia_search_inputs.py` | 97 | 19069 |
| `tests/test_concordia_search_s08.py` | 54 | 8540 |
| `tests/test_concordia_task_writeback_s15.py` | 38 | 11913 |
| `tests/test_concordia_tududi_s14.py` | 28 | 29639 |
| `tests/test_concordia_ui_s07.py` | 32 | 6244 |
| `tests/test_config_decode_reuse.py` | 20 | 88 |
| `tests/test_config_inspection_reuse.py` | 11 | 135 |
| `tests/test_connector_foundation.py` | 17 | 978 |
| `tests/test_connector_lifecycle.py` | 6 | 1196 |
| `tests/test_cura_ai_completion.py` | 20 | 5940 |
| `tests/test_cura_document_decisions.py` | 6 | 3974 |
| `tests/test_cura_icons.py` | 37 | 293 |
| `tests/test_cura_legacy_maintenance_preview.py` | 9 | 1855 |
| `tests/test_cura_maintenance_activity.py` | 11 | 5562 |
| `tests/test_cura_package_resources.py` | 54 | 1998 |
| `tests/test_cura_preferences.py` | 63 | 4800 |
| `tests/test_cura_primary_upgrade.py` | 9 | 22 |
| `tests/test_cura_recovery_capacity_boundary.py` | 2 | 354 |
| `tests/test_cura_release_identity.py` | 20 | 4443 |
| `tests/test_cura_retention_recovery.py` | 12 | 2460 |
| `tests/test_cura_review_runtime.py` | 10 | 240 |
| `tests/test_cura_s09_preferences.py` | 29 | 3704 |
| `tests/test_cura_s09_tray.py` | 24 | 14 |
| `tests/test_cura_shell.py` | 12 | 12953 |
| `tests/test_cura_shell_js.py` | 3 | 241 |
| `tests/test_custodia_admission_observations.py` | 40 | 61 |
| `tests/test_custodia_authority_costs.py` | 13 | 7 |
| `tests/test_custodia_diagnostics.py` | 9 | 88 |
| `tests/test_custodia_guided_setup.py` | 45 | 1675 |
| `tests/test_custodia_language_preferences.py` | 20 | 9733 |
| `tests/test_custodia_local_file_locality.py` | 9 | 1 |
| `tests/test_custodia_model_cancellation.py` | 17 | 351 |
| `tests/test_custodia_native_download.py` | 20 | 33 |
| `tests/test_custodia_native_packaging.py` | 7 | 35 |
| `tests/test_custodia_native_sbom.py` | 7 | 52 |
| `tests/test_custodia_network_lifecycle.py` | 9 | 701 |
| `tests/test_custodia_parent_lifetime.py` | 2 | 1 |
| `tests/test_custodia_pdf_boundary.py` | 3 | 231 |
| `tests/test_custodia_preview_freshness.py` | 13 | 1375 |
| `tests/test_custodia_qualification_failures.py` | 7 | 34089 |
| `tests/test_custodia_recommendation.py` | 12 | 29 |
| `tests/test_custodia_resource_limits.py` | 10 | 1 |
| `tests/test_custodia_synthesis_recovery.py` | 7 | 6160 |
| `tests/test_custodia_windows_package.py` | 4 | 12 |
| `tests/test_dependency_governance.py` | 3 | 3 |
| `tests/test_desktop_about.py` | 66 | 14140 |
| `tests/test_deterministic_build.py` | 9 | 122 |
| `tests/test_document_bundle_limits.py` | 3 | 64 |
| `tests/test_document_bundle_validation.py` | 2 | 192 |
| `tests/test_document_bundles.py` | 5 | 885 |
| `tests/test_duplicate_assurance.py` | 7 | 2147 |
| `tests/test_duplicate_conflicts.py` | 6 | 170 |
| `tests/test_durable_scheduler.py` | 19 | 2177 |
| `tests/test_email_bundle.py` | 2 | 5 |
| `tests/test_email_canonical_validation.py` | 3 | 525 |
| `tests/test_email_containers.py` | 17 | 16 |
| `tests/test_email_contract.py` | 12 | 8 |
| `tests/test_email_jobs.py` | 13 | 1526 |
| `tests/test_email_mime.py` | 19 | 23 |
| `tests/test_email_packaging.py` | 3 | 3 |
| `tests/test_email_portability.py` | 3 | 2568 |
| `tests/test_email_real_smoke.py` | 2 | 1 |
| `tests/test_email_sources.py` | 17 | 268 |
| `tests/test_email_surfaces.py` | 3 | 463 |
| `tests/test_emendatio_activation.py` | 4 | 4 |
| `tests/test_entitas_integrated_qualification.py` | 10 | 32510 |
| `tests/test_external_folder_availability.py` | 1 | 37 |
| `tests/test_extractor_parity.py` | 3 | 313 |
| `tests/test_extractor_xlsx_images.py` | 2 | 519 |
| `tests/test_extractor_zip.py` | 6 | 123 |
| `tests/test_file_family_profiles.py` | 19 | 1528 |
| `tests/test_folder_settings.py` | 7 | 960 |
| `tests/test_folder_source_enrollment.py` | 52 | 1949 |
| `tests/test_folder_sources.py` | 15 | 2094 |
| `tests/test_google_adapter_lifecycle.py` | 6 | 144 |
| `tests/test_google_connection.py` | 54 | 10284 |
| `tests/test_google_intake_coordination.py` | 7 | 5710 |
| `tests/test_google_jobs.py` | 13 | 4685 |
| `tests/test_governed_catalogs.py` | 8 | 158 |
| `tests/test_guarded_web_transport.py` | 83 | 2447 |
| `tests/test_hierarchy_classification.py` | 12 | 1157 |
| `tests/test_inbox_operations.py` | 8 | 1708 |
| `tests/test_incremental_search_index.py` | 9 | 1408 |
| `tests/test_independent_rebuild.py` | 5 | 58 |
| `tests/test_ingestion_runs.py` | 11 | 3400 |
| `tests/test_ingestion_security.py` | 1 | 65 |
| `tests/test_installation_interfaces.py` | 6 | 1436 |
| `tests/test_installation_verification.py` | 87 | 544 |
| `tests/test_instance_lifecycle.py` | 20 | 5367 |
| `tests/test_instance_repair.py` | 33 | 17977 |
| `tests/test_instance_repair_pending.py` | 21 | 9834 |
| `tests/test_iudicium_journey.py` | 9 | 61364 |
| `tests/test_knowledge_object_activity.py` | 56 | 11857 |
| `tests/test_knowledge_object_contract.py` | 69 | 103 |
| `tests/test_knowledge_object_review.py` | 46 | 12523 |
| `tests/test_knowledge_object_review_activity.py` | 18 | 16295 |
| `tests/test_knowledge_object_services.py` | 57 | 10895 |
| `tests/test_knowledge_object_storage.py` | 43 | 25226 |
| `tests/test_local_path_guard.py` | 4 | 15 |
| `tests/test_maintenance_backup_diagnostics.py` | 26 | 1564 |
| `tests/test_maintenance_catalog.py` | 14 | 5725 |
| `tests/test_maintenance_queue_contention.py` | 15 | 4811 |
| `tests/test_maintenance_reviewed_plans.py` | 7 | 349 |
| `tests/test_manual_web_acquisition.py` | 28 | 5383 |
| `tests/test_markdown_library_viewer.py` | 11 | 3218 |
| `tests/test_mobile_retrieval.py` | 23 | 7916 |
| `tests/test_mobile_shell_contract.py` | 5 | 886 |
| `tests/test_model_read_buffer.py` | 1 | 8 |
| `tests/test_network_interfaces.py` | 3 | 692 |
| `tests/test_network_status.py` | 11 | 3 |
| `tests/test_node_conformance_lifecycle.py` | 1 | 89 |
| `tests/test_oauth_authorization.py` | 19 | 750 |
| `tests/test_object_migration_permissions.py` | 20 | 9150 |
| `tests/test_ocr_contract.py` | 28 | 48 |
| `tests/test_ocr_execution.py` | 27 | 2785 |
| `tests/test_ocr_kit.py` | 44 | 1843 |
| `tests/test_ocr_kit_release.py` | 11 | 198 |
| `tests/test_ocr_real_smoke.py` | 3 | 1 |
| `tests/test_offline_release_verifier.py` | 8 | 207 |
| `tests/test_operations_maintenance.py` | 34 | 1625 |
| `tests/test_paths.py` | 2 | 22 |
| `tests/test_perceptio_integration.py` | 6 | 4946 |
| `tests/test_photo_profiles.py` | 13 | 1863 |
| `tests/test_photo_real_smoke.py` | 1 | 1 |
| `tests/test_portable_transfer.py` | 29 | 11507 |
| `tests/test_processing_autonomy.py` | 54 | 15473 |
| `tests/test_public_roadmap.py` | 47 | 50 |
| `tests/test_publication.py` | 24 | 504 |
| `tests/test_publication_distribution.py` | 24 | 4898 |
| `tests/test_publication_updates.py` | 5 | 1439 |
| `tests/test_qualification.py` | 24 | 5503 |
| `tests/test_qualification_contract.py` | 3 | 1 |
| `tests/test_qualification_documentation.py` | 4 | 4 |
| `tests/test_qualification_real_smoke.py` | 1 | 1 |
| `tests/test_qualification_surfaces.py` | 4 | 1346 |
| `tests/test_rebuild_coordination.py` | 6 | 2629 |
| `tests/test_release_assurance.py` | 6 | 91 |
| `tests/test_release_installed.py` | 15 | 28 |
| `tests/test_release_manifest.py` | 3 | 15 |
| `tests/test_representations.py` | 27 | 2127 |
| `tests/test_resource_statistics.py` | 13 | 2393 |
| `tests/test_retention_boundaries.py` | 16 | 10428 |
| `tests/test_review_atomic_removal.py` | 12 | 297 |
| `tests/test_review_authority_observation.py` | 1 | 41 |
| `tests/test_review_decision_routes.py` | 11 | 3360 |
| `tests/test_review_documents_observation.py` | 3 | 20 |
| `tests/test_review_evidence_reads.py` | 7 | 9 |
| `tests/test_review_intake_routing.py` | 8 | 1808 |
| `tests/test_review_origin_observation.py` | 4 | 29 |
| `tests/test_review_path_observation.py` | 22 | 75 |
| `tests/test_review_placement_routing.py` | 24 | 5600 |
| `tests/test_runtime_boundaries.py` | 2 | 10 |
| `tests/test_s07_documentation.py` | 6 | 9 |
| `tests/test_scheduler_control.py` | 17 | 1976 |
| `tests/test_scheduler_cooperative_sources.py` | 4 | 1435 |
| `tests/test_scheduler_readers.py` | 3 | 292 |
| `tests/test_setup_activity.py` | 4 | 11108 |
| `tests/test_setup_coordinator.py` | 15 | 24684 |
| `tests/test_setup_qualification.py` | 1 | 7773 |
| `tests/test_setup_source_scope.py` | 4 | 291 |
| `tests/test_setup_space_name.py` | 5 | 40 |
| `tests/test_setup_trial_inputs.py` | 14 | 1272 |
| `tests/test_setup_trials.py` | 5 | 1358 |
| `tests/test_shell_settings.py` | 37 | 1432 |
| `tests/test_source_exclusion_contention.py` | 12 | 5298 |
| `tests/test_source_exclusions.py` | 47 | 1901 |
| `tests/test_source_reconciliation.py` | 17 | 5778 |
| `tests/test_startup_diagnostic_copy.py` | 21 | 2383 |
| `tests/test_startup_process.py` | 16 | 275 |
| `tests/test_startup_readiness.py` | 43 | 2935 |
| `tests/test_startup_windows.py` | 2 | 114 |
| `tests/test_transcript_documentation.py` | 3 | 3 |
| `tests/test_transcript_jobs.py` | 11 | 2869 |
| `tests/test_transcript_packaging.py` | 4 | 2 |
| `tests/test_transcript_parsers.py` | 19 | 6 |
| `tests/test_transcript_real_smoke.py` | 2 | 1 |
| `tests/test_transcript_sources.py` | 5 | 841 |
| `tests/test_transcript_surfaces.py` | 6 | 1545 |
| `tests/test_updates.py` | 28 | 881 |
| `tests/test_verify_release_bundle.py` | 7 | 233 |
| `tests/test_vertical_slice.py` | 4 | 404 |
| `tests/test_video_packaging.py` | 2 | 2 |
| `tests/test_video_profiles.py` | 14 | 1565 |
| `tests/test_video_real_smoke.py` | 1 | 1 |
| `tests/test_win32_file_api_setup.py` | 15 | 19 |
| `tests/test_windows_identity.py` | 6 | 900 |
| `tests/test_windows_json_snapshots.py` | 12 | 291 |
| `tests/test_windows_package_manifest.py` | 2 | 7 |
| `tests/test_windows_pdf_lock.py` | 9 | 14 |
| `tests/test_windows_public_baselines.py` | 3 | 1 |
| `tests/test_windows_pytest_sharding.py` | 6 | 1811 |
| `tests/test_windows_shard_costs.py` | 18 | 15 |
| `tests/test_windows_shard_timings.py` | 3 | 2573 |
