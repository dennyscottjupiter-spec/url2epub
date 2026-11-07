# ---
# purpose: Runs one URL-to-EPUB conversion on the engine; never raises, streams log lines
# exports: Result, LineWriter, convert(), start()
# depends: engine.py, paths.py, settings.py
# gotcha: the engine keeps state in module globals and patches stdout/input, so _LOCK serializes runs
# ---
import contextlib
import io
import threading
import time
import traceback
from dataclasses import dataclass

from . import engine, paths
from .settings import Settings

_LOCK = threading.Lock()
_NO_INPUT = object()


@dataclass
class Result:
    ok: bool
    url: str
    title: str = ""
    author: str = ""
    path: str = ""
    size_kb: int = 0
    chapters: int = 0
    images: int = 0
    chars: int = 0
    seconds: float = 0.0
    error: str = ""


class LineWriter(io.TextIOBase):
    """Stdout stand-in that hands each complete line to a callback."""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback
        self._partial = ""

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self._partial += s
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            self._callback(line)
        return len(s)

    def flush(self) -> None:
        if self._partial:
            self._callback(self._partial)
            self._partial = ""


def _exit_text(code) -> str:
    if code in (None, 0):
        return "Stopped."
    text = " ".join(str(code).split()).removeprefix("ERROR: ")
    return text[:1].upper() + text[1:]  # the engine's messages can start lowercase after the prefix


def _run(mod, url, s: Settings, log, ask_full_page, t0: float) -> Result:
    writer = LineWriter(log)
    prev_input = vars(mod).get("input", _NO_INPUT)
    mod.input = lambda prompt="": "1" if ask_full_page() else "2"
    try:
        with contextlib.redirect_stdout(writer):
            title, author, article, base = mod.resolve_article(url)
            # counted before split_into_chapters, which inserts marker strings into the tree
            chars = mod.text_len(article)
            if s.embed_images:
                images = mod.collect_images(article, base)
            else:
                for img in article.find_all("img"):
                    img.decompose()
                images = []
            chapters = mod.split_into_chapters(article)
            out_dir = s.resolved_output_dir()
            out_dir.mkdir(parents=True, exist_ok=True)
            path = paths.unique_path(out_dir, mod.sanitize_filename(title))
            mod.write_epub(str(path), title, author, base, chapters, images)
            log(f"Saved {path}")
    finally:
        writer.flush()
        if prev_input is _NO_INPUT:
            del mod.input
        else:
            mod.input = prev_input
    return Result(
        True, url, title=title, author=author, path=str(path),
        size_kb=max(1, path.stat().st_size // 1024),
        chapters=len(chapters), images=len(images), chars=chars,
        seconds=round(time.monotonic() - t0, 1),
    )


def convert(url: str, s: Settings, log=lambda line: None, ask_full_page=lambda: False) -> Result:
    with _LOCK:
        t0 = time.monotonic()
        try:
            mod = engine.load_engine()
            engine.apply_settings(mod, s)
            try:
                url = mod.normalize_url(url)
            except ValueError as e:
                return Result(False, url, error=str(e))
            return _run(mod, url, s, log, ask_full_page, t0)
        except SystemExit as e:
            return Result(False, url, error=_exit_text(e.code))
        except Exception as e:
            for line in traceback.format_exc().splitlines():
                log(line)
            return Result(False, url, error=f"{type(e).__name__}: {e}")


def start(url: str, s: Settings, on_log, on_done, ask_full_page=lambda: False) -> threading.Thread:
    def work():
        on_done(convert(url, s, on_log, ask_full_page))

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread
