from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TrayState:
    language: str
    service_status: str
    endpoint: str
    visible: bool = True

    def normalized(self) -> TrayState:
        return TrayState(
            language=self.language if self.language in {"en", "it"} else "en",
            service_status=self.service_status.strip()[:80] or "stopped",
            endpoint=self.endpoint.strip()[:80] or "http://127.0.0.1:44851",
            visible=bool(self.visible),
        )


TRAY_LABELS = {
    "en": {
        "open": "Open Provelume",
        "status": "Service: {value}",
        "endpoint": "Endpoint: {value}",
        "settings": "Shell settings",
        "restart": "Restart local service",
        "quit": "Exit Provelume",
        "tooltip": "Provelume · {status} · {endpoint}",
    },
    "it": {
        "open": "Apri Provelume",
        "status": "Servizio: {value}",
        "endpoint": "Endpoint: {value}",
        "settings": "Impostazioni shell",
        "restart": "Riavvia il servizio locale",
        "quit": "Esci da Provelume",
        "tooltip": "Provelume · {status} · {endpoint}",
    },
}

TRAY_STATUS_LABELS = {
    "en": {
        "starting": "starting",
        "running": "running",
        "stopping": "stopping",
        "stopped": "stopped",
        "occupied": "endpoint occupied",
        "crashed": "stopped unexpectedly",
        "server_failed": "start failed",
        "endpoint_rolled_back": "endpoint rolled back",
    },
    "it": {
        "starting": "in avvio",
        "running": "in esecuzione",
        "stopping": "in arresto",
        "stopped": "arrestato",
        "occupied": "endpoint occupato",
        "crashed": "arrestato in modo imprevisto",
        "server_failed": "avvio non riuscito",
        "endpoint_rolled_back": "endpoint ripristinato",
    },
}


class TrayLifecycleHarness:
    """Deterministic lifecycle model used by the permanent Windows smoke."""

    def __init__(self, *, enabled: bool):
        self.enabled = enabled
        self.service_instances = 0
        self.window_visible = True
        self.running = True

    def start_service(self) -> None:
        if self.service_instances == 0:
            self.service_instances = 1

    def open_interface(self) -> None:
        self.start_service()
        self.window_visible = True

    def close_window(self) -> None:
        if self.enabled:
            self.window_visible = False
        else:
            self.quit()

    def restart_service(self) -> None:
        self.service_instances = 1

    def quit(self) -> None:
        self.service_instances = 0
        self.window_visible = False
        self.running = False

    def evidence(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "tray_enabled": self.enabled,
            "service_instances": self.service_instances,
            "window_visible": self.window_visible,
            "shell_running": self.running,
            "network_used": False,
        }


