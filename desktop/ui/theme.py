# ---
# purpose: Fast native theme: ttk "clam" restyled from palette tokens, recolor listeners, Win11 title bar
# exports: apply(), listen(), colors(), current(), px(), reduced_motion(), rrect()
# depends: ui/palette.py
# gotcha: sv-ttk was dropped on purpose: its image-drawn widgets made every tab switch take 1-3 s on this PC
# ---
import ctypes
import sys
import tkinter as tk
from tkinter import ttk

from ui import palette

_state = {"name": "dark"}


def current():
    return _state["name"]


def colors(name=None):
    return palette.PALETTES[name or _state["name"]]


def listen(widget, fn):
    # stored per toplevel so a destroyed App (tests build many) never gets called again
    widget.winfo_toplevel().__dict__.setdefault("_recolor", []).append(fn)


def px(widget, n):
    return int(round(n * widget.winfo_fpixels("1i") / 96))


def reduced_motion():
    # Windows "Animation effects" off (SPI_GETCLIENTAREAANIMATION) means: skip decorative motion
    if sys.platform != "win32":
        return False
    try:
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)
        return not on.value
    except (AttributeError, OSError):
        return False


def rrect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def apply(root, name):
    _state["name"] = name if name in palette.PALETTES else "dark"
    c = colors()
    style = ttk.Style(root)
    style.theme_use("clam")
    _configure(style, c)
    root.configure(background=c["bg"])
    for fn in getattr(root, "_recolor", []):
        fn(c)
    root.after(30, _title_bar, root, c)


def _configure(s, c):
    flat = {"bordercolor": c["border"], "lightcolor": c["raised"], "darkcolor": c["raised"]}
    s.configure(".", background=c["bg"], foreground=c["text"], font=palette.FONT_UI,
                troughcolor=c["field"], selectbackground=c["select"], selectforeground=c["text"],
                insertcolor=c["text"], focuscolor=c["focus"], **flat)
    s.configure("TFrame", background=c["bg"])
    s.configure("Sidebar.TFrame", background=c["sidebar"])
    s.configure("TLabel", background=c["bg"], foreground=c["text"])
    s.configure("Muted.TLabel", foreground=c["muted"])
    s.configure("Small.TLabel", foreground=c["muted"], font=palette.FONT_SMALL)
    s.configure("Title.TLabel", font=palette.FONT_TITLE)
    s.configure("Subtitle.TLabel", foreground=c["muted"], font=palette.FONT_SUBTITLE)
    s.configure("Section.TLabel", font=palette.FONT_SECTION)
    s.configure("Status.TLabel", foreground=c["muted"], font=palette.FONT_SMALL, background=c["bg"])

    field = {"fieldbackground": c["field"], "foreground": c["text"], "bordercolor": c["border"],
             "lightcolor": c["field"], "darkcolor": c["field"], "insertcolor": c["text"]}
    focus = [("focus", c["accent"] if current() == "light" else c["focus"])]
    for name in ("TEntry", "TSpinbox"):
        s.configure(name, padding=(10, 7), **field)
        s.map(name, bordercolor=focus, lightcolor=focus, darkcolor=[("focus", c["field"])],
              fieldbackground=[("disabled", c["bg"])], foreground=[("disabled", c["muted"])])
    s.configure("TSpinbox", arrowcolor=c["muted"], arrowsize=12, background=c["raised"])
    s.map("TSpinbox", background=[("active", c["select"])], arrowcolor=[("active", c["text"])])

    check = {"background": c["bg"], "foreground": c["text"], "indicatorbackground": c["field"],
             "indicatorforeground": c["accent"],
             "upperbordercolor": c["border"], "lowerbordercolor": c["border"], "indicatormargin": (0, 0, 10, 0),
             "indicatorsize": 15,
             "padding": (2, 5), "focuscolor": c["bg"]}
    s.configure("TCheckbutton", **check)
    s.map("TCheckbutton", background=[("active", c["bg"])], indicatorbackground=[("pressed", c["select"])],
          foreground=[("focus", c["text"])], upperbordercolor=[("focus", c["focus"])],
          lowerbordercolor=[("focus", c["focus"])])

    s.configure("Segment.Toolbutton", background=c["raised"], foreground=c["muted"], padding=(18, 7),
                font=palette.FONT_UI, anchor="center", **flat)
    s.map("Segment.Toolbutton",
          background=[("selected", c["accent"]), ("active", c["select"])],
          foreground=[("selected", c["on_accent"]), ("active", c["text"])],
          bordercolor=[("selected", c["accent"]), ("focus", c["focus"])],
          lightcolor=[("selected", c["accent"])], darkcolor=[("selected", c["accent"])])

    s.configure("Treeview", background=c["raised"], fieldbackground=c["raised"], foreground=c["text"],
                rowheight=30, borderwidth=0, font=palette.FONT_UI, **flat)
    s.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["text"])])
    s.configure("Treeview.Heading", background=c["bg"], foreground=c["muted"], font=palette.FONT_SMALL,
                padding=(8, 7), relief="flat", bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"])
    s.map("Treeview.Heading", background=[("active", c["raised"])], foreground=[("active", c["text"])])
    s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # arrow-less, slim scrollbar: just a thumb in a trough
    s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
        ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    s.configure("Vertical.TScrollbar", troughcolor=c["raised"], background=c["border"], arrowsize=9,
                bordercolor=c["raised"], lightcolor=c["border"], darkcolor=c["border"], gripcount=0)
    s.map("Vertical.TScrollbar", background=[("active", c["muted"])], lightcolor=[("active", c["muted"])],
          darkcolor=[("active", c["muted"])])

    # clam sizes the bar from arrowsize, not thickness; below 6 its borders hide the fill entirely
    s.configure("Horizontal.TProgressbar", troughcolor=c["raised"], background=c["accent"], arrowsize=6,
                bordercolor=c["raised"], lightcolor=c["accent"], darkcolor=c["accent"])


def _hex_to_colorref(h):
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return ctypes.c_int(r | (g << 8) | (b << 16))


def _title_bar(root, c):
    # DWM 20 = dark mode (Win10 20H1+); 35/36 = caption/text color (Win11, ignored elsewhere)
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        if not hwnd or not root.winfo_ismapped():  # frame not created yet: try again shortly
            root.after(50, _title_bar, root, c)
            return
        dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dark = ctypes.c_int(1 if current() == "dark" else 0)
        for attr, value in ((20, dark), (35, _hex_to_colorref(c["sidebar"])), (36, _hex_to_colorref(c["text"]))):
            dwm(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
        # SWP_FRAMECHANGED|NOMOVE|NOSIZE|NOZORDER|NOACTIVATE: repaint the already-drawn title bar
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x20 | 0x2 | 0x1 | 0x4 | 0x10)
    except (AttributeError, OSError, tk.TclError):  # TclError: window already destroyed
        pass
