# ---
# purpose: Imports the url2epub engine (repo root in dev, bundle when frozen) and applies Settings to it
# exports: load_engine(), apply_settings()
# depends: paths.py, settings.py
# gotcha: windowed PyInstaller builds have sys.stdout None, but the engine prints, so streams are stubbed first
# ---
import os
import sys

from . import paths
from .settings import Settings

_mod = None


def load_engine():
    global _mod
    if _mod is None:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        root = str(paths.engine_dir())
        if root not in sys.path:
            sys.path.insert(0, root)
        import url2epub

        _mod = url2epub
    return _mod


def apply_settings(mod, s: Settings) -> None:
    mod.TIMEOUT = s.timeout
    mod.MAX_IMAGE_BYTES = s.max_image_mb * 1024 * 1024
    mod.OUTPUT_DIR = str(s.resolved_output_dir())
