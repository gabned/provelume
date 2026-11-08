"""Synthetic installed OCR qualification; no personal documents or live Sources."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / "core"))

from provelume.ocr_contract import OcrContractError, OcrSettings  # noqa: E402
from provelume.ocr_kit import ENGINE, TSV_CONFIG, WORKER  # noqa: E402
from provelume.ocr_process import minimal_child_environment, run_bounded_process  # noqa: E402
from provelume.publication import canonical_bytes, file_identity  # noqa: E402
from provelume.service import ProvelumeInstance  # noqa: E402


def _snapshot(instance):
    return {
        p.relative_to(instance.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for directory in ("knowledge", "originals")
        for p in (instance.root / directory).rglob("*")
        if p.is_file()
    }


def _native_pdf(path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    text = (
        "Reliable native printed text with sufficient printable characters for the existing "
        "automatic OCR skip policy. " * 5
    )
    stream = DecodedStreamObject()
    stream.set_data(("BT /F1 12 Tf 30 700 Td (" + text + ") Tj ET").encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


def _corpus(root):
    from PIL import Image, ImageDraw, ImageFont

    root.mkdir()
    for language, line in (
        ("eng", "PROVELUME ENGLISH DOCUMENT 123"),
        ("ita", "PROVELUME DOCUMENTO ITALIANO 123"),
    ):
        # Deterministic paper grain keeps this ordinary scanned-page corpus
        # below the existing decompression-ratio ceiling. A flat white canvas
        # compresses like a hostile expansion fixture, especially in PNG/PDF.
        size = (1800, 500)
        grain = hashlib.shake_256(b"Concordia S04 synthetic paper v1").digest(size[0] * size[1])
        shades = bytes(242 + value % 14 for value in range(256))
        image = Image.frombytes("L", size, grain.translate(shades)).convert("RGB")
        ImageDraw.Draw(image).text((80, 180), line, fill="black", font=ImageFont.load_default(64))
        for extension, options in (
            ("png", {}),
            ("jpg", {"quality": 95}),
            ("bmp", {}),
            ("tiff", {"compression": "raw"}),
            ("pdf", {"resolution": 300, "quality": 95}),
        ):
            image.save(root / f"{language}.{extension}", **options)
        image.close()
    _native_pdf(root / "native.pdf")
    (root / "corrupt.pdf").write_bytes(b"%PDF-1.7\ninvalid synthetic PDF")


def _fault(worker, temporary, kind):
    """Suspend only our newly created frozen worker, then exercise real kill/cleanup."""
    original_popen = subprocess.Popen
    processes = []
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
    ntdll.NtSuspendProcess.restype = ctypes.c_long

    def launch(*args, **kwargs):
        command = args[0] if args else kwargs["args"]
        process = original_popen(*args, **kwargs)
        if Path(command[0]) == worker:
            processes.append(process)
            if ntdll.NtSuspendProcess(ctypes.c_void_p(int(process._handle))) != 0:
                process.kill()
                process.wait(5)
                raise ValueError("Owned-worker fault injection failed")
        return process

    try:
        with patch("subprocess.Popen", launch):
            try:
                run_bounded_process(
                    [str(worker), "probe"],
                    temporary_directory=temporary,
                    timeout_seconds=1,
                    stdout_limit=262144,
                    stderr_limit=16384,
                    cancelled=(lambda: True) if kind == "cancel" else None,
                    environment=minimal_child_environment(temporary),
                )
                raise AssertionError("Fault did not stop the frozen worker")
            except OcrContractError as exc:
                assert exc.code == (
                    "ocr_cancelled" if kind == "cancel" else "ocr_deadline_exceeded"
                )
        assert len(processes) == 1 and all(p.poll() is not None for p in processes)
        assert not list(temporary.iterdir())
        return {
            "case": kind,
            "result": "PASS",
            "owned_pids": [p.pid for p in processes],
            "owned_processes_remaining": 0,
            "method": "NtSuspendProcess fault injection",
        }
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(5)


def qualify(executable, kit, root, output, build_report, installer):
    if sys.platform != "win32":
        raise ValueError("Native disposable Windows runner required")
    root.mkdir()
    environment = dict(os.environ, LOCALAPPDATA=str(root / "Host"), PATH="")
    counter = 0

    def command(*arguments, expected=0):
        nonlocal counter
        counter += 1
        result = root / f"command-{counter:03}.json"
        process = subprocess.run(
            [
                str(executable),
                "--ocr-result-file",
                str(result),
                "--ocr-command",
                *map(str, arguments),
            ],
            env=environment,
            timeout=180,
            check=False,
        )
        payload = json.loads(result.read_text(encoding="utf-8"))
        evidence = output.parent / result.name
        evidence.write_bytes(result.read_bytes())
        if process.returncode != expected:
            print(
                json.dumps(
                    {
                        "failed_command": arguments[0],
                        "returncode": process.returncode,
                        "result": payload,
                    },
                    ensure_ascii=True,
                )[:4000],
                flush=True,
            )
            raise AssertionError((arguments[0], process.returncode))
        return payload

    source = root / "Corpus"
    _corpus(source)
    instance = ProvelumeInstance.initialise(root / "Synthetic Instance")
    instance.ingest(source)
    before = _snapshot(instance)
    identity = json.loads(build_report.read_text())["kit"]
    assert file_identity(kit) == identity
    current = root / "Host/Provelume/ocr/kits" / identity["sha256"]
    rules = []
    powershell = Path(os.environ["SYSTEMROOT"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    profiles = json.loads(
        subprocess.check_output(
            [
                str(powershell),
                "-NoProfile",
                "-Command",
                "Get-NetFirewallProfile | Select-Object Name,"
                "@{Name='Enabled';Expression={$_.Enabled.ToString()}} | ConvertTo-Json -Compress",
            ],
            text=True,
            timeout=30,
        )
    )
    assert len(profiles) == 3 and all(
        p["Name"] in {"Domain", "Public", "Private"} for p in profiles
    )
    try:
        subprocess.run(
            [
                str(powershell),
                "-NoProfile",
                "-Command",
                "Set-NetFirewallProfile -All -Enabled True -ErrorAction Stop",
            ],
            check=True,
            timeout=30,
        )
        for index, path in enumerate((executable, current / WORKER, current / ENGINE)):
            name = f"Provelume-OCR-S04-{os.getpid()}-{index}"
            rules.append(name)
            # Paths enter the command as argv through environment; no shell interpolation.
            script = (
                "New-NetFirewallRule -Name $env:OCR_RULE -DisplayName $env:OCR_RULE "
                "-Direction Outbound -Program $env:OCR_PROGRAM -Action Block -Enabled True "
                "-Profile Any | Out-Null; "
                "$rule = Get-NetFirewallRule -Name $env:OCR_RULE -PolicyStore ActiveStore; "
                "if ($rule.Enabled -ne 'True' -or $rule.Action -ne 'Block' -or "
                "$rule.Direction -ne 'Outbound') { exit 2 }; "
                "$application = $rule | Get-NetFirewallApplicationFilter; "
                "if ($application.Program -ne $env:OCR_PROGRAM) { exit 2 }; "
                "if (@(Get-NetFirewallProfile | Where-Object Enabled -ne 'True').Count "
                "-ne 0) { exit 2 }"
            )
            subprocess.run(
                [str(powershell), "-NoProfile", "-Command", script],
                check=True,
                env=dict(os.environ, OCR_RULE=name, OCR_PROGRAM=str(path)),
                timeout=30,
            )
        assert command("ocr-capability", instance.root)["state"] == "disabled"
        imported = command("kit-import", kit, "--expected-sha256", identity["sha256"])
        assert imported["ocr_enablement_changed"] is False
        assert command("ocr-capability", instance.root)["state"] == "disabled"
        base_runtime = file_identity(executable.parent / "_internal/python312.dll")
        assert base_runtime == file_identity(current / "worker/_internal/python312.dll")
        manifest = json.loads((current / "ocr-kit.json").read_text())
        instance.configure_ocr(OcrSettings(mode="forced", languages=("eng", "ita")))
        capability = command("ocr-capability", instance.root)
        assert capability["available"] is True
        assert capability["adapter"]["engine_version"] == "5.5.3"
        assert capability["renderer"]["adapter_version"] == "1+" + identity["sha256"]
        cases = []
        documents = {Path(d["locator"]).name: d for d in instance.store.list_canonical("documents")}
        for name, document in sorted(documents.items()):
            version = document["current_version_id"]
            if name == "corrupt.pdf":
                result = command("ocr-queue", instance.root, version, expected=2)
                assert result["code"] == "ocr_corrupt_input"
            elif name == "native.pdf":
                result = command("ocr-queue", instance.root, version, "--mode", "automatic")
                assert result["scheduled"] is False
            else:
                language = name.split(".")[0]
                print(json.dumps({"ocr_fixture": name, "language": language}), flush=True)
                queued = command("ocr-queue", instance.root, version, "--language", language)
                completed = command("ocr-run", instance.root, queued["job"]["id"])
                assert completed["status"] == "succeeded"
                (bundle,) = instance.list_ocr_bundles(version)
                texts = [
                    (instance.root / p["text_ref"]).read_text(encoding="utf-8")
                    for p in bundle["manifest"]["pages"]
                ]
                assert any("PROVELUME" in text.upper() for text in texts), name
                assert bundle["manifest"]["authoritative"] is False
            cases.append(
                {"input": name, "sha256": file_identity(source / name)["sha256"], "result": "PASS"}
            )
        paths = [
            ENGINE,
            TSV_CONFIG,
            WORKER,
            "tessdata/ita.traineddata",
            "worker/_internal/python312.dll",
        ]
        paths += [r["path"] for r in manifest["files"] if r["path"].endswith("/pdfium.dll")]
        assert len(paths) == 6
        negatives = []
        for name in paths:
            path = current / name
            backup = root / "missing-component"
            path.rename(backup)
            try:
                report = command("ocr-capability", instance.root)
                assert report["available"] is False
                expected = (
                    "ocr_engine_unavailable"
                    if name in {ENGINE, TSV_CONFIG}
                    else "ocr_language_pack_missing"
                    if name.startswith("tessdata/")
                    else "ocr_renderer_unavailable"
                )
                assert report["error"]["code"] == expected
                negatives.append({"component": name, "code": expected, "result": "PASS"})
            finally:
                backup.rename(path)
        temporary = root / "fault-temporary"
        temporary.mkdir()
        faults = [_fault(current / WORKER, temporary, kind) for kind in ("cancel", "timeout")]
        assert _snapshot(instance) == before
        assert not list(instance.ocr.temporary_root.iterdir())
        personal_trials = [command("personal-qualify", root / ("Personal " + mode),
                                   "--retention", mode, "--ocr-ready", "--kit", kit,
                                   "--expected-sha256", identity["sha256"])
                           for mode in ("keep", "transit")]
        assert all(result["result"] == "PASS" and result["ocr"] == "AUTOMATIC_PASS"
                   and result["backup_restore"] == "PASS" for result in personal_trials)
        setup_trials = [result["setup"] for result in personal_trials]
        calendar_trial = command("icalendar-qualify", root / "Synthetic Calendars")
        assert calendar_trial["result"] == "PASS" and not calendar_trial["network_used"]
        asana_trial = command("asana-qualify", root / "Synthetic Asana")
        assert asana_trial["result"] == "PASS" and not asana_trial["network_used"]
        tududi_trial = command("tududi-qualify", root / "Synthetic Tududi")
        assert tududi_trial["result"] == "PASS" and not tududi_trial["network_used"]
        writeback_trial = command("task-writeback-qualify", root / "Synthetic Task Writes")
        assert writeback_trial["result"] == "PASS" and not writeback_trial["network_used"]
        assert writeback_trial["release_gate"] == "DEFERRED_BY_MAINTAINER"
        assert writeback_trial["release_scope"] == "ASANA_TUDUDI_READ_ONLY_0_15_0"
        mirror_trial = command("mirror-qualify", root / "Synthetic Mirrors")
        assert mirror_trial["result"] == "PASS" and not mirror_trial["network_used"]
        assert not mirror_trial["transport_process_used"]
        assert mirror_trial["publication"] == "TRANSPORT_NOT_QUALIFIED"
        assert mirror_trial["same_root_restore_no_replay"] == "PASS"
        assert all(result["result"] == "PASS" and len(result["documents"]) == 2
                   and result["selected_settings_readback"] for result in setup_trials)
        instance.configure_ocr(replace(instance.ocr.configured_settings(), mode="disabled"))
        assert command("kit-remove")["status"] == "removed"
        assert command("ocr-capability", instance.root)["state"] == "disabled"
        report = {
            "schema_version": 1,
            "result": "PASS",
            "kit": identity,
            "installer_executable": file_identity(executable),
            "installer": file_identity(installer),
            "build_identity": imported["build_identity"],
            "matching_python_runtime": base_runtime,
            "source_commit": manifest["commit"],
            "os": sys.getwindowsversion()._asdict()
            if hasattr(sys.getwindowsversion(), "_asdict")
            else str(sys.getwindowsversion()),
            "cases": cases,
            "missing_components": negatives,
            "faults": faults,
            "s07_setup_trials": setup_trials,
            "s09_personal_trials": personal_trials,
            "s12_icalendar_trial": calendar_trial,
            "s13_asana_trial": asana_trial,
            "s14_tududi_trial": tududi_trial,
            "s15_task_writeback_trial": writeback_trial,
            "s16_mirror_trial": mirror_trial,
            "originals_and_canonical": "UNCHANGED",
            "path": "EMPTY_FOR_INSTALLED_COMMANDS",
            "external_python_required": False,
            "network": "Outbound Windows Firewall block rules for exact three executables",
            "firewall_profiles_before": profiles,
            "firewall_profiles_during_test": "ENABLED_AND_ACTIVE_RULE_PROGRAM_BINDING_VERIFIED",
            "qualification_host_is_admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
            "manual_windows_11_home_pro_25h2": "NOT_RUN",
            "publication": "NOT_TRIGGERED",
        }
        output.write_bytes(canonical_bytes(report))
        print(
            json.dumps(
                {
                    "result": report["result"],
                    "cases": len(cases),
                    "negative_cases": len(negatives),
                    "fault_cases": len(faults),
                }
            )
        )
    finally:
        for name in rules:
            subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-Command",
                    "$rule = Get-NetFirewallRule -Name $env:OCR_RULE "
                    "-ErrorAction SilentlyContinue; "
                    "if ($rule) { $rule | Remove-NetFirewallRule -ErrorAction Stop }",
                ],
                env=dict(os.environ, OCR_RULE=name),
                check=True,
                timeout=30,
            )
        for profile in profiles:
            subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-Command",
                    "Set-NetFirewallProfile -Name $env:OCR_PROFILE_NAME "
                    "-Enabled $env:OCR_PROFILE_ENABLED -ErrorAction Stop",
                ],
                env=dict(
                    os.environ,
                    OCR_PROFILE_NAME=profile["Name"],
                    OCR_PROFILE_ENABLED=profile["Enabled"],
                ),
                check=True,
                timeout=30,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("executable", "kit", "root", "output", "build-report", "installer"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    qualify(args.executable, args.kit, args.root, args.output, args.build_report, args.installer)
