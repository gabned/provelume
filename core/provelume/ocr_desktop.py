"""Explicit frozen OCR operator entry: bounded JSON result, no GUI/server dispatch."""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from .mirror_cli import add_mirror_commands, handle_mirror_command
from .ocr_cli import add_ocr_commands, handle_ocr_command
from .ocr_kit import OcrKitError, _safe, active_kit, host_root, import_kit, remove_kit
from .publication import PublicationError
from .shell_settings import ShellSettingsBusy


def run_ocr_command(arguments: list[str], result_file: Path) -> int:
    parser = argparse.ArgumentParser(prog="Provelume --ocr-command")
    commands = parser.add_subparsers(dest="command", required=True)
    install = commands.add_parser("kit-import")
    install.add_argument("archive", type=Path)
    install.add_argument("--receipt", type=Path)
    install.add_argument("--development", action="store_true")
    install.add_argument("--expected-sha256")
    commands.add_parser("kit-status")
    commands.add_parser("kit-remove")
    setup = commands.add_parser("setup-qualify")
    setup.add_argument("instance", type=Path)
    setup.add_argument("--retention", choices=("keep", "transit"), required=True)
    setup.add_argument("--kit", type=Path)
    setup.add_argument("--expected-sha256")
    personal = commands.add_parser("personal-qualify")
    personal.add_argument("instance", type=Path)
    personal.add_argument("--retention", choices=("keep", "transit"), required=True)
    personal.add_argument("--ocr-ready", action="store_true")
    personal.add_argument("--kit", type=Path)
    personal.add_argument("--expected-sha256")
    calendar = commands.add_parser("icalendar-qualify")
    calendar.add_argument("instance", type=Path)
    asana = commands.add_parser("asana-qualify")
    asana.add_argument("instance", type=Path)
    tududi = commands.add_parser("tududi-qualify")
    tududi.add_argument("instance", type=Path)
    writeback = commands.add_parser("task-writeback-qualify")
    writeback.add_argument("instance", type=Path)
    mirror = commands.add_parser("mirror-qualify")
    mirror.add_argument("instance", type=Path)
    git_mirror = commands.add_parser("git-mirror-qualify")
    git_mirror.add_argument("instance", type=Path)
    github_mirror = commands.add_parser("github-mirror-qualify")
    github_mirror.add_argument("instance", type=Path)
    gitlab_mirror = commands.add_parser("gitlab-mirror-qualify")
    gitlab_mirror.add_argument("instance", type=Path)
    gitea_mirror = commands.add_parser("gitea-mirror-qualify")
    gitea_mirror.add_argument("instance", type=Path)
    gitea_server = commands.add_parser("gitea-server-qualify")
    gitea_server.add_argument("instance", type=Path)
    gitea_server.add_argument("--binary", type=Path, required=True)
    gitea_server.add_argument("--api-only", action="store_true")
    folder_mirror = commands.add_parser("folder-mirror-qualify")
    folder_mirror.add_argument("instance", type=Path)
    rsync_mirror = commands.add_parser("rsync-mirror-qualify")
    rsync_mirror.add_argument("instance", type=Path)
    rsync_mirror.add_argument("--fixture-image", required=True)
    rsync_mirror.add_argument("--expected-source-commit", required=True)
    rsync_agent = commands.add_parser("rsync-credential-qualify")
    rsync_agent.add_argument("instance", type=Path)
    rsync_windows = commands.add_parser("rsync-windows-components-qualify")
    rsync_windows.add_argument("instance", type=Path)
    rsync_windows.add_argument("--fixture-directory", required=True, type=Path)
    integrated = commands.add_parser("concordia-integrated-qualify")
    integrated.add_argument("instance", type=Path)
    add_mirror_commands(commands)
    add_ocr_commands(commands)
    try:
        options = parser.parse_args(arguments)
        destination = _safe(result_file)
        if destination.is_relative_to(_safe(host_root())):
            return 2
        if hasattr(options, "instance") and destination.is_relative_to(_safe(options.instance)):
            return 2
        # The output must be available before any operation changes state.
        with destination.open("x", encoding="utf-8", newline="\n") as stream:
            try:
                if options.command == "concordia-integrated-qualify":
                    from .concordia_qualification import qualify_concordia

                    result = qualify_concordia(options.instance)
                elif options.command == "rsync-mirror-qualify":
                    from .mirror_rsync_qualification import qualify_rsync_mirror

                    result = qualify_rsync_mirror(
                        options.instance,
                        image=options.fixture_image,
                        expected_source_commit=options.expected_source_commit,
                    )
                elif options.command == "rsync-windows-components-qualify":
                    from .mirror_rsync_windows_qualification import qualify_components

                    result = qualify_components(
                        options.instance, fixture_directory=options.fixture_directory
                    )
                elif options.command == "rsync-credential-qualify":
                    from .mirror_rsync_agent_qualification import qualify_agent

                    result = qualify_agent(options.instance)
                elif options.command == "folder-mirror-qualify":
                    from .mirror_folder_qualification import qualify_folder_mirror

                    result = qualify_folder_mirror(options.instance)
                elif options.command == "gitea-server-qualify":
                    from .mirror_gitea_server_qualification import qualify_gitea_server

                    result = qualify_gitea_server(
                        options.instance, options.binary, api_only=options.api_only
                    )
                elif options.command == "gitea-mirror-qualify":
                    from .mirror_gitea_qualification import qualify_gitea_mirror

                    result = qualify_gitea_mirror(options.instance)
                elif options.command == "gitlab-mirror-qualify":
                    from .mirror_gitlab_qualification import qualify_gitlab_mirror

                    result = qualify_gitlab_mirror(options.instance)
                elif options.command == "github-mirror-qualify":
                    from .mirror_github_qualification import qualify_github_mirror

                    result = qualify_github_mirror(options.instance)
                elif options.command == "git-mirror-qualify":
                    from .mirror_git_qualification import qualify_git_mirror

                    result = qualify_git_mirror(options.instance)
                elif options.command == "mirror-qualify":
                    from .mirror_qualification import qualify_mirrors

                    result = qualify_mirrors(options.instance)
                elif options.command == "task-writeback-qualify":
                    from .task_writeback_qualification import qualify_task_writeback

                    result = qualify_task_writeback(options.instance)
                elif options.command == "tududi-qualify":
                    from .tududi_qualification import qualify_tududi

                    result = qualify_tududi(options.instance)
                elif options.command == "asana-qualify":
                    from .asana_qualification import qualify_asana

                    result = qualify_asana(options.instance)
                elif options.command == "icalendar-qualify":
                    from .icalendar_qualification import qualify_icalendar

                    result = qualify_icalendar(options.instance)
                elif options.command == "personal-qualify":
                    from .personal_qualification import qualify_personal

                    result = qualify_personal(
                        options.instance,
                        retention=options.retention,
                        ocr_required=options.ocr_ready,
                        kit=options.kit,
                        kit_sha256=options.expected_sha256,
                    )
                elif options.command == "setup-qualify":
                    from .setup_qualification import qualify_setup

                    result = qualify_setup(
                        options.instance,
                        retention=options.retention,
                        kit=options.kit,
                        kit_sha256=options.expected_sha256,
                    )
                elif options.command == "kit-import":
                    result = import_kit(
                        options.archive,
                        receipt_path=options.receipt,
                        expected_sha256=options.expected_sha256,
                        development=options.development,
                    )
                elif options.command == "kit-remove":
                    result = remove_kit()
                elif options.command == "kit-status":
                    kit = active_kit()
                    manifest = kit.verify()
                    result = {
                        "status": "present-verified",
                        "sha256": kit.sha256,
                        "commit": manifest["commit"],
                        "network_used": False,
                        "ocr_enablement_changed": False,
                    }
                else:
                    output = io.StringIO()
                    with redirect_stdout(output):
                        code = handle_mirror_command(options)
                        if code is None:
                            code = handle_ocr_command(options)
                    stream.write(output.getvalue())
                    return code if code in (0, 2) else 2
                json.dump(result, stream, sort_keys=True)
                stream.write("\n")
                return 0
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                OcrKitError,
                PublicationError,
                ShellSettingsBusy,
            ) as exc:
                failure = {
                    "status": "unavailable",
                    "code": (
                        "provisioning_busy"
                        if isinstance(exc, ShellSettingsBusy)
                        else getattr(exc, "code", "invalid_kit")
                    ),
                    "network_used": False,
                }
                if options.command == "rsync-windows-components-qualify":
                    from .mirror_rsync_windows_qualification import WindowsComponentsFailure

                    if isinstance(exc, WindowsComponentsFailure):
                        failure["qualification_evidence"] = exc.evidence
                if options.command == "gitea-mirror-qualify":
                    from .mirror_gitea_qualification import GiteaMirrorQualificationFailure

                    if isinstance(exc, GiteaMirrorQualificationFailure):
                        failure["qualification_evidence"] = exc.evidence
                if options.command == "gitea-server-qualify":
                    from .mirror_gitea_server_qualification import GiteaQualificationFailure

                    if isinstance(exc, GiteaQualificationFailure):
                        failure["qualification_evidence"] = exc.evidence
                        failure["network_used"] = None
                json.dump(failure, stream)
                stream.write("\n")
                return 2
    except (OSError, ValueError, OcrKitError):
        return 2
