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
from ui import VERSION, dialogs, palette, theme
from ui.app import PAGES, App
from ui.widgets import Button

HINT = "Paste an article link and press Convert to EPUB. Progress shows here."
MISSING = ("File not found", "That EPUB was moved or deleted.")
NO_SELECTION = ("Nothing selected", "Select a conversion in the list first.")

def _fake_dialogs(monkeypatch, calls, tmp_path):
    answers = {"choose_folder": str(tmp_path / "books"),
               "save_as": lambda parent, name, ext, types: str(tmp_path / ("export" + ext))}
    for name in ("ask_full_page", "error", "info", "confirm", "choose_folder", "save_as"):
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
    assert theme.current() == "light" and ttk.Style(ui).lookup("TFrame", "background") == palette.LIGHT["bg"]
    assert ui.convert_view.log.cget("background") == palette.LIGHT["raised"]  # tk widgets follow too
    sv.dark_rb.invoke()
    assert theme.current() == "dark" and ttk.Style(ui).lookup("TFrame", "background") == palette.DARK["bg"]
    sv.timeout_var.set("50")
    sv.save_btn.invoke()
    sv.reset_btn.invoke()
    assert sv.timeout_var.get() == "30"
    assert json.loads(ui.settings_path.read_text(encoding="utf-8"))["timeout"] == 30
    assert ("confirm", ("Restore defaults", "Reset every setting to its default value?")) in calls
    sv.appdata_btn.invoke()
    assert calls[-1] == ("open_path", str(paths.app_dir()))

def test_sidebar_folder_button_and_export_error(app, monkeypatch):
    ui, calls = app
    folder = ui.settings_path.parent / "books"
    ui.settings.output_dir = str(folder)
    ui.folder_btn.invoke()
    assert ("open_path", str(folder)) in calls
    convert(ui, "https://example.com/a")
    monkeypatch.setattr(reports, "export_csv", lambda *a: (_ for _ in ()).throw(PermissionError("locked")))
    ui.history_view.export_csv_btn.invoke()
    assert ("error", ("Couldn't export", "locked")) in calls


def test_sidebar_rows_and_shortcuts_switch_pages(app):
    ui, _ = app
    ui.deiconify()
    ui.update()  # synthetic clicks and keys only reach a mapped window
    for key, _label in PAGES:
        ui.sidebar.rows[key]["text"].event_generate("<Button-1>")
        assert ui.current_page == key and ui.sidebar.current == key
    ui.convert_view.url_entry.focus_force()
    ui.update()
    for i, (key, _label) in enumerate(PAGES, start=1):
        ui.event_generate(f"<Control-Key-{i}>")
        ui.update()
        assert ui.current_page == key
    ui.event_generate("<Control-l>")
    ui.update()
    assert ui.current_page == "convert" and ui.focus_get() is ui.convert_view.url_entry


def test_about_page_shows_version_and_changelog(app):
    ui, _ = app
    text = ui.about_view.log.get("1.0", "end")
    assert f"Version {VERSION}" in text and "Version 1.0.0" in text
    assert ui.about_view.log.cget("state") == "disabled"


def test_keycap_button_api(app):
    ui, _ = app
    hits = []
    btn = Button(ui, text="Go", command=lambda: hits.append(1))
    btn.place(x=0, y=0)  # pack would leave it no room beside the expanding page frames
    ui.deiconify()
    ui.update()
    btn.focus_force()
    ui.update()
    btn.event_generate("<KeyPress-space>")
    ui.update()
    ui.after(150)
    ui.update()
    assert hits == [1]
    btn.state(["disabled"])
    assert btn.instate(["disabled"]) and not btn.instate(["!disabled"])
    btn.invoke()
    assert hits == [1]
    btn.state(["!disabled"])
    btn.configure(text="Going")
    assert btn.cget("text") == "Going" and btn.instate(["!disabled"])
    btn.invoke()
    assert hits == [1, 1]


def test_cover_glint_runs_and_stops(app, monkeypatch):
    ui, _ = app
    monkeypatch.setattr(theme, "reduced_motion", lambda: False)
    convert(ui, "https://example.com/a")
    cover = ui.convert_view.cover
    end = time.monotonic() + 3
    while cover._glint is not None:
        assert time.monotonic() < end
        ui.update()
        time.sleep(0.01)
    assert not cover.canvas.find_withtag("glint")


def test_open_failure_is_reported(app, monkeypatch):
    ui, calls = app
    convert(ui, "https://example.com/a")

    def boom(path):  # what Windows raises when no app is registered for .epub (WinError 1155)
        raise OSError(1155, "No application is associated")

    monkeypatch.setattr(opener, "open_path", boom)
    monkeypatch.setattr(opener, "reveal", boom)
    ui.convert_view.cover.open_btn.invoke()
    ui.history_view.tree.selection_set("0")
    ui.history_view.open_btn.invoke()
    ui.history_view.reveal_btn.invoke()
    ui.settings.output_dir = str(ui.settings_path.parent / "books")  # keep the real output folder untouched
    ui.folder_btn.invoke()
    assert [args[0] for name, args in calls if name == "error"] == ["Couldn't open the book"] * 3 + ["Couldn't open the folder"]


def test_history_write_failure_does_not_block_convert(app, monkeypatch):
    ui, _ = app

    def locked(*args):
        raise PermissionError("locked")

    monkeypatch.setattr(reports, "append", locked)
    convert(ui, "https://example.com/a")
    cv = ui.convert_view
    assert cv.cover.result.title == "A Book"
    assert "could not update the history" in cv.log.get("1.0", "end")
    assert cv.convert_btn.instate(["!disabled"])


def test_full_page_dialog_error_does_not_hang(app, monkeypatch):
    ui, _ = app

    def broken(parent):
        raise RuntimeError("tk")

    monkeypatch.setattr(dialogs, "ask_full_page", broken)
    convert(ui, "https://example.com/a")
    assert ui.convert_view.cover.result is not None


def test_destroy_cancels_title_bar_timer(tmp_path):
    ui = App(settings_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl")
    ui.withdraw()
    ui.update()
    assert "_title_bar_id" in ui.__dict__  # still polling: the window is not mapped
    ui.destroy()
    assert "_title_bar_id" not in ui.__dict__