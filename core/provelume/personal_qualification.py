"""Synthetic S09 journey on the real services; never a human/platform receipt."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlencode

from .ai_setup import AiSetup
from .build_info import current_build_info
from .instance_backup import extract_backup, verify_backup
from .review_effects import ReviewUnavailable
from .service import ProvelumeInstance
from .setup_qualification import qualify_setup
from .setup_trial_http import _get
from .shell_settings import ShellSettingsManager, default_settings
from .web import create_app


def _canonical(root):
    paths = [root / "provelume.yml", root / "instance-manifest.json"]
    for directory in ("knowledge", "originals"):
        paths.extend(path for path in (root / directory).rglob("*") if path.is_file())
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in paths}


def qualify_personal(root, *, retention, ocr_required=False, languages=None,
                     kit=None, kit_sha256=None):
    """Create only a fresh synthetic target, preserving every failed observation.

    OCR-ready is earned by the real setup trial and optional verified kit. A
    deferred run exercises native text only and explicitly leaves OCR NOT_RUN.
    """
    root = Path(root)
    setup = qualify_setup(root, retention=retention, ocr_required=ocr_required,
                          languages=languages, kit=kit, kit_sha256=kit_sha256,
                          exercise_recovery=True)
    instance = ProvelumeInstance(root / "Synthetic Space")
    settings = ShellSettingsManager(root / "launcher.json", default_settings())
    app = create_app(instance.root, shell_settings_file=settings.path)
    before = _canonical(instance.root)
    ai = AiSetup(instance)
    ai_before = {"configuration": ai.configuration(), "control": ai.jobs._control()}
    if ai_before["configuration"]["mode"] != "off" or ai_before["control"]["mode"] != "off":
        raise ReviewUnavailable("Personal qualification requires the default AI-Off state")

    routes = []
    query = "PROVELUME"
    if not instance.search(query):
        raise ReviewUnavailable("The synthetic native trial has no searchable text")
    for mode in ("current", "preview"):
        revision = settings.load().settings.revision
        settings.set_interface_mode(mode, expected_revision=revision)
        for language in ("en", "it", "de", "es", "fr", "pt", "ro"):
            for case, params, expected in (
                ("initial", {"q": "  "}, 200),
                ("invalid_date", {"q": query, "date_from": "2026-02-30"}, 400),
                ("matching", {"q": query}, 200),
                ("filtered_empty", {"q": query, "media_type": "text/plain"}, 200),
                ("recovered", {"q": query}, 200),
            ):
                status, body = asyncio.run(_get(
                    app, "/search", host="127.0.0.1", port=8765, maximum=512 * 1024,
                    query_string=urlencode({"lang": language, **params}).encode("ascii")))
                if status != expected or b'id="search-query"' not in body:
                    raise ReviewUnavailable("Personal search route failed")
                if case == "filtered_empty" and b'id="search-remove-filters"' not in body:
                    raise ReviewUnavailable("The combined S08 recovery action is absent")
                routes.append({"mode": mode, "language": language, "case": case,
                               "status": status, "sha256": hashlib.sha256(body).hexdigest()})
    ai_after = {"configuration": ai.configuration(), "control": ai.jobs._control()}
    if _canonical(instance.root) != before or ai_after != ai_before:
        raise ReviewUnavailable("Consultation or search changed canonical data or AI state")

    archive = instance.backup(destination=root / "Synthetic Backups")
    verify_backup(archive["archive"])
    extract_backup(archive["archive"], root / "Restored Space")
    restored = ProvelumeInstance(root / "Restored Space")
    if _canonical(restored.root) != before or restored.validate_instance()["status"] != "valid":
        raise ReviewUnavailable("The personal backup recovery changed canonical data")
    if not restored.search(query):
        raise ReviewUnavailable("The restored Instance cannot rebuild its native search")
    return {"schema": "provelume-personal-qualification/v1", "result": "PASS",
            "build": current_build_info(), "setup": setup, "search_routes": routes,
            "ai": "OFF_UNCHANGED", "canonical": "UNCHANGED", "backup_restore": "PASS",
            "consultation_history": setup["consultation_history"],
            "ocr": "AUTOMATIC_PASS" if ocr_required else "DEFERRED_NOT_RUN",
            "rendered_browser": "NOT_RUN", "installed_package": "NOT_RUN",
            "final_0_14_and_0_13_upgrades": "NOT_RUN",
            "windows_11_home_25h2": "NOT_RUN",
            "windows_11_pro_25h2_manual": "DEFERRED_BY_MAINTAINER / NOT_RUN",
            "publication": "NOT_TRIGGERED"}
