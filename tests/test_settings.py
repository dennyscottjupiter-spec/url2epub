import codecs
import json

from core import paths, settings
from core.settings import Settings


def test_round_trip(tmp_path):
    f = tmp_path / "s.json"
    original = Settings(output_dir=str(tmp_path), theme="light", timeout=45,
                        max_image_mb=3, embed_images=False, open_folder_after=True)
    settings.save(original, f)
    assert settings.load(f) == original


def test_save_and_load_default_to_app_dir():
    settings.save(Settings(theme="light"))
    assert paths.settings_file().exists()
    assert settings.load().theme == "light"


def test_missing_file_gives_defaults(tmp_path):
    assert settings.load(tmp_path / "nope.json") == Settings()


def test_corrupt_or_non_dict_json_gives_defaults(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert settings.load(bad) == Settings()
    bad.write_text("[1, 2]", encoding="utf-8")
    assert settings.load(bad) == Settings()


def test_bom_file_is_accepted(tmp_path):
    f = tmp_path / "s.json"
    f.write_bytes(codecs.BOM_UTF8 + b'{"theme": "light"}')
    assert settings.load(f) == Settings(theme="light")


def test_wrong_types_fall_back_per_field(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"timeout": "fast", "max_image_mb": True, "embed_images": "yes",
                             "theme": 5, "output_dir": 7, "open_folder_after": True}),
                 encoding="utf-8")
    assert settings.load(f) == Settings(open_folder_after=True)


def test_unknown_keys_ignored(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"theme": "light", "legacy": 1}), encoding="utf-8")
    assert settings.load(f) == Settings(theme="light")


def test_normalize_clamps_and_resets_theme():
    s = settings.normalize(Settings(timeout=999, max_image_mb=0, theme="blue"))
    assert (s.timeout, s.max_image_mb, s.theme) == (120, 1, "dark")
    assert settings.normalize(Settings(timeout=1)).timeout == 5
    assert settings.normalize(Settings(max_image_mb=99)).max_image_mb == 50


def test_resolved_output_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(paths.Path, "home", lambda: tmp_path)
    assert Settings().resolved_output_dir() == tmp_path
    assert Settings(output_dir=str(tmp_path / "x")).resolved_output_dir() == tmp_path / "x"
