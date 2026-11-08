# ---
# purpose: Keycap Button: rounded, raised on a lip that sinks when pressed; mimics the ttk.Button API
# exports: Button, header(), bordered()
# depends: ui/theme.py, ui/palette.py
# gotcha: implements invoke/state/instate/cget/configure(text=) so views and tests treat it like ttk.Button
# ---
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ui import palette, theme

PAD_X, PAD_Y, LIP, RADIUS, RING = 16, 6, 3, 7, 2


def header(parent, title, subtitle=""):
    """Page heading in Sitka with a muted one-line explainer; returns the subtitle label."""
    ttk.Label(parent, text=title, style="Title.TLabel").pack(anchor="w")
    sub = ttk.Label(parent, text=subtitle, style="Subtitle.TLabel")
    sub.pack(anchor="w", pady=(2, 18))
    return sub


def bordered(parent):
    """A frame with a 1 px palette border that follows theme changes."""
    frame = tk.Frame(parent, highlightthickness=1, borderwidth=0)
    theme.listen(frame, lambda c: frame.configure(highlightbackground=c["border"], highlightcolor=c["border"],
                                                  background=c["raised"]))
    return frame


class Button(tk.Canvas):
    def __init__(self, parent, text="", command=None, variant="secondary", on="bg"):
        super().__init__(parent, highlightthickness=0, borderwidth=0, takefocus=1, cursor="hand2")
        self._text, self._command, self.variant, self.on = text, command, variant, on
        self._disabled = self._hover = self._down = self._focus = False
        self._font = palette.FONT_UI_BOLD if variant == "accent" else palette.FONT_UI
        for seq, fn in (("<Enter>", lambda e: self._set(hover=True)), ("<Leave>", lambda e: self._set(hover=False, down=False)),
                        ("<ButtonPress-1>", self._press), ("<ButtonRelease-1>", self._release),
                        ("<FocusIn>", lambda e: self._set(focus=True)), ("<FocusOut>", lambda e: self._set(focus=False)),
                        ("<KeyPress-space>", self._key), ("<Return>", self._key), ("<KP_Enter>", self._key),
                        ("<Configure>", lambda e: self._draw())):
            self.bind(seq, fn)
        theme.listen(self, lambda c: self._draw())
        self._resize()

    # ttk.Button-compatible surface
    def invoke(self):
        if not self._disabled and self._command:
            return self._command()

    def state(self, specs=None):
        for spec in specs or ():
            if spec in ("disabled", "!disabled"):
                self._disabled = spec == "disabled"
                self.configure(cursor="arrow" if self._disabled else "hand2", takefocus=0 if self._disabled else 1)
        self._draw()

    def instate(self, specs):
        return all(self._disabled == (s == "disabled") for s in specs if s.lstrip("!") == "disabled")

    def configure(self, cnf=None, **kw):
        changed = False
        for key, attr in (("text", "_text"), ("command", "_command")):
            if key in kw:
                setattr(self, attr, kw.pop(key))
                changed = True
        result = super().configure(cnf, **kw) if (cnf or kw) else None
        if changed:
            self._resize()
        return result

    config = configure

    def cget(self, key):
        return self._text if key == "text" else super().cget(key)

    # drawing
    def _resize(self):
        f = tkfont.Font(font=self._font)
        w = f.measure(self._text) + 2 * theme.px(self, PAD_X + RING)
        h = f.metrics("linespace") + 2 * theme.px(self, PAD_Y + RING) + theme.px(self, LIP)
        super().configure(width=w, height=h)
        self._draw()

    def _set(self, **flags):
        for k, v in flags.items():
            setattr(self, "_" + k, v)
        self._draw()

    def _press(self, event):
        if not self._disabled:
            self.focus_set()
            self._set(down=True)

    def _release(self, event):
        was_down = self._down
        self._set(down=False)
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if was_down and inside:
            self.invoke()

    def _key(self, event):
        if self._disabled:
            return "break"
        self._set(down=True)
        self.after(90, lambda: (self._set(down=False), self.invoke()))
        return "break"

    def _colors(self, c):
        if self._disabled:
            return c["raised"] if self.variant != "accent" else c["border"], None, c["faint"], c["border"]
        if self.variant == "accent":
            face = c["accent_down"] if self._down else c["accent_hover"] if self._hover else c["accent"]
            return face, c["accent_lip"], c["on_accent"], face
        face = c["select"] if (self._hover or self._down) else c["raised"]
        fg = c["bad"] if self.variant == "danger" else c["text"]
        return face, c["lip"], fg, c["border"]

    def _draw(self):
        c = theme.colors()
        self.delete("all")
        self["background"] = c[self.on]
        w, h = self.winfo_width(), self.winfo_height()
        if w <= 1:  # not laid out yet: use the requested size
            w, h = int(self["width"]), int(self["height"])
        ring, lip, r = theme.px(self, RING), theme.px(self, LIP), theme.px(self, RADIUS)
        face, lip_color, fg, outline = self._colors(c)
        x1, y1, x2, y2 = ring, ring, w - ring - 1, h - ring - lip - 1
        sink = lip if (self._down and lip_color) else 0
        if lip_color and not self._down:
            theme.rrect(self, x1, y1 + lip, x2, y2 + lip, r, fill=lip_color, outline=lip_color)
        theme.rrect(self, x1, y1 + sink, x2, y2 + sink, r, fill=face, outline=outline)
        if self._focus and not self._disabled:
            theme.rrect(self, x1 - ring + 1, y1 - ring + 1, x2 + ring - 1, y2 + lip + ring - 1, r + ring,
                        fill="", outline=c["focus"], width=1)
        self.create_text((x1 + x2) / 2, (y1 + y2) / 2 + sink, text=self._text, fill=fg, font=self._font)
