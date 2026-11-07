# ---
# purpose: Drives every button, menu entry and the Enter key through the real App, with fake worker, dialogs and opener
# exports: test_* functions
# depends: ui/app.py, core/runner.py
# ---
import json
import threading
import time
from pathlib import Path
from tkinter import ttk

import pytest

from core import connections, opener, paths, reports, runner
from ui import dialogs
from ui.app import App

HINT = "Paste an article link and press Convert to EPUB. Progress shows here."
MISSING = ("File not found", "That EPUB was moved or deleted.")
NO_SELECTION = ("Nothing selected", "Select a conversion in the list first.")

def _fake_dialogs(monkeypatch, calls, tmp_path):
    answers = {"choose_folder": str(tmp_path / "books"),
               "save_as": lambda parent, name, ext, types: str(tmp_path / ("export" + ext))}
    for name in ("ask_full_page", "error", "info", "confirm", "about", "choose_folder", "save_as"):
        monkeypatch.setattr(dialogs, name, _spy(calls, name, answers.get(name, True)))

def _spy(calls, name, answer):
    def call(parent, *args):
        calls.append((name, args))
        return answer(parent, *args) if callable(answer) else answer
    return call

def _fake_opener(monkeypatch, calls):
    def spy(name):
        def call(path):
            if not Path(path).exists():
                raise FileNotFoundError(path)
            calls.append((name, str(path)))
        return call
    monkeypatch.setattr(opener, "open_path", spy("open_path"))
    monkeypatch.setattr(opener, "reveal", spy("reveal"))

def _fake_start(tmp_path):
    def start(url, s, on_log, on_done, ask_full_page):
        def work():
            on_log("fetching")
            if "fail" in url:
                return on_done(runner.Result(False, url, error="Boom"))
            ask_full_page()
            epub = tmp_path / "Book.epub"
            epub.write_bytes(b"x" * 2048)
            on_done(runner.Result(True, url, title="A Book", author="Ann", path=str(epub), size_kb=2, chapters=3, images=1))
        threading.Thread(target=work, daemon=True).start()
    return start

@pytest.fixture
def app(tmp_path, monkeypatch):
    calls = []
    _fake_dialogs(monkeypatch, calls, tmp_path)
    _fake_opener(monkeypatch, calls)
    probes = [connections.Probe("Internet (example.com)", "https://example.com/", True, status=200, ms=12),
              connections.Probe("Wayback Machine", "https://archive.org/", False, error="timeout")]
    ui = App(settings_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl",
             start=_fake_start(tmp_path), check_all=lambda: probes)
    ui.withdraw()
    yield ui, calls
    ui.destroy()

def pump(ui, until):
    end = time.monotonic() + 5
    while not until():
        assert time.monotonic() < end, "timed out waiting for the UI"
        ui.drain()
        ui.update()
        time.sleep(0.01)

def convert(ui, url):
    ui.convert_view.url_var.set(url)
    ui.convert_view.convert_btn.invoke()
    pump(ui, lambda: not ui.convert_view.busy)

def test_convert_button_and_enter_key(app):
    ui, calls = app
    ui.convert_view.convert_btn.invoke()
    assert ("error", ("No link yet", "Paste the address of an article first.")) in calls
    convert(ui, "https://example.com/a")
    cv = ui.convert_view
    assert cv.cover.result.title == "A Book" and cv.cover.open_btn.instate(["!disabled"])
    assert len(reports.load(ui.history_path)) == 1 and ("ask_full_page", ()) in calls
    assert "fetching" in cv.log.get("1.0", "end") and ui.status_var.get().startswith("Saved ")
    convert(ui, "https://example.com/fail")
    assert ("error", ("Couldn't convert this page", "Boom")) in calls
    assert cv.cover.result is None
    ui.deiconify()
    cv.url_var.set("https://example.com/a")
    cv.url_entry.focus_force()
    ui.update()
    cv.url_entry.event_generate("<Return>")
    pump(ui, lambda: cv.cover.result is not None)

def test_paste_and_clear_log(app, monkeypatch):
    ui, _ = app
    cv = ui.convert_view
    monkeypatch.setattr(cv, "clipboard_get", lambda: "  https://example.com/p \n")
    cv.paste_btn.invoke()
    assert cv.url_var.get() == "https://example.com/p"
    convert(ui, "https://example.com/a")
    cv.clear_btn.invoke()
    assert cv.log.get("1.0", "end-1c") == HINT

