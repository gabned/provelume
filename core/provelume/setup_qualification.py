"""Bounded synthetic installed check, using automatic runtime producers.

This is an explicit diagnostic entry for a new empty local target. It is not a
manual OCR command, a release gate substitute or a Windows 25H2 human result.
"""

import asyncio
import hashlib
import time
from importlib.resources import files
from pathlib import Path

from .maintenance_local_files import prepare_local_directory
from .review_effects import ReviewUnavailable
from .service import ProvelumeInstance
from .setup_coordinator import SetupCoordinator
from .setup_trial_http import _get, verify_trial_http
from .setup_trial_inputs import FIXTURES
from .setup_trials import SetupTrials
from .shell_settings import ShellSettingsManager, default_settings
from .web import create_app


def qualify_setup(root, *, retention, ocr_required=True, languages=None, kit=None, kit_sha256=None):
    root = Path(root)
    if (kit is None) != (kit_sha256 is None):
        raise ReviewUnavailable("Select the exact kit and its independently verified fingerprint")
    if root.exists() or root.is_symlink():
        raise ReviewUnavailable("Setup qualification requires a new synthetic target")
    with prepare_local_directory(root, create=True) as (owned, _binding):
        instance = ProvelumeInstance.initialise(owned / "Synthetic Space")
        settings = ShellSettingsManager(owned / "launcher.json", default_settings())
        coordinator = SetupCoordinator(instance, settings)
        inbox = owned / "Synthetic Input"
        inbox.mkdir()
        sentinel = inbox / "unselected-sentinel.txt"
        sentinel.write_bytes(b"Unselected S07 synthetic sentinel\n")
        sentinel_hash = hashlib.sha256(sentinel.read_bytes()).hexdigest()
        coordinator.prepare(0, path=inbox, name="S07 synthetic Inbox")
        kit_preparation = None
        if kit is not None:
            before = instance.store.read_config()
            kit_preparation = coordinator.preview_ocr(archive=kit, expected_sha256=kit_sha256)
            coordinator.install_ocr(coordinator.progress.read()["revision"], archive=kit,
                                    expected_sha256=kit_sha256,
                                    preview_revision=kit_preparation["revision"])
            if instance.store.read_config() != before:
                raise ReviewUnavailable("Component preparation changed Instance settings")
        choices = {**coordinator.defaults(), "retention": retention, "ocr": ocr_required,
                   "languages": languages or ["eng", "ita"], "automation": "manual"}
        coordinator.start_trial(coordinator.progress.read()["revision"], choices,
                                request_key="s07-installed-trial-001")
        trial_id = coordinator.progress.read()["operations"]["test"]
        trials = SetupTrials(instance.store)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            instance.run_scheduler_cycle(max_jobs=1)
            observed = trials.observations(trial_id)
            if observed["processing_ready"]:
                break
            terminal_bad = [row["job"] for row in observed["documents"] if row["job"] and
                            row["job"]["status"] in {"failed", "cancelled", "dead_letter"}]
            if terminal_bad:
                raise ReviewUnavailable("The actual automatic trial child failed")
            time.sleep(.05)
        else:
            raise ReviewUnavailable("The bounded automatic setup trial did not finish")
        app = create_app(instance.root, shell_settings_file=settings.path)
        observed = asyncio.run(verify_trial_http(app, instance.store, trial_id, port=44851))
        if not observed["complete"]:
            raise ReviewUnavailable("The synthetic consultation trial failed")
        # Exercise actual frozen templates and catalogs, not resource presence alone.
        responses = {}
        for step in ("space", "folders", "ocr", "automation", "test", "summary"):
            async def get_step(selected=step):
                # _get has no client-selected URL or external transport.
                return await _get(app, "/setup", host="127.0.0.1", port=44851,
                                  maximum=512 * 1024,
                                  query_string=("step=" + selected).encode("ascii"))

            status, body = asyncio.run(get_step())
            if (status != 200 or b"setup-form" not in body
                    or f'name="step" value="{step}"'.encode() not in body):
                raise ReviewUnavailable("The installed setup template failed")
            responses[step] = {"status": status, "sha256": hashlib.sha256(body).hexdigest()}
        before = instance.store.read_config()
        if before.get("ocr", {}).get("mode", "disabled") != "disabled":
            raise ReviewUnavailable("The trial changed the global OCR mode")
        preview = coordinator.preview(choices)
        coordinator.apply(coordinator.progress.read()["revision"], choices=choices,
                          preview_revision=preview["revision"])
        if not coordinator.application()["complete"]:
            raise ReviewUnavailable("The installed setup Apply readback failed")
        future = inbox / "after-apply-native.pdf"
        future.write_bytes(files("provelume").joinpath(
            "resources", "setup-trial", FIXTURES["native"]["name"]).read_bytes())
        instance.observe_folder_source(choices["source_id"])
        # Retain the real existing five-second quiescence policy, not a test override.
        time.sleep(5.1)
        refreshed = instance.refresh_folder_source(choices["source_id"],
                                                    request_key="s07-future-001")
        if refreshed["job"]["status"] != "succeeded":
            raise ReviewUnavailable("The configured Source acquisition failed")
        instance.run_scheduler_cycle(max_jobs=1)
        documents = [row for row in instance.store.list_canonical("documents")
                     if row["locator"] == future.name and row["source_id"] == choices["source_id"]]
        if len(documents) != 1:
            raise ReviewUnavailable("The configured Source did not acquire exactly the new input")
        acquisitions = instance.store.list_canonical("acquisitions")
        if (len(acquisitions) != len(observed["documents"]) + 1
                or any(row["locator"] == sentinel.name for row in acquisitions)):
            raise ReviewUnavailable("The Source acquired an excluded backlog or trial input")
        future_original = instance.document_original(documents[0]["id"])
        if hashlib.sha256(future_original["data"]).hexdigest() != FIXTURES["native"]["sha256"]:
            raise ReviewUnavailable("The future acquisition Original failed verification")
        if future.exists() != (retention == "keep"):
            raise ReviewUnavailable("The configured Source Inbox outcome was not observed")
        if hashlib.sha256(sentinel.read_bytes()).hexdigest() != sentinel_hash:
            raise ReviewUnavailable("An unselected synthetic sentinel changed")
        if instance.validate_instance()["status"] != "valid":
            raise ReviewUnavailable("The synthetic Instance failed deep validation")
        return {"schema_version": 1, "result": "PASS", "retention": retention,
                "ocr_required": ocr_required, "languages": choices["languages"],
                "resources": {row["fixture"]: FIXTURES[row["fixture"]]
                              for row in observed["documents"]},
                "documents": [{"fixture": row["fixture"], "text_kind": row["text_kind"],
                               "original_verified": row["original_verified"],
                               "content_search": row["search_verified"],
                               "consultation": row["consultation_verified"],
                               "inbox_outcome": row["inbox_outcome"]}
                              for row in observed["documents"]],
                "six_template_responses": responses, "selected_settings_readback": True,
                "kit_preparation": kit_preparation,
                "future_native": {"acquired": True, "original_verified": True,
                                  "input_retained": future.exists(), "backlog_acquired": False},
                "sentinel": "UNCHANGED", "manual_windows_11_home_pro_25h2": "NOT_RUN",
                "rendered_browser": "NOT_RUN", "publication": "NOT_TRIGGERED"}
