# ---
# purpose: Convert page: link field, progress line, live log, and the bound book once a conversion finishes
# exports: ConvertView, HINT
# depends: ui/cover.py, ui/widgets.py, ui/dialogs.py, ui/theme.py, core/opener.py
# gotcha: widgets change only on the Tk thread; worker callbacks arrive through App.call_soon
# ---
import tkinter as tk
from tkinter import ttk

from core import opener
from ui import dialogs, palette, theme
from ui.cover import CoverCard
from ui.widgets import Button, bordered, header

HINT = "Paste an article link and press Convert to EPUB. Progress shows here."


class ConvertView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.busy = False
        self.url_var = tk.StringVar()
        header(self, "Turn an article into a book",
               "Paste a link. url2epub keeps the article, drops the clutter and binds it as an EPUB.")

        top = ttk.Frame(self)
        top.pack(fill="x")
        self.url_entry = ttk.Entry(top, textvariable=self.url_var, font=palette.FONT_ENTRY)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.url_entry.bind("<Return>", lambda event: self.convert())
        self.paste_btn = Button(top, text="Paste", command=self.paste)
        self.paste_btn.pack(side="left", padx=(0, 6))
        self.convert_btn = Button(top, text="Convert to EPUB", command=self.convert, variant="accent")
        self.convert_btn.pack(side="left")

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", pady=(14, 22))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.cover = CoverCard(body, self.open_epub, self.reveal_epub)
        self.cover.pack(side="left", anchor="n", padx=(0, 28))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Progress", style="Section.TLabel").pack(side="left")
        self.clear_btn = Button(bar, text="Clear log", command=self.clear_log)
        self.clear_btn.pack(side="right")
        box = bordered(right)
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, font=palette.FONT_MONO, wrap="word", state="disabled", highlightthickness=0,
                           borderwidth=0, padx=14, pady=12, spacing1=2, spacing3=2)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        theme.listen(self, self._recolor)
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
        self.cover.working()
        self.append_log(f"Converting {url}")
        self.app.start_job(url)

    def clear_log(self):
        self._replace_log(HINT)

    def append_log(self, line):
        self.log.configure(state="normal")
        tag = "error" if line.lstrip().startswith(("ERROR", "Traceback", "WARNING")) else ""
        self.log.insert("end", line + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    on_log = append_log

    def on_done(self, result):
        self.progress.stop()
        # an indeterminate bar keeps its last spot after stop(), so reset to a determinate bar
        self.progress.configure(mode="determinate", value=100 if result.ok else 0)
        self._set_busy(False)
        if result.ok:
            self.cover.show(result)
            self.append_log(f"Done in {result.seconds:g} s.")
        else:
            self.cover.clear()
            dialogs.error(self, "Couldn't convert this page", result.error or "Unknown error.")

    def open_epub(self):
        self._open(opener.open_path)

    def reveal_epub(self):
        self._open(opener.reveal)

    def _recolor(self, c):
        self.log.configure(background=c["raised"], foreground=c["text"], insertbackground=c["text"],
                           selectbackground=c["select"], selectforeground=c["text"])
        self.log.tag_configure("hint", foreground=c["muted"])
        self.log.tag_configure("error", foreground=c["bad"])

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
        self.log.insert("end", text, "hint")
        self.log.configure(state="disabled")
