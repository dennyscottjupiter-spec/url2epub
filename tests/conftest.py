# Puts the repo root (url2epub.py) and desktop/ (package `core`) on sys.path; isolates app data per test.
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "desktop"))


@pytest.fixture(autouse=True)
def appdir(tmp_path, monkeypatch):
    path = tmp_path / "appdata"
    monkeypatch.setenv("URL2EPUB_APPDIR", str(path))
    return path
