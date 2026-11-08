# ---
# purpose: About page: what url2epub is, privacy and credits on the left, the changelog on the right
# exports: AboutView
# depends: ui/changelog.py, ui/widgets.py, ui/theme.py, ui/palette.py, core/paths.py
# ---
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from core import paths
from ui import VERSION, palette, theme
from ui.changelog import ENTRIES
from ui.widgets import bordered

ABOUT = (
    "url2epub turns a web article into an EPUB you can read on a Kindle, Kobo or any e-reader. "
    "It finds the article text, drops menus and ads, keeps the images, and starts a new chapter at each heading.",
    "There is no url2epub server: pages are downloaded by your computer. When a site blocks that, url2epub may "
    "ask the Wayback Machine, archive.today or Jina Reader for a copy, and those services see the link.",
)
BULLET = "◆  "
CREDITS = ("Icon made from Microsoft Fluent Emoji (MIT License). Built with Python, tkinter, Requests and "
           "Beautiful Soup. url2epub is free software under the MIT License.")


class AboutView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 36))
        icon_path = paths.assets_dir() / "url2epub.png"
        self.icon = tk.PhotoImage(file=str(icon_path)).subsample(2) if icon_path.exists() else None
        if self.icon:
            ttk.Label(left, image=self.icon).pack(anchor="w", pady=(0, 8))
        ttk.Label(left, text="url2epub", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text=f"Version {VERSION}", style="Subtitle.TLabel").pack(anchor="w", pady=(0, 16))
        for text in ABOUT:
            ttk.Label(left, text=text, wraplength=330, justify="left").pack(anchor="w", pady=(0, 10))
        ttk.Label(left, text=CREDITS, style="Small.TLabel", wraplength=330, justify="left").pack(anchor="w", pady=(6, 0))

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="Changelog", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        box = bordered(right)
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, wrap="word", highlightthickness=0, borderwidth=0, padx=20, pady=16,
                           font=palette.FONT_UI, cursor="arrow")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self._fill()
        theme.listen(self, self._recolor)

    def _fill(self):
        t = self.log
        for i, (heading, date, items) in enumerate(ENTRIES):
            t.insert("end", heading + "\n", ("heading",) if i else ("heading", "first"))
            t.insert("end", date + "\n", "date")
            for item in items:
                t.insert("end", BULLET, ("item", "bullet"))
                t.insert("end", item + "\n", "item")
        t.configure(state="disabled")

    def _recolor(self, c):
        t = self.log
        t.configure(background=c["raised"], foreground=c["text"], selectbackground=c["select"])
        t.tag_configure("heading", font=palette.FONT_SECTION, spacing1=18, foreground=c["text"])
        t.tag_configure("first", spacing1=0)
        t.tag_configure("date", font=palette.FONT_SMALL, foreground=c["muted"], spacing3=8)
        t.tag_configure("bullet", foreground=c["ribbon"], font=palette.FONT_SMALL)
        # wrapped lines start under the text, not under the bullet
        t.tag_configure("item", spacing3=6, lmargin2=tkfont.Font(font=palette.FONT_SMALL).measure(BULLET))
