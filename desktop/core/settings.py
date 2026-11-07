# ---
# purpose: User settings dataclass with tolerant JSON load, range clamping and plain save
# exports: Settings, load(), normalize(), save()
# depends: paths.py
# gotcha: save() writes in place, not temp+os.replace, because Windows readers lock files
# ---
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import paths


@dataclass
class Settings:
    output_dir: str = ""  # "" means paths.default_output_dir()
    theme: str = "dark"  # "dark" | "light"
    timeout: int = 30  # seconds, clamped 5..120
    max_image_mb: int = 10  # clamped 1..50
    embed_images: bool = True
    open_folder_after: bool = False

    def resolved_output_dir(self) -> Path:
        return Path(self.output_dir) if self.output_dir else paths.default_output_dir()


def _coerce(value, default):
    # bool subclasses int, so it is excluded from the int check explicitly
    if isinstance(default, bool):
        ok = isinstance(value, bool)
    elif isinstance(default, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    else:
        ok = isinstance(value, str)
    return value if ok else default


def normalize(s: Settings) -> Settings:
    s.timeout = min(max(s.timeout, 5), 120)
    s.max_image_mb = min(max(s.max_image_mb, 1), 50)
    if s.theme not in ("dark", "light"):
        s.theme = "dark"
    return s


def load(path=None) -> Settings:
    path = paths.settings_file() if path is None else Path(path)
    base = Settings()
    try:
        # utf-8-sig tolerates a BOM, which PowerShell 5.1 writes by default
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return base
    if not isinstance(raw, dict):
        return base
    for f in fields(base):
        if f.name in raw:
            setattr(base, f.name, _coerce(raw[f.name], getattr(base, f.name)))
    return normalize(base)


def save(s: Settings, path=None) -> None:
    path = paths.settings_file() if path is None else Path(path)
    text = json.dumps(asdict(s), indent=2)  # build first so a failure cannot truncate the file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
