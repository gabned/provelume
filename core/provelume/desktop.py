from __future__ import annotations

import argparse
import json
import locale
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import uvicorn

from . import __version__
from .about import current_about
from .service import ProvelumeInstance
from .updates import UpdateCandidate, UpdateError, check_for_updates, download_update
from .web import create_app

SETTINGS_SCHEMA_VERSION = 1
DESKTOP_DIAGNOSTICS_SCHEMA_VERSION = 1
MUTEX_NAME = "Local\\ProvelumeDesktop"


@dataclass(frozen=True, slots=True)
class LauncherSettings:
    instance_path: str
    update_channel: str = "preview"
    check_on_start: bool = False
    language: str = "en"
    schema_version: int = SETTINGS_SCHEMA_VERSION

    def normalized(self) -> LauncherSettings:
        channel = self.update_channel if self.update_channel in {"stable", "preview"} else "preview"
        language = self.language if self.language in {"en", "it"} else "en"
        return LauncherSettings(
            instance_path=str(Path(self.instance_path).expanduser()),
            update_channel=channel,
            check_on_start=bool(self.check_on_start),
            language=language,
        )


def state_directory() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "Provelume"
    state_home = os.environ.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "provelume"
    return Path.home() / ".local" / "state" / "provelume"


def default_instance_directory() -> Path:
    return Path.home() / "Documents" / "Provelume"


def settings_path() -> Path:
    return state_directory() / "launcher.json"


def default_language() -> str:
    try:
        configured = locale.getlocale()[0] or ""
    except (ValueError, TypeError):
        configured = ""
    return "it" if configured.casefold().startswith("it") else "en"


def default_settings() -> LauncherSettings:
    return LauncherSettings(
        instance_path=str(default_instance_directory()),
        language=default_language(),
    )


def load_settings(path: Path | None = None) -> LauncherSettings:
    selected = path or settings_path()
    if not selected.is_file() or selected.is_symlink():
        return default_settings()
    try:
        value = json.loads(selected.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "instance_path",
            "update_channel",
            "check_on_start",
            "language",
        }:
            raise ValueError("unsupported launcher settings fields")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError("unsupported launcher settings schema")
        if not isinstance(value["instance_path"], str) or not value["instance_path"].strip():
            raise ValueError("launcher instance path is invalid")
        if not isinstance(value["check_on_start"], bool):
            raise ValueError("launcher update policy is invalid")
        return LauncherSettings(**value).normalized()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return default_settings()


def save_settings(settings: LauncherSettings, path: Path | None = None) -> Path:
    selected = (path or settings_path()).expanduser().resolve()
    selected.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(settings.normalized()), indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{selected.name}.",
            suffix=".tmp",
            dir=selected.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, selected)
        temporary_name = None
    finally:
        if temporary_name is not None:
            with suppress(OSError):
                Path(temporary_name).unlink()
    return selected


