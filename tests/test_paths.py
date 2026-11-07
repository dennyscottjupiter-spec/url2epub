import sys

import pytest

from core import paths


def test_app_dir_honours_override_and_creates_it(appdir):
    assert paths.app_dir() == appdir
    assert appdir.is_dir()
    assert paths.settings_file() == appdir / "settings.json"
    assert paths.history_file() == appdir / "history.jsonl"


def test_app_dir_falls_back_to_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv("URL2EPUB_APPDIR")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    assert paths.app_dir() == tmp_path / "roaming" / "url2epub"


def test_default_output_dir_prefers_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert paths.default_output_dir() == tmp_path
    (tmp_path / "Downloads").mkdir()
    assert paths.default_output_dir() == tmp_path / "Downloads"


def test_engine_dir_points_at_repo_root_in_dev():
    assert (paths.engine_dir() / "url2epub.py").is_file()


def test_engine_dir_uses_meipass_when_frozen(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.engine_dir() == tmp_path


@pytest.mark.parametrize("stem,expected", [
    ("con", "_con"),
    ("COM1", "_COM1"),
    ("LPT9", "_LPT9"),
    ("", "article"),
    ("My_Title", "My_Title"),
])
def test_safe_stem(stem, expected):
    assert paths.safe_stem(stem) == expected


def test_unique_path_numbers_collisions(tmp_path):
    first = paths.unique_path(tmp_path, "My_Title")
    assert first.name == "My_Title.epub"
    first.write_bytes(b"x")
    second = paths.unique_path(tmp_path, "My_Title")
    assert second.name == "My_Title (2).epub"
    second.write_bytes(b"x")
    assert paths.unique_path(tmp_path, "My_Title").name == "My_Title (3).epub"


def test_unique_path_guards_reserved_names(tmp_path):
    assert paths.unique_path(tmp_path, "CON").name == "_CON.epub"
