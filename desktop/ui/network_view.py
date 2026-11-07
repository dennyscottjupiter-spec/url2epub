import threading
from tkinter import ttk

from core import connections

CHECK_TEXT = "Check connections"
COLUMNS = (("service", "Service", 220), ("status", "Status", 110), ("http", "HTTP", 70),
           ("time", "Time", 90), ("detail", "Detail", 400))


class NetworkView(ttk.Frame):
    def __init__(self, parent, app, check_all=connections.check_all):
        super().__init__(parent, padding=12)
        self.app = app
        self._check_all = check_all
        ttk.Label(
            self, text="Checks the services url2epub uses to fetch pages and recover blocked ones.",
        ).pack(anchor="w")
        self.check_btn = ttk.Button(self, text=CHECK_TEXT, command=self.check)
        self.check_btn.pack(anchor="w", pady=8)
        self.tree = ttk.Treeview(self, columns=[c[0] for c in COLUMNS], show="headings")
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=50, stretch=key == "detail")
        self.tree.pack(fill="both", expand=True)

    def check(self):
        self.check_btn.configure(text="Checking…")
        self.check_btn.state(["disabled"])
        self.tree.delete(*self.tree.get_children())
        threading.Thread(target=self._run, daemon=True).start()

    def show(self, probes):
        for p in probes:
            self.tree.insert("", "end", values=(
                p.name, "Reachable" if p.ok else "Unreachable",
                "—" if p.status is None else p.status, f"{p.ms} ms", p.error,
            ))
        self.check_btn.configure(text=CHECK_TEXT)
        self.check_btn.state(["!disabled"])
        ok = sum(p.ok for p in probes)
        self.app.set_status(f"{ok} of {len(probes)} services reachable")

    def _run(self):
        self.app.call_soon(self.show, self._check_all())
