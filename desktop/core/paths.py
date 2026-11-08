# ---
# purpose: App-data dirs, default output folder, engine location, collision-free output names
# exports: APP_NAME, app_dir(), settings_file(), history_file(), default_output_dir(), engine_dir(), assets_dir(), safe_stem(), unique_path()
# gotcha: URL2EPUB_APPDIR overrides app_dir() entirely (tests isolate with it)
# ---
import os
import sys
from pathlib import Path

APP_NAME = "url2epub"

_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def app_dir() -> Path:
    override = os.environ.get("URL2EPUB_APPDIR")
    if override:
        base = Path(override)
    else:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) / APP_NAME if appdata else Path.home() / f".{APP_NAME}"
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_file() -> Path:
    return app_dir() / "settings.json"


def history_file() -> Path:
    return app_dir() / "history.jsonl"


def default_output_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


def engine_dir() -> Path:
    # PyInstaller unpacks bundled files under _MEIPASS; in dev, url2epub.py sits at the repo root.
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "assets"
    return Path(__file__).resolve().parents[1] / "assets"


def safe_stem(stem: str) -> str:
    # Windows treats CON.epub as the console device, so reserved stems get a prefix.
    if stem.upper() in _RESERVED:
        return "_" + stem
    return stem or "article"


def unique_path(directory: Path, stem: str, ext: str = ".epub") -> Path:
    base = safe_stem(stem)
    candidate = directory / (base + ext)
    n = 2
    while candidate.exists():
        candidate = directory / f"{base} ({n}){ext}"
        n += 1
    return candidate
