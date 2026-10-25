from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from contextlib import suppress
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import uvicorn

from . import __version__
from .about import RELEASES_URL, current_about
from .about import SOURCE_REPOSITORY_URL as SOURCE_REPOSITORY_URL
from .about import public_about_links as public_about_links
from .catalog_registry import exported_catalogs, namespace_catalog, resolve_language
from .instance_lifecycle import InstanceLifecycleBusy
from .publication import RECEIPT_NAME, PublicationError, import_publication
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
from .startup_process import ManagedStartup
from .startup_readiness import (
    ReadinessContext,
    StartupReadinessError,
    bootstrap_stdin,
    read_bootstrap,
)
from .updates import SOURCE_REPOSITORY as SOURCE_REPOSITORY
from .updates import (
    UpdateCandidate,
    UpdateError,
    check_for_updates,
    download_update,
)
from .web import create_app
from .windows_tray import TRAY_LABELS, TrayState, WindowsTray

SETTINGS_SCHEMA_VERSION = SHELL_SETTINGS_SCHEMA_VERSION
DESKTOP_DIAGNOSTICS_SCHEMA_VERSION = 2
MUTEX_NAME = "Local\\ProvelumeDesktop"


def format_update_failure(error: BaseException, text: dict[str, str]) -> str:
    """Render a bounded localized diagnostic without exposing raw response data."""

    code = getattr(error, "code", "unexpected")
    detail = text.get(f"update_error_{code}", text["update_error_unexpected"])
    context: list[str] = []
    stage = getattr(error, "stage", None)
    if stage:
        context.append(text.get(f"update_stage_{stage}", stage))
    origin = getattr(error, "endpoint_origin", None)
    if origin in {"https://api.github.com", "https://github.com"}:
        context.append(origin)
    status = getattr(error, "http_status", None)
    if type(status) is int and 400 <= status <= 599:
        context.append(f"HTTP {status}")
    code_label = f"{text['diagnostic_code']}: {code}"
    context.append(code_label)
    return f"{detail} ({' · '.join(context)})"


def load_settings(path: Path | None = None) -> LauncherSettings:
    selected = path or settings_path()
    return ShellSettingsManager(selected, default_settings()).load().settings


def save_settings(settings: LauncherSettings, path: Path | None = None) -> Path:
    selected = path or settings_path()
    return ShellSettingsManager(selected, default_settings()).save(settings)


