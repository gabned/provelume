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
DEFAULT_SHARD_TIMEOUT_SECONDS = 480
MIN_SHARD_TIMEOUT_SECONDS = 60
MAX_SHARD_TIMEOUT_SECONDS = 480
MAX_REPLAY_BYTES = 2 * 1024 * 1024
CHILD_ENV = "PROVELUME_WINDOWS_SHARD_CHILD"
FORCE_ENV = "PROVELUME_WINDOWS_SHARD_FORCE"
DISABLE_ENV = "PROVELUME_WINDOWS_SHARD_DISABLE"

# Relative allocation hints from the complete successful accepted-main Windows
# run 35498405366 (job 106045602773), commit 84b94a18dd99c4504543140e7f9656004056be04.
# Costs are rounded milliseconds across setup/call/teardown for all 160 complete,
# non-failing modules. Count mismatches and new modules retain the count fallback.
# These hints are allocation data only, never execution budgets or qualification.
# Provenance and unchanged gate inventory: docs/qualification/windows-ci-20260922.md.
_COUNT_COST = 1000
_MODULE_COST_HINTS = (
    ("tests/test_action_center_adapters.py", 43, 61150),
    ("tests/test_action_center_model.py", 37, 27514),
    ("tests/test_action_center_routes.py", 9, 24534),
    ("tests/test_action_notifications.py", 65, 2969),
    ("tests/test_agent_protocol_v1_2.py", 11, 60672),
    ("tests/test_agent_protocol_v1_2_1.py", 21, 37),
    ("tests/test_agent_protocol_v1_4.py", 21, 18),
    ("tests/test_agent_protocol_v1_4_1.py", 65, 1466),
    ("tests/test_agent_protocol_v1_4_1_slice_issue_transition.py", 16, 224),
    ("tests/test_agent_protocol_v1_4_2_ops.py", 223, 11811),
    ("tests/test_agent_protocol_v1_4_7.py", 57, 614),
    ("tests/test_agent_protocol_work_check.py", 17, 5448),
    ("tests/test_agent_protocol_work_recovery.py", 33, 30114),
    ("tests/test_agent_protocol_work_source.py", 37, 23),
    ("tests/test_anchored_installation.py", 23, 645),
    ("tests/test_annotation_editor.py", 23, 17041),
    ("tests/test_annotation_route_failures.py", 4, 5116),
    ("tests/test_api_browser.py", 4, 7328),
    ("tests/test_atomic_commit.py", 19, 2730),
    ("tests/test_audio_packaging.py", 2, 4),
    ("tests/test_audio_profiles.py", 24, 11369),
    ("tests/test_audio_real_smoke.py", 1, 1),
    ("tests/test_build_configuration.py", 5, 14),
    ("tests/test_build_info.py", 13, 13),
    ("tests/test_build_input_bundle.py", 5, 193),
    ("tests/test_build_input_lock.py", 6, 259),
    ("tests/test_canonical_brand.py", 8, 4006),
    ("tests/test_capacity_admission.py", 30, 3814),
    ("tests/test_changelog_policy.py", 3, 4),
    ("tests/test_cli.py", 9, 865),
    ("tests/test_cli_parser_selection.py", 6, 6900),
    ("tests/test_component_inventory.py", 15, 1545),
    ("tests/test_config_decode_reuse.py", 20, 398),
    ("tests/test_config_inspection_reuse.py", 11, 1109),
    ("tests/test_connector_foundation.py", 17, 8290),
    ("tests/test_connector_lifecycle.py", 5, 5318),
    ("tests/test_cura_document_decisions.py", 6, 11581),
    ("tests/test_cura_icons.py", 37, 1498),
    ("tests/test_cura_legacy_maintenance_preview.py", 9, 9910),
    ("tests/test_cura_maintenance_activity.py", 11, 15058),
    ("tests/test_cura_package_resources.py", 36, 4084),
    ("tests/test_cura_preferences.py", 63, 15008),
    ("tests/test_cura_recovery_capacity_boundary.py", 2, 4124),
    ("tests/test_cura_retention_recovery.py", 12, 28366),
    ("tests/test_cura_review_runtime.py", 10, 4278),
    ("tests/test_cura_shell.py", 12, 35778),
    ("tests/test_cura_shell_js.py", 1, 5378),
    ("tests/test_dependency_governance.py", 3, 6),
    ("tests/test_desktop_about.py", 27, 7368),
    ("tests/test_deterministic_build.py", 9, 240),
    ("tests/test_document_bundle_limits.py", 3, 1127),
    ("tests/test_document_bundle_validation.py", 2, 1863),
    ("tests/test_document_bundles.py", 5, 8288),
    ("tests/test_duplicate_assurance.py", 7, 19580),
    ("tests/test_duplicate_conflicts.py", 6, 2878),
    ("tests/test_durable_scheduler.py", 19, 14417),
    ("tests/test_email_bundle.py", 2, 4),
    ("tests/test_email_canonical_validation.py", 3, 6042),
    ("tests/test_email_containers.py", 17, 57),
    ("tests/test_email_contract.py", 12, 71),
    ("tests/test_email_jobs.py", 13, 19061),
    ("tests/test_email_mime.py", 19, 62),
    ("tests/test_email_packaging.py", 3, 3),
    ("tests/test_email_portability.py", 3, 13566),
    ("tests/test_email_real_smoke.py", 2, 1),
    ("tests/test_email_sources.py", 17, 2896),
    ("tests/test_email_surfaces.py", 3, 3282),
    ("tests/test_emendatio_activation.py", 4, 9),
    ("tests/test_external_folder_availability.py", 1, 402),
    ("tests/test_extractor_parity.py", 3, 3806),
    ("tests/test_extractor_xlsx_images.py", 2, 2456),
    ("tests/test_extractor_zip.py", 6, 3185),
    ("tests/test_file_family_profiles.py", 19, 9072),
    ("tests/test_folder_settings.py", 7, 5473),
    ("tests/test_folder_source_enrollment.py", 52, 10745),
    ("tests/test_folder_sources.py", 15, 24437),
    ("tests/test_google_adapter_lifecycle.py", 6, 2011),
    ("tests/test_google_connection.py", 53, 62661),
    ("tests/test_google_intake_coordination.py", 7, 36682),
    ("tests/test_google_jobs.py", 13, 21724),
    ("tests/test_guarded_web_transport.py", 83, 41523),
    ("tests/test_hierarchy_classification.py", 12, 20513),
    ("tests/test_inbox_operations.py", 8, 8016),
    ("tests/test_incremental_search_index.py", 6, 12308),
    ("tests/test_independent_rebuild.py", 5, 285),
    ("tests/test_ingestion_runs.py", 8, 8884),
    ("tests/test_ingestion_security.py", 1, 384),
    ("tests/test_installation_interfaces.py", 5, 1844),
    ("tests/test_installation_verification.py", 80, 1740),
    ("tests/test_instance_lifecycle.py", 19, 19603),
    ("tests/test_instance_repair.py", 33, 78645),
    ("tests/test_instance_repair_pending.py", 21, 66151),
    ("tests/test_maintenance_backup_diagnostics.py", 26, 9668),
    ("tests/test_maintenance_catalog.py", 14, 53498),
    ("tests/test_maintenance_queue_contention.py", 15, 9702),
    ("tests/test_maintenance_reviewed_plans.py", 7, 10462),
    ("tests/test_manual_web_acquisition.py", 27, 35559),
    ("tests/test_markdown_library_viewer.py", 10, 19621),
    ("tests/test_network_interfaces.py", 3, 1817),
    ("tests/test_network_status.py", 11, 7),
    ("tests/test_oauth_authorization.py", 19, 14890),
    ("tests/test_ocr_contract.py", 28, 162),
    ("tests/test_ocr_execution.py", 25, 21625),
    ("tests/test_ocr_real_smoke.py", 1, 1),
    ("tests/test_offline_release_verifier.py", 8, 757),
    ("tests/test_operations_maintenance.py", 29, 6546),
    ("tests/test_paths.py", 2, 220),
    ("tests/test_perceptio_integration.py", 6, 29475),
    ("tests/test_photo_profiles.py", 13, 12750),
    ("tests/test_photo_real_smoke.py", 1, 1),
    ("tests/test_portable_transfer.py", 29, 98189),
    ("tests/test_public_roadmap.py", 47, 117),
    ("tests/test_publication.py", 24, 2650),
    ("tests/test_publication_distribution.py", 24, 9003),
    ("tests/test_publication_updates.py", 5, 2451),
    ("tests/test_qualification.py", 24, 56465),
    ("tests/test_qualification_contract.py", 3, 4),
    ("tests/test_qualification_documentation.py", 4, 7),
    ("tests/test_qualification_real_smoke.py", 1, 1),
    ("tests/test_qualification_surfaces.py", 4, 8627),
    ("tests/test_rebuild_coordination.py", 6, 8883),
    ("tests/test_release_assurance.py", 6, 227),
    ("tests/test_release_manifest.py", 3, 69),
    ("tests/test_representations.py", 27, 21119),
    ("tests/test_resource_statistics.py", 13, 7668),
    ("tests/test_retention_boundaries.py", 16, 35673),
    ("tests/test_review_authority_observation.py", 1, 293),
    ("tests/test_review_decision_routes.py", 11, 15983),
    ("tests/test_review_documents_observation.py", 3, 322),
    ("tests/test_review_evidence_reads.py", 7, 40),
    ("tests/test_review_intake_routing.py", 8, 15359),
    ("tests/test_review_origin_observation.py", 4, 436),
    ("tests/test_review_path_observation.py", 22, 300),
    ("tests/test_review_placement_routing.py", 23, 29239),
    ("tests/test_runtime_boundaries.py", 2, 17),
    ("tests/test_s07_documentation.py", 6, 9),
    ("tests/test_scheduler_control.py", 17, 51561),
    ("tests/test_scheduler_cooperative_sources.py", 4, 5902),
    ("tests/test_shell_settings.py", 33, 1465),
    ("tests/test_source_exclusions.py", 47, 12961),
    ("tests/test_source_reconciliation.py", 17, 29700),
    ("tests/test_transcript_documentation.py", 3, 3),
    ("tests/test_transcript_jobs.py", 11, 23926),
    ("tests/test_transcript_packaging.py", 4, 5),
    ("tests/test_transcript_parsers.py", 19, 18),
    ("tests/test_transcript_real_smoke.py", 2, 1),
    ("tests/test_transcript_sources.py", 5, 3678),
    ("tests/test_transcript_surfaces.py", 6, 12222),
    ("tests/test_updates.py", 25, 2094),
    ("tests/test_verify_release_bundle.py", 7, 261),
    ("tests/test_vertical_slice.py", 4, 4184),
    ("tests/test_video_packaging.py", 2, 3),
    ("tests/test_video_profiles.py", 14, 5067),
    ("tests/test_video_real_smoke.py", 1, 1),
    ("tests/test_windows_identity.py", 6, 1015),
    ("tests/test_windows_package_manifest.py", 2, 10),
    ("tests/test_windows_public_baselines.py", 3, 5),
    ("tests/test_windows_pytest_sharding.py", 6, 3279),
    ("tests/test_windows_shard_costs.py", 18, 14),
    ("tests/test_windows_shard_timings.py", 2, 3797),
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
                    # the unchanged aggregate deadline interrupts a quiet run.
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
