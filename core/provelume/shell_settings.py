from __future__ import annotations

import hashlib
import json
import locale
import os
import socket
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SHELL_SETTINGS_SCHEMA_VERSION = 2
SHELL_PREFERENCES_SCHEMA_VERSION = 1
SHELL_CAPABILITIES_SCHEMA_VERSION = 1
DEFAULT_LOCAL_PORT = 44851
MIN_LOCAL_PORT = 1024
MAX_LOCAL_PORT = 65535
LOCAL_HOST = "127.0.0.1"
MAX_SETTINGS_BYTES = 64 * 1024
MAX_PREFERENCES_BYTES = 16 * 1024
MAX_SETTINGS_REVISION = (1 << 63) - 1
APP_USER_MODEL_ID = "Provelume.Desktop"
THEMES = frozenset({"system", "light", "dark"})
LANGUAGES = frozenset({"en", "it"})
UPDATE_CHANNELS = frozenset({"preview", "stable"})


def state_directory() -> Path:
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "Provelume"
        return Path.home() / "AppData" / "Local" / "Provelume"
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


class ShellSettingsError(RuntimeError):
    code = "shell_settings_error"


class ShellSettingsBusy(ShellSettingsError):
    code = "configuration_busy"


class ShellSettingsStale(ShellSettingsError):
    code = "stale_configuration"


class ShellPortUnavailable(ShellSettingsError):
    code = "port_unavailable"


class ShellPreferencesError(ShellSettingsError):
    code = "preferences_invalid"


@dataclass(frozen=True, slots=True)
class LauncherSettings:
    instance_path: str
    update_channel: str = "preview"
    check_on_start: bool = False
    language: str = "en"
    endpoint_port: int = DEFAULT_LOCAL_PORT
    last_good_port: int = DEFAULT_LOCAL_PORT
    restart_required: bool = False
    tray_enabled: bool = True
    login_startup: bool = False
    theme: str = "system"
    revision: int = 0
    schema_version: int = SHELL_SETTINGS_SCHEMA_VERSION

    def normalized(self) -> LauncherSettings:
        instance_path = str(Path(self.instance_path).expanduser())
        if not instance_path.strip() or len(instance_path) > 4096:
            raise ShellSettingsError("launcher instance path is invalid")
        endpoint_port = validate_port(self.endpoint_port)
        last_good_port = validate_port(self.last_good_port)
        if (
            type(self.revision) is not int
            or self.revision < 0
            or self.revision > MAX_SETTINGS_REVISION
        ):
            raise ShellSettingsError("launcher settings revision is invalid")
        if any(
            not isinstance(value, bool)
            for value in (
                self.check_on_start,
                self.restart_required,
                self.tray_enabled,
                self.login_startup,
            )
        ):
            raise ShellSettingsError("launcher settings boolean is invalid")
        return LauncherSettings(
            instance_path=instance_path,
            update_channel=(
                self.update_channel if self.update_channel in UPDATE_CHANNELS else "preview"
            ),
            check_on_start=self.check_on_start,
            language=self.language if self.language in LANGUAGES else "en",
            endpoint_port=endpoint_port,
            last_good_port=last_good_port,
            restart_required=self.restart_required,
            tray_enabled=self.tray_enabled,
            login_startup=self.login_startup,
            theme=self.theme if self.theme in THEMES else "system",
            revision=self.revision,
        )

    def as_payload(self) -> dict[str, Any]:
        value = self.normalized()
        return {
            "schema_version": SHELL_SETTINGS_SCHEMA_VERSION,
            "revision": value.revision,
            "instance_path": value.instance_path,
            "update_channel": value.update_channel,
            "check_on_start": value.check_on_start,
            "language": value.language,
            "endpoint": {
                "host": LOCAL_HOST,
                "port": value.endpoint_port,
                "last_good_port": value.last_good_port,
                "restart_required": value.restart_required,
            },
            "shell": {
                "tray_enabled": value.tray_enabled,
                "login_startup": value.login_startup,
                "theme": value.theme,
            },
        }

    def public_view(self, *, warning: str | None = None) -> dict[str, Any]:
        value = self.normalized()
        return {
            "schema_version": SHELL_CAPABILITIES_SCHEMA_VERSION,
            "configuration_schema_version": SHELL_SETTINGS_SCHEMA_VERSION,
            "revision": value.revision,
            "endpoint": {
                "scheme": "http",
                "host": LOCAL_HOST,
                "port": value.endpoint_port,
                "display": f"http://{LOCAL_HOST}:{value.endpoint_port}",
                "binding": "loopback_only",
                "source": (
                    "default"
                    if value.endpoint_port == DEFAULT_LOCAL_PORT and value.revision == 0
                    else "persisted"
                ),
                "restart_required": value.restart_required,
            },
            "shell": {
                "tray_enabled": value.tray_enabled,
                "login_startup": value.login_startup,
                "theme": value.theme,
                "app_user_model_id": APP_USER_MODEL_ID,
            },
            "limits": {
                "default_port": DEFAULT_LOCAL_PORT,
                "minimum_port": MIN_LOCAL_PORT,
                "maximum_port": MAX_LOCAL_PORT,
                "reserved_ports": f"1-{MIN_LOCAL_PORT - 1}",
                "random_fallback": False,
                "remote_binding": False,
                "firewall_changes": False,
            },
            "warning": warning,
            "network_used": False,
        }


