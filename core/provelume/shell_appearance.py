"""Apply host appearance before widgets paint; retain OS high-contrast colors."""

import os


def windows_appearance():
    if os.name != "nt":
        return {"dark": False, "high_contrast": False, "observed": False}
    import ctypes
    import winreg
    from ctypes import wintypes

    class HighContrast(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwFlags", wintypes.DWORD),
            ("lpszDefaultScheme", wintypes.LPWSTR),
        ]

    contrast = HighContrast()
    contrast.cbSize = ctypes.sizeof(contrast)
    observed = bool(
        ctypes.windll.user32.SystemParametersInfoW(
            0x0042,
            contrast.cbSize,
            ctypes.byref(contrast),
            0,
        )
    )
    dark = False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            dark = value == 0
    except OSError:
        pass
    return {
        "dark": dark,
        "high_contrast": observed and bool(contrast.dwFlags & 1),
        "observed": observed,
    }


def native_palette(choice, *, system_dark=False, high_contrast=False):
    if choice not in {"system", "light", "dark"}:
        raise ValueError("invalid appearance choice")
    if high_contrast:
        return None
    dark = choice == "dark" or choice == "system" and system_dark
    return (
        {
            "background": "#202421",
            "foreground": "#eff2ef",
            "fieldbackground": "#171a18",
            "focus": "#add3e9",
        }
        if dark
        else {
            "background": "#ffffff",
            "foreground": "#1f2421",
            "fieldbackground": "#f5f3ed",
            "focus": "#365f7a",
        }
    )


def apply_native_appearance(root, choice):
    from tkinter import ttk

    host = windows_appearance()
    palette = native_palette(choice, system_dark=host["dark"], high_contrast=host["high_contrast"])
    if palette is None:
        return {"choice": choice, "high_contrast": True, "system_colors_preserved": True}
    style = ttk.Style(root)
    style.theme_use("clam")
    for name in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label", "TCheckbutton"):
        style.configure(name, background=palette["background"], foreground=palette["foreground"])
    for name in ("TButton", "TEntry", "TCombobox"):
        style.configure(name, **palette)
    style.map(
        "TButton",
        background=[("active", palette["fieldbackground"])],
        foreground=[("disabled", palette["foreground"]), ("active", palette["foreground"])],
    )
    root.configure(background=palette["background"])
    return {"choice": choice, "high_contrast": False, "system_colors_preserved": False}
