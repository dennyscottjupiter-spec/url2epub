# ---
# purpose: Main window: sidebar shelf, stacked pages raised on demand, status line, worker-to-Tk queue
# exports: App, PAGES
# depends: ui/sidebar.py, ui/*_view.py, ui/theme.py, ui/dialogs.py, core/runner.py, core/reports.py
# gotcha: Tk is not thread-safe; worker threads only call call_soon(), never widget methods
# ---
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from core import connections, opener, paths, reports, runner, settings
from ui import (about_view, convert_view, dialogs, history_view, network_view, settings_view, theme)
from ui.sidebar import Sidebar

PAGES = (("convert", "Convert"), ("history", "History"), ("connections", "Connections"),
         ("settings", "Settings"), ("about", "About"))


class App(tk.Tk):
    def __init__(self, settings_path=None, history_path=None,
                 start=runner.start, check_all=connections.check_all):
        super().__init__()
        self.settings_path = paths.settings_file() if settings_path is None else settings_path
        self.history_path = paths.history_file() if history_path is None else history_path
        self._start = start
        self.settings = settings.load(self.settings_path)
        self.title("url2epub")
        # fit small laptop screens (1366x768 here) while leaving room for the taskbar
        w, h = min(1100, self.winfo_screenwidth() - 60), min(720, self.winfo_screenheight() - 110)
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{max(0, (self.winfo_screenheight() - h) // 2 - 30)}")
        self.minsize(860, 560)
        self._set_icon()
        self._queue = queue.Queue()

        self.sidebar = Sidebar(self, PAGES, self.show_page, self.open_output_folder)
        self.sidebar.pack(side="left", fill="y")
        self.folder_btn = self.sidebar.folder_btn
        main = ttk.Frame(self)
        main.pack(side="left", fill="both", expand=True)

        status = ttk.Frame(main, padding=(36, 8, 36, 10))
        status.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value=f"Books are saved to {self.settings.resolved_output_dir()}")
        ttk.Label(status, textvariable=self.status_var, style="Status.TLabel").pack(side="left")
        rule = tk.Frame(main, height=1)
        rule.pack(side="bottom", fill="x", padx=36)
        theme.listen(rule, lambda c: rule.configure(background=c["border"]))

        stack = ttk.Frame(main, padding=(36, 28, 36, 14))
        stack.pack(fill="both", expand=True)
        stack.rowconfigure(0, weight=1)
        stack.columnconfigure(0, weight=1)
        self.convert_view = convert_view.ConvertView(stack, self)
        self.history_view = history_view.HistoryView(stack, self)
        self.network_view = network_view.NetworkView(stack, self, check_all=check_all)
        self.settings_view = settings_view.SettingsView(stack, self)
        self.about_view = about_view.AboutView(stack, self)
        self.pages = dict(zip([k for k, _ in PAGES], (self.convert_view, self.history_view, self.network_view,
                                                       self.settings_view, self.about_view)))
        for view in self.pages.values():
            view.grid(row=0, column=0, sticky="nsew")

        for i, (key, _) in enumerate(PAGES, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, k=key: self.show_page(k))
        self.bind_all("<Control-l>", lambda e: self.focus_link())
        theme.apply(self, self.settings.theme)
        self.show_page("convert")
        self._pump_id = self.after(50, self._pump)

    def destroy(self):
        self.after_cancel(self._pump_id)
        theme.cancel_title_bar(self)
        super().destroy()

    def _set_icon(self):
        ico = paths.assets_dir() / "url2epub.ico"
        if sys.platform == "win32" and ico.exists():
            try:
                self.iconbitmap(default=str(ico))
            except tk.TclError:
                pass

    def show_page(self, key):
        self.current_page = key
        self.pages[key].tkraise()
        self.sidebar.select(key)

    def focus_link(self):
        self.show_page("convert")
        self.convert_view.url_entry.focus_set()
        self.convert_view.url_entry.select_range(0, "end")

    def set_status(self, text):
        self.status_var.set(text)

    def set_theme(self, name):
        theme.apply(self, name)

    def open_output_folder(self):
        folder = self.settings.resolved_output_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            opener.open_path(folder)
        except OSError as e:  # e.g. the saved output folder is on a missing drive
            dialogs.error(self, "Couldn't open the folder", str(e))

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
            try:
                answer["value"] = dialogs.ask_full_page(self)
            except Exception:  # a dialog error must not leave the worker waiting forever
                answer["value"] = False
            finally:
                done.set()

        self.call_soon(ask)
        done.wait()
        return answer.get("value", False)

    def _job_done(self, result):
        try:
            reports.append(result, self.history_path)
            self.history_view.refresh()
        except OSError as e:  # a locked or unwritable history file must not leave Convert busy
            self.convert_view.append_log(f"WARNING: could not update the history ({e})")
        self.convert_view.on_done(result)
        if not result.ok:
            self.set_status("Conversion failed")
            return
        # file name only: a full path runs off the status line (the log keeps the full path)
        self.set_status(f"Saved {Path(result.path).name}")
        if self.settings.open_folder_after:
            try:
                opener.reveal(result.path)
            except OSError:
                pass

    def _pump(self):
        # reschedule first so one failing callback cannot stop the loop
        self._pump_id = self.after(50, self._pump)
        self.drain()
