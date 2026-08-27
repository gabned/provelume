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
        "stopped": "Stopped",
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
        "stopped": "Fermato",
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
        "server_failed": "Non è stato possibile avviare il servizio locale.",
        "about_text": (
            "Provelume {version}\nCanale: {channel}\nTag: {tag}\nCommit: {commit}\n"
            "Pacchetto: {packaging}\nFirma di piattaforma: {signature}\n\n"
            "Le informazioni su versione e prodotto sono lette in locale."
        ),
    },
}


class DesktopShell:
    def __init__(self, root, *, initial_settings: LauncherSettings):
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
        self.candidate: UpdateCandidate | None = None
        self.update_generation = 0
        self.closed = False

        self.status = tk.StringVar(value=self.text["instance_ready"])
        self.update_status = tk.StringVar(value=self.text["current"])
        self.instance_text = tk.StringVar(value=str(self.instance))
        self.check_on_start = tk.BooleanVar(value=self.settings.check_on_start)
        self.channel = tk.StringVar(value=self.settings.update_channel)

        self._ensure_instance(self.instance)
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
        root.geometry("680x520")
        root.minsize(620, 480)
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill="both", expand=True)

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
        self.open_button = ttk.Button(row, text=self.text["open"], command=self.open_product)
        self.open_button.pack(side="left")
        ttk.Button(row, text=self.text["stop"], command=self.stop_server).pack(side="left", padx=8)
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
        ttk.Button(actions, text=self.text["check_now"], command=self.check_updates).pack(
            side="left"
        )
        self.download_button = ttk.Button(
            actions,
            text=self.text["download"],
            command=self.download_candidate,
            state="disabled",
        )
        self.download_button.pack(side="left", padx=8)

        ttk.Label(outer, text=self.text["offline"]).pack(anchor="w", pady=(6, 0))

    def _ensure_instance(self, path: Path) -> None:
        try:
            created = not (path / "provelume.yml").is_file()
            if (path / "provelume.yml").is_file():
                instance = ProvelumeInstance(path)
            else:
                instance = ProvelumeInstance.initialise(path, name="My Provelume")
            if created:
                config = instance.store.read_config()
                config.setdefault("ui", {})["language"] = self.settings.language
                instance.store.write_config(config)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"cannot initialise local Instance: {exc}") from exc

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
        self.status.set(self.text["starting"])
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

    def _server_ready(
        self,
        process: subprocess.Popen[bytes],
        port: int,
        ready: bool,
    ) -> None:
        if self.closed or self.server is not process or self.server_port != port:
            return
        if ready and process.poll() is None:
            self.status.set(self.text["running"])
            webbrowser.open(f"http://127.0.0.1:{port}/")
        else:
            self.status.set(self.text["server_failed"])
            self.stop_server()

    def stop_server(self) -> None:
        process = self.server
        self.server = None
        self.server_port = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
        if not self.closed:
            self.status.set(self.text["stopped"])

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

    def _update_failed(self, error: str, generation: int, channel: str) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = None
        self.update_status.set(self.text["failed"].format(error=error))
        self.download_button.configure(state="disabled")

    def _update_checked(
        self,
        candidate: UpdateCandidate | None,
        generation: int,
        channel: str,
    ) -> None:
        if not self._is_current_update_request(generation, channel):
            return
        self.candidate = candidate
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
        DesktopShell(root, initial_settings=load_settings())
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
            options.bootstrap_instance,
        )
    )
    if selected_modes > 1:
        raise SystemExit("select only one desktop execution mode")
    if options.diagnostics_file is not None:
        write_diagnostics(options.diagnostics_file)
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