def test_cover_open_reveal_and_missing_file(app):
    ui, calls = app
    convert(ui, "https://example.com/a")
    cover = ui.convert_view.cover
    path = cover.result.path
    cover.open_btn.invoke()
    cover.reveal_btn.invoke()
    assert ("open_path", path) in calls and ("reveal", path) in calls
    Path(path).unlink()
    cover.open_btn.invoke()
    assert ("error", MISSING) in calls

def test_history_buttons(app):
    ui, calls = app
    hv = ui.history_view
    hv.refresh_btn.invoke()
    for btn in (hv.open_btn, hv.reveal_btn, hv.copy_btn):
        btn.invoke()
    assert calls.count(("info", NO_SELECTION)) == 3
    hv.export_csv_btn.invoke()
    assert ("info", ("Nothing to export", "Convert an article first.")) in calls

    convert(ui, "https://example.com/a")
    path = ui.convert_view.cover.result.path
    convert(ui, "https://example.com/fail")
    hv.tree.selection_set("1")  # newest first, so the success is second
    for btn in (hv.open_btn, hv.reveal_btn, hv.copy_btn):
        btn.invoke()
    assert ("open_path", path) in calls and ("reveal", path) in calls
    assert ui.clipboard_get() == "https://example.com/a"
    hv.tree.selection_set("0")  # the failed row has no file
    hv.open_btn.invoke()
    assert ("error", MISSING) in calls

    hv.export_csv_btn.invoke()
    hv.export_md_btn.invoke()
    assert all((ui.history_path.parent / f"export.{ext}").exists() for ext in ("csv", "md"))
    hv.clear_btn.invoke()
    assert hv.rows == [] and reports.load(ui.history_path) == []

def test_network_check(app):
    ui, _ = app
    nv = ui.network_view
    nv.check_btn.invoke()
    pump(ui, lambda: len(nv.tree.get_children()) == 2)
    assert nv.check_btn.instate(["!disabled"]) and nv.check_btn.cget("text") == "Check connections"
    assert ui.status_var.get() == "1 of 2 services reachable"

def test_settings_browse_save_and_toggles(app):
    ui, _ = app
    sv = ui.settings_view
    sv.browse_btn.invoke()
    sv.timeout_var.set("999")
    sv.embed_cb.invoke()
    sv.folder_cb.invoke()
    sv.save_btn.invoke()
    saved = json.loads(ui.settings_path.read_text(encoding="utf-8"))
    assert saved["timeout"] == 120 and saved["embed_images"] is False and saved["open_folder_after"] is True
    assert saved["output_dir"] == str(ui.settings_path.parent / "books")
    assert sv.timeout_var.get() == "120" and ui.status_var.get().endswith(saved["output_dir"])

def test_theme_reset_and_settings_folder(app):
    ui, calls = app
    sv = ui.settings_view
    sv.light_rb.invoke()
    assert ttk.Style(ui).theme_use() == "sun-valley-light"
    sv.dark_rb.invoke()
    assert ttk.Style(ui).theme_use() == "sun-valley-dark"
    sv.timeout_var.set("50")
    sv.save_btn.invoke()
    sv.reset_btn.invoke()
    assert sv.timeout_var.get() == "30"
    assert json.loads(ui.settings_path.read_text(encoding="utf-8"))["timeout"] == 30
    assert ("confirm", ("Restore defaults", "Reset every setting to its default value?")) in calls
    sv.appdata_btn.invoke()
    assert calls[-1] == ("open_path", str(paths.app_dir()))

def test_status_bar_buttons_and_export_error(app, monkeypatch):
    ui, calls = app
    folder = ui.settings_path.parent / "books"
    ui.settings.output_dir = str(folder)
    ui.folder_btn.invoke()
    ui.about_btn.invoke()
    assert ("open_path", str(folder)) in calls and ("about", ()) in calls
    convert(ui, "https://example.com/a")
    monkeypatch.setattr(reports, "export_csv", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    ui.history_view.export_csv_btn.invoke()
    assert ("error", ("Couldn't export", "locked")) in calls
