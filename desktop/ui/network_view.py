# ---
# purpose: Connections page: probes the services url2epub depends on, on a worker thread
# exports: NetworkView, CHECK_TEXT
# depends: core/connections.py, ui/widgets.py, ui/theme.py
# ---
import threading
from tkinter import ttk

from core import connections
from ui import theme
from ui.widgets import Button, bordered, header

CHECK_TEXT = "Check connections"
COLUMNS = (("service", "Service", 220), ("status", "Status", 120), ("http", "HTTP", 70),
           ("time", "Time", 90), ("detail", "Detail", 400))


class NetworkView(ttk.Frame):
    def __init__(self, parent, app, check_all=connections.check_all):
        super().__init__(parent)
        self.app = app
        self._check_all = check_all
        header(self, "Connections",
               "Checks the sites url2epub uses to fetch pages and to recover pages that block it.")
        self.check_btn = Button(self, text=CHECK_TEXT, command=self.check, variant="accent")
        self.check_btn.pack(anchor="w", pady=(0, 14))
        table = bordered(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings")
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=width, minwidth=50, stretch=key == "detail")
        self.tree.pack(fill="both", expand=True)
        theme.listen(self, self._recolor)

    def _recolor(self, c):
        self.tree.tag_configure("ok", foreground=c["ok"])
        self.tree.tag_configure("bad", foreground=c["bad"])

    def check(self):
        self.check_btn.configure(text="Checking…")
        self.check_btn.state(["disabled"])
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._run, daemon=True).start()

    def show(self, probes):
        for p in probes:
            self.tree.insert("", "end", tags=("ok" if p.ok else "bad",), values=(
                p.name, "● Reachable" if p.ok else "● Unreachable",
                "—" if p.status is None else p.status, f"{p.ms} ms", p.error,
            ))
        self.check_btn.configure(text=CHECK_TEXT)
        self.check_btn.state(["!disabled"])
        ok = sum(p.ok for p in probes)
        self.app.set_status(f"{ok} of {len(probes)} services reachable")

    def _run(self):
        self.app.call_soon(self.show, self._check_all())
