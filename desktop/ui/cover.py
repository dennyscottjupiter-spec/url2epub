# ---
# purpose: Book-cover card on a Canvas: a finished conversion drawn as an e-reader library tile
# exports: CoverCard
# depends: ui/theme.py (fonts and colors)
# ---
import tkinter as tk
from tkinter import ttk

from ui import theme

W, H = 210, 290
MARGIN = 8
SPINE = 14
TEXT_X = MARGIN + SPINE + 18
TEXT_W = 150
TITLE_TOP, TITLE_LIMIT = 36, 192  # the title may not run below TITLE_LIMIT (about six lines)
MUTED = "#8a8a8a"


def _clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def _shrink_to_fit(c, item, limit):
    # drops words from the end until the text stops above the limit, so the rule below never collides
    text = c.itemcget(item, "text")
    while c.bbox(item)[3] > limit and " " in text:
        text = text.rsplit(" ", 1)[0] + "…"
        c.itemconfigure(item, text=text)


class CoverCard(ttk.Frame):
    def __init__(self, parent, on_open, on_reveal):
        super().__init__(parent)
        self.result = None
        self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0)
        self.canvas.grid(row=0, column=0, columnspan=2)
        self.open_btn = ttk.Button(self, text="Open EPUB", command=on_open)
        self.open_btn.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 4))
        self.reveal_btn = ttk.Button(self, text="Show in folder", command=on_reveal)
        self.reveal_btn.grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(4, 0))
        self.clear()

    def set_bg(self, color):
        self.canvas.configure(background=color)

    def clear(self):
        self.result = None
        c = self.canvas
        c.delete("all")
        c.create_rectangle(MARGIN, MARGIN, W - MARGIN, H - MARGIN, outline=MUTED, dash=(4, 4))
        c.create_text(W // 2, H // 2, text="Your book appears here", fill=MUTED, font=theme.FONT_COVER_META)
        self._set_buttons(False)

    def show(self, result):
        c = self.canvas
        self.result = result
        c.delete("all")
        c.create_rectangle(MARGIN, MARGIN, W - MARGIN, H - MARGIN, fill=theme.COVER_PAPER, outline="")
        c.create_rectangle(MARGIN, MARGIN, MARGIN + SPINE, H - MARGIN, fill=theme.COVER_SPINE, outline="")
        title = c.create_text(
            TEXT_X, TITLE_TOP, text=_clip(result.title or "Untitled", 120), width=TEXT_W, anchor="nw",
            fill=theme.COVER_INK, font=theme.FONT_COVER_TITLE,
        )
        _shrink_to_fit(c, title, TITLE_LIMIT)
        rule = c.bbox(title)[3] + 10
        c.create_line(TEXT_X, rule, TEXT_X + TEXT_W, rule, fill=theme.COVER_INK)
        if result.author:
            c.create_text(
                TEXT_X, rule + 10, text=_clip(result.author, 40), width=TEXT_W, anchor="nw",
                fill=theme.COVER_INK, font=theme.FONT_COVER_META,
            )
        # two lines: the full one-line meta is about 184 px and the text column is 150 px
        meta = f"{_plural(result.chapters, 'chapter')} · {_plural(result.images, 'image')}\n{result.size_kb:,} KB"
        c.create_text(
            TEXT_X, H - 14, text=meta, width=TEXT_W, anchor="sw", justify="left",
            fill=theme.COVER_INK, font=theme.FONT_COVER_META,
        )
        self._set_buttons(True)

    def _set_buttons(self, on):
        state = "!disabled" if on else "disabled"
        self.open_btn.state([state])
        self.reveal_btn.state([state])