def declare_startup_update_policy(instance_path: Path, *, enabled: bool) -> None:
    """Declare a component preference without changing independent global consent."""

    # A concurrent canonical commit can expose a pending transaction while holding
    # the lifecycle lock. Wait before opening, without reversing lifecycle/policy
    # lock order or retrying any policy write.
    deadline = time.monotonic() + 2.0
    while True:
        try:
            instance = ProvelumeInstance(instance_path)
            break
        except InstanceLifecycleBusy:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(0.025, remaining))
    with instance.connectors.policy_commit_guard(purpose="startup-update-policy"):
        config = instance.store.read_config()
        network = config.setdefault("network", {})
        if not isinstance(network, dict):
            raise ValueError("Instance network configuration must be an object")
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
        "settings_schema_version": loaded.settings.schema_version,
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
    theme: str = "system",
) -> Path:
    """Build the real Tk launcher off-loop and record bounded layout evidence."""

    if language not in STRINGS:
        raise ValueError("UI diagnostics language must be registered")
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
                    theme=theme,
                ),
                auto_start_service=False,
                enable_native_tray=False,
                enable_first_run_dialog=False,
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
            from .shell_appearance import appearance_evidence

            appearance = appearance_evidence(root, shell.channel_box)
            measured = [shell.open_button, shell.stop_button, shell.choose_button,
                        shell.create_button, shell.check_button, shell.download_button,
                        shell.channel_box, shell.startup_check, shell.shell_settings_button]
            control_bounds = [{"requested_width": widget.winfo_reqwidth(),
                               "width": widget.winfo_width(),
                               "requested_height": widget.winfo_reqheight(),
                               "height": widget.winfo_height()} for widget in measured]
            payload = {
                "schema_version": 1,
                "language": language,
                "theme": theme,
                "appearance": appearance,
                "control_bounds": control_bounds,
                "controls_fit": all(row["requested_width"] <= row["width"]
                                    and row["requested_height"] <= row["height"]
                                    for row in control_bounds),
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
            open_launcher=lambda: actions.append("launcher"),
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
        for command_id in (1, 7, 2, 3, 4):
            tray.exercise_action(command_id)
        root.update_idletasks()
        root.update()
        if actions != ["open", "launcher", "settings", "restart", "quit"]:
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
        Path(__file__).resolve().parent / "static" / "brand" / "provelume.ico",
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


STRINGS = exported_catalogs("desktop.STRINGS")


class DesktopShell:
    def __init__(
        self,
        root,
        *,
        initial_settings: LauncherSettings,
        create_instance_if_missing: bool = True,
        auto_start_service: bool = True,
        enable_native_tray: bool = True,
        enable_first_run_dialog: bool = True,
    ):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.settings = initial_settings.normalized()
        from .shell_appearance import apply_native_appearance

        self.appearance = apply_native_appearance(self.root, self.settings.theme)
        self.settings_manager = ShellSettingsManager(settings_path(), default_settings())
        self.text = STRINGS[resolve_language(self.settings.language)]
        self.instance = Path(self.settings.instance_path).expanduser()
        self.server: subprocess.Popen[bytes] | None = None
        self.server_port: int | None = None
        self.server_ready = False
        self.open_target: str | None = None
        self.instance_available = False
        self._instance_error_observed = False
        self.candidate: UpdateCandidate | None = None
        self.update_generation = 0
        self.closed = False
        self._startup: ManagedStartup | None = None
        self._startup_poll_scheduled = False
        self._startup_status_on_finish = "stopped"
        self._restart_after_stop = False
        self._close_requested = False
        self._pending_instance: Path | None = None
        self._pending_installer = None
        self._initial_instance_preparation = auto_start_service
        self._startup_update_check_pending = auto_start_service
        self._initial_creation_allowed = create_instance_if_missing
        self._initial_creation_consumed = threading.Event()
        self.tray: WindowsTray | None = None
        self._tray_close_explained = False
        self._tray_observation_running = False

        self.status = tk.StringVar(value=self.text[
            "startup_preparing" if auto_start_service else "instance_ready"
        ])
        self.update_status = tk.StringVar(value=self.text["not_checked"])
        self.instance_text = tk.StringVar(value=str(self.instance))
        self.check_on_start = tk.BooleanVar(value=self.settings.check_on_start)
        self.channel = tk.StringVar(value=self.settings.update_channel)

        instance_error: str | None = None
        if not auto_start_service:
            # Offline layout diagnostics use their own disposable fixture and
            # request no service or interactive startup lifecycle.
            try:
                self._ensure_instance(self.instance, create_if_missing=create_instance_if_missing)
            except RuntimeError as exc:
                instance_error = str(exc)
            else:
                self.instance_available = True
                declare_startup_update_policy(self.instance, enabled=self.settings.check_on_start)
        self._build()
        if auto_start_service:
            self.check_button.configure(state="disabled")
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
                open_interface=self.open_product,
                open_launcher=self.show_window,
                open_settings=self.open_shell_settings,
                restart_service=self.restart_server,
                quit_application=self.close,
                icon_path=_versioned_icon_path(),
                open_queue=self.open_queue_status,
                pause_resume=self.open_queue_controls,
            )
            if not self.tray.start():
                self.tray = None
            else:
                self.root.after(1000, self._refresh_tray_queue)
        if enable_first_run_dialog and self.settings.revision == 0:
            self.root.after(0, self.show_first_run)
        if auto_start_service:
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
        brand_png = Path(__file__).resolve().parent / "static" / "brand" / "provelume-48.png"
        if brand_png.is_file():
            with suppress(self.tk.TclError):
                self.brand_image = self.tk.PhotoImage(file=str(brand_png))
                title.configure(image=self.brand_image, compound="left", padding=(0, 0, 8, 0))
        title.pack(anchor="w")
        ttk.Label(outer, text=self.text["launcher_hint"], wraplength=560,
                  justify="left").pack(anchor="w", fill="x", pady=(6, 16))

        identity = ttk.LabelFrame(outer, text=self.text["installed"], padding=14)
        identity.pack(fill="x", pady=(0, 14))
        about = current_about()
        ttk.Label(
            identity,
            text=f"{about['version']} · {about['channel']}",
        ).pack(side="left")
        ttk.Button(identity, text=self.text["about"], command=self.show_about).pack(side="right")

        instance = ttk.LabelFrame(outer, text=self.text["instance"], padding=14)
        instance.pack(fill="x", pady=(0, 14))
        ttk.Label(instance, textvariable=self.instance_text, wraplength=520,
                  justify="left").pack(anchor="w", fill="x")
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
            style="Primary.TButton",
        )
        self.stop_button = ttk.Button(
            row,
            text=self.text["stop"],
            command=self.stop_server,
            state="disabled",
        )
        self.startup_details_button = ttk.Button(
            row, text=self.text["startup_details"], command=self.show_startup_diagnostics,
        )
        self._responsive_actions(row, [self.open_button, self.stop_button,
                                       self.startup_details_button])
        locations = ttk.Frame(instance)
        locations.pack(fill="x", pady=(8, 0))
        self.choose_button = ttk.Button(
            locations,
            text=self.text["choose"],
            command=self.choose_instance,
        )
        self.create_button = ttk.Button(
            locations,
            text=self.text["create"],
            command=self.create_instance,
        )
        self._responsive_actions(locations, [self.create_button, self.choose_button])

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
        ).pack(anchor="w", fill="x")
        self.shell_settings_button = ttk.Button(
            shell,
            text=self.text["shell_settings"],
            command=self.open_shell_settings,
        )
        self.shell_settings_button.pack(fill="x", pady=(8, 0))

        updates = ttk.LabelFrame(outer, text=self.text["updates"], padding=14)
        updates.pack(fill="x", pady=(0, 14))
        policy = ttk.Frame(updates)
        policy.pack(fill="x", anchor="w")
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
        self.channel_box = channels
        self.startup_check = ttk.Checkbutton(
            updates,
            text=self.text["check_start"],
            variable=self.check_on_start,
            command=self._save_policy,
            style="Startup.TCheckbutton",
        )
        self.startup_check.pack(anchor="w", pady=(4, 0))
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
        self.download_button = ttk.Button(
            actions,
            text=self.text["download"],
            command=self.download_candidate,
            state="disabled",
        )
        self._responsive_actions(actions, [self.check_button, self.download_button])

        ttk.Label(outer, text=self.text["offline"]).pack(anchor="w", pady=(6, 0))
        def fit_text(event):
            self.ttk.Style(root).configure("Startup.TCheckbutton",
                                           wraplength=max(120, event.width - 90))
            for frame in (outer, instance, shell, updates):
                for widget in frame.winfo_children():
                    if widget.winfo_class() == "TLabel" and widget.cget("wraplength"):
                        widget.configure(wraplength=max(120, event.width - 60))
        outer.bind("<Configure>", fit_text, add="+")
        def scroll(event):
            if event.widget.winfo_toplevel() is root and event.widget.winfo_class() != "TCombobox":
                canvas.yview_scroll(-int(event.delta / 120), "units")
                return "break"
        root.bind("<MouseWheel>", scroll, add="+")

    def _responsive_actions(self, frame, buttons) -> None:
        """Keep every action reachable at high DPI without truncating its label."""
        layout = None
        def arrange(event=None):
            nonlocal layout
            width = event.width if event is not None else frame.winfo_width()
            columns = len(buttons) if sum(b.winfo_reqwidth() + 8 for b in buttons) <= width else 1
            if layout == columns:
                return
            layout = columns
            for index, button in enumerate(buttons):
                frame.columnconfigure(index, weight=1 if index < columns else 0)
                button.grid(row=index // columns, column=index % columns, sticky="ew",
                            padx=(0, 8) if columns > 1 and index < columns - 1 else 0,
                            pady=(0, 6) if columns == 1 and index < len(buttons) - 1 else 0)
        frame.bind("<Configure>", arrange)
        arrange()

    def _show_instance_error(self, message: str) -> None:
        self.instance_available = False
        self._instance_error_observed = True
        self.status.set(message)
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.choose_button.configure(state="normal")
        self.create_button.configure(state="normal")

    def _ensure_instance(self, path: Path, *, create_if_missing: bool,
                         language: str | None = None) -> None:
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
                config.setdefault("ui", {})["language"] = (
                    self.settings.language if language is None else language
                )
                instance.store.write_config(config)
        except RuntimeError:
            raise
        except (OSError, ValueError) as exc:
            raise RuntimeError(self.text["instance_open_failed"].format(error=exc)) from exc

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
        self._pending_installer = None
        startup = getattr(self, "_startup", None)
        if startup is not None and not startup.done.is_set():
            if startup.cleanup_unconfirmed:
                self._show_startup_unconfirmed()
                return
            self._pending_instance = path
            self.stop_server()
            return
        ProvelumeInstance(path)
        self.stop_server()
        self.instance = path.expanduser().resolve()
        self.instance_available = True
        self._instance_error_observed = False
        self.instance_text.set(str(self.instance))
        self.status.set(self.text["instance_ready"])
        self.open_button.configure(state="normal")
        self.choose_button.configure(state="normal")
        self.create_button.configure(state="normal")
        self.check_button.configure(state="normal")
        self._replace_settings(instance_path=str(self.instance))
        declare_startup_update_policy(
            self.instance,
            enabled=self.settings.check_on_start,
        )
        self._initial_instance_preparation = False

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
        self.start_server(open_target="/")

    def start_server(self, *, open_target: str | None = None) -> None:
        startup = getattr(self, "_startup", None)
        if startup is not None and not startup.done.is_set():
            if startup.cancelled.is_set() or startup.phase in {"STOPPING", "STOP_UNCONFIRMED"}:
                return
            if self.server_ready and open_target is not None:
                webbrowser.open(f"http://127.0.0.1:{self.server_port}{open_target}")
            elif open_target is not None:
                self.open_target = open_target
            return
        if self.server is not None and self.server.poll() is None:
            if self.server_ready and open_target is not None:
                webbrowser.open(f"http://127.0.0.1:{self.server_port}{open_target}")
            elif not self.server_ready:
                self.open_target = open_target
            return
        if self.closed or getattr(self, "_close_requested", False):
            return
        self.server = None
        self.server_port = None
        self.server_ready = False
        self.open_target = open_target
        self._startup_status_on_finish = "stopped"
        self._pending_installer = None
        prepare_instance = None
        if getattr(self, "_initial_instance_preparation", False):
            selected_instance = self.instance

            def prepare_instance(settings):
                from .maintenance_local_files import (
                    DirectoryCloseUnconfirmed,
                    MaintenanceTargetError,
                    prepare_local_directory,
                )

                create = (self._initial_creation_allowed
                          and not self._initial_creation_consumed.is_set())
                # A first-run creation grant is consumed before its possible
                # effects, including a cancelled or failed preparation.
                self._initial_creation_consumed.set()
                try:
                    with prepare_local_directory(selected_instance, create=create,
                                                  checkpoint=attempt._checkpoint):
                        attempt._checkpoint()
                        self._ensure_instance(selected_instance, create_if_missing=create,
                                              language=settings.language)
                        attempt._checkpoint()
                        declare_startup_update_policy(selected_instance,
                                                      enabled=settings.check_on_start)
                except DirectoryCloseUnconfirmed:
                    raise
                except MaintenanceTargetError as exc:
                    message = (self.text["missing_instance"] if exc.code == "target_missing"
                               else self.text["instance_open_failed"].format(error=exc.code))
                    raise RuntimeError(message) from None

        attempt = ManagedStartup(self.instance, self.settings_manager, _command_for_backend,
                                 prepare_instance=prepare_instance)
        self._startup = attempt
        self.status.set(self.text["startup_preparing"])
        self._update_tray("starting")
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._startup_selection_controls(False)
        self._startup.start()
        self._schedule_startup_poll()

    def _startup_selection_controls(self, enabled):
        for name in ("choose_button", "create_button"):
            button = getattr(self, name, None)
            if button is not None:
                button.configure(state="normal" if enabled else "disabled")

    def _schedule_startup_poll(self):
        if not self.closed and not getattr(self, "_startup_poll_scheduled", False):
            self._startup_poll_scheduled = True
            self.root.after(25, self._poll_startup)

    def _show_startup_unconfirmed(self):
        if getattr(self, "_pending_installer", None) is not None:
            self._pending_installer = None
            self.update_status.set(self.text["startup_stop_unconfirmed"])
        self.server_ready = False
        self._restart_after_stop = False
        self._pending_instance = None
        self.status.set(self.text["startup_stop_unconfirmed"])
        self._update_tray("stop_unconfirmed")
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self._startup_selection_controls(False)

    def _startup_error_text(self, code):
        key = {
            "preparation_timeout": "startup_error_preparation",
            "spawn_failed": "startup_error_spawn", "bootstrap_failed": "startup_error_bootstrap",
            "process_exited": "startup_error_exit", "endpoint_occupied": "port_unavailable",
            "readiness_timeout": "startup_error_timeout",
            "readiness_contract_unsupported": "startup_error_protocol",
            "readiness_response_invalid": "startup_error_protocol",
            "readiness_binding_failed": "startup_error_protocol",
            "startup_configuration_invalid": "startup_error_configuration",
            "startup_integrity_failed": "startup_error_integrity",
            "startup_initialization_failed": "startup_error_initialization",
        }.get(code, "server_failed")
        return self.text[key]

    def _poll_startup(self):
        self._startup_poll_scheduled = False
        startup = self._startup
        if self.closed or startup is None:
            return
        if (not startup.done.is_set() and not startup.cancelled.is_set()
                and startup.phase in {"PREPARING", "SPAWNING", "WAITING_READY"}
                and time.monotonic() >= min(startup.total_deadline, startup.phase_deadline)):
            code = {"PREPARING": "preparation_timeout", "SPAWNING": "bootstrap_failed"}.get(
                startup.phase, "readiness_timeout"
            )
            startup.request_stop(code)
            self.server_ready = False
            self.status.set(self.text["stopping"])
        if startup.cleanup_unconfirmed:
            self._show_startup_unconfirmed()
        while self._startup is startup:
            try:
                kind, details = startup.events.get_nowait()
            except queue.Empty:
                break
            if kind == "prepared":
                self.instance_available = True
                self._instance_error_observed = False
                self._initial_instance_preparation = False
                self.settings = details["settings"]
                self.server_port = details["port"]
                self.check_button.configure(state="normal")
                if not startup.cancelled.is_set():
                    self.status.set(self.text["startup_waiting"])
                    if getattr(self, "_startup_update_check_pending", False):
                        self._startup_update_check_pending = False
                        if self.settings.check_on_start:
                            self.check_updates(interactive=False)
            elif kind == "spawned":
                self.server = details["process"]
                self.server_port = details["port"]
            elif kind == "ready" and not startup.cancelled.is_set():
                if startup.instance != self.instance:
                    startup.request_stop()
                    continue
                self.settings = details["settings"]
                self._server_ready(details["process"], details["port"], True)
                self._startup_selection_controls(True)
            elif kind == "stopping":
                self.server_ready = False
                self.status.set(self.text["stopping"])
                self._update_tray("stopping")
            elif kind == "unconfirmed":
                self._show_startup_unconfirmed()
            elif kind == "finished":
                self.server = None
                self.server_port = None
                self.server_ready = False
                self.open_target = None
                if details["settings"] is not None:
                    self.settings = details["settings"]
                code = details["code"]
                if code not in {None, "cancelled"}:
                    preparation_error = details.get("preparation_error")
                    if preparation_error is not None:
                        self.instance_available = False
                        self._instance_error_observed = True
                    text = preparation_error or self._startup_error_text(code)
                    if details["rolled_back"]:
                        text = self.text["endpoint_rolled_back"] + " " + text
                    self.status.set(text)
                    self._update_tray("occupied" if code == "endpoint_occupied"
                                      else "server_failed")
                else:
                    status = self._startup_status_on_finish
                    self.status.set(self.text[status])
                    self._update_tray(status)
                self.open_button.configure(
                    state="normal" if (self.instance_available or not getattr(
                        self, "_instance_error_observed", False)) else "disabled"
                )
                self.stop_button.configure(state="disabled")
                self._startup_selection_controls(True)
        if startup.done.is_set():
            if self._close_requested:
                self._finish_close()
            elif getattr(self, "_pending_installer", None) is not None:
                self._launch_pending_installer()
            elif self._pending_instance is not None:
                selected = self._pending_instance
                self._pending_instance = None
                try:
                    self._select_instance(selected)
                except (OSError, ValueError):
                    self.status.set(self.text["invalid_instance"])
            elif self._restart_after_stop:
                self._restart_after_stop = False
                self.start_server()
        else:
            self._schedule_startup_poll()

    def show_startup_diagnostics(self):
        startup = self._startup
        events = startup.diagnostic_snapshot() if startup is not None else []
        body = self.text["startup_details_help"] + "\n\n"
        if not events:
            body += self.text["startup_details_empty"]
        for event in events:
            body += f"{event['phase']}: {event['code']} · {event['elapsed_ms']} ms"
            if "exit_code" in event:
                body += f" · exit={event['exit_code']}"
            body += "\n"
        self._show_local_modal(title=self.text["startup_details"], body=body,
                               links=[], confirm=False)

    def open_shell_settings(self) -> None:
        target = f"/settings/shell?lang={self.settings.language}"
        self.start_server(open_target=target)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        with suppress(Exception):
            self.root.focus_force()

    def open_queue_status(self) -> None:
        self.start_server(open_target="/attention")

    def open_queue_controls(self) -> None:
        # Job selection and Pause/Resume confirmation use the existing durable
        # scheduler controls. The tray creates no global pause flag or job queue.
        self.start_server(open_target="/scheduler")

    def show_first_run(self) -> None:
        from .shell_preferences import preference_display

        labels = namespace_catalog(resolve_language(self.settings.language), "preferences")
        selected = self.settings
        resolved = resolve_language(selected.language)
        body = "\n".join(
            [
                labels["first_run_help"],
                f"{labels['field.language']}: {selected.language} → {resolved}",
                f"{labels['field.endpoint_port']}: 127.0.0.1:{selected.endpoint_port}",
                labels["field.tray_enabled"]
                + ": "
                + preference_display("tray_enabled", selected.tray_enabled, resolved),
                labels["field.login_startup"]
                + ": "
                + preference_display("login_startup", selected.login_startup, resolved),
                f"{labels['instance']}: {self.instance.name}",
            ]
        )
        self._show_local_modal(title=labels["first_run"], body=body, links=[], confirm=False)

    def _refresh_tray_queue(self) -> None:
        if self.closed or self.tray is None:
            return
        if self.server_ready and not self._tray_observation_running:
            self._tray_observation_running = True
            port, selected_instance, selected_process = self.server_port, self.instance, self.server

            def observe():
                from .tray_queue import normalize_queue

                queue = None
                try:
                    # Direct loopback only, bounded bytes/time, never proxy or redirect.
                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self, *args, **kwargs):
                            return None

                    opener = urllib.request.build_opener(
                        urllib.request.ProxyHandler({}),
                        NoRedirect(),
                    )
                    url = f"http://127.0.0.1:{port}/api/v1/shell/queue"
                    with opener.open(url, timeout=3) as reply:
                        raw = reply.read(8193)
                    if len(raw) <= 8192:
                        queue = normalize_queue(json.loads(raw))
                except (OSError, ValueError):
                    pass

                def deliver():
                    self._tray_observation_running = False
                    if (
                        not self.closed
                        and self.tray is not None
                        and self.server_ready
                        and self.server_port == port
                        and self.instance == selected_instance
                        and self.server is selected_process
                    ):
                        self.tray.update(
                            service_status="running",
                            endpoint=f"http://127.0.0.1:{port}",
                            queue=queue,
                        )

                if not self.closed:
                    self.root.after(0, deliver)

            threading.Thread(target=observe, name="ProvelumeTrayObservation", daemon=True).start()
        self.root.after(15000, self._refresh_tray_queue)

    def _update_tray(self, status: str) -> None:
        tray = getattr(self, "tray", None)
        if tray is not None:
            port = self.server_port or self.settings.endpoint_port
            tray.update(
                service_status=status,
                endpoint=f"http://127.0.0.1:{port}",
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
            target = getattr(self, "open_target", "/")
            self.open_target = None
            if target is not None:
                webbrowser.open(f"http://127.0.0.1:{port}{target}")
        else:
            self.stop_server(final_status="server_failed")

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
        startup = getattr(self, "_startup", None)
        if startup is not None and not startup.done.is_set():
            if startup.cleanup_unconfirmed:
                self._show_startup_unconfirmed()
                self._schedule_startup_poll()
                return
            self._startup_status_on_finish = final_status
            self.open_target = None
            self.server_ready = False
            startup.request_stop()
            self.status.set(self.text["stopping"])
            self._update_tray("stopping")
            self.open_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self._startup_selection_controls(False)
            self._schedule_startup_poll()
            return
        process = self.server
        if process is not None and process.poll() is None:
            # No live child can be discarded without its owning startup worker.
            self._show_startup_unconfirmed()
            return
        self.server = None
        self.server_port = None
        self.server_ready = False
        if not self.closed:
            self.status.set(self.text[final_status])
            self._update_tray(final_status)
            self.open_button.configure(state="normal" if self.instance_available else "disabled")
            self.stop_button.configure(state="disabled")

    def restart_server(self) -> None:
        self._pending_installer = None
        startup = getattr(self, "_startup", None)
        if startup is not None and not startup.done.is_set():
            if startup.cleanup_unconfirmed:
                self._show_startup_unconfirmed()
                return
            self._restart_after_stop = True
            self.stop_server()
            return
        self.stop_server()
        if self.server is None:
            self.root.after(0, self.start_server)

    def window_close(self) -> None:
        manager = getattr(self, "settings_manager", None)
        if manager is not None:
            self.settings = manager.load().settings
            self.text = STRINGS[resolve_language(self.settings.language)]
        if self.settings.tray_enabled and self.tray is not None:
            if not getattr(self, "_tray_close_explained", False):
                text = namespace_catalog(resolve_language(self.settings.language), "tray")
                if not self._show_local_modal(
                    title=self.text["title"], body=text["first_close"], links=[], confirm=True
                ):
                    return
                self._tray_close_explained = True
            self.root.withdraw()
            startup = getattr(self, "_startup", None)
            state = "running" if self.server_ready else "stopped"
            if startup is not None and not startup.done.is_set():
                state = ("stop_unconfirmed" if startup.cleanup_unconfirmed
                         else "stopping" if startup.cancelled.is_set() else "starting")
            self._update_tray(state)
            return
        self.close()

    def check_updates(self, interactive: bool = True) -> None:
        if not interactive:
            # The permission check opens the Instance too. Keep that read off
            # Tk, preserve the current UI when denied, and bind late results to
            # the existing generation/channel rather than a new user request.
            threading.Thread(target=self._startup_update_check_worker,
                             args=(self.instance, self.update_generation, self.channel.get()),
                             name="ProvelumeStartupUpdateCheck", daemon=True).start()
            return
        channel = self.channel.get()
        if interactive and not self._confirm_update_check(channel):
            return
        self.update_generation += 1
        generation = self.update_generation
        self.candidate = None
        self.update_status.set(self.text["checking"])
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="disabled")
        threading.Thread(
            target=self._check_updates_worker,
            args=(channel, generation),
            daemon=True,
        ).start()

    def _startup_update_check_worker(self, instance, generation, channel):
        if self.closed or getattr(self, "_close_requested", False):
            return
        if not startup_update_policy_enabled(instance):
            return
        if (self.closed or getattr(self, "_close_requested", False)
                or self.instance != instance or self.update_generation != generation):
            return
        self._check_updates_worker(channel, generation)

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
            if not self.closed:
                self.root.after(
                    0,
                    lambda error=exc: self._update_failed(error, generation, channel),
                )
            return
        if not self.closed:
            self.root.after(
                0,
                lambda: self._update_checked(
                    candidate, generation, channel, result.get("newer_preview_version")
                ),
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
        self.update_status.set(self.text["not_checked"])
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="normal")

    def _update_failed(self, error: BaseException, generation: int, channel: str) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = None
        detail = format_update_failure(error, self.text)
        self.update_status.set(self.text["failed"].format(error=detail))
        self.download_button.configure(state="disabled")
        self.check_button.configure(state="normal")

    def _update_checked(
        self,
        candidate: UpdateCandidate | None,
        generation: int,
        channel: str,
        newer_preview_version: str | None = None,
    ) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = candidate
        self.check_button.configure(state="normal")
        if candidate is None:
            status = self.text["current"].format(channel=channel)
            if channel == "stable" and newer_preview_version:
                status += " " + self.text["preview_other_channel"].format(
                    version=newer_preview_version
                )
            self.update_status.set(status)
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
            if not self.closed:
                self.root.after(
                    0,
                    lambda error=exc: self._update_failed(error, generation, channel),
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

        if not self._is_current_update_request(generation, channel) or self.candidate != candidate:
            return
        self.update_status.set(self.text["download_ready"])
        if not messagebox.askyesno("Provelume", self.text["install_notice"]):
            self.download_button.configure(state="normal")
            return
        self._pending_installer = (path, candidate, generation, channel,
                                   getattr(self, "_startup", None))
        self.stop_server()
        self._launch_pending_installer()

    def _launch_pending_installer(self):
        pending = getattr(self, "_pending_installer", None)
        if pending is None:
            return
        path, candidate, generation, channel, owner = pending
        if owner is not getattr(self, "_startup", None):
            self._pending_installer = None
            return
        if owner is not None and not owner.done.is_set():
            return
        self._pending_installer = None
        if (not self._is_current_update_request(generation, channel)
                or self.candidate != candidate or self._close_requested):
            return
        if self.server is not None and self.server.poll() is None:
            self._show_startup_unconfirmed()
            return
        command = [str(path)]
        if candidate.publication_required:
            command.append(f"/PUBLICATIONRECEIPT={path.parent / RECEIPT_NAME}")
        try:
            subprocess.Popen(command, cwd=str(path.parent))
        except OSError as exc:
            self._update_failed(exc, generation, channel)
            return
        self.close()

    def _show_local_modal(
        self,
        *,
        title: str,
        body: str,
        links: list[tuple[str, str]],
        confirm: bool,
    ) -> bool:
        dialog = self.tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.resizable(False, False)
        icon = _versioned_icon_path()
        if icon is not None and os.name == "nt":
            with suppress(self.tk.TclError):
                dialog.iconbitmap(default=str(icon))

        frame = self.ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        self.ttk.Label(
            frame,
            text=body,
            wraplength=520,
            justify="left",
        ).pack(anchor="w")

        if links:
            link_row = self.ttk.Frame(frame)
            link_row.pack(fill="x", pady=(16, 0))
            for label, url in links:
                self.ttk.Button(
                    link_row,
                    text=label,
                    command=lambda selected=url: webbrowser.open(selected),
                ).pack(side="left", padx=(0, 8))

        result = False

        def finish(value: bool) -> None:
            nonlocal result
            result = value
            dialog.destroy()

        action_row = self.ttk.Frame(frame)
        action_row.pack(fill="x", pady=(18, 0))
        if confirm:
            cancel = self.ttk.Button(
                action_row,
                text=self.text["cancel"],
                command=lambda: finish(False),
            )
            cancel.pack(side="right")
            primary = self.ttk.Button(
                action_row,
                text=self.text["continue"],
                command=lambda: finish(True),
            )
            primary.pack(side="right", padx=(0, 8))
            dialog.bind("<Return>", lambda _event: finish(True))
        else:
            primary = self.ttk.Button(
                action_row,
                text=self.text["close"],
                command=lambda: finish(False),
            )
            primary.pack(side="right")
        dialog.bind("<Escape>", lambda _event: finish(False))
        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.grab_set()
        primary.focus_set()
        self.root.wait_window(dialog)
        return result

    def _confirm_update_check(self, channel: str) -> bool:
        return self._show_local_modal(
            title=self.text["updates"],
            body=self.text["network_notice"].format(channel=channel),
            links=[(self.text["open_releases"], RELEASES_URL)],
            confirm=True,
        )

    def show_about(self) -> None:
        about = current_about()
        links = public_about_links(about)
        actions = [
            (self.text["open_repository"], links["repository"]),
            (self.text["open_releases"], links["releases"]),
        ]
        if "installed_release" in links:
            actions.append((self.text["open_installed_release"], links["installed_release"]))
        self._show_local_modal(
            title=self.text["about"],
            body=self.text["about_text"].format(
                version=about["version"],
                channel=about["channel"],
                tag=about["tag"] or "—",
                commit=about["commit"] or "—",
                packaging=about["runtime"]["packaging"],
                platform=about["runtime"]["platform"],
                architecture=about["runtime"]["architecture"],
                identity=about["build_identity_status"],
                signature=about["updates"]["platform_signature"],
            ),
            links=actions,
            confirm=False,
        )

    def close(self) -> None:
        if self.closed:
            return
        self._close_requested = True
        self._restart_after_stop = False
        self._pending_instance = None
        self._pending_installer = None
        self.stop_server()
        startup = getattr(self, "_startup", None)
        if startup is not None and not startup.done.is_set():
            return
        if getattr(self, "server", None) is not None:
            return
        self._finish_close()

    def _finish_close(self):
        self.closed = True
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
        messagebox.showinfo("Provelume", STRINGS[resolve_language(language)]["already_running"])
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
    parser.add_argument("--startup-bootstrap-stdin", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int)
    parser.add_argument("--import-publication", type=Path)
    parser.add_argument("--publication-manifest", type=Path)
    parser.add_argument("--publication-payload", type=Path)
    parser.add_argument("--publication-destination", type=Path)
    parser.add_argument(
        "--tray",
        action="store_true",
        help="start the installed Windows shell using its configured tray preference",
    )
    parser.add_argument("--diagnostics-file", type=Path)
    parser.add_argument("--native-tray-smoke-file", type=Path)
    parser.add_argument("--google-credential-smoke-file", type=Path)
    parser.add_argument("--ui-diagnostics-file", type=Path)
    parser.add_argument("--ui-diagnostics-language", choices=sorted(STRINGS), default="en")
    parser.add_argument(
        "--ui-diagnostics-dpi",
        type=int,
        choices=(100, 125, 150, 200),
        default=100,
    )
    parser.add_argument("--ui-diagnostics-width", type=int, default=800)
    parser.add_argument("--ui-diagnostics-height", type=int, default=600)
    parser.add_argument("--ui-diagnostics-theme", choices=("system", "light", "dark"),
                        default="system")
    parser.add_argument("--bootstrap-instance", type=Path)
    parser.add_argument(
        "--instance-result-file", type=Path,
        help="New JSON report outside the Instance; use before --instance-command",
    )
    parser.add_argument(
        "--instance-command", nargs=argparse.REMAINDER,
        help="Explicit validate/migrate/backup/restore/export/import operator command",
    )
    parser.add_argument("--instance-name", default="My Provelume")
    parser.add_argument("--validate-port", type=int)
    parser.add_argument("--initialize-shell-settings", action="store_true")
    parser.add_argument("--remove-login-startup", action="store_true")
    parser.add_argument("--install-port", type=int, default=DEFAULT_LOCAL_PORT)
    parser.add_argument("--install-language", choices=sorted(STRINGS), default="en")
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
    if options.startup_bootstrap_stdin and options.serve is None:
        return 73
    selected_modes = sum(
        value is not None
        for value in (
            options.import_publication,
            options.serve,
            options.diagnostics_file,
            options.native_tray_smoke_file,
            options.google_credential_smoke_file,
            options.ui_diagnostics_file,
            options.bootstrap_instance,
            options.instance_command,
            options.validate_port,
            True if options.initialize_shell_settings else None,
            True if options.remove_login_startup else None,
        )
    )
    if selected_modes > 1:
        raise SystemExit("select only one desktop execution mode")
    if options.instance_command is not None:
        if options.instance_result_file is None:
            return 2
        from .instance_desktop import run_instance_command

        return run_instance_command(options.instance_command, options.instance_result_file)
    if options.instance_result_file is not None:
        raise SystemExit("Instance result file requires the explicit operator mode")
    if options.import_publication is not None:
        if options.publication_manifest is None or options.publication_payload is None:
            return 2
        try:
            import_publication(
                options.import_publication,
                manifest_path=options.publication_manifest,
                payload_path=options.publication_payload,
                destination=options.publication_destination,
            )
        except (OSError, PublicationError):
            return 2
        return 0
    if any(
        value is not None
        for value in (
            options.publication_manifest,
            options.publication_payload,
            options.publication_destination,
        )
    ):
        raise SystemExit("publication paths require the explicit import mode")
    if options.diagnostics_file is not None:
        write_diagnostics(options.diagnostics_file)
        return 0
    if options.native_tray_smoke_file is not None:
        return 0 if write_native_tray_smoke(options.native_tray_smoke_file) else 2
    if options.google_credential_smoke_file is not None:
        from .google_credentials import write_windows_credential_smoke

        return 0 if write_windows_credential_smoke(options.google_credential_smoke_file) else 2
    if options.ui_diagnostics_file is not None:
        write_ui_diagnostics(
            options.ui_diagnostics_file,
            language=options.ui_diagnostics_language,
            dpi_percent=options.ui_diagnostics_dpi,
            viewport_width=options.ui_diagnostics_width,
            viewport_height=options.ui_diagnostics_height,
            theme=options.ui_diagnostics_theme,
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
                    replace(
                        default_settings(),
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
        private_stop = None
        try:
            selected_port = effective_port(
                explicit_port=options.port,
                persisted=load_settings(),
            )["port"]
            validate_port(selected_port)
        except ShellSettingsError as exc:
            if options.startup_bootstrap_stdin:
                return 74
            raise SystemExit(str(exc)) from exc
        if options.startup_bootstrap_stdin:
            from .maintenance_local_files import open_local_directory

            try:
                with bootstrap_stdin() as stream:
                    material = read_bootstrap(stream)
                if os.name == "nt":
                    from .startup_windows import ChildStopSignal

                    private_stop = ChildStopSignal(material.stop_event_name())
                with open_local_directory(options.serve) as (_, identity):
                    context = ReadinessContext(material, identity, selected_port)
                    app = create_app(options.serve, effective_port=selected_port, _startup=context)
                material = None
            except StartupReadinessError as exc:
                if private_stop is not None:
                    private_stop.close()
                return {"bootstrap_failed": 73, "startup_configuration_invalid": 74,
                        "startup_integrity_failed": 75}.get(exc.code, 76)
            except (OSError, ValueError, ShellSettingsError):
                if private_stop is not None:
                    private_stop.close()
                return 74
            except Exception:
                if private_stop is not None:
                    private_stop.close()
                return 76
        else:
            app = create_app(options.serve, effective_port=selected_port)
        serve_options = {"host": "127.0.0.1", "port": selected_port, "log_level": "warning",
                         "log_config": None, "access_log": False}
        if private_stop is not None:
            server = uvicorn.Server(uvicorn.Config(app, **serve_options))
            if not private_stop.run(server):
                return 76
        else:
            uvicorn.run(app, **serve_options)
        return 0
    return run_ui(start_hidden=options.tray)


if __name__ == "__main__":
    raise SystemExit(main())