@dataclass(frozen=True, slots=True)
class LoadedSettings:
    settings: LauncherSettings
    warning: str | None


def validate_port(value: int | str) -> int:
    if type(value) is int:
        selected = value
    elif (
        isinstance(value, str)
        and value
        and value.isascii()
        and value.isdigit()
    ):
        selected = int(value)
    else:
        raise ShellSettingsError("port must be an integer")
    if not MIN_LOCAL_PORT <= selected <= MAX_LOCAL_PORT:
        raise ShellSettingsError(
            f"port must be between {MIN_LOCAL_PORT} and {MAX_LOCAL_PORT}; "
            f"ports 1-{MIN_LOCAL_PORT - 1} are reserved"
        )
    return selected


def probe_port(port: int | str) -> dict[str, Any]:
    selected = validate_port(port)
    available = False
    error_code: int | None = None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind((LOCAL_HOST, selected))
            available = True
        except OSError as exc:
            error_code = exc.errno
    return {
        "schema_version": 1,
        "host": LOCAL_HOST,
        "port": selected,
        "available": available,
        "status": "available" if available else "occupied",
        "error_code": error_code,
        "network_used": False,
    }


def _acquire_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ShellSettingsBusy("another shell configuration operation is active") from exc
        return
    import fcntl

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, PermissionError) as exc:
        raise ShellSettingsBusy("another shell configuration operation is active") from exc


def _release_os_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(descriptor, fcntl.LOCK_UN)


def _is_reparse_point(path: Path) -> bool:
    if os.name != "nt" or not path.exists():
        return False
    try:
        return bool(path.stat(follow_symlinks=False).st_file_attributes & 0x400)
    except (AttributeError, OSError):
        return True


def _guard_path(path: Path, *, allow_missing: bool) -> Path:
    selected = path.expanduser().absolute()
    if len(str(selected)) > 4096:
        raise ShellPreferencesError("preferences path is too long")
    if selected.exists():
        if selected.is_symlink() or _is_reparse_point(selected):
            raise ShellPreferencesError("symlink and reparse-point preferences are not allowed")
    elif not allow_missing:
        raise ShellPreferencesError("preferences file does not exist")
    parent = selected.parent
    while parent != parent.parent:
        if parent.exists() and (parent.is_symlink() or _is_reparse_point(parent)):
            raise ShellPreferencesError("symlink and reparse-point parents are not allowed")
        parent = parent.parent
    return selected


