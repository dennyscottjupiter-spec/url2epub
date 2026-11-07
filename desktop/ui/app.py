# ---
# purpose: Main window: four tabs, status bar with folder/about buttons, and the worker-to-Tk queue
# exports: App
# depends: ui/*_view.py, ui/theme.py, ui/dialogs.py, core/runner.py, core/reports.py
# gotcha: Tk is not thread-safe; worker threads only call call_soon(), never widget methods
# ---
import queue
import threading
import tkinter as tk
from tkinter import ttk

from core import connections, opener, paths, reports, runner, settings
from ui import convert_view, dialogs, history_view, network_view, settings_view, theme


class App(tk.Tk):
    def __init__(self, settings_path=None, history_path=None,
                 start=runner.start, check_all=connections.check_all):
        super().__init__()
        self.settings_path = paths.settings_file() if settings_path is None else settings_path
        self.history_path = paths.history_file() if history_path is None else history_path
        self._start = start
        self.settings = settings.load(self.settings_path)
        self.title("url2epub")
        self.geometry("1000x660")
        self.minsize(780, 540)
        theme.apply(self, self.settings.theme)
        self._queue = queue.Queue()

        # status bar instead of a menu bar: Windows draws tk menu bars white, even in dark mode
        bar = ttk.Frame(self, padding=(10, 0, 8, 6))
        bar.pack(side="bottom", fill="x")
        # buttons packed before the label so a long status text can't push them off-screen
        self.about_btn = ttk.Button(bar, text="About", command=lambda: dialogs.about(self))
        self.about_btn.pack(side="right")
        self.folder_btn = ttk.Button(bar, text="Open output folder", command=self.open_output_folder)
        self.folder_btn.pack(side="right", padx=(0, 6))
        self.status_var = tk.StringVar(value=f"Books are saved to {self.settings.resolved_output_dir()}")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left", fill="x", expand=True)
        self.notebook = ttk.Notebook(self, padding=8)
        self.notebook.pack(fill="both", expand=True)
        self.convert_view = convert_view.ConvertView(self.notebook, self)
        self.history_view = history_view.HistoryView(self.notebook, self)
        self.network_view = network_view.NetworkView(self.notebook, self, check_all=check_all)
        self.settings_view = settings_view.SettingsView(self.notebook, self)
        for view, label in ((self.convert_view, "Convert"), (self.history_view, "History"),
                            (self.network_view, "Network"), (self.settings_view, "Settings")):
            self.notebook.add(view, text=label)

        self.convert_view.apply_colors(self.settings.theme)
        self._pump_id = self.after(50, self._pump)

    def destroy(self):
        self.after_cancel(self._pump_id)
        super().destroy()

    def set_status(self, text):
        self.status_var.set(text)

    def set_theme(self, name):
        theme.apply(self, name)
        self.convert_view.apply_colors(name)

    def open_output_folder(self):
        folder = self.settings.resolved_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        opener.open_path(folder)

    def call_soon(self, fn, *args):
        self._queue.put((fn, args))

    def drain(self):
        while True:
            try:
                fn, args = self._queue.get_nowait()
            except queue.Empty:
                return
            fn(*args)

    def start_job(self, url):
        self._start(
            url, self.settings,
            on_log=lambda line: self.call_soon(self.convert_view.on_log, line),
            on_done=lambda result: self.call_soon(self._job_done, result),
            ask_full_page=self._ask_full_page,
        )

    def _ask_full_page(self):
        # runs on the worker thread: the question is asked on the Tk thread and the worker waits for the answer
        done = threading.Event()
        answer = {}

        def ask():
            answer["value"] = dialogs.ask_full_page(self)
            done.set()

        self.call_soon(ask)
        done.wait()
        return answer.get("value", False)

    def _job_done(self, result):
        reports.append(result, self.history_path)
        self.history_view.refresh()
        self.convert_view.on_done(result)
        if not result.ok:
            self.set_status("Conversion failed")
            return
        self.set_status(f"Saved {result.path}")
        if self.settings.open_folder_after:
            try:
                opener.reveal(result.path)
            except OSError:
                pass

    def _pump(self):
        # reschedule first so one failing callback cannot stop the loop
        self._pump_id = self.after(50, self._pump)
        self.drain()
