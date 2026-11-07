# ---
# purpose: Offline tests for core.runner: convert() outcomes, log streaming, input hook, start()
# depends: core/engine.py (monkeypatches resolve_article and collect_images on the real engine module)
# ---
import threading
import zipfile
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from core import engine
from core.runner import LineWriter, Result, convert, start
from core.settings import Settings

ARTICLE = "<h1>A</h1><p>x</p><h2>B</h2><p>y</p>"


def _soup(html=ARTICLE):
    return BeautifulSoup(html, "html.parser")


def _fake_resolve(url):
    print("[meta ] title : My Title")
    return ("My Title", "Ann", _soup(), "https://e.com")


@pytest.fixture
def mod(monkeypatch):
    m = engine.load_engine()
    # convert() writes these globals; restoring them keeps other tests unaffected
    for name in ("TIMEOUT", "MAX_IMAGE_BYTES", "OUTPUT_DIR"):
        monkeypatch.setattr(m, name, getattr(m, name))
    monkeypatch.setattr(m, "collect_images", lambda soup, base: [])
    monkeypatch.setattr(m, "resolve_article", _fake_resolve)
    return m


@pytest.fixture
def out(tmp_path):
    return Settings(output_dir=str(tmp_path / "out"))


def test_line_writer_splits_lines_and_flushes_tail():
    got = []
    w = LineWriter(got.append)
    w.write("one\nme")
    w.write("tw")
    w.write("o\n")
    w.write("tail")
    assert got == ["one", "metwo"]
    w.flush()
    assert got == ["one", "metwo", "tail"]


def test_success_writes_epub_and_streams_log(mod, out):
    lines = []
    r = convert("e.com/article", out, log=lines.append)
    assert r.ok, r.error
    assert (r.title, r.author, r.url) == ("My Title", "Ann", "https://e.com/article")
    assert (r.chapters, r.images, r.chars) == (2, 0, len("A x B y"))
    assert r.size_kb >= 1
    assert Path(r.path).name == "My_Title.epub"
    with zipfile.ZipFile(r.path) as z:
        assert z.namelist()[0] == "mimetype"
    assert "[meta ] title : My Title" in lines
    assert lines[-1] == f"Saved {r.path}"


def test_second_run_gets_numbered_name(mod, out):
    first = convert("https://e.com/a", out)
    second = convert("https://e.com/a", out)
    assert Path(first.path).name == "My_Title.epub"
    assert Path(second.path).name == "My_Title (2).epub"


def test_system_exit_message_is_cleaned(mod, out, monkeypatch):
    def fail(url):
        raise SystemExit("ERROR: boom\n       more")

    monkeypatch.setattr(mod, "resolve_article", fail)
    r = convert("https://e.com/a", out)
    assert not r.ok
    assert r.error == "boom more"


def test_unexpected_exception_is_reported_not_raised(mod, out, monkeypatch):
    def crash(url):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mod, "resolve_article", crash)
    lines = []
    r = convert("https://e.com/a", out, log=lines.append)
    assert not r.ok
    assert r.error.startswith("RuntimeError")
    assert any(line.startswith("Traceback") for line in lines)


def test_invalid_url_fails_before_engine_runs(mod, out):
    r = convert("", out)
    assert not r.ok
    assert r.error == "Empty URL."


@pytest.mark.parametrize("answer,expected", [(True, "1"), (False, "2")])
def test_input_prompt_answered_from_callback(mod, out, monkeypatch, answer, expected):
    seen = []

    def resolve_with_prompt(url):
        # the engine calls input() as a module global, so the fake must go through mod.input
        seen.append(mod.input("Choose 1 or 2: "))
        return _fake_resolve(url)

    monkeypatch.setattr(mod, "resolve_article", resolve_with_prompt)
    r = convert("https://e.com/a", out, ask_full_page=lambda: answer)
    assert r.ok
    assert seen == [expected]


def test_embed_images_off_drops_img_tags(mod, out, monkeypatch):
    calls = []

    def spy_collect(soup, base):
        calls.append(soup)
        return []

    def resolve_with_img(url):
        return ("My Title", "Ann", _soup('<h1>A</h1><p>x<img src="a.png"></p><h2>B</h2><p>y</p>'),
                "https://e.com")

    monkeypatch.setattr(mod, "collect_images", spy_collect)
    monkeypatch.setattr(mod, "resolve_article", resolve_with_img)
    out.embed_images = False
    r = convert("https://e.com/a", out)
    assert r.ok
    assert calls == []
    with zipfile.ZipFile(r.path) as z:
        xhtml = b"".join(z.read(n) for n in z.namelist() if n.endswith(".xhtml"))
    assert b"<img" not in xhtml


def test_input_hook_is_restored_when_it_existed(mod, out, monkeypatch):
    sentinel = lambda prompt="": "sentinel"  # noqa: E731
    monkeypatch.setattr(mod, "input", sentinel, raising=False)
    convert("https://e.com/a", out)
    assert mod.input is sentinel


def test_input_hook_is_removed_when_it_did_not_exist(mod, out, monkeypatch):
    monkeypatch.delattr(mod, "input", raising=False)
    convert("https://e.com/a", out)
    assert "input" not in vars(mod)


def test_start_runs_in_daemon_thread_and_reports(mod, out):
    done = threading.Event()
    got = []

    def on_done(result):
        got.append(result)
        done.set()

    t = start("https://e.com/a", out, on_log=lambda line: None, on_done=on_done)
    assert t.daemon
    assert done.wait(timeout=30)
    assert isinstance(got[0], Result) and got[0].ok
