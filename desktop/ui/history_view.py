# ---
# purpose: History page: past conversions in a striped table, open/copy actions, CSV and Markdown export, clear
# exports: HistoryView
# depends: core/reports.py, core/opener.py, ui/dialogs.py, ui/widgets.py, ui/theme.py
# gotcha: tree iids are row indexes into self.rows, so refresh() must rebuild both together
# ---
from pathlib import Path
from tkinter import ttk

from core import opener, reports
from ui import dialogs, theme
from ui.widgets import Button, bordered, header

COLUMNS = (
    ("when", "When", 150), ("status", "Result", 80), ("title", "Title", 300),
    ("kb", "KB", 70), ("chapters", "Chapters", 80), ("images", "Images", 70),
    ("url", "Link", 300),
)
STRETCH = ("title", "url")


def _values(r):
    return (
        r.get("when", ""), "Saved" if r.get("ok") else "Failed", r.get("title") or r.get("error", ""),
        r.get("size_kb", ""), r.get("chapters", ""), r.get("images", ""), r.get("url", ""),
    )


def _summary_text(s):
    if not s["total"]:
        return "No conversions yet. Every article you convert is listed here."
    noun = "conversion" if s["total"] == 1 else "conversions"
    return f"{s['total']} {noun}: {s['ok']} saved, {s['failed']} failed, {s['total_kb']:,} KB in total."


class HistoryView(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.rows = []
        self.summary = header(self, "History")

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 12))
        self.open_btn = Button(bar, text="Open EPUB", command=self.open_epub, variant="accent")
        self.reveal_btn = Button(bar, text="Show in folder", command=self.reveal_epub)
        self.copy_btn = Button(bar, text="Copy link", command=self.copy_link)
        for btn in (self.open_btn, self.reveal_btn, self.copy_btn):
            btn.pack(side="left", padx=(0, 6))
        # housekeeping lives under the table, away from the per-book actions
        foot = ttk.Frame(self)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        self.export_csv_btn = Button(foot, text="Export CSV…", command=self.export_csv)
        self.export_md_btn = Button(foot, text="Export Markdown…", command=self.export_md)
        self.refresh_btn = Button(foot, text="Refresh", command=self.refresh)
        for btn in (self.export_csv_btn, self.export_md_btn, self.refresh_btn):
            btn.pack(side="left", padx=(0, 6))
        self.clear_btn = Button(foot, text="Clear history", command=self.clear_history, variant="danger")
        self.clear_btn.pack(side="right")

        table = bordered(self)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading, anchor="w")
            self.tree.column(key, width=width, minwidth=50, stretch=key in STRETCH)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda event: self.open_epub() if self.tree.identify_row(event.y) else None)
        self.tree.bind("<Return>", lambda event: self.open_epub())
        theme.listen(self, self._recolor)
        self.refresh()

    def _recolor(self, c):
        self.tree.tag_configure("stripe", background=c["bg"])
        self.tree.tag_configure("failed", foreground=c["bad"])

    def refresh(self):
        self.rows = reports.load(self.app.history_path)
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            tags = (("stripe",) if i % 2 else ()) + (() if row.get("ok") else ("failed",))
            self.tree.insert("", "end", iid=str(i), values=_values(row), tags=tags)
        self.summary.configure(text=_summary_text(reports.summary(self.rows)))

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
