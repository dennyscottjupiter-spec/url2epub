# ---
# purpose: The finished conversion drawn as a cloth-bound book with gilt stamping, plus a one-time foil glint
# exports: CoverCard
# depends: ui/theme.py, ui/palette.py, ui/widgets.py
# ---
import tkinter as tk
from tkinter import ttk

from ui import palette, theme
from ui.widgets import Button

W, H = 236, 344
X1, Y1, X2, Y2 = 14, 10, 206, 278  # the cloth board; pages and shadow sit to its lower right
SPINE = 18
FRAME = 11  # gilt frame inset from the board edge
GLINT_STEPS, GLINT_MS = 18, 26


def _clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _shrink_to_fit(c, item, limit):
    # drops words from the end until the text stops above the limit
    text = c.itemcget(item, "text")
    while c.bbox(item)[3] > limit and " " in text:
        text = text.rsplit(" ", 1)[0] + "…"
        c.itemconfigure(item, text=text)


class CoverCard(ttk.Frame):
    def __init__(self, parent, on_open, on_reveal):
        super().__init__(parent)
        self.result = None
        self._glint = None
        self.canvas = tk.Canvas(self, width=W, height=H, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, columnspan=2)
        self.open_btn = Button(self, text="Open EPUB", command=on_open, variant="accent")
        self.open_btn.grid(row=1, column=0, sticky="ew", padx=(10, 3))
        self.reveal_btn = Button(self, text="Show in folder", command=on_reveal)
        self.reveal_btn.grid(row=1, column=1, sticky="ew", padx=(3, 10))
        theme.listen(self, lambda c: self._redraw())
        self.clear()

    def _redraw(self):
        self.canvas.configure(background=theme.colors()["bg"])
        if self.result:
            self._draw_book(self.result)
        else:
            self._draw_empty(self._empty_text)

    def clear(self):
        self.result = None
        self._empty_text = "Your book appears here"
        self._redraw()
        self._set_buttons(False)

    def working(self):
        self.result = None
        self._empty_text = "Binding your book…"
        self._redraw()
        self._set_buttons(False)

    def show(self, result):
        self.result = result
        self._redraw()
        self._set_buttons(True)
        if not theme.reduced_motion():
            self._start_glint()

    def _draw_empty(self, text):
        c, p = self.canvas, theme.colors()
        c.delete("all")
        c.create_rectangle(X1, Y1, X2, Y2, outline=p["faint"], dash=(5, 4))
        c.create_line(X1 + SPINE, Y1, X1 + SPINE, Y2, fill=p["faint"], dash=(5, 4))
        cx = (X1 + SPINE + X2) / 2
        c.create_text(cx, (Y1 + Y2) / 2, text=text, fill=p["muted"], font=palette.FONT_COVER_AUTHOR,
                      width=X2 - X1 - SPINE - 24, justify="center")

    def _draw_book(self, result):
        c, p, k = self.canvas, theme.colors(), palette.COVER
        c.delete("all")
        shadow = k["shadow_dark"] if theme.current() == "dark" else k["shadow_light"]
        c.create_rectangle(X1 + 7, Y1 + 9, X2 + 7, Y2 + 9, fill=shadow, outline="")
        # page block peeking out past the board, with a few page lines
        c.create_rectangle(X1 + 4, Y1 + 4, X2 + 4, Y2 + 4, fill=k["pages"], outline=k["pages_edge"])
        for i in (1, 2, 3):
            c.create_line(X2 + i, Y1 + 4 + i, X2 + i, Y2 + 4, fill=k["pages_edge"])
        c.create_rectangle(X1, Y1, X2, Y2, fill=k["cloth"], outline="")
        c.create_rectangle(X1, Y1, X1 + SPINE, Y2, fill=k["spine"], outline="")
        c.create_line(X1 + SPINE + 2, Y1, X1 + SPINE + 2, Y2, fill=k["spine"])  # hinge groove
        for y in (Y1 + 16, Y1 + 20, Y2 - 20, Y2 - 16):
            c.create_line(X1 + 4, y, X1 + SPINE - 4, y, fill=k["gilt_soft"])
        fx1, fy1, fx2, fy2 = X1 + SPINE + FRAME, Y1 + FRAME, X2 - FRAME, Y2 - FRAME
        c.create_rectangle(fx1, fy1, fx2, fy2, outline=k["gilt"])
        c.create_rectangle(fx1 + 4, fy1 + 4, fx2 - 4, fy2 - 4, outline=k["gilt_soft"])

        cx, inner = (fx1 + fx2) / 2, fx2 - fx1 - 28
        title = c.create_text(cx, fy1 + 30, text=_clip(result.title or "Untitled", 110), width=inner,
                              anchor="n", justify="center", fill=k["gilt"], font=palette.FONT_COVER_TITLE)
        _shrink_to_fit(c, title, fy1 + 158)
        y = c.bbox(title)[3] + 16
        # drawn fleuron: a diamond between two hairlines, so it never depends on a font glyph
        c.create_line(cx - 30, y, cx - 8, y, fill=k["gilt_soft"])
        c.create_line(cx + 8, y, cx + 30, y, fill=k["gilt_soft"])
        c.create_polygon(cx, y - 4, cx + 4, y, cx, y + 4, cx - 4, y, fill=k["gilt"], outline="")
        if result.author:
            c.create_text(cx, y + 14, text=_clip(result.author, 40), width=inner, anchor="n", justify="center",
                          fill=k["gilt_soft"], font=palette.FONT_COVER_AUTHOR)
        c.create_text(cx, fy2 - 14, text="url2epub", fill=k["gilt_soft"], font=palette.FONT_SMALL)

        meta = (f"{_plural(result.chapters, 'chapter')}, {_plural(result.images, 'image')}\n"
                f"{result.size_kb:,} KB")
        c.create_text((X1 + X2) / 2, Y2 + 22, text=meta, anchor="n", justify="center", fill=p["muted"],
                      font=palette.FONT_SMALL)

    def destroy(self):
        if self._glint:
            self.after_cancel(self._glint)
        super().destroy()

    def _start_glint(self):
        if self._glint:
            self.after_cancel(self._glint)
        self._glint_step(0)

    def _glint_step(self, i):
        c = self.canvas
        c.delete("glint")
        if i > GLINT_STEPS or not self.result:
            self._glint = None
            return
        left, right = X1 + SPINE + 3, X2
        span = right - left + 120
        x = left - 60 + span * i / GLINT_STEPS
        clamp = lambda v: min(max(v, left), right)  # keep the band on the board
        pts = [clamp(x), Y1, clamp(x + 26), Y1, clamp(x - 34), Y2, clamp(x - 60), Y2]
        c.create_polygon(pts, fill="#FFF4D6", stipple="gray25", outline="", tags="glint")
        self._glint = self.after(GLINT_MS, self._glint_step, i + 1)

    def _set_buttons(self, on):
        state = "!disabled" if on else "disabled"
        self.open_btn.state([state])
        self.reveal_btn.state([state])
