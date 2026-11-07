import ctypes
import sys
import tkinter as tk

FONT_MONO = ("Consolas", 10)
FONT_COVER_TITLE = ("Georgia", 14, "bold")
FONT_COVER_META = ("Georgia", 10)
COVER_PAPER = "#C9CCCF"
COVER_INK = "#2B2B2B"
COVER_SPINE = "#8A9097"


def apply(root, name):
    try:
        import sv_ttk
    except ImportError:
        from tkinter import ttk

        ttk.Style(root).theme_use("clam")  # sv_ttk is optional; clam still runs
        return
    sv_ttk.set_theme(name, root)
    # a timer, never update_idletasks(): flushing here runs before sv_ttk has finished and leaves
    # every frame light grey; after_idle is too early (no native window yet, title stays white)
    root.after(50, _title_bar, root, name == "dark")


def _title_bar(root, dark):
    # sv_ttk can't reach the native title bar; Windows 10 20H1+/11 darken it via DWM attribute 20
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd or not root.winfo_ismapped():  # frame not created yet: try again shortly
            root.after(50, _title_bar, root, dark)
            return
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        # SWP_FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER|NOACTIVATE: repaint the already-drawn title bar
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x20 | 0x2 | 0x1 | 0x4 | 0x10)
    except (AttributeError, OSError, tk.TclError):  # TclError: window already destroyed
        pass


def text_colors(name):
    # tk.Text is not ttk-themed, so its colors are set by hand
    if name == "light":
        return ("#fbfbfb", "#1c1c1c", "#1c1c1c")
    return ("#1f1f1f", "#d6d6d6", "#d6d6d6")