class WindowsTray:
    """Small native Win32 notification-area shell with text-labelled actions."""

    def __init__(
        self,
        root,
        *,
        state: TrayState,
        open_interface: Callable[[], None],
        open_settings: Callable[[], None],
        restart_service: Callable[[], None],
        quit_application: Callable[[], None],
        icon_path: Path | None = None,
    ):
        self.root = root
        self.state = state.normalized()
        self._callbacks = {
            1: open_interface,
            2: open_settings,
            3: restart_service,
            4: quit_application,
        }
        self.icon_path = icon_path
        self.available = False
        self.icon_source = "unavailable"
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._window: int | None = None
        self._thread_id: int | None = None
        self._stop_requested = threading.Event()
        self._notification_added = False
        self._notification_updated: bool | None = None
        self._notification_deleted: bool | None = None

    def start(self) -> bool:
        if os.name != "nt":
            return False
        self._notification_added = False
        self._notification_updated = None
        self._notification_deleted = None
        self._stop_requested.clear()
        self._ready.clear()
        self._thread = threading.Thread(
            target=self._message_loop,
            name="ProvelumeWindowsTray",
            daemon=True,
        )
        self._thread.start()
        self._ready.wait(timeout=5)
        if not self.available:
            self.stop()
        return self.available

    def update(self, *, service_status: str, endpoint: str) -> None:
        self.state = replace(
            self.state,
            service_status=service_status,
            endpoint=endpoint,
        ).normalized()
        if self._window is not None:
            import ctypes
            from ctypes import wintypes

            post_message = ctypes.windll.user32.PostMessageW
            post_message.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            post_message.restype = wintypes.BOOL
            post_message(self._window, 0x8000 + 21, 0, 0)

    def stop(self) -> None:
        self._stop_requested.set()
        if self._window is not None:
            import ctypes
            from ctypes import wintypes

            post_message = ctypes.windll.user32.PostMessageW
            post_message.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            post_message.restype = wintypes.BOOL
            post_message(self._window, 0x0010, 0, 0)
        elif self._thread_id is not None:
            import ctypes
            from ctypes import wintypes

            post_thread_message = ctypes.windll.user32.PostThreadMessageW
            post_thread_message.argtypes = [
                wintypes.DWORD,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            post_thread_message.restype = wintypes.BOOL
            post_thread_message(self._thread_id, 0x0012, 0, 0)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self.available = False

    def exercise_action(self, command_id: int) -> None:
        """Dispatch one bounded menu action for installed native smoke evidence."""

        if command_id not in self._callbacks:
            raise ValueError("unsupported tray action")
        self._dispatch(command_id)

    def lifecycle_evidence(self) -> dict[str, object]:
        thread = self._thread
        return {
            "schema_version": 1,
            "notification_added": self._notification_added,
            "notification_updated": self._notification_updated is True,
            "notification_deleted": self._notification_deleted is True,
            "icon_source": self.icon_source,
            "native_window_released": self._window is None,
            "thread_stopped": thread is None or not thread.is_alive(),
            "network_used": False,
        }

    def _dispatch(self, command_id: int) -> None:
        callback = self._callbacks.get(command_id)
        if callback is not None:
            self.root.after(0, callback)

    def _message_loop(self) -> None:  # pragma: no cover - exercised on windows-latest
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32
        WM_APP_TRAY = 0x8000 + 20
        WM_APP_UPDATE = 0x8000 + 21
        WM_COMMAND = 0x0111
        WM_CLOSE = 0x0010
        WM_DESTROY = 0x0002
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205
        WM_CONTEXTMENU = 0x007B
        NIM_ADD = 0
        NIM_MODIFY = 1
        NIM_DELETE = 2
        NIF_MESSAGE = 1
        NIF_ICON = 2
        NIF_TIP = 4
        MF_STRING = 0
        MF_GRAYED = 1
        MF_SEPARATOR = 0x0800
        TPM_RIGHTBUTTON = 2
        TPM_RETURNCMD = 0x0100
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010

        class WNDCLASSW(ctypes.Structure):
            pass

        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        WNDCLASSW._fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

        class NOTIFYICONDATAW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT),
                ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256),
                ("uTimeoutOrVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16),
                ("hBalloonIcon", wintypes.HICON),
            ]

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadIconW.restype = wintypes.HICON
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.WORD
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        user32.TrackPopupMenu.restype = wintypes.UINT
        shell32.ExtractIconExW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.HICON),
            ctypes.POINTER(wintypes.HICON),
            wintypes.UINT,
        ]
        shell32.ExtractIconExW.restype = wintypes.UINT
        shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(NOTIFYICONDATAW),
        ]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        icon = wintypes.HICON()
        icon_source = "system_fallback"
        owns_icon = False
        candidates = [
            self.icon_path,
            Path(getattr(sys, "_MEIPASS", "")) / "assets" / "provelume.ico",
            Path(sys.executable).with_name("provelume.ico"),
        ]
        for candidate in candidates:
            if candidate is None or not candidate.is_file():
                continue
            loaded = user32.LoadImageW(
                None,
                str(candidate),
                IMAGE_ICON,
                0,
                0,
                LR_LOADFROMFILE,
            )
            if loaded:
                icon = wintypes.HICON(loaded)
                icon_source = "versioned_asset"
                owns_icon = True
                break
        if not icon:
            large = wintypes.HICON()
            small = wintypes.HICON()
            if shell32.ExtractIconExW(
                sys.executable,
                0,
                ctypes.byref(large),
                ctypes.byref(small),
                1,
            ):
                if small:
                    icon = small
                    if large:
                        user32.DestroyIcon(large)
                else:
                    icon = large
                icon_source = "executable_resource"
                owns_icon = bool(icon)
        if not icon:
            icon = user32.LoadIconW(None, 32512)

        notification: NOTIFYICONDATAW | None = None

        def tooltip() -> str:
            value = self.state.normalized()
            labels = TRAY_LABELS[value.language]
            status = TRAY_STATUS_LABELS[value.language].get(
                value.service_status,
                value.service_status,
            )
            return labels["tooltip"].format(
                status=status,
                endpoint=value.endpoint,
            )[:127]

        def modify_notification() -> None:
            if notification is None:
                return
            notification.szTip = tooltip()
            self._notification_updated = bool(
                shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(notification))
            )

        def delete_notification() -> None:
            nonlocal notification
            if notification is None:
                return
            deleted = bool(shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(notification)))
            self._notification_deleted = deleted or self._notification_deleted is True
            notification = None

        def show_menu(window: int) -> None:
            value = self.state.normalized()
            labels = TRAY_LABELS[value.language]
            status = TRAY_STATUS_LABELS[value.language].get(
                value.service_status,
                value.service_status,
            )
            menu = user32.CreatePopupMenu()
            try:
                user32.AppendMenuW(menu, MF_STRING, 1, labels["open"])
                user32.AppendMenuW(
                    menu,
                    MF_STRING | MF_GRAYED,
                    10,
                    labels["status"].format(value=status),
                )
                user32.AppendMenuW(
                    menu,
                    MF_STRING | MF_GRAYED,
                    11,
                    labels["endpoint"].format(value=value.endpoint),
                )
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(menu, MF_STRING, 2, labels["settings"])
                user32.AppendMenuW(menu, MF_STRING, 3, labels["restart"])
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(menu, MF_STRING, 4, labels["quit"])
                point = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(point))
                user32.SetForegroundWindow(window)
                selected = user32.TrackPopupMenu(
                    menu,
                    TPM_RIGHTBUTTON | TPM_RETURNCMD,
                    point.x,
                    point.y,
                    0,
                    window,
                    None,
                )
                if selected:
                    self._dispatch(int(selected))
            finally:
                user32.DestroyMenu(menu)

        @WNDPROC
        def window_proc(window, message, wparam, lparam):
            nonlocal notification
            if message == WM_APP_TRAY:
                event = int(lparam)
                if event == WM_LBUTTONDBLCLK:
                    self._dispatch(1)
                elif event in {WM_RBUTTONUP, WM_CONTEXTMENU}:
                    show_menu(window)
                return 0
            if message == WM_APP_UPDATE:
                modify_notification()
                return 0
            if message == WM_COMMAND:
                self._dispatch(int(wparam) & 0xFFFF)
                return 0
            if message == WM_CLOSE:
                delete_notification()
                user32.DestroyWindow(window)
                return 0
            if message == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(window, message, wparam, lparam)

        class_name = f"ProvelumeTrayWindow-{os.getpid()}"
        module = kernel32.GetModuleHandleW(None)
        window_class = WNDCLASSW(
            0,
            window_proc,
            0,
            0,
            module,
            icon,
            None,
            None,
            None,
            class_name,
        )
        atom = user32.RegisterClassW(ctypes.byref(window_class))
        if not atom:
            if owns_icon:
                user32.DestroyIcon(icon)
            self._ready.set()
            return
        window = user32.CreateWindowExW(
            0,
            class_name,
            "Provelume",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            module,
            None,
        )
        if not window:
            user32.UnregisterClassW(class_name, module)
            if owns_icon:
                user32.DestroyIcon(icon)
            self._ready.set()
            return
        self._window = int(window)
        self._thread_id = int(kernel32.GetCurrentThreadId())
        notification = NOTIFYICONDATAW()
        notification.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        notification.hWnd = window
        notification.uID = 1
        notification.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        notification.uCallbackMessage = WM_APP_TRAY
        notification.hIcon = icon
        notification.szTip = tooltip()
        added = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(notification)))
        self._notification_added = added
        self.available = added and not self._stop_requested.is_set()
        self.icon_source = icon_source
        self._ready.set()
        if not self.available:
            if added:
                delete_notification()
            user32.DestroyWindow(window)
        else:
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        delete_notification()
        if user32.IsWindow(window):
            user32.DestroyWindow(window)
        self._window = None
        self._thread_id = None
        self.available = False
        if owns_icon:
            user32.DestroyIcon(icon)
        user32.UnregisterClassW(class_name, module)
