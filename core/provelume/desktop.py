from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

import uvicorn

from . import __version__
from .about import current_about
from .service import ProvelumeInstance
from .shell_settings import (
    APP_USER_MODEL_ID,
    DEFAULT_LOCAL_PORT,
    SHELL_SETTINGS_SCHEMA_VERSION,
    LauncherSettings,
    ShellSettingsError,
    ShellSettingsManager,
    configure_login_startup,
    default_settings,
    effective_port,
    probe_port,
    settings_path,
    state_directory,
    validate_port,
)
from .updates import UpdateCandidate, UpdateError, check_for_updates, download_update
from .web import create_app
from .windows_tray import TRAY_LABELS, TrayState, WindowsTray

SETTINGS_SCHEMA_VERSION = SHELL_SETTINGS_SCHEMA_VERSION
DESKTOP_DIAGNOSTICS_SCHEMA_VERSION = 2
MUTEX_NAME = "Local\\ProvelumeDesktop"


def load_settings(path: Path | None = None) -> LauncherSettings:
    selected = path or settings_path()
    return ShellSettingsManager(selected, default_settings()).load().settings


def save_settings(settings: LauncherSettings, path: Path | None = None) -> Path:
    selected = path or settings_path()
    return ShellSettingsManager(selected, default_settings()).save(settings)


def declare_startup_update_policy(instance_path: Path, *, enabled: bool) -> None:
    """Keep the Instance capability inventory aligned with launcher startup policy."""

    instance = ProvelumeInstance(instance_path)
    with instance.connectors.policy_commit_guard(purpose="startup-update-policy"):
        config = instance.store.read_config()
        network = config.setdefault("network", {})
        if not isinstance(network, dict):
            raise ValueError("Instance network configuration must be an object")
        network["external_access"] = bool(enabled)
        network["update_checks"] = bool(enabled)
        network["update_endpoint"] = "https://api.github.com"
        network["update_data_categories"] = []
        instance.store.write_config(config)


def startup_update_policy_enabled(instance_path: Path) -> bool:
    """Fail closed unless both the global and component policies allow startup checks."""

    try:
        config = ProvelumeInstance(instance_path).store.read_config()
    except (OSError, ValueError):
        return False
    network = config.get("network")
    return bool(
        isinstance(network, dict)
        and network.get("external_access") is True
        and network.get("update_checks") is True
    )


def diagnostics_payload() -> dict[str, Any]:
    loaded = ShellSettingsManager(settings_path(), default_settings()).load()
    return {
        "schema_version": DESKTOP_DIAGNOSTICS_SCHEMA_VERSION,
        "desktop_shell": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "about": current_about(),
        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
        "settings_warning": loaded.warning,
        "endpoint": loaded.settings.public_view(warning=loaded.warning)["endpoint"],
        "shell": loaded.settings.public_view(warning=loaded.warning)["shell"],
        "windows_identity": {
            "app_user_model_id": APP_USER_MODEL_ID,
            "process_app_user_model_id": _configure_windows_identity(),
            "product": "Provelume",
            "publisher_authentication": "not_established",
            "authenticode": "unsigned",
            "icon": _icon_identity_payload(),
        },
        "network_used": False,
    }


