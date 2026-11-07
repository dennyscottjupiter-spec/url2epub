# ---
# purpose: History tab: past conversions in a table, open/copy actions, CSV and Markdown export, clear
# exports: HistoryView
# depends: core/reports.py, core/opener.py, ui/dialogs.py
# gotcha: tree iids are row indexes into self.rows, so refresh() must rebuild both together
# ---
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from core import opener, reports
from ui import dialogs

COLUMNS = (
    ("when", "When", 150), ("status", "Status", 70), ("title", "Title", 300),
    ("kb", "KB", 70), ("chapters", "Chapters", 80), ("images", "Images", 70),
    ("url", "Link", 300),
)
STRETCH = ("title", "url")


def _values(r):
    return (
        r.get("when", ""), "OK" if r.get("ok") else "Failed", r.get("title") or r.get("error", ""),
        r.get("size_kb", ""), r.get("chapters", ""), r.get("images", ""), r.get("url", ""),
    )


def _summary_text(s):
    if not s["total"]:
        return "No conversions yet. Converted articles are listed here."
    noun = "conversion" if s["total"] == 1 else "conversions"
    return f"{s['total']} {noun}, {s['ok']} OK, {s['failed']} failed, {s['total_kb']:,} KB in total"


class HistoryView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.rows = []
        self.summary_var = tk.StringVar()
        ttk.Label(self, textvariable=self.summary_var).pack(anchor="w", pady=(0, 8))

        table = ttk.Frame(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, minwidth=50, stretch=key in STRETCH)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda event: self.open_epub() if self.tree.identify_row(event.y) else None)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", pady=(8, 0))
        self.refresh_btn = ttk.Button(buttons, text="Refresh", command=self.refresh)
        self.open_btn = ttk.Button(buttons, text="Open EPUB", command=self.open_epub)
        self.reveal_btn = ttk.Button(buttons, text="Show in folder", command=self.reveal_epub)
        self.copy_btn = ttk.Button(buttons, text="Copy link", command=self.copy_link)
        self.export_csv_btn = ttk.Button(buttons, text="Export CSV…", command=self.export_csv)
        self.export_md_btn = ttk.Button(buttons, text="Export Markdown…", command=self.export_md)
        self.clear_btn = ttk.Button(buttons, text="Clear history", command=self.clear_history)
        for btn in (self.refresh_btn, self.open_btn, self.reveal_btn, self.copy_btn,
                    self.export_csv_btn, self.export_md_btn, self.clear_btn):
            btn.pack(side="left", padx=(0, 6))
        self.refresh()

    def refresh(self):
        self.rows = reports.load(self.app.history_path)
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(i), values=_values(row))
        self.summary_var.set(_summary_text(reports.summary(self.rows)))

    def selected(self):
        sel = self.tree.selection()
        return self.rows[int(sel[0])] if sel else None

    def open_epub(self):
        self._open_selected(opener.open_path)

    def reveal_epub(self):
        self._open_selected(opener.reveal)

    def copy_link(self):
        row = self._need_row()
        if row is None:
            return
        self.clipboard_clear()
        self.clipboard_append(row.get("url", ""))
        self.app.set_status("Link copied")

    def export_csv(self):
        self._export(".csv", [("CSV", "*.csv")], reports.export_csv)

    def export_md(self):
        self._export(".md", [("Markdown", "*.md")], reports.export_markdown)

    def clear_history(self):
        if dialogs.confirm(self, "Clear history", "Remove every entry from the history list? Your EPUB files are kept."):
            reports.clear(self.app.history_path)
            self.refresh()

    def _need_row(self):
        row = self.selected()
        if row is None:
            dialogs.info(self, "Nothing selected", "Select a conversion in the list first.")
        return row

    def _open_selected(self, action):
        row = self._need_row()
        if row is None:
            return
        path = row.get("path", "")
        # a failed row has no path, and an empty path would open the working folder
        if not path or not Path(path).exists():
            dialogs.error(self, "File not found", "That EPUB was moved or deleted.")
            return
        action(path)

    def _export(self, ext, filetypes, writer):
        if not self.rows:
            dialogs.info(self, "Nothing to export", "Convert an article first.")
            return
        path = dialogs.save_as(self, f"url2epub-history{ext}", ext, filetypes)
        if not path:
            return
        try:
            writer(self.rows, path)
        except OSError as e:  # read-only folder, file open in Excel, ...
            dialogs.error(self, "Couldn't export", str(e))
            return
        self.app.set_status(f"Exported {path}")