def _parse_settings(value: Any, defaults: LauncherSettings) -> LauncherSettings:
    if not isinstance(value, dict):
        raise ShellSettingsError("launcher settings must be an object")
    schema_version = value.get("schema_version")
    if type(schema_version) is not int:
        raise ShellSettingsError("launcher settings schema is invalid")
    if schema_version == 1:
        expected = {
            "schema_version",
            "instance_path",
            "update_channel",
            "check_on_start",
            "language",
        }
        if set(value) != expected:
            raise ShellSettingsError("legacy launcher settings fields are invalid")
        return LauncherSettings(
            instance_path=value["instance_path"],
            update_channel=value["update_channel"],
            check_on_start=value["check_on_start"],
            language=value["language"],
        ).normalized()
    if schema_version != SHELL_SETTINGS_SCHEMA_VERSION:
        raise ShellSettingsError("unsupported launcher settings schema")
    expected = {
        "schema_version",
        "revision",
        "instance_path",
        "update_channel",
        "check_on_start",
        "language",
        "endpoint",
        "shell",
    }
    if set(value) != expected:
        raise ShellSettingsError("launcher settings fields are invalid")
    endpoint = value.get("endpoint")
    shell = value.get("shell")
    if not isinstance(endpoint, dict) or set(endpoint) != {
        "host",
        "port",
        "last_good_port",
        "restart_required",
    }:
        raise ShellSettingsError("launcher endpoint settings are invalid")
    if endpoint.get("host") != LOCAL_HOST:
        raise ShellSettingsError("launcher endpoint host must remain loopback")
    if not isinstance(shell, dict) or set(shell) != {
        "tray_enabled",
        "login_startup",
        "theme",
    }:
        raise ShellSettingsError("launcher shell settings are invalid")
    if (
        value.get("update_channel") not in UPDATE_CHANNELS
        or value.get("language") not in LANGUAGES
        or shell.get("theme") not in THEMES
    ):
        raise ShellSettingsError("launcher settings enum is invalid")
    booleans = (
        value.get("check_on_start"),
        endpoint.get("restart_required"),
        shell.get("tray_enabled"),
        shell.get("login_startup"),
    )
    if any(not isinstance(item, bool) for item in booleans):
        raise ShellSettingsError("launcher settings boolean is invalid")
    return LauncherSettings(
        instance_path=value.get("instance_path", defaults.instance_path),
        update_channel=value.get("update_channel", defaults.update_channel),
        check_on_start=value.get("check_on_start", defaults.check_on_start),
        language=value.get("language", defaults.language),
        endpoint_port=endpoint.get("port"),
        last_good_port=endpoint.get("last_good_port"),
        restart_required=endpoint.get("restart_required"),
        tray_enabled=shell.get("tray_enabled"),
        login_startup=shell.get("login_startup"),
        theme=shell.get("theme"),
        revision=value.get("revision"),
    ).normalized()