def write_diagnostics(path: Path) -> Path:
    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(diagnostics_payload(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def write_ui_diagnostics(
    path: Path,
    *,
    language: str,
    dpi_percent: int,
    viewport_width: int,
    viewport_height: int,
) -> Path:
    """Build the real Tk launcher off-loop and record bounded layout evidence."""

    if language not in STRINGS:
        raise ValueError("UI diagnostics language must be en or it")
    if dpi_percent not in {100, 125, 150, 200}:
        raise ValueError("UI diagnostics DPI must be 100, 125, 150 or 200 percent")
    if viewport_width < 640 or viewport_height < 480:
        raise ValueError("UI diagnostics viewport is below the supported probe boundary")

    dpi_awareness = _configure_windows_dpi_awareness()
    import tkinter as tk

    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="provelume-ui-diagnostics-") as temporary:
        root = tk.Tk()
        try:
            root.tk.call("tk", "scaling", (96 * dpi_percent / 100) / 72)
            instance = Path(temporary) / f"Synthetic Instance {language}"
            shell = DesktopShell(
                root,
                initial_settings=LauncherSettings(
                    instance_path=str(instance),
                    language=language,
                ),
                auto_start_service=False,
                enable_native_tray=False,
            )
            target_width, target_height = _window_dimensions(
                viewport_width,
                viewport_height,
            )
            root.geometry(f"{target_width}x{target_height}")
            root.update_idletasks()
            root.update()
            canvas = shell.scroll_canvas
            bounds = canvas.bbox("all") or (0, 0, 0, 0)
            controls = {
                "open": str(shell.open_button.cget("state")),
                "stop": str(shell.stop_button.cget("state")),
                "choose": str(shell.choose_button.cget("state")),
                "create": str(shell.create_button.cget("state")),
                "check": str(shell.check_button.cget("state")),
                "download": str(shell.download_button.cget("state")),
            }
            action_labels = [
                str(shell.open_button.cget("text")),
                str(shell.stop_button.cget("text")),
                str(shell.check_button.cget("text")),
                str(shell.download_button.cget("text")),
            ]
            payload = {
                "schema_version": 1,
                "language": language,
                "dpi_percent": dpi_percent,
                "dpi_awareness": dpi_awareness,
                "modeled_viewport": {
                    "width": viewport_width,
                    "height": viewport_height,
                },
                "window": {
                    "width": root.winfo_width(),
                    "height": root.winfo_height(),
                    "target_width": target_width,
                    "target_height": target_height,
                },
                "scroll_surface": {
                    "viewport_width": canvas.winfo_width(),
                    "viewport_height": canvas.winfo_height(),
                    "content_width": max(0, int(bounds[2] - bounds[0])),
                    "content_height": max(0, int(bounds[3] - bounds[1])),
                },
                "controls": controls,
                "action_labels": action_labels,
                "all_action_labels_present": all(label.strip() for label in action_labels),
                "network_used": False,
                "instance_content_sent": False,
            }
            destination.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            shell.close()
        finally:
            with suppress(Exception):
                root.destroy()
    return destination


def write_native_tray_smoke(path: Path) -> bool:
    """Exercise the frozen shell's real Win32 tray lifecycle and write safe evidence."""

    destination = path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": "FAIL",
        "failure_code": "native_tray_not_started",
        "frozen_executable": bool(getattr(sys, "frozen", False)),
        "windows_identity": "not_checked",
        "labels_en_it_complete": set(TRAY_LABELS["en"]) == set(TRAY_LABELS["it"]),
        "action_sequence": [],
        "notification": {
            "schema_version": 1,
            "notification_added": False,
            "notification_updated": False,
            "notification_deleted": False,
            "icon_source": "unavailable",
            "native_window_released": True,
            "thread_stopped": True,
            "network_used": False,
        },
        "network_used": False,
        "private_content_logged": False,
    }
    root = None
    tray: WindowsTray | None = None
    actions: list[str] = []
    try:
        if os.name != "nt":
            payload["failure_code"] = "native_tray_requires_windows"
            raise RuntimeError("native tray smoke requires Windows")
        if not bool(getattr(sys, "frozen", False)):
            payload["failure_code"] = "native_tray_requires_frozen_executable"
            raise RuntimeError("native tray smoke requires the frozen executable")
        payload["failure_code"] = "windows_identity_not_configured"
        payload["windows_identity"] = _configure_windows_identity()
        if payload["windows_identity"] != "configured":
            raise RuntimeError("Windows identity was not configured")

        import tkinter as tk

        payload["failure_code"] = "native_tray_window_unavailable"
        root = tk.Tk()
        root.withdraw()
        tray = WindowsTray(
            root,
            state=TrayState(
                language="en",
                service_status="stopped",
                endpoint=f"http://127.0.0.1:{DEFAULT_LOCAL_PORT}",
            ),
            open_interface=lambda: actions.append("open"),
            open_settings=lambda: actions.append("settings"),
            restart_service=lambda: actions.append("restart"),
            quit_application=lambda: actions.append("quit"),
            icon_path=_versioned_icon_path(),
        )
        if not tray.start():
            raise RuntimeError("native notification icon was not created")

        payload["failure_code"] = "native_tray_update_failed"
        tray.update(
            service_status="running",
            endpoint=f"http://127.0.0.1:{DEFAULT_LOCAL_PORT}",
        )
        update_deadline = time.monotonic() + 2
        while (
            not tray.lifecycle_evidence()["notification_updated"]
            and time.monotonic() < update_deadline
        ):
            time.sleep(0.02)
        if not tray.lifecycle_evidence()["notification_updated"]:
            raise RuntimeError("native notification icon was not updated")

        payload["failure_code"] = "native_tray_actions_failed"
        for command_id in (1, 2, 3, 4):
            tray.exercise_action(command_id)
        root.update_idletasks()
        root.update()
        if actions != ["open", "settings", "restart", "quit"]:
            raise RuntimeError("native tray actions were not dispatched")

        payload["failure_code"] = "native_tray_shutdown_failed"
        tray.stop()
        evidence = tray.lifecycle_evidence()
        if not all(
            evidence[name]
            for name in (
                "notification_added",
                "notification_updated",
                "notification_deleted",
                "native_window_released",
                "thread_stopped",
            )
        ) or evidence["icon_source"] not in {
            "versioned_asset",
            "executable_resource",
        }:
            raise RuntimeError("native tray resources were not released")
        payload["status"] = "PASS"
        payload["failure_code"] = None
    except Exception:
        # Fail closed without placing exception text, paths or platform details in evidence.
        pass
    finally:
        if tray is not None:
            with suppress(Exception):
                tray.stop()
            payload["notification"] = tray.lifecycle_evidence()
        if root is not None:
            with suppress(Exception):
                root.destroy()
        payload["action_sequence"] = actions
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return payload["status"] == "PASS"


def _acquire_windows_mutex():
    if os.name != "nt":
        return object()
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return None
    return handle


def _release_windows_mutex(handle: object) -> None:
    if os.name == "nt" and handle is not None:
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.windll.kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(handle)


def _command_for_backend(instance: Path, port: int) -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        return [sys.executable, "--serve", str(instance), "--port", str(port)]
    return [
        sys.executable,
        "-m",
        "provelume.desktop",
        "--serve",
        str(instance),
        "--port",
        str(port),
    ]


