# ---
# purpose: End-to-end: serve tests/fixtures/dummy_article.html on localhost, convert it with the REAL engine
#          (runner and the GUI's Convert button), then open the EPUB and check every part of it
# exports: test_* functions
# depends: core/runner.py, ui/app.py, url2epub.py, tests/fixtures/
# ---
import functools
import http.server
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from core import reports, runner
from core.settings import Settings
from ui import dialogs

FIXTURES = Path(__file__).parent / "fixtures"
TITLE, AUTHOR = "The Lighthouse Keeper's Logbook", "Marta Quill"


@pytest.fixture(scope="module")
def served():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/dummy_article.html"
    server.shutdown()


def check_epub(path):
    """Opens the EPUB like a reader would and returns its visible text."""
    with zipfile.ZipFile(path) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        names = z.namelist()
        assert "META-INF/container.xml" in names
        for name in names:
            if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
                ET.fromstring(z.read(name))  # every markup file must be well-formed XML
        images = [n for n in names if n.endswith(".png")]
        assert len(images) == 1 and z.read(images[0]) == (FIXTURES / "dummy_figure.png").read_bytes()
        text = " ".join(z.read(n).decode("utf-8") for n in names if n.endswith(".xhtml"))
    for kept in ("fog is only a cloud", "keep the light clean", "Chapter three: One thing learned"):
        assert kept in text
    for junk in ("ADVERTISEMENT", "Cookie settings", "Related posts", "Ten lamps"):
        assert junk not in text
    return text


def test_runner_converts_dummy_article(served, tmp_path):
    lines = []
    result = runner.convert(served, Settings(output_dir=str(tmp_path)), log=lines.append)
    assert result.ok, (result.error, lines)
    assert (result.title, result.author) == (TITLE, AUTHOR)
    assert result.images == 1 and result.chapters >= 3
    check_epub(result.path)


def test_gui_convert_button_with_real_engine(served, tmp_path, monkeypatch):
    from ui.app import App

    errors = []
    monkeypatch.setattr(dialogs, "error", lambda parent, *a: errors.append(a))
    ui = App(settings_path=tmp_path / "s.json", history_path=tmp_path / "h.jsonl")
    try:
        ui.withdraw()
        ui.settings.output_dir = str(tmp_path / "books")
        ui.convert_view.url_var.set(served)
        ui.convert_view.convert_btn.invoke()
        end = time.monotonic() + 60
        while ui.convert_view.busy:
            assert time.monotonic() < end, "conversion did not finish"
            ui.drain()
            ui.update()
            time.sleep(0.02)
        assert not errors
        result = ui.convert_view.cover.result
        assert result.ok and result.title == TITLE and Path(result.path).parent == tmp_path / "books"
        assert ui.convert_view.cover.open_btn.instate(["!disabled"])
        assert reports.load(ui.history_path)[0]["title"] == TITLE
        assert ui.status_var.get() == f"Saved {Path(result.path).name}"
        assert ui.convert_view.progress.cget("value") == 100  # the bar ends full, not blank
        check_epub(result.path)
    finally:
        ui.destroy()