def _atomic_json(path: Path, value: dict[str, Any], *, maximum: int) -> None:
    selected = _guard_path(path, allow_missing=True)
    selected.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    encoded = payload.encode("utf-8")
    if len(encoded) > maximum:
        raise ShellSettingsError("shell configuration exceeds its size limit")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{selected.name}.",
            suffix=".tmp",
            dir=selected.parent,
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(encoded)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, selected)
        temporary_name = None
        if os.name != "nt":
            directory = os.open(selected.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary_name is not None:
            with suppress(OSError):
                Path(temporary_name).unlink()


class ShellSettingsManager:
    def __init__(self, path: Path, defaults: LauncherSettings):
        self.path = path.expanduser().absolute()
        self.defaults = defaults.normalized()
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")

    def load(self) -> LoadedSettings:
        if not self.path.exists():
            return LoadedSettings(self.defaults, "settings_missing_using_defaults")
        try:
            selected = _guard_path(self.path, allow_missing=False)
            if selected.stat().st_size > MAX_SETTINGS_BYTES:
                raise ShellSettingsError("launcher settings exceed the size limit")
            value = json.loads(selected.read_text(encoding="utf-8"))
            settings = _parse_settings(value, self.defaults)
            warning = (
                "legacy_settings_loaded_pending_migration"
                if isinstance(value, dict) and value.get("schema_version") == 1
                else None
            )
            return LoadedSettings(settings, warning)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ShellSettingsError,
            TypeError,
            ValueError,
        ):
            return LoadedSettings(self.defaults, "settings_invalid_using_safe_defaults")

    @contextmanager
    def hold(self) -> Iterator[None]:
        _guard_path(self.path, allow_missing=True)
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.is_symlink() or _is_reparse_point(self.lock_path):
            raise ShellSettingsBusy("shell configuration lock is unsafe")
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
            0o600,
        )
        locked = False
        try:
            _acquire_os_lock(descriptor)
            locked = True
            yield
        finally:
            try:
                if locked:
                    _release_os_lock(descriptor)
            finally:
                os.close(descriptor)

    def save(self, settings: LauncherSettings) -> Path:
        _atomic_json(self.path, settings.normalized().as_payload(), maximum=MAX_SETTINGS_BYTES)
        return self.path

    def recover_abandoned_writes(self) -> dict[str, Any]:
        removed = 0
        with self.hold():
            pattern = f".{self.path.name}.*.tmp"
            for candidate in list(self.path.parent.glob(pattern))[:32]:
                if (
                    candidate.is_file()
                    and not candidate.is_symlink()
                    and not _is_reparse_point(candidate)
                ):
                    candidate.unlink(missing_ok=True)
                    removed += 1
        return {
            "schema_version": 1,
            "status": "recovered" if removed else "clean",
            "abandoned_writes_removed": removed,
            "limit": 32,
            "network_used": False,
        }

    def mutate(
        self,
        mutator: Callable[[LauncherSettings], LauncherSettings],
        *,
        expected_revision: int | None = None,
        post_commit: Callable[[LauncherSettings], None] | None = None,
    ) -> LauncherSettings:
        with self.hold():
            current = self.load().settings
            if expected_revision is not None and current.revision != expected_revision:
                raise ShellSettingsStale("shell configuration changed; reload before retrying")
            if current.revision >= MAX_SETTINGS_REVISION:
                raise ShellSettingsError("shell configuration revision limit was reached")
            candidate = mutator(current).normalized()
            candidate = replace(candidate, revision=current.revision + 1)
            self.save(candidate)
            try:
                if post_commit is not None:
                    post_commit(candidate)
            except Exception:
                self.save(current)
                raise
            return candidate

    def set_port(
        self,
        port: int | str,
        *,
        expected_revision: int | None = None,
        require_available: bool = True,
    ) -> LauncherSettings:
        selected = validate_port(port)

        def change(current: LauncherSettings) -> LauncherSettings:
            if selected == current.endpoint_port:
                return current
            if require_available and not probe_port(selected)["available"]:
                raise ShellPortUnavailable("requested loopback port is already occupied")
            return replace(
                current,
                endpoint_port=selected,
                last_good_port=current.endpoint_port,
                restart_required=True,
            )

        return self.mutate(change, expected_revision=expected_revision)

    def reset_port(self, *, expected_revision: int | None = None) -> LauncherSettings:
        return self.set_port(DEFAULT_LOCAL_PORT, expected_revision=expected_revision)

    def mark_endpoint_started(self, port: int, *, expected_revision: int) -> LauncherSettings:
        selected = validate_port(port)

        def change(current: LauncherSettings) -> LauncherSettings:
            if current.endpoint_port != selected:
                raise ShellSettingsStale("running endpoint no longer matches configuration")
            return replace(current, last_good_port=selected, restart_required=False)

        return self.mutate(change, expected_revision=expected_revision)

    def rollback_endpoint(self, *, expected_revision: int) -> LauncherSettings:
        def change(current: LauncherSettings) -> LauncherSettings:
            if current.last_good_port == current.endpoint_port:
                raise ShellSettingsError("no distinct endpoint rollback is available")
            if not probe_port(current.last_good_port)["available"]:
                raise ShellPortUnavailable("previous loopback port is also occupied")
            return replace(
                current,
                endpoint_port=current.last_good_port,
                restart_required=True,
            )

        return self.mutate(change, expected_revision=expected_revision)

    def set_preferences(
        self,
        *,
        tray_enabled: bool | None = None,
        login_startup: bool | None = None,
        theme: str | None = None,
        language: str | None = None,
        expected_revision: int | None = None,
        startup_command: str | None = None,
    ) -> LauncherSettings:
        if theme is not None and theme not in THEMES:
            raise ShellSettingsError("theme must be system, light or dark")
        if language is not None and language not in LANGUAGES:
            raise ShellSettingsError("language must be en or it")

        def change(current: LauncherSettings) -> LauncherSettings:
            return replace(
                current,
                tray_enabled=current.tray_enabled if tray_enabled is None else tray_enabled,
                login_startup=(
                    current.login_startup if login_startup is None else login_startup
                ),
                theme=current.theme if theme is None else theme,
                language=current.language if language is None else language,
            )

        post_commit: Callable[[LauncherSettings], None] | None = None
        if login_startup is not None:
            def apply_login_startup(candidate: LauncherSettings) -> None:
                configure_login_startup(
                    candidate.login_startup,
                    command=startup_command,
                )

            post_commit = apply_login_startup
        return self.mutate(
            change,
            expected_revision=expected_revision,
            post_commit=post_commit,
        )

    def configure(
        self,
        *,
        port: int | str,
        tray_enabled: bool,
        login_startup: bool,
        theme: str,
        language: str,
        expected_revision: int,
        startup_command: str | None = None,
    ) -> LauncherSettings:
        selected_port = validate_port(port)
        if theme not in THEMES:
            raise ShellSettingsError("theme must be system, light or dark")
        if language not in LANGUAGES:
            raise ShellSettingsError("language must be en or it")
        before = self.load().settings

        def change(current: LauncherSettings) -> LauncherSettings:
            port_changed = selected_port != current.endpoint_port
            if port_changed and not probe_port(selected_port)["available"]:
                raise ShellPortUnavailable("requested loopback port is already occupied")
            return replace(
                current,
                endpoint_port=selected_port,
                last_good_port=current.endpoint_port if port_changed else current.last_good_port,
                restart_required=current.restart_required or port_changed,
                tray_enabled=tray_enabled,
                login_startup=login_startup,
                theme=theme,
                language=language,
            )

        post_commit: Callable[[LauncherSettings], None] | None = None
        if login_startup != before.login_startup or (
            os.name == "nt" and bool(getattr(sys, "frozen", False))
        ):
            def apply_login_startup(candidate: LauncherSettings) -> None:
                configure_login_startup(
                    candidate.login_startup,
                    command=startup_command,
                )

            post_commit = apply_login_startup
        return self.mutate(
            change,
            expected_revision=expected_revision,
            post_commit=post_commit,
        )

    def export_preferences(self, destination: Path) -> dict[str, Any]:
        current = self.load().settings
        payload = {
            "schema_version": SHELL_PREFERENCES_SCHEMA_VERSION,
            "kind": "provelume-shell-preferences",
            "endpoint_port": current.endpoint_port,
            "tray_enabled": current.tray_enabled,
            "login_startup": current.login_startup,
            "theme": current.theme,
            "language": current.language,
        }
        selected = _guard_path(destination, allow_missing=True)
        _atomic_json(selected, payload, maximum=MAX_PREFERENCES_BYTES)
        encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        return {
            "schema_version": 1,
            "status": "exported",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "size_bytes": len(encoded),
            "contains_instance_path": False,
            "network_used": False,
        }

    def import_preferences(
        self,
        source: Path,
        *,
        expected_revision: int | None = None,
    ) -> LauncherSettings:
        selected = _guard_path(source, allow_missing=False)
        if selected.stat().st_size > MAX_PREFERENCES_BYTES:
            raise ShellPreferencesError("preferences import exceeds the size limit")
        try:
            value = json.loads(selected.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ShellPreferencesError("preferences import is not valid JSON") from exc
        expected = {
            "schema_version",
            "kind",
            "endpoint_port",
            "tray_enabled",
            "login_startup",
            "theme",
            "language",
        }
        if not isinstance(value, dict) or set(value) != expected:
            raise ShellPreferencesError("preferences import fields are invalid")
        if (
            value.get("schema_version") != SHELL_PREFERENCES_SCHEMA_VERSION
            or value.get("kind") != "provelume-shell-preferences"
            or not isinstance(value.get("tray_enabled"), bool)
            or not isinstance(value.get("login_startup"), bool)
            or value.get("theme") not in THEMES
            or value.get("language") not in LANGUAGES
        ):
            raise ShellPreferencesError("preferences import contract is invalid")
        selected_port = validate_port(value["endpoint_port"])
        current = self.load().settings
        if selected_port != current.endpoint_port and not probe_port(selected_port)["available"]:
            raise ShellPortUnavailable("imported loopback port is already occupied")

        def change(settings: LauncherSettings) -> LauncherSettings:
            if selected_port != settings.endpoint_port and not probe_port(selected_port)[
                "available"
            ]:
                raise ShellPortUnavailable("imported loopback port is already occupied")
            return replace(
                settings,
                endpoint_port=selected_port,
                last_good_port=(
                    settings.endpoint_port
                    if selected_port != settings.endpoint_port
                    else settings.last_good_port
                ),
                restart_required=(
                    settings.restart_required or selected_port != settings.endpoint_port
                ),
                tray_enabled=value["tray_enabled"],
                login_startup=value["login_startup"],
                theme=value["theme"],
                language=value["language"],
            )

        post_commit: Callable[[LauncherSettings], None] | None = None
        if value["login_startup"] != current.login_startup or (
            os.name == "nt" and bool(getattr(sys, "frozen", False))
        ):
            def apply_login_startup(candidate: LauncherSettings) -> None:
                configure_login_startup(candidate.login_startup)

            post_commit = apply_login_startup
        return self.mutate(
            change,
            expected_revision=expected_revision,
            post_commit=post_commit,
        )


def validate_startup_executable(executable: str) -> str:
    executable_path = Path(executable)
    if (
        not executable.strip()
        or len(executable) > 4096
        or any(character in executable for character in {'"', "\x00", "\r", "\n"})
        or not executable_path.is_absolute()
        or executable_path.suffix.casefold() != ".exe"
    ):
        raise ShellSettingsError("login startup command is invalid")
    try:
        selected = _guard_path(executable_path, allow_missing=False)
    except ShellPreferencesError as exc:
        raise ShellSettingsError("login startup command is invalid") from exc
    if not selected.is_file():
        raise ShellSettingsError("login startup command is invalid")
    return str(selected)


def configure_login_startup(enabled: bool, *, command: str | None = None) -> None:
    if not isinstance(enabled, bool):
        raise ShellSettingsError("login startup preference is invalid")
    if os.name != "nt":
        raise ShellSettingsError("login startup is available only in installed Windows mode")
    if command is None and not bool(getattr(sys, "frozen", False)):
        raise ShellSettingsError("login startup requires the installed Windows executable")
    import winreg

    executable = validate_startup_executable(command or sys.executable)
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        key_path,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(key, "Provelume", 0, winreg.REG_SZ, f'"{executable}" --tray')
        else:
            with suppress(FileNotFoundError):
                winreg.DeleteValue(key, "Provelume")


def effective_port(*, explicit_port: int | None, persisted: LauncherSettings) -> dict[str, Any]:
    if explicit_port is not None:
        return {
            "port": validate_port(explicit_port),
            "source": "explicit_override",
            "persisted_port": persisted.endpoint_port,
        }
    return {
        "port": persisted.endpoint_port,
        "source": (
            "default" if persisted.endpoint_port == DEFAULT_LOCAL_PORT else "persisted"
        ),
        "persisted_port": persisted.endpoint_port,
    }