def _configure_windows_identity() -> str:
    """Set taskbar grouping identity before any native window is created."""

    if os.name != "nt":
        return "not_applicable"
    try:
        import ctypes

        configure = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        configure.argtypes = [ctypes.c_wchar_p]
        configure.restype = ctypes.c_long
        result = configure(APP_USER_MODEL_ID)
        return "configured" if result == 0 else "failed"
    except (AttributeError, OSError, ValueError):
        return "failed"


def _versioned_icon_path() -> Path | None:
    candidates = [
        Path(getattr(sys, "_MEIPASS", "")) / "assets" / "provelume.ico",
        Path(__file__).resolve().parents[2] / "assets" / "windows" / "provelume.ico",
        Path(sys.executable).with_name("provelume.ico"),
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _icon_identity_payload() -> dict[str, Any]:
    path = _versioned_icon_path()
    if path is None:
        return {
            "status": "controlled_fallback_required",
            "sizes": [16, 20, 24, 32, 40, 48, 64, 128, 256],
            "sha256": None,
        }
    payload = path.read_bytes()
    return {
        "status": "versioned_asset",
        "sizes": [16, 20, 24, 32, 40, 48, 64, 128, 256],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }


def _window_dimensions(screen_width: int, screen_height: int) -> tuple[int, int]:
    """Fit the launcher inside reduced work areas while keeping its preferred size."""

    width = min(680, max(320, screen_width - 48))
    height = min(520, max(320, screen_height - 96))
    return width, height


def _configure_windows_dpi_awareness() -> str:
    """Request modern DPI handling before Tk creates a window, with safe fallbacks."""

    if os.name != "nt":
        return "not_applicable"
    try:
        import ctypes

        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per_monitor_v2"
    except (AttributeError, OSError, ValueError):
        pass
    try:
        import ctypes

        result = ctypes.windll.shcore.SetProcessDpiAwareness(1)
        if result in {0, -2147024891}:
            return "system_aware"
    except (AttributeError, OSError, ValueError):
        pass
    return "platform_default"


STRINGS = {
    "en": {
        "title": "Provelume Preview",
        "tagline": "Knowledge you can trace.",
        "installed": "Installed version",
        "instance": "Local Instance",
        "instance_ready": "Ready",
        "open": "Open Provelume",
        "stop": "Stop",
        "choose": "Choose existing…",
        "create": "Create new…",
        "updates": "Updates",
        "channel": "Channel",
        "check_start": "Check at startup (contacts GitHub)",
        "check_now": "Check now",
        "download": "Download update",
        "about": "About",
        "offline": "Local-first. No cloud or external AI is required.",
        "starting": "Starting the local service…",
        "running": "Running locally",
        "stopping": "Stopping the local service…",
        "stopped": "Stopped",
        "server_exited": "The local service stopped unexpectedly. You can start it again.",
        "checking": "Checking GitHub Releases…",
        "current": "This installation is up to date.",
        "available": "Version {version} is available.",
        "failed": "The update check failed: {error}",
        "downloading": "Downloading and verifying {version}…",
        "download_ready": "The verified installer is ready.",
        "network_notice": (
            "This check contacts GitHub Releases. It sends no Instance content. "
            "Continue?"
        ),
        "unsigned_notice": (
            "This preview installer is not Authenticode-signed. Its size and SHA-256 will be "
            "checked against the release metadata, but publisher authentication is not yet "
            "established. Download it?"
        ),
        "install_notice": "Start the installer now? Provelume will close first.",
        "invalid_instance": "The selected folder is not a valid Provelume Instance.",
        "missing_instance": (
            "The saved Provelume Instance could not be found. Choose its new location or create "
            "another Instance; no replacement was created automatically."
        ),
        "instance_open_failed": "The local Instance could not be opened: {error}",
        "server_failed": "The local service could not start.",
        "port_unavailable": (
            "The configured endpoint is occupied. Choose another explicit port or restore "
            "44851 in Shell settings. No random port was selected."
        ),
        "endpoint_rolled_back": (
            "The local service failed; the endpoint setting was rolled back to the previous "
            "known value. Restart explicitly after reviewing Shell settings."
        ),
        "shell_settings": "Shell settings",
        "endpoint": "Local endpoint",
        "tray_enabled": "Keep running in the system tray",
        "theme": "Theme",
        "already_running": "Provelume is already running.",
        "about_text": (
            "Provelume {version}\nChannel: {channel}\nTag: {tag}\nCommit: {commit}\n"
            "Package: {packaging}\nPlatform signature: {signature}\n\n"
            "About and version information are read locally."
        ),
    },
    "it": {
        "title": "Provelume Preview",
        "tagline": "Conoscenza di cui puoi ricostruire l'origine.",
        "installed": "Versione installata",
        "instance": "Istanza locale",
        "instance_ready": "Pronta",
        "open": "Apri Provelume",
        "stop": "Ferma",
        "choose": "Scegli esistente…",
        "create": "Crea nuova…",
        "updates": "Aggiornamenti",
        "channel": "Canale",
        "check_start": "Controlla all'avvio (contatta GitHub)",
        "check_now": "Controlla ora",
        "download": "Scarica aggiornamento",
        "about": "Informazioni",
        "offline": "Local-first. Non richiede cloud né AI esterna.",
        "starting": "Avvio del servizio locale…",
        "running": "In esecuzione in locale",
        "stopping": "Arresto del servizio locale…",
        "stopped": "Fermato",
        "server_exited": (
            "Il servizio locale si è arrestato in modo imprevisto. Puoi avviarlo di nuovo."
        ),
        "checking": "Controllo GitHub Releases…",
        "current": "Questa installazione è aggiornata.",
        "available": "È disponibile la versione {version}.",
        "failed": "Controllo aggiornamenti non riuscito: {error}",
        "downloading": "Download e verifica della versione {version}…",
        "download_ready": "L'installer verificato è pronto.",
        "network_notice": (
            "Questo controllo contatta GitHub Releases. Non invia contenuti dell'istanza. "
            "Continuare?"
        ),
        "unsigned_notice": (
            "Questo installer preview non ha ancora firma Authenticode. Dimensione e SHA-256 "
            "saranno confrontati con i metadati di release, ma l'autenticazione dell'editore "
            "non è ancora stabilita. Scaricarlo?"
        ),
        "install_notice": "Avviare ora l'installer? Provelume verrà prima chiuso.",
        "invalid_instance": "La cartella scelta non è un'istanza Provelume valida.",
        "missing_instance": (
            "L'istanza Provelume salvata non è stata trovata. Scegli la nuova posizione o crea "
            "un'altra istanza; non ne è stata creata automaticamente una sostitutiva."
        ),
        "instance_open_failed": "Impossibile aprire l'istanza locale: {error}",
        "server_failed": "Non è stato possibile avviare il servizio locale.",
        "port_unavailable": (
            "L'endpoint configurato è occupato. Scegli un'altra porta esplicita o ripristina "
            "44851 nelle impostazioni shell. Non è stata scelta una porta casuale."
        ),
        "endpoint_rolled_back": (
            "Il servizio locale non si è avviato; l'endpoint è stato ripristinato al precedente "
            "valore noto. Riavvia esplicitamente dopo aver verificato le impostazioni shell."
        ),
        "shell_settings": "Impostazioni shell",
        "endpoint": "Endpoint locale",
        "tray_enabled": "Mantieni in esecuzione nell'area di notifica",
        "theme": "Tema",
        "already_running": "Provelume è già in esecuzione.",
        "about_text": (
            "Provelume {version}\nCanale: {channel}\nTag: {tag}\nCommit: {commit}\n"
            "Pacchetto: {packaging}\nFirma di piattaforma: {signature}\n\n"
            "Le informazioni su versione e prodotto sono lette in locale."
        ),
    },
}


class DesktopShell:
    def __init__(
        self,
        root,
        *,
        initial_settings: LauncherSettings,
        create_instance_if_missing: bool = True,
        auto_start_service: bool = True,
        enable_native_tray: bool = True,
    ):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.settings = initial_settings.normalized()
        self.settings_manager = ShellSettingsManager(settings_path(), default_settings())
        self.text = STRINGS[self.settings.language]
        self.instance = Path(self.settings.instance_path).expanduser()
        self.server: subprocess.Popen[bytes] | None = None
        self.server_port: int | None = None
        self.server_ready = False
        self.open_target: str | None = None
        self.instance_available = False
        self.candidate: UpdateCandidate | None = None
        self.update_generation = 0
        self.closed = False
        self.tray: WindowsTray | None = None

        self.status = tk.StringVar(value=self.text["instance_ready"])
        self.update_status = tk.StringVar(value=self.text["current"])
        self.instance_text = tk.StringVar(value=str(self.instance))
        self.check_on_start = tk.BooleanVar(value=self.settings.check_on_start)
        self.channel = tk.StringVar(value=self.settings.update_channel)

        instance_error: str | None = None
        try:
            self._ensure_instance(
                self.instance,
                create_if_missing=create_instance_if_missing,
            )
        except RuntimeError as exc:
            instance_error = str(exc)
        else:
            self.instance_available = True
            declare_startup_update_policy(
                self.instance,
                enabled=self.settings.check_on_start,
            )
        self._build()
        if instance_error is not None:
            self._show_instance_error(instance_error)
        self.root.protocol("WM_DELETE_WINDOW", self.window_close)
        if os.name == "nt" and self.settings.tray_enabled and enable_native_tray:
            endpoint = f"http://127.0.0.1:{self.settings.endpoint_port}"
            self.tray = WindowsTray(
                self.root,
                state=TrayState(
                    language=self.settings.language,
                    service_status="stopped",
                    endpoint=endpoint,
                ),
                open_interface=self.show_window,
                open_settings=self.open_shell_settings,
                restart_service=self.restart_server,
                quit_application=self.close,
                icon_path=_versioned_icon_path(),
            )
            if not self.tray.start():
                self.tray = None
        if auto_start_service and self.instance_available:
            self.root.after(250, self.start_server)
        if self.settings.check_on_start and self.instance_available:
            self.root.after(400, lambda: self.check_updates(interactive=False))

    def _build(self) -> None:
        ttk = self.ttk
        root = self.root
        root.title(self.text["title"])
        icon = _versioned_icon_path()
        if icon is not None and os.name == "nt":
            with suppress(self.tk.TclError):
                root.iconbitmap(default=str(icon))
        width, height = _window_dimensions(root.winfo_screenwidth(), root.winfo_screenheight())
        root.geometry(f"{width}x{height}")
        root.minsize(min(520, width), min(360, height))

        viewport = ttk.Frame(root)
        viewport.pack(fill="both", expand=True)
        canvas = self.tk.Canvas(viewport, highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        outer = ttk.Frame(canvas, padding=24)
        content_window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_window, width=event.width),
        )
        self.scroll_canvas = canvas

        title = ttk.Label(outer, text="Provelume", font=("Segoe UI", 24, "bold"))
        title.pack(anchor="w")
        ttk.Label(outer, text=self.text["tagline"]).pack(anchor="w", pady=(0, 20))

        identity = ttk.LabelFrame(outer, text=self.text["installed"], padding=14)
        identity.pack(fill="x", pady=(0, 14))
        about = current_about()
        ttk.Label(
            identity,
            text=f"{about['version']} · {about['channel']} · {about['runtime']['packaging']}",
        ).pack(side="left")
        ttk.Button(identity, text=self.text["about"], command=self.show_about).pack(side="right")

        instance = ttk.LabelFrame(outer, text=self.text["instance"], padding=14)
        instance.pack(fill="x", pady=(0, 14))
        ttk.Label(instance, textvariable=self.instance_text).pack(anchor="w")
        ttk.Label(
            instance,
            textvariable=self.status,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))
        row = ttk.Frame(instance)
        row.pack(fill="x")
        self.open_button = ttk.Button(
            row,
            text=self.text["open"],
            command=self.open_product,
            state="normal",
        )
        self.open_button.pack(side="left")
        self.stop_button = ttk.Button(
            row,
            text=self.text["stop"],
            command=self.stop_server,
            state="disabled",
        )
        self.stop_button.pack(side="left", padx=8)
        self.choose_button = ttk.Button(
            row,
            text=self.text["choose"],
            command=self.choose_instance,
        )
        self.choose_button.pack(side="right")
        self.create_button = ttk.Button(
            row,
            text=self.text["create"],
            command=self.create_instance,
        )
        self.create_button.pack(side="right", padx=8)

        shell = ttk.LabelFrame(outer, text=self.text["shell_settings"], padding=14)
        shell.pack(fill="x", pady=(0, 14))
        ttk.Label(
            shell,
            text=(
                f"{self.text['endpoint']}: http://127.0.0.1:{self.settings.endpoint_port} · "
                f"{self.text['theme']}: {self.settings.theme}"
            ),
            wraplength=560,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            shell,
            text=self.text["shell_settings"],
            command=self.open_shell_settings,
        ).pack(side="right")

        updates = ttk.LabelFrame(outer, text=self.text["updates"], padding=14)
        updates.pack(fill="x", pady=(0, 14))
        policy = ttk.Frame(updates)
        policy.pack(fill="x")
        ttk.Label(policy, text=self.text["channel"]).pack(side="left")
        channels = ttk.Combobox(
            policy,
            textvariable=self.channel,
            values=("preview", "stable"),
            state="readonly",
            width=10,
        )
        channels.pack(side="left", padx=8)
        channels.bind("<<ComboboxSelected>>", lambda _event: self._save_policy())
        ttk.Checkbutton(
            policy,
            text=self.text["check_start"],
            variable=self.check_on_start,
            command=self._save_policy,
        ).pack(side="right")
        ttk.Label(updates, textvariable=self.update_status, wraplength=600).pack(
            anchor="w", pady=(10, 10)
        )
        actions = ttk.Frame(updates)
        actions.pack(fill="x")
        self.check_button = ttk.Button(
            actions,
            text=self.text["check_now"],
            command=self.check_updates,
            state="normal",
        )
        self.check_button.pack(side="left")
        self.download_button = ttk.Button(
            actions,
            text=self.text["download"],
            command=self.download_candidate,
            state="disabled",
        )
        self.download_button.pack(side="left", padx=8)

        ttk.Label(outer, text=self.text["offline"]).pack(anchor="w", pady=(6, 0))

    def _show_instance_error(self, message: str) -> None:
        self.instance_available = False
        self.status.set(message)
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.choose_button.configure(state="normal")
        self.create_button.configure(state="normal")

    def _ensure_instance(self, path: Path, *, create_if_missing: bool) -> None:
        try:
            created = not (path / "provelume.yml").is_file()
            if (path / "provelume.yml").is_file():
                instance = ProvelumeInstance(path)
            elif not create_if_missing:
                raise RuntimeError(self.text["missing_instance"])
            else:
                instance = ProvelumeInstance.initialise(path, name="My Provelume")
            if created:
                config = instance.store.read_config()
                config.setdefault("ui", {})["language"] = self.settings.language
                instance.store.write_config(config)
        except RuntimeError:
            raise
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                self.text["instance_open_failed"].format(error=exc)
            ) from exc

    def _replace_settings(self, **changes: object) -> None:
        def change(current: LauncherSettings) -> LauncherSettings:
            values = asdict(current)
            values.update(changes)
            return LauncherSettings(**values).normalized()

        self.settings = self.settings_manager.mutate(change)

    def _save_policy(self) -> None:
        previous_channel = self.settings.update_channel
        self._replace_settings(
            update_channel=self.channel.get(),
            check_on_start=self.check_on_start.get(),
        )
        if self.instance_available:
            declare_startup_update_policy(
                self.instance,
                enabled=self.settings.check_on_start,
            )
        if self.settings.update_channel != previous_channel:
            self._invalidate_update_result()

    def _select_instance(self, path: Path) -> None:
        ProvelumeInstance(path)
        self.stop_server()
        self.instance = path.expanduser().resolve()
        self.instance_available = True
        self.instance_text.set(str(self.instance))
        self.status.set(self.text["instance_ready"])
        self.open_button.configure(state="normal")
        self.choose_button.configure(state="normal")
        self.create_button.configure(state="normal")
        self._replace_settings(instance_path=str(self.instance))
        declare_startup_update_policy(
            self.instance,
            enabled=self.settings.check_on_start,
        )

    def choose_instance(self) -> None:
        from tkinter import filedialog, messagebox

        selected = filedialog.askdirectory(initialdir=str(self.instance.parent))
        if not selected:
            return
        try:
            self._select_instance(Path(selected))
        except (OSError, ValueError):
            messagebox.showerror("Provelume", self.text["invalid_instance"])

    def create_instance(self) -> None:
        from tkinter import filedialog, messagebox, simpledialog

        selected = filedialog.askdirectory(initialdir=str(self.instance.parent))
        if not selected:
            return
        name = simpledialog.askstring(
            "Provelume",
            self.text["instance"],
            initialvalue="My Provelume",
        )
        if name is None:
            return
        try:
            instance = ProvelumeInstance.initialise(
                Path(selected),
                name=name.strip() or "My Provelume",
            )
            config = instance.store.read_config()
            config.setdefault("ui", {})["language"] = self.settings.language
            instance.store.write_config(config)
            self._select_instance(Path(selected))
        except (OSError, ValueError):
            messagebox.showerror("Provelume", self.text["invalid_instance"])

    def open_product(self) -> None:
        if self.server is not None and self.server.poll() is None and self.server_port is not None:
            if self.server_ready:
                webbrowser.open(f"http://127.0.0.1:{self.server_port}/")
            else:
                self.open_target = "/"
            return
        self.start_server(open_target="/")

    def start_server(self, *, open_target: str | None = None) -> None:
        try:
            ProvelumeInstance(self.instance)
        except (OSError, ValueError):
            from tkinter import messagebox

            self._show_instance_error(self.text["invalid_instance"])
            messagebox.showerror("Provelume", self.text["invalid_instance"])
            return
        loaded = self.settings_manager.load()
        self.settings = loaded.settings
        port = self.settings.endpoint_port
        if not probe_port(port)["available"]:
            self.status.set(self.text["port_unavailable"])
            self.open_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._update_tray("occupied")
            return
        command = _command_for_backend(self.instance, port)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self.server = process
        self.server_port = port
        self.server_ready = False
        self.open_target = open_target
        self.status.set(self.text["starting"])
        self._update_tray("starting")
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        threading.Thread(
            target=self._wait_for_server,
            args=(process, port),
            daemon=True,
        ).start()

    def open_shell_settings(self) -> None:
        target = f"/settings/shell?lang={self.settings.language}"
        if self.server is not None and self.server.poll() is None and self.server_ready:
            webbrowser.open(f"http://127.0.0.1:{self.server_port}{target}")
            return
        self.start_server(open_target=target)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        with suppress(Exception):
            self.root.focus_force()

    def _update_tray(self, status: str) -> None:
        tray = getattr(self, "tray", None)
        if tray is not None:
            port = self.server_port or self.settings.endpoint_port
            tray.update(
                service_status=status,
                endpoint=f"http://127.0.0.1:{port}",
            )

    def _wait_for_server(self, process: subprocess.Popen[bytes], port: int) -> None:
        url = f"http://127.0.0.1:{port}/health"
        ready = False
        for _attempt in range(60):
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=0.5) as response:
                    ready = response.status == 200
                if ready:
                    break
            except OSError:
                time.sleep(0.15)
        if self.closed:
            return
        self.root.after(0, lambda: self._server_ready(process, port, ready))
        if ready:
            exit_code = process.wait()
            if not self.closed:
                self.root.after(
                    0,
                    lambda: self._server_exited(process, port, exit_code),
                )

    def _server_ready(
        self,
        process: subprocess.Popen[bytes],
        port: int,
        ready: bool,
    ) -> None:
        if self.closed or self.server is not process or self.server_port != port:
            return
        if ready and process.poll() is None:
            self.server_ready = True
            self.status.set(self.text["running"])
            self._update_tray("running")
            self.open_button.configure(state="normal")
            self.stop_button.configure(state="normal")
            manager = getattr(self, "settings_manager", None)
            if manager is not None and self.settings.restart_required:
                with suppress(ShellSettingsError):
                    self.settings = manager.mark_endpoint_started(
                        port,
                        expected_revision=self.settings.revision,
                    )
            target = getattr(self, "open_target", "/")
            self.open_target = None
            if target is not None:
                webbrowser.open(f"http://127.0.0.1:{port}{target}")
        else:
            rolled_back = False
            manager = getattr(self, "settings_manager", None)
            settings = getattr(self, "settings", None)
            if (
                manager is not None
                and settings is not None
                and settings.restart_required
                and settings.last_good_port != settings.endpoint_port
            ):
                try:
                    self.settings = manager.rollback_endpoint(
                        expected_revision=settings.revision,
                    )
                    rolled_back = True
                except ShellSettingsError:
                    pass
            self.stop_server(
                final_status="endpoint_rolled_back" if rolled_back else "server_failed"
            )

    def _server_exited(
        self,
        process: subprocess.Popen[bytes],
        port: int,
        _exit_code: int,
    ) -> None:
        if self.closed or self.server is not process or self.server_port != port:
            return
        self.server = None
        self.server_port = None
        self.server_ready = False
        self.status.set(self.text["server_exited"])
        self._update_tray("crashed")
        self.open_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def stop_server(self, *, final_status: str = "stopped") -> None:
        process = self.server
        self.server = None
        self.server_port = None
        self.server_ready = False
        if process is not None and process.poll() is None:
            if not self.closed:
                self.status.set(self.text["stopping"])
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if not self.closed:
                        self.status.set(self.text["server_failed"])
        if not self.closed:
            self.status.set(self.text[final_status])
            self._update_tray(final_status)
            self.open_button.configure(
                state="normal" if self.instance_available else "disabled"
            )
            self.stop_button.configure(state="disabled")

    def restart_server(self) -> None:
        self.stop_server()
        self.root.after(100, self.start_server)

    def window_close(self) -> None:
        manager = getattr(self, "settings_manager", None)
        if manager is not None:
            self.settings = manager.load().settings
        if self.settings.tray_enabled and self.tray is not None:
            self.root.withdraw()
            self._update_tray("running" if self.server_ready else "stopped")
            return
        self.close()

    def check_updates(self, interactive: bool = True) -> None:
        if not interactive and not startup_update_policy_enabled(self.instance):
            return
        if interactive:
            from tkinter import messagebox

            if not messagebox.askyesno("Provelume", self.text["network_notice"]):
                return
        self.update_generation += 1
        generation = self.update_generation
        self.candidate = None
        self.update_status.set(self.text["checking"])
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="disabled")
        channel = self.channel.get()
        threading.Thread(
            target=self._check_updates_worker,
            args=(channel, generation),
            daemon=True,
        ).start()

    def _check_updates_worker(self, channel: str, generation: int) -> None:
        try:
            result = check_for_updates(
                current_version=__version__,
                channel=channel,
            )
            candidate = (
                UpdateCandidate(**result["candidate"])
                if result.get("candidate") is not None
                else None
            )
        except (OSError, UpdateError, TypeError, ValueError) as exc:
            message = str(exc)
            if not self.closed:
                self.root.after(
                    0,
                    lambda: self._update_failed(message, generation, channel),
                )
            return
        if not self.closed:
            self.root.after(
                0,
                lambda: self._update_checked(candidate, generation, channel),
            )

    def _is_current_update_request(self, generation: int, channel: str) -> bool:
        return (
            not self.closed
            and generation == self.update_generation
            and channel == self.channel.get()
        )

    def _invalidate_update_result(self) -> None:
        self.update_generation += 1
        self.candidate = None
        self.update_status.set(self.text["current"])
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="normal")

    def _update_failed(self, error: str, generation: int, channel: str) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = None
        self.update_status.set(self.text["failed"].format(error=error))
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="normal")

    def _update_checked(
        self,
        candidate: UpdateCandidate | None,
        generation: int,
        channel: str,
    ) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = candidate
        self.check_button.configure(state="normal")
        if candidate is None:
            self.update_status.set(self.text["current"])
            self.download_button.configure(state="disabled")
        else:
            self.update_status.set(self.text["available"].format(version=candidate.version))
            self.download_button.configure(state="normal")

    def download_candidate(self) -> None:
        from tkinter import messagebox

        candidate = self.candidate
        if candidate is None:
            return
        if not messagebox.askyesno("Provelume", self.text["unsigned_notice"]):
            return
        self.update_status.set(self.text["downloading"].format(version=candidate.version))
        self.download_button.configure(state="disabled")
        threading.Thread(
            target=self._download_worker,
            args=(candidate, self.update_generation, self.channel.get()),
            daemon=True,
        ).start()

    def _download_worker(
        self,
        candidate: UpdateCandidate,
        generation: int,
        channel: str,
    ) -> None:
        try:
            destination = state_directory() / "updates" / candidate.version
            path = download_update(candidate, destination)
        except (OSError, UpdateError) as exc:
            message = str(exc)
            if not self.closed:
                self.root.after(
                    0,
                    lambda: self._update_failed(message, generation, channel),
                )
            return
        if not self.closed:
            self.root.after(
                0,
                lambda: self._installer_ready(path, candidate, generation, channel),
            )

    def _installer_ready(
        self,
        path: Path,
        candidate: UpdateCandidate,
        generation: int,
        channel: str,
    ) -> None:
        from tkinter import messagebox

        if (
            not self._is_current_update_request(generation, channel)
            or self.candidate != candidate
        ):
            return
        self.update_status.set(self.text["download_ready"])
        if not messagebox.askyesno("Provelume", self.text["install_notice"]):
            self.download_button.configure(state="normal")
            return
        self.stop_server()
        subprocess.Popen([str(path)], cwd=str(path.parent))
        self.close()

    def show_about(self) -> None:
        from tkinter import messagebox

        about = current_about()
        messagebox.showinfo(
            self.text["about"],
            self.text["about_text"].format(
                version=about["version"],
                channel=about["channel"],
                tag=about["tag"] or "—",
                commit=about["commit"] or "—",
                packaging=about["runtime"]["packaging"],
                signature=about["updates"]["platform_signature"],
            ),
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.stop_server()
        if self.tray is not None:
            self.tray.stop()
            self.tray = None
        self.root.destroy()


def run_ui(*, start_hidden: bool = False) -> int:
    _configure_windows_identity()
    _configure_windows_dpi_awareness()
    import tkinter as tk
    from tkinter import messagebox

    mutex = _acquire_windows_mutex()
    if mutex is None:
        root = tk.Tk()
        root.withdraw()
        icon = _versioned_icon_path()
        if icon is not None and os.name == "nt":
            with suppress(tk.TclError):
                root.iconbitmap(default=str(icon))
        language = load_settings().language
        messagebox.showinfo("Provelume", STRINGS[language]["already_running"])
        root.destroy()
        return 0
    try:
        root = tk.Tk()
        try:
            with suppress(ShellSettingsError, OSError):
                ShellSettingsManager(settings_path(), default_settings()).recover_abandoned_writes()
            persisted_settings = settings_path().is_file()
            shell = DesktopShell(
                root,
                initial_settings=load_settings(),
                create_instance_if_missing=not persisted_settings,
            )
            if start_hidden and shell.tray is not None:
                root.withdraw()
        except RuntimeError as exc:
            root.withdraw()
            messagebox.showerror("Provelume", str(exc))
            root.destroy()
            return 1
        root.mainloop()
        return 0
    finally:
        _release_windows_mutex(mutex)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Provelume", add_help=True)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument(
        "--tray",
        action="store_true",
        help="start the installed Windows shell using its configured tray preference",
    )
    parser.add_argument("--diagnostics-file", type=Path)
    parser.add_argument("--native-tray-smoke-file", type=Path)
    parser.add_argument("--ui-diagnostics-file", type=Path)
    parser.add_argument("--ui-diagnostics-language", choices=("en", "it"), default="en")
    parser.add_argument(
        "--ui-diagnostics-dpi",
        type=int,
        choices=(100, 125, 150, 200),
        default=100,
    )
    parser.add_argument("--ui-diagnostics-width", type=int, default=800)
    parser.add_argument("--ui-diagnostics-height", type=int, default=600)
    parser.add_argument("--bootstrap-instance", type=Path)
    parser.add_argument("--instance-name", default="My Provelume")
    parser.add_argument("--validate-port", type=int)
    parser.add_argument("--initialize-shell-settings", action="store_true")
    parser.add_argument("--remove-login-startup", action="store_true")
    parser.add_argument("--install-port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--install-language", choices=("en", "it"), default="en")
    parser.add_argument(
        "--install-tray",
        choices=("enabled", "disabled"),
        default="enabled",
    )
    parser.add_argument(
        "--install-login-startup",
        choices=("enabled", "disabled"),
        default="disabled",
    )
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    selected_modes = sum(
        value is not None
        for value in (
            options.serve,
            options.diagnostics_file,
            options.native_tray_smoke_file,
            options.ui_diagnostics_file,
            options.bootstrap_instance,
            options.validate_port,
            True if options.initialize_shell_settings else None,
            True if options.remove_login_startup else None,
        )
    )
    if selected_modes > 1:
        raise SystemExit("select only one desktop execution mode")
    if options.diagnostics_file is not None:
        write_diagnostics(options.diagnostics_file)
        return 0
    if options.native_tray_smoke_file is not None:
        return 0 if write_native_tray_smoke(options.native_tray_smoke_file) else 2
    if options.ui_diagnostics_file is not None:
        write_ui_diagnostics(
            options.ui_diagnostics_file,
            language=options.ui_diagnostics_language,
            dpi_percent=options.ui_diagnostics_dpi,
            viewport_width=options.ui_diagnostics_width,
            viewport_height=options.ui_diagnostics_height,
        )
        return 0
    if options.bootstrap_instance is not None:
        ProvelumeInstance.initialise(
            options.bootstrap_instance,
            name=options.instance_name,
        )
        return 0
    if options.validate_port is not None:
        try:
            result = probe_port(options.validate_port)
        except ShellSettingsError:
            return 2
        return 0 if result["available"] else 2
    if options.initialize_shell_settings:
        selected = settings_path()
        if selected.exists():
            try:
                existing = load_settings(selected)
                configure_login_startup(
                    existing.login_startup,
                    command=sys.executable,
                )
            except (OSError, ShellSettingsError):
                return 2
            return 0
        try:
            port = validate_port(options.install_port)
            if not probe_port(port)["available"]:
                return 2
            login_startup = options.install_login_startup == "enabled"
            configure_login_startup(
                login_startup,
                command=sys.executable,
            )
            try:
                save_settings(
                    LauncherSettings(
                        instance_path=str(Path.home() / "Documents" / "Provelume"),
                        language=options.install_language,
                        endpoint_port=port,
                        last_good_port=port,
                        tray_enabled=options.install_tray == "enabled",
                        login_startup=login_startup,
                    )
                )
            except (OSError, ShellSettingsError):
                with suppress(OSError, ShellSettingsError):
                    configure_login_startup(False, command=sys.executable)
                raise
        except (OSError, ShellSettingsError):
            return 2
        return 0
    if options.remove_login_startup:
        try:
            configure_login_startup(False, command=sys.executable)
        except (OSError, ShellSettingsError):
            return 2
        return 0
    if options.serve is not None:
        try:
            selected_port = effective_port(
                explicit_port=options.port,
                persisted=load_settings(),
            )["port"]
            validate_port(selected_port)
        except ShellSettingsError as exc:
            raise SystemExit(str(exc)) from exc
        app = create_app(options.serve, effective_port=selected_port)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=selected_port,
            log_level="warning",
            log_config=None,
            access_log=False,
        )
        return 0
    return run_ui(start_hidden=options.tray)


if __name__ == "__main__":
    raise SystemExit(main())
