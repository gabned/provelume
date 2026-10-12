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
            "muted": "#aab4ad",
            "border": "#59675e",
        }
        if dark
        else {
            "background": "#ffffff",
            "foreground": "#1f2421",
            "fieldbackground": "#f5f3ed",
            "focus": "#365f7a",
            "muted": "#606c64",
            "border": "#89968e",
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
    style.configure(".", background=palette["background"], foreground=palette["foreground"],
                    bordercolor=palette["border"], lightcolor=palette["border"],
                    darkcolor=palette["border"], focuscolor=palette["focus"],
                    selectbackground="#205d83", selectforeground="#ffffff")
    style.map(".", background=[("disabled", palette["background"])],
              foreground=[("disabled", palette["muted"])])
    for name in ("TFrame", "TLabel", "TLabelframe", "TLabelframe.Label", "TCheckbutton"):
        style.configure(name, background=palette["background"], foreground=palette["foreground"])
    for name in ("TButton", "TEntry", "TCombobox"):
        style.configure(name, background=palette["fieldbackground"],
                        fieldbackground=palette["fieldbackground"],
                        foreground=palette["foreground"], padding=(10, 7))
    style.map(
        "TButton",
        background=[("active", palette["fieldbackground"])],
        foreground=[("disabled", palette["muted"]), ("active", palette["foreground"])],
        bordercolor=[("focus", palette["focus"])],
    )
    style.configure("Primary.TButton", background="#205d83", foreground="#ffffff")
    style.map("Primary.TButton", background=[("disabled", palette["fieldbackground"]),
                                             ("pressed", "#174764"), ("active", "#174764")],
              foreground=[("disabled", palette["muted"]), ("!disabled", "#ffffff")])
    for name in ("TEntry", "TCombobox"):
        style.map(name, fieldbackground=[("disabled", palette["background"]),
                                         ("readonly", palette["fieldbackground"])],
                  foreground=[("disabled", palette["muted"]),
                              ("readonly", palette["foreground"])],
                  bordercolor=[("focus", palette["focus"])],
                  lightcolor=[("focus", palette["focus"])])
    style.configure("TCombobox", arrowcolor=palette["foreground"])
    style.map("TCombobox", background=[("active", palette["fieldbackground"]),
                                       ("pressed", palette["fieldbackground"])],
              arrowcolor=[("disabled", palette["muted"])])
    style.configure("TCheckbutton", indicatorbackground=palette["fieldbackground"],
                    indicatorforeground=palette["foreground"], padding=(0, 7))
    style.map("TCheckbutton", background=[("active", palette["background"])],
              indicatorbackground=[("selected", "#205d83")],
              indicatorforeground=[("selected", "#ffffff")])
    style.configure("TScrollbar", background=palette["fieldbackground"],
                    troughcolor=palette["background"], arrowcolor=palette["foreground"])
    style.map("TScrollbar", background=[("active", palette["border"]),
                                        ("pressed", palette["border"])])
    for option, color in {"background": palette["fieldbackground"],
                          "foreground": palette["foreground"],
                          "selectBackground": "#205d83", "selectForeground": "#ffffff"}.items():
        root.option_add("*TCombobox*Listbox." + option, color)
    root.option_add("*Canvas.background", palette["background"])
    root.configure(background=palette["background"])
    dark = choice == "dark" or choice == "system" and host["dark"]
    root.bind("<Map>", lambda event: (
        _windows_caption(root, dark) if event.widget is root else None), add="+")
    return {"choice": choice, "high_contrast": False, "system_colors_preserved": False}


def _windows_caption(root, dark):
    """Let DWM paint the caption; unsupported hosts retain their native caption."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    try:
        ancestor = ctypes.windll.user32.GetAncestor
        ancestor.argtypes = [wintypes.HWND, wintypes.UINT]
        ancestor.restype = wintypes.HWND
        window = ancestor(root.winfo_id(), 2)  # GA_ROOT: Tk's native top-level wrapper.
        setter = ctypes.windll.dwmapi.DwmSetWindowAttribute
        setter.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        setter.restype = ctypes.c_long
        enabled = wintypes.BOOL(dark)
        if setter(window, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)) != 0:
            setter(window, 19, ctypes.byref(enabled), ctypes.sizeof(enabled))
    except (AttributeError, OSError):
        pass


def appearance_evidence(root, combobox):
    """Measure resolved Tk colors, including the real readonly dropdown list."""
    from tkinter import ttk

    style = ttk.Style(root)
    def contrast(foreground, background):
        def luminance(color):
            rgb = [part / 65535 for part in root.winfo_rgb(color)]
            rgb = [part / 12.92 if part <= .04045 else ((part + .055) / 1.055) ** 2.4
                   for part in rgb]
            return sum(part * weight for part, weight in
                       zip(rgb, (.2126, .7152, .0722), strict=True))
        levels = sorted([luminance(foreground), luminance(background)])
        return (levels[1] + .05) / (levels[0] + .05)
    colors = {}
    for name, states, background in [("readonly", ("readonly", "!focus"), "fieldbackground"),
                                      ("readonly_focus", ("readonly", "focus"), "fieldbackground")]:
        foreground = style.lookup("TCombobox", "foreground", states)
        field = style.lookup("TCombobox", background, states)
        colors[name] = {"foreground": foreground, "background": field,
                        "contrast": contrast(foreground, field)}
    popdown = root.tk.call("ttk::combobox::PopdownWindow", str(combobox))
    # Posting reads geometry/colors only: no selection, callback or network mutation.
    root.tk.call("ttk::combobox::Post", str(combobox))
    try:
        for name, foreground, background in [("dropdown", "foreground", "background"),
                                             ("dropdown_selection", "selectforeground",
                                              "selectbackground")]:
            fg = root.tk.call(str(popdown) + ".f.l", "cget", "-" + foreground)
            bg = root.tk.call(str(popdown) + ".f.l", "cget", "-" + background)
            colors[name] = {"foreground": fg, "background": bg, "contrast": contrast(fg, bg)}
    finally:
        root.tk.call("ttk::combobox::Unpost", str(combobox))
    return colors
