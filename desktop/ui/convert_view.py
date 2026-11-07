# ---
# purpose: Convert tab: link entry, progress bar, live log, and the book cover after a conversion
# exports: ConvertView
# depends: ui/cover.py, ui/dialogs.py, core/opener.py
# gotcha: widgets change only on the Tk thread; worker callbacks arrive through App.call_soon
# ---
import tkinter as tk
from tkinter import ttk

from core import opener
from ui import dialogs, theme
from ui.cover import CoverCard

HINT = "Paste an article link and press Convert to EPUB. Progress shows here."


class ConvertView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.busy = False
        self.url_var = tk.StringVar()

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Article link").pack(side="left", padx=(0, 8))
        self.url_entry = ttk.Entry(top, textvariable=self.url_var)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.url_entry.bind("<Return>", lambda event: self.convert())
        self.paste_btn = ttk.Button(top, text="Paste", command=self.paste)
        self.paste_btn.pack(side="left", padx=(0, 8))
        self.convert_btn = ttk.Button(top, text="Convert to EPUB", style="Accent.TButton", command=self.convert)
        self.convert_btn.pack(side="left")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", pady=8)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.cover = CoverCard(body, self.open_epub, self.reveal_epub)
        self.cover.pack(side="left", anchor="n", padx=(0, 16))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        log_box = ttk.Frame(right)
        log_box.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_box, font=theme.FONT_MONO, wrap="word", state="disabled",
            highlightthickness=0, borderwidth=0, padx=10, pady=8,
        )
        scroll = ttk.Scrollbar(log_box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.clear_btn = ttk.Button(right, text="Clear log", command=self.clear_log)
        self.clear_btn.pack(anchor="e", pady=(8, 0))
        self.clear_log()

    def paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:  # clipboard is empty or holds no text
            return
        self.url_var.set(text.strip())

    def convert(self):
        if self.busy:
            return
        url = self.url_var.get().strip()
        if not url:
            dialogs.error(self, "No link yet", "Paste the address of an article first.")
            return
        self._set_busy(True)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self._replace_log("")
        self.cover.clear()
        self.append_log(f"Converting {url}")
        self.app.start_job(url)

    def clear_log(self):
        self._replace_log(HINT)

    def append_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    on_log = append_log

    def on_done(self, result):
        self.progress.stop()
        # an indeterminate bar keeps its last spot after stop(), so reset to an empty determinate bar
        self.progress.configure(mode="determinate", value=0)
        self._set_busy(False)
        if result.ok:
            self.cover.show(result)
        else:
            self.cover.clear()
            dialogs.error(self, "Couldn't convert this page", result.error or "Unknown error.")

    def open_epub(self):
        self._open(opener.open_path)

    def reveal_epub(self):
        self._open(opener.reveal)

    def apply_colors(self, name):
        bg, fg, insert = theme.text_colors(name)
        self.log.configure(background=bg, foreground=fg, insertbackground=insert)
        self.cover.set_bg(bg)

    def _open(self, action):
        try:
            action(self.cover.result.path)
        except FileNotFoundError:
            dialogs.error(self, "File not found", "That EPUB was moved or deleted.")

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "!disabled"
        for widget in (self.convert_btn, self.url_entry, self.paste_btn):
            widget.state([state])

    def _replace_log(self, text):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", text)
        self.log.configure(state="disabled")