def declare_startup_update_policy(instance_path: Path, *, enabled: bool) -> None:
    """Keep the Instance capability inventory aligned with launcher startup policy."""

    instance = ProvelumeInstance(instance_path)
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
    return {
        "schema_version": DESKTOP_DIAGNOSTICS_SCHEMA_VERSION,
        "desktop_shell": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "about": current_about(),
        "settings_schema_version": SETTINGS_SCHEMA_VERSION,
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
            )
            target_width, target_height = _window_dimensions(
                viewport_width,
                viewport_height,
            )
            root.geometry(f"{target_width}x{target_height}")
            root.update_idletasks()
            canvas = shell.scroll_canvas
            bounds = canvas.bbox("all") or (0, 0, 0, 0)
            controls = {
                "open": str(shell.open_button.cget("state")),
                "stop": str(shell.stop_button.cget("state")),
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


def _acquire_windows_mutex():
    if os.name != "nt":
        return object()
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return None
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        return None
    return handle


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


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


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
    ):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.tk = tk
        self.ttk = ttk
        self.settings = initial_settings.normalized()
        self.text = STRINGS[self.settings.language]
        self.instance = Path(self.settings.instance_path).expanduser()
        self.server: subprocess.Popen[bytes] | None = None
        self.server_port: int | None = None
        self.server_ready = False
        self.candidate: UpdateCandidate | None = None
        self.update_generation = 0
        self.closed = False

        self.status = tk.StringVar(value=self.text["instance_ready"])
        self.update_status = tk.StringVar(value=self.text["current"])
        self.instance_text = tk.StringVar(value=str(self.instance))
        self.check_on_start = tk.BooleanVar(value=self.settings.check_on_start)
        self.channel = tk.StringVar(value=self.settings.update_channel)

        self._ensure_instance(
            self.instance,
            create_if_missing=create_instance_if_missing,
        )
        declare_startup_update_policy(
            self.instance,
            enabled=self.settings.check_on_start,
        )
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if self.settings.check_on_start:
            self.root.after(400, lambda: self.check_updates(interactive=False))

    def _build(self) -> None:
        ttk = self.ttk
        root = self.root
        root.title(self.text["title"])
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
        ttk.Label(instance, textvariable=self.status).pack(anchor="w", pady=(4, 10))
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
        ttk.Button(row, text=self.text["choose"], command=self.choose_instance).pack(side="right")
        ttk.Button(row, text=self.text["create"], command=self.create_instance).pack(
            side="right", padx=8
        )

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
        values = asdict(self.settings)
        values.update(changes)
        self.settings = LauncherSettings(**values).normalized()
        save_settings(self.settings)

    def _save_policy(self) -> None:
        previous_channel = self.settings.update_channel
        self._replace_settings(
            update_channel=self.channel.get(),
            check_on_start=self.check_on_start.get(),
        )
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
        self.instance_text.set(str(self.instance))
        self.status.set(self.text["instance_ready"])
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
            return
        try:
            ProvelumeInstance(self.instance)
        except (OSError, ValueError):
            from tkinter import messagebox

            messagebox.showerror("Provelume", self.text["invalid_instance"])
            return
        port = _available_port()
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
        self.status.set(self.text["starting"])
        self.open_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        threading.Thread(
            target=self._wait_for_server,
            args=(process, port),
            daemon=True,
        ).start()

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
            self.open_button.configure(state="normal")
            self.stop_button.configure(state="normal")
            webbrowser.open(f"http://127.0.0.1:{port}/")
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
        if not self.closed:
            self.status.set(self.text[final_status])
            self.open_button.configure(state="normal")
            self.stop_button.configure(state="disabled")

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
        self.root.destroy()


def run_ui() -> int:
    _configure_windows_dpi_awareness()
    import tkinter as tk
    from tkinter import messagebox

    mutex = _acquire_windows_mutex()
    if mutex is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Provelume", "Provelume is already running.")
        root.destroy()
        return 0
    root = tk.Tk()
    try:
        persisted_settings = settings_path().is_file()
        DesktopShell(
            root,
            initial_settings=load_settings(),
            create_instance_if_missing=not persisted_settings,
        )
    except RuntimeError as exc:
        root.withdraw()
        messagebox.showerror("Provelume", str(exc))
        root.destroy()
        return 1
    root.mainloop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Provelume", add_help=True)
    parser.add_argument("--serve", type=Path)
    parser.add_argument("--port", type=int, default=8040)
    parser.add_argument("--diagnostics-file", type=Path)
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
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = build_parser().parse_args(arguments)
    selected_modes = sum(
        value is not None
        for value in (
            options.serve,
            options.diagnostics_file,
            options.ui_diagnostics_file,
            options.bootstrap_instance,
        )
    )
    if selected_modes > 1:
        raise SystemExit("select only one desktop execution mode")
    if options.diagnostics_file is not None:
        write_diagnostics(options.diagnostics_file)
        return 0
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
    if options.serve is not None:
        if not 1 <= options.port <= 65535:
            raise SystemExit("port must be between 1 and 65535")
        app = create_app(options.serve)
        uvicorn.run(app, host="127.0.0.1", port=options.port, log_level="warning")
        return 0
    return run_ui()


if __name__ == "__main__":
    raise SystemExit(main())
