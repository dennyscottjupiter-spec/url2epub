# ---
# purpose: Left navigation shelf: wordmark, one row per page with a gilt bookmark ribbon on the current one
# exports: Sidebar
# depends: ui/theme.py, ui/palette.py, ui/widgets.py, core/paths.py
# gotcha: the selected row takes the page background, so it reads as a tab joined to the page
# ---
import tkinter as tk

from core import paths
from ui import VERSION, palette, theme
from ui.widgets import Button


class Sidebar(tk.Frame):
    def __init__(self, parent, pages, on_select, on_folder):
        super().__init__(parent, width=theme.px(parent, 210))
        self.pack_propagate(False)
        self._on_select = on_select
        self.current = None
        self.rows = {}
        self.icon = None
        icon_path = paths.assets_dir() / "url2epub.png"
        if icon_path.exists():
            self.icon = tk.PhotoImage(file=str(icon_path)).subsample(6)
        head = tk.Frame(self)
        head.pack(fill="x", padx=18, pady=(20, 26))
        self.logo = tk.Label(head, image=self.icon) if self.icon else None
        if self.logo:
            self.logo.pack(side="left", padx=(0, 10))
        self.wordmark = tk.Label(head, text="url2epub", font=palette.FONT_WORDMARK)
        self.wordmark.pack(side="left")
        self._plain = [self, head]

        for i, (key, label) in enumerate(pages, start=1):
            row = tk.Frame(self, cursor="hand2", takefocus=1)
            row.pack(fill="x", pady=1)
            ribbon = tk.Frame(row, width=theme.px(self, 4))
            ribbon.pack(side="left", fill="y")
            text = tk.Label(row, text=label, font=palette.FONT_NAV, anchor="w", padx=16, pady=9)
            text.pack(side="left", fill="x", expand=True)
            hint = tk.Label(row, text=f"Ctrl+{i}", font=palette.FONT_SMALL, padx=12)
            hint.pack(side="right")
            for w in (row, text, hint):
                w.bind("<Button-1>", lambda e, k=key: on_select(k))
                w.bind("<Enter>", lambda e, k=key: self._hover(k, True))
                w.bind("<Leave>", lambda e, k=key: self._hover(k, False))
            row.bind("<Return>", lambda e, k=key: on_select(k))
            row.bind("<space>", lambda e, k=key: on_select(k))
            row.bind("<FocusIn>", lambda e, k=key: self._hover(k, True))
            row.bind("<FocusOut>", lambda e, k=key: self._hover(k, False))
            self.rows[key] = {"row": row, "ribbon": ribbon, "text": text, "hint": hint, "hover": False}

        foot = tk.Frame(self)
        foot.pack(side="bottom", fill="x", padx=14, pady=(0, 16))
        self.folder_btn = Button(foot, text="Open output folder", command=on_folder, on="sidebar")
        self.folder_btn.pack(fill="x")
        self.version = tk.Label(foot, text=f"Version {VERSION}", font=palette.FONT_SMALL)
        self.version.pack(anchor="w", padx=4, pady=(10, 0))
        self._plain += [foot]
        theme.listen(self, self._recolor)

    def select(self, key):
        self.current = key
        self._recolor(theme.colors())

    def _hover(self, key, on):
        self.rows[key]["hover"] = on
        self._paint_row(key, theme.colors())

    def _paint_row(self, key, c):
        r = self.rows[key]
        selected = key == self.current
        bg = c["bg"] if selected else c["raised"] if r["hover"] else c["sidebar"]
        for w in (r["row"], r["text"], r["hint"]):
            w.configure(background=bg)
        r["ribbon"].configure(background=c["ribbon"] if selected else bg)
        r["text"].configure(foreground=c["text"] if selected or r["hover"] else c["muted"])
        r["hint"].configure(foreground=c["muted"] if r["hover"] else bg)

    def _recolor(self, c):
        for w in self._plain:
            w.configure(background=c["sidebar"])
        if self.logo:
            self.logo.configure(background=c["sidebar"])
        self.wordmark.configure(background=c["sidebar"], foreground=c["text"])
        self.version.configure(background=c["sidebar"], foreground=c["muted"])
        for key in self.rows:
            self._paint_row(key, c)
