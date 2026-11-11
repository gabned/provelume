# S23 maximum observed Windows costs, 11 November 2026

Source `e3420d623f583755c84dcc51036b9b5e71255849` retains all its outcomes:
on [Core43023914820](https://github.com/gabned/provelume/actions/runs/43023914820),
attempt1 group0 fails Node preparation15s; group1 succeeds in8m08s. Its later
native Cura contract success proves recovery on another runner of the same
Windows2025/Node22.23.4 profile, without proving the failed host's cause. One full
Core retry is documented because the pinned artifact/verifier contract requires
all four shards in the same attempt. No partial-attempt evidence is mixed.

Attempt2 [group0](https://github.com/gabned/provelume/actions/runs/43023914820/job/130543504589)
PASS in7m37s; [group1](https://github.com/gabned/provelume/actions/runs/43023914820/job/130543504662)
retains CANCELLED10m despite both native shards PASS489.29/498.80s. Aggregator
130548700892 remains BLOCKED. Ubuntu130543504601 PASS6060/66/419 in589.30s;
workspace130543504502 retains preparation failure. No prior result is rewritten.

The existing module observer supplies443 complete non-failing observations for
all295 modules/6046 selected parents. The new hints use the largest actually
observed setup/call/teardown total for each module, rounded to milliseconds.
No multiplier, invented time, failed/interrupted module or test-count change is
introduced. Maxima acknowledge the observed host variation; they do not predict
future runtime or prove a cloud-host cause. All observations and their exact
decoded-log provenance remain in the local R10 record.

| Shard | Same observed maxima, old allocation | Same maxima, refreshed allocation |
| --- | ---: | ---: |
| 0 | 359.683s | 421.117s |
| 1 | 343.638s | 421.121s |
| 2 | 486.379s | 421.123s |
| 3 | 494.782s | 421.121s |

This replay uses placeholder labels only for counts. Native parent/subtest
identity, complete disjoint coverage and outcome verification remain with the
unchanged native verifier. The allocator AST is identical after removing only
the hint assignment. Count fallback, every collected test, four workers/two
groups, native540s/job10m, upload/cleanup, all workflows, pin/Protocol source and
every gate remain unchanged. Earlier timing documents remain unchanged.

The separate Gitea installed-fixture `gitea_fixture_interruption` is a failure
of the intentionally interrupted private publication check, not evidence that
the server failed to start. The previous diagnostic concealed its original
error code. Additional closed context now retains a recognized prior code and
stage while keeping UNKNOWN/failure2 and the original predicates. No backend
message, raw credential output or private path is added. The original cause
remains NOT_DEMONSTRATED until a fresh observation establishes it.

Independent Actions artifact verification stays BLOCKED_BY_MAINTAINER/NOT_WAIVED.
Decoded logs/API metadata only; no Actions ZIP downloaded. All R4–R9, original
BIND S07 and findings remain unchanged. No S07 experiment, merge, release,
publication or intermediate PC installation follows. New-head qualification
is mandatory; neither native PASS nor this replay overrides a cancelled job.

## Exact maximum observations used

| Module | Selected/completed parents | Rounded maximum milliseconds | Decoded source log |
| --- | ---: | ---: | --- |
| `tests/test_action_center_adapters.py` | 43 | 14817 | `windows-group1-e3420d6-a2.log` |
| `tests/test_action_center_model.py` | 37 | 3928 | `windows-group1-e3420d6-a2.log` |
| `tests/test_action_center_routes.py` | 9 | 9518 | `windows-group1-e3420d6-a2.log` |
| `tests/test_action_notifications.py` | 65 | 825 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_consumer.py` | 60 | 70992 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_consumer_scope.py` | 37 | 90 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_transfer.py` | 38 | 91263 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_2.py` | 15 | 132860 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_2_1.py` | 47 | 189 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4.py` | 21 | 14 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4_1.py` | 65 | 819 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4_1_slice_issue_transition.py` | 16 | 133 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4_2_ops.py` | 247 | 11513 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4_7.py` | 63 | 594 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_v1_4_9.py` | 14 | 1325 | `windows-group0-e3420d6-a2.log` |
| `tests/test_agent_protocol_work_check.py` | 36 | 6858 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_work_recovery.py` | 38 | 71606 | `windows-group1-e3420d6-a2.log` |
| `tests/test_agent_protocol_work_source.py` | 37 | 15 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_classification_evaluation.py` | 60 | 451 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_classification_proposals.py` | 39 | 18361 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_classification_request.py` | 22 | 6737 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_classification_targets.py` | 33 | 2752 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_context.py` | 90 | 613 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_gateway.py` | 94 | 612 | `windows-group1-e3420d6-a1.log` |
| `tests/test_ai_jobs.py` | 25 | 6420 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_jobs_boundaries.py` | 26 | 10362 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_jobs_controls.py` | 29 | 2199 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_llama_prefix.py` | 21 | 16 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_llama_wait.py` | 5 | 2 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_model_download.py` | 42 | 89 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_model_progress_js.py` | 1 | 566 | `windows-group1-e3420d6-a1.log` |
| `tests/test_ai_models.py` | 95 | 1426 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_provider.py` | 105 | 4636 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_runtime.py` | 82 | 5030 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_runtime_cpu.py` | 24 | 20 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_runtime_warm_qualification.py` | 28 | 30 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ai_setup.py` | 63 | 16369 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_synthesis.py` | 69 | 21824 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ai_synthesis_profile.py` | 89 | 75 | `windows-group0-e3420d6-a2.log` |
| `tests/test_anchored_installation.py` | 23 | 121 | `windows-group0-e3420d6-a2.log` |
| `tests/test_annotation_editor.py` | 23 | 1826 | `windows-group0-e3420d6-a2.log` |
| `tests/test_annotation_route_failures.py` | 4 | 606 | `windows-group0-e3420d6-a2.log` |
| `tests/test_api_browser.py` | 6 | 3025 | `windows-group0-e3420d6-a2.log` |
| `tests/test_api_registration.py` | 1 | 383 | `windows-group0-e3420d6-a2.log` |
| `tests/test_api_shared_routes.py` | 3 | 328 | `windows-group0-e3420d6-a2.log` |
| `tests/test_atomic_commit.py` | 47 | 749 | `windows-group0-e3420d6-a2.log` |
| `tests/test_atomic_digest_bounds.py` | 9 | 26 | `windows-group1-e3420d6-a2.log` |
| `tests/test_atomic_journal_paths.py` | 14 | 19 | `windows-group0-e3420d6-a2.log` |
| `tests/test_atomic_single_io.py` | 6 | 174 | `windows-group1-e3420d6-a2.log` |
| `tests/test_atomic_transaction_pool.py` | 8 | 172 | `windows-group0-e3420d6-a2.log` |
| `tests/test_audio_packaging.py` | 2 | 3 | `windows-group1-e3420d6-a2.log` |
| `tests/test_audio_profiles.py` | 24 | 2740 | `windows-group1-e3420d6-a2.log` |
| `tests/test_audio_real_smoke.py` | 1 | 1 | `windows-group0-e3420d6-a2.log` |
| `tests/test_build_configuration.py` | 5 | 6 | `windows-group0-e3420d6-a2.log` |
| `tests/test_build_info.py` | 13 | 7 | `windows-group0-e3420d6-a2.log` |
| `tests/test_build_input_bundle.py` | 5 | 39 | `windows-group0-e3420d6-a2.log` |
| `tests/test_build_input_lock.py` | 6 | 64 | `windows-group0-e3420d6-a2.log` |
| `tests/test_canonical_brand.py` | 8 | 2785 | `windows-group1-e3420d6-a2.log` |
| `tests/test_capacity_admission.py` | 30 | 469 | `windows-group0-e3420d6-a2.log` |
| `tests/test_capture_adapter.py` | 29 | 2490 | `windows-group0-e3420d6-a2.log` |
| `tests/test_capture_guard_comparison.py` | 9 | 21 | `windows-group1-e3420d6-a2.log` |
| `tests/test_capture_journal.py` | 38 | 2117 | `windows-group1-e3420d6-a2.log` |
| `tests/test_capture_path_guard.py` | 13 | 17 | `windows-group0-e3420d6-a2.log` |
| `tests/test_capture_requests.py` | 28 | 26 | `windows-group1-e3420d6-a2.log` |
| `tests/test_capture_shell_contract.py` | 6 | 829 | `windows-group1-e3420d6-a2.log` |
| `tests/test_capture_surface.py` | 28 | 3709 | `windows-group0-e3420d6-a2.log` |
| `tests/test_changelog_policy.py` | 3 | 5 | `windows-group1-e3420d6-a2.log` |
| `tests/test_classification_review.py` | 32 | 12264 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cli.py` | 9 | 104 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cli_parser_selection.py` | 6 | 7664 | `windows-group1-e3420d6-a2.log` |
| `tests/test_component_inventory.py` | 20 | 1331 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_asana_s13.py` | 26 | 34582 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_capture_marker_fixture.py` | 2 | 1 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_connectors_s10.py` | 21 | 1959 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_cpu_topology.py` | 13 | 189 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_folder_s21.py` | 19 | 9033 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_git_admission.py` | 3 | 863 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_git_s17.py` | 37 | 48533 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_gitea_s20.py` | 32 | 38809 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_github_s18.py` | 32 | 42488 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_gitlab_s19.py` | 27 | 42356 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_gmail_recovery_s23.py` | 6 | 3078 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_google_calendar_s11.py` | 11 | 10301 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_icalendar_s12.py` | 30 | 8847 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_inbox_transit.py` | 51 | 19282 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_integrated_s23.py` | 1 | 34069 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_journal_comparison.py` | 8 | 3 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_kernel_native.py` | 8 | 37 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_kernel_observer.py` | 19 | 74 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_mirror_credential_context.py` | 9 | 8 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_mirrors_s16.py` | 46 | 7925 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_ocr_sources.py` | 44 | 23749 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_personal_s09.py` | 2 | 27275 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_productivity_intake.py` | 12 | 5693 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_rsync_fixture_cleanup.py` | 6 | 10 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_rsync_s22.py` | 23 | 200 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_rsync_state_s22.py` | 22 | 26 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_rsync_windows_diagnostics.py` | 13 | 32 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_search_inputs.py` | 97 | 23933 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_search_s08.py` | 54 | 10790 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_task_writeback_s15.py` | 38 | 14598 | `windows-group0-e3420d6-a2.log` |
| `tests/test_concordia_tududi_s14.py` | 28 | 64342 | `windows-group1-e3420d6-a2.log` |
| `tests/test_concordia_ui_s07.py` | 32 | 5083 | `windows-group0-e3420d6-a2.log` |
| `tests/test_config_decode_reuse.py` | 20 | 102 | `windows-group1-e3420d6-a2.log` |
| `tests/test_config_inspection_reuse.py` | 11 | 326 | `windows-group1-e3420d6-a2.log` |
| `tests/test_connector_foundation.py` | 17 | 1233 | `windows-group1-e3420d6-a2.log` |
| `tests/test_connector_lifecycle.py` | 6 | 845 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_ai_completion.py` | 20 | 7342 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_document_decisions.py` | 6 | 3531 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_icons.py` | 37 | 643 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_legacy_maintenance_preview.py` | 9 | 2310 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_maintenance_activity.py` | 11 | 5490 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_package_resources.py` | 54 | 3034 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_preferences.py` | 63 | 5685 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_primary_upgrade.py` | 9 | 29 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_recovery_capacity_boundary.py` | 2 | 822 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_release_identity.py` | 20 | 5687 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_retention_recovery.py` | 12 | 5976 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_review_runtime.py` | 10 | 377 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_s09_preferences.py` | 29 | 5077 | `windows-group0-e3420d6-a2.log` |
| `tests/test_cura_s09_tray.py` | 24 | 30 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_shell.py` | 12 | 13788 | `windows-group1-e3420d6-a2.log` |
| `tests/test_cura_shell_js.py` | 3 | 203 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_admission_observations.py` | 40 | 87 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_authority_costs.py` | 13 | 10 | `windows-group1-e3420d6-a1.log` |
| `tests/test_custodia_diagnostics.py` | 9 | 95 | `windows-group1-e3420d6-a1.log` |
| `tests/test_custodia_guided_setup.py` | 45 | 2401 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_language_preferences.py` | 20 | 7777 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_local_file_locality.py` | 9 | 3 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_model_cancellation.py` | 17 | 266 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_native_download.py` | 20 | 63 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_native_packaging.py` | 7 | 45 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_native_sbom.py` | 7 | 80 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_network_lifecycle.py` | 9 | 979 | `windows-group1-e3420d6-a2.log` |
| `tests/test_custodia_parent_lifetime.py` | 2 | 1 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_pdf_boundary.py` | 3 | 191 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_preview_freshness.py` | 13 | 1752 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_qualification_failures.py` | 7 | 31604 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_recommendation.py` | 12 | 27 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_resource_limits.py` | 10 | 2 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_synthesis_recovery.py` | 7 | 8028 | `windows-group0-e3420d6-a2.log` |
| `tests/test_custodia_windows_package.py` | 4 | 11 | `windows-group0-e3420d6-a2.log` |
| `tests/test_dependency_governance.py` | 3 | 3 | `windows-group1-e3420d6-a2.log` |
| `tests/test_desktop_about.py` | 66 | 11398 | `windows-group0-e3420d6-a2.log` |
| `tests/test_deterministic_build.py` | 9 | 148 | `windows-group1-e3420d6-a2.log` |
| `tests/test_document_bundle_limits.py` | 3 | 82 | `windows-group0-e3420d6-a2.log` |
| `tests/test_document_bundle_validation.py` | 2 | 1159 | `windows-group1-e3420d6-a1.log` |
| `tests/test_document_bundles.py` | 5 | 720 | `windows-group0-e3420d6-a2.log` |
| `tests/test_duplicate_assurance.py` | 7 | 1782 | `windows-group1-e3420d6-a2.log` |
| `tests/test_duplicate_conflicts.py` | 6 | 222 | `windows-group0-e3420d6-a2.log` |
| `tests/test_durable_scheduler.py` | 19 | 2355 | `windows-group0-e3420d6-a2.log` |
| `tests/test_email_bundle.py` | 2 | 3 | `windows-group0-e3420d6-a2.log` |
| `tests/test_email_canonical_validation.py` | 3 | 707 | `windows-group0-e3420d6-a2.log` |
| `tests/test_email_containers.py` | 17 | 26 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_contract.py` | 12 | 9 | `windows-group0-e3420d6-a2.log` |
| `tests/test_email_jobs.py` | 13 | 3020 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_mime.py` | 19 | 52 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_packaging.py` | 3 | 2 | `windows-group0-e3420d6-a2.log` |
| `tests/test_email_portability.py` | 3 | 3083 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_real_smoke.py` | 2 | 1 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_sources.py` | 17 | 593 | `windows-group1-e3420d6-a2.log` |
| `tests/test_email_surfaces.py` | 3 | 532 | `windows-group0-e3420d6-a2.log` |
| `tests/test_emendatio_activation.py` | 4 | 5 | `windows-group0-e3420d6-a2.log` |
| `tests/test_entitas_integrated_qualification.py` | 10 | 22183 | `windows-group0-e3420d6-a2.log` |
| `tests/test_external_folder_availability.py` | 1 | 71 | `windows-group1-e3420d6-a2.log` |
| `tests/test_extractor_parity.py` | 3 | 414 | `windows-group1-e3420d6-a2.log` |
| `tests/test_extractor_xlsx_images.py` | 2 | 325 | `windows-group0-e3420d6-a2.log` |
| `tests/test_extractor_zip.py` | 6 | 266 | `windows-group1-e3420d6-a2.log` |
| `tests/test_file_family_profiles.py` | 19 | 1641 | `windows-group0-e3420d6-a2.log` |
| `tests/test_folder_settings.py` | 7 | 933 | `windows-group1-e3420d6-a2.log` |
| `tests/test_folder_source_enrollment.py` | 52 | 1282 | `windows-group0-e3420d6-a2.log` |
| `tests/test_folder_sources.py` | 15 | 2428 | `windows-group0-e3420d6-a2.log` |
| `tests/test_git_process_wakeup.py` | 8 | 15 | `windows-group1-e3420d6-a2.log` |
| `tests/test_google_adapter_lifecycle.py` | 6 | 184 | `windows-group0-e3420d6-a2.log` |
| `tests/test_google_connection.py` | 54 | 10880 | `windows-group1-e3420d6-a2.log` |
| `tests/test_google_intake_coordination.py` | 7 | 3767 | `windows-group0-e3420d6-a2.log` |
| `tests/test_google_jobs.py` | 13 | 2851 | `windows-group0-e3420d6-a2.log` |
| `tests/test_governed_catalogs.py` | 8 | 207 | `windows-group0-e3420d6-a2.log` |
| `tests/test_guarded_web_transport.py` | 83 | 6256 | `windows-group1-e3420d6-a2.log` |
| `tests/test_hierarchy_classification.py` | 12 | 1665 | `windows-group0-e3420d6-a2.log` |
| `tests/test_inbox_operations.py` | 8 | 1771 | `windows-group1-e3420d6-a2.log` |
| `tests/test_incremental_search_index.py` | 9 | 893 | `windows-group0-e3420d6-a2.log` |
| `tests/test_independent_rebuild.py` | 5 | 50 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ingestion_runs.py` | 11 | 3558 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ingestion_security.py` | 1 | 31 | `windows-group0-e3420d6-a2.log` |
| `tests/test_installation_interfaces.py` | 6 | 897 | `windows-group1-e3420d6-a2.log` |
| `tests/test_installation_verification.py` | 87 | 685 | `windows-group1-e3420d6-a2.log` |
| `tests/test_instance_lifecycle.py` | 20 | 3750 | `windows-group0-e3420d6-a2.log` |
| `tests/test_instance_repair.py` | 33 | 13264 | `windows-group0-e3420d6-a2.log` |
| `tests/test_instance_repair_pending.py` | 21 | 15253 | `windows-group1-e3420d6-a2.log` |
| `tests/test_iudicium_journey.py` | 9 | 68054 | `windows-group1-e3420d6-a2.log` |
| `tests/test_knowledge_object_activity.py` | 56 | 23228 | `windows-group1-e3420d6-a2.log` |
| `tests/test_knowledge_object_contract.py` | 69 | 122 | `windows-group1-e3420d6-a2.log` |
| `tests/test_knowledge_object_review.py` | 46 | 15899 | `windows-group0-e3420d6-a2.log` |
| `tests/test_knowledge_object_review_activity.py` | 18 | 16502 | `windows-group1-e3420d6-a2.log` |
| `tests/test_knowledge_object_services.py` | 57 | 8360 | `windows-group0-e3420d6-a2.log` |
| `tests/test_knowledge_object_storage.py` | 43 | 18213 | `windows-group0-e3420d6-a2.log` |
| `tests/test_local_path_guard.py` | 4 | 16 | `windows-group0-e3420d6-a2.log` |
| `tests/test_maintenance_backup_diagnostics.py` | 26 | 1869 | `windows-group1-e3420d6-a2.log` |
| `tests/test_maintenance_catalog.py` | 14 | 4166 | `windows-group0-e3420d6-a2.log` |
| `tests/test_maintenance_queue_contention.py` | 15 | 6301 | `windows-group1-e3420d6-a1.log` |
| `tests/test_maintenance_reviewed_plans.py` | 7 | 427 | `windows-group0-e3420d6-a2.log` |
| `tests/test_manual_web_acquisition.py` | 28 | 3706 | `windows-group0-e3420d6-a2.log` |
| `tests/test_markdown_library_viewer.py` | 11 | 8234 | `windows-group1-e3420d6-a2.log` |
| `tests/test_mobile_retrieval.py` | 23 | 5105 | `windows-group0-e3420d6-a2.log` |
| `tests/test_mobile_shell_contract.py` | 5 | 1187 | `windows-group0-e3420d6-a2.log` |
| `tests/test_model_read_buffer.py` | 1 | 11 | `windows-group1-e3420d6-a2.log` |
| `tests/test_network_interfaces.py` | 3 | 718 | `windows-group0-e3420d6-a2.log` |
| `tests/test_network_status.py` | 11 | 3 | `windows-group0-e3420d6-a2.log` |
| `tests/test_node_conformance_lifecycle.py` | 1 | 75 | `windows-group1-e3420d6-a2.log` |
| `tests/test_oauth_authorization.py` | 19 | 900 | `windows-group0-e3420d6-a2.log` |
| `tests/test_object_migration_permissions.py` | 20 | 6425 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ocr_contract.py` | 28 | 21 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ocr_execution.py` | 27 | 4656 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ocr_kit.py` | 44 | 2010 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ocr_kit_release.py` | 11 | 235 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ocr_real_smoke.py` | 3 | 1 | `windows-group0-e3420d6-a2.log` |
| `tests/test_offline_release_verifier.py` | 8 | 285 | `windows-group1-e3420d6-a2.log` |
| `tests/test_operations_maintenance.py` | 34 | 1213 | `windows-group0-e3420d6-a2.log` |
| `tests/test_paths.py` | 2 | 28 | `windows-group1-e3420d6-a2.log` |
| `tests/test_perceptio_integration.py` | 6 | 3216 | `windows-group0-e3420d6-a2.log` |
| `tests/test_photo_profiles.py` | 13 | 2551 | `windows-group0-e3420d6-a2.log` |
| `tests/test_photo_real_smoke.py` | 1 | 1 | `windows-group0-e3420d6-a2.log` |
| `tests/test_portable_transfer.py` | 29 | 25610 | `windows-group1-e3420d6-a2.log` |
| `tests/test_processing_autonomy.py` | 54 | 18335 | `windows-group1-e3420d6-a2.log` |
| `tests/test_public_roadmap.py` | 47 | 97 | `windows-group1-e3420d6-a1.log` |
| `tests/test_publication.py` | 24 | 527 | `windows-group0-e3420d6-a2.log` |
| `tests/test_publication_distribution.py` | 24 | 4019 | `windows-group1-e3420d6-a2.log` |
| `tests/test_publication_updates.py` | 5 | 1264 | `windows-group1-e3420d6-a2.log` |
| `tests/test_qualification.py` | 24 | 7913 | `windows-group1-e3420d6-a2.log` |
| `tests/test_qualification_contract.py` | 3 | 2 | `windows-group0-e3420d6-a2.log` |
| `tests/test_qualification_documentation.py` | 4 | 11 | `windows-group1-e3420d6-a1.log` |
| `tests/test_qualification_real_smoke.py` | 1 | 1 | `windows-group1-e3420d6-a1.log` |
| `tests/test_qualification_surfaces.py` | 4 | 898 | `windows-group0-e3420d6-a2.log` |
| `tests/test_rebuild_coordination.py` | 6 | 1903 | `windows-group0-e3420d6-a2.log` |
| `tests/test_release_assurance.py` | 6 | 62 | `windows-group0-e3420d6-a2.log` |
| `tests/test_release_installed.py` | 15 | 24 | `windows-group0-e3420d6-a2.log` |
| `tests/test_release_manifest.py` | 3 | 13 | `windows-group1-e3420d6-a1.log` |
| `tests/test_representations.py` | 27 | 2449 | `windows-group0-e3420d6-a2.log` |
| `tests/test_resource_statistics.py` | 13 | 1179 | `windows-group0-e3420d6-a2.log` |
| `tests/test_retention_boundaries.py` | 16 | 12947 | `windows-group1-e3420d6-a2.log` |
| `tests/test_review_atomic_removal.py` | 12 | 294 | `windows-group1-e3420d6-a2.log` |
| `tests/test_review_authority_observation.py` | 1 | 60 | `windows-group1-e3420d6-a1.log` |
| `tests/test_review_decision_routes.py` | 11 | 6373 | `windows-group1-e3420d6-a1.log` |
| `tests/test_review_documents_observation.py` | 3 | 42 | `windows-group1-e3420d6-a2.log` |
| `tests/test_review_evidence_reads.py` | 7 | 10 | `windows-group0-e3420d6-a2.log` |
| `tests/test_review_intake_routing.py` | 8 | 3549 | `windows-group1-e3420d6-a2.log` |
| `tests/test_review_origin_observation.py` | 4 | 37 | `windows-group0-e3420d6-a2.log` |
| `tests/test_review_path_observation.py` | 22 | 94 | `windows-group0-e3420d6-a2.log` |
| `tests/test_review_placement_routing.py` | 24 | 5776 | `windows-group1-e3420d6-a2.log` |
| `tests/test_runtime_boundaries.py` | 2 | 29 | `windows-group1-e3420d6-a1.log` |
| `tests/test_s07_documentation.py` | 6 | 11 | `windows-group1-e3420d6-a2.log` |
| `tests/test_scheduler_control.py` | 17 | 4838 | `windows-group1-e3420d6-a2.log` |
| `tests/test_scheduler_cooperative_sources.py` | 4 | 907 | `windows-group0-e3420d6-a2.log` |
| `tests/test_scheduler_readers.py` | 3 | 302 | `windows-group1-e3420d6-a2.log` |
| `tests/test_setup_activity.py` | 4 | 14250 | `windows-group0-e3420d6-a2.log` |
| `tests/test_setup_coordinator.py` | 15 | 30553 | `windows-group1-e3420d6-a2.log` |
| `tests/test_setup_qualification.py` | 1 | 9562 | `windows-group1-e3420d6-a2.log` |
| `tests/test_setup_source_scope.py` | 4 | 709 | `windows-group1-e3420d6-a2.log` |
| `tests/test_setup_space_name.py` | 5 | 69 | `windows-group1-e3420d6-a2.log` |
| `tests/test_setup_trial_inputs.py` | 14 | 888 | `windows-group0-e3420d6-a2.log` |
| `tests/test_setup_trials.py` | 5 | 3159 | `windows-group1-e3420d6-a2.log` |
| `tests/test_shell_settings.py` | 37 | 2168 | `windows-group1-e3420d6-a2.log` |
| `tests/test_source_exclusion_contention.py` | 12 | 3374 | `windows-group0-e3420d6-a2.log` |
| `tests/test_source_exclusions.py` | 47 | 4246 | `windows-group1-e3420d6-a2.log` |
| `tests/test_source_reconciliation.py` | 17 | 8686 | `windows-group1-e3420d6-a2.log` |
| `tests/test_ssh_agent_completion_diagnostics.py` | 5 | 5 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ssh_agent_report_commit.py` | 6 | 50 | `windows-group0-e3420d6-a2.log` |
| `tests/test_ssh_agent_windows_io_completion.py` | 5 | 4 | `windows-group1-e3420d6-a2.log` |
| `tests/test_startup_diagnostic_copy.py` | 21 | 3798 | `windows-group1-e3420d6-a1.log` |
| `tests/test_startup_process.py` | 16 | 279 | `windows-group0-e3420d6-a2.log` |
| `tests/test_startup_readiness.py` | 43 | 2200 | `windows-group0-e3420d6-a2.log` |
| `tests/test_startup_windows.py` | 2 | 83 | `windows-group0-e3420d6-a2.log` |
| `tests/test_transcript_documentation.py` | 3 | 4 | `windows-group1-e3420d6-a2.log` |
| `tests/test_transcript_jobs.py` | 11 | 3585 | `windows-group0-e3420d6-a2.log` |
| `tests/test_transcript_packaging.py` | 4 | 3 | `windows-group0-e3420d6-a2.log` |
| `tests/test_transcript_parsers.py` | 19 | 16 | `windows-group1-e3420d6-a2.log` |
| `tests/test_transcript_real_smoke.py` | 2 | 1 | `windows-group1-e3420d6-a2.log` |
| `tests/test_transcript_sources.py` | 5 | 1073 | `windows-group1-e3420d6-a2.log` |
| `tests/test_transcript_surfaces.py` | 6 | 3673 | `windows-group1-e3420d6-a2.log` |
| `tests/test_updates.py` | 28 | 1610 | `windows-group1-e3420d6-a2.log` |
| `tests/test_verify_release_bundle.py` | 7 | 165 | `windows-group1-e3420d6-a2.log` |
| `tests/test_vertical_slice.py` | 4 | 233 | `windows-group0-e3420d6-a2.log` |
| `tests/test_video_packaging.py` | 2 | 2 | `windows-group1-e3420d6-a2.log` |
| `tests/test_video_profiles.py` | 14 | 1709 | `windows-group1-e3420d6-a2.log` |
| `tests/test_video_real_smoke.py` | 1 | 1 | `windows-group1-e3420d6-a2.log` |
| `tests/test_win32_file_api_setup.py` | 15 | 11 | `windows-group0-e3420d6-a2.log` |
| `tests/test_windows_identity.py` | 6 | 996 | `windows-group1-e3420d6-a2.log` |
| `tests/test_windows_json_snapshots.py` | 12 | 241 | `windows-group0-e3420d6-a2.log` |
| `tests/test_windows_package_manifest.py` | 2 | 6 | `windows-group0-e3420d6-a2.log` |
| `tests/test_windows_pdf_lock.py` | 9 | 6 | `windows-group0-e3420d6-a2.log` |
| `tests/test_windows_public_baselines.py` | 3 | 2 | `windows-group1-e3420d6-a2.log` |
| `tests/test_windows_pytest_sharding.py` | 6 | 3464 | `windows-group1-e3420d6-a2.log` |
| `tests/test_windows_shard_costs.py` | 18 | 10 | `windows-group0-e3420d6-a2.log` |
| `tests/test_windows_shard_timings.py` | 3 | 4658 | `windows-group1-e3420d6-a2.log` |
