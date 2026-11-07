# ---
# purpose: Open a file/folder with the OS default app, or reveal a file in Explorer
# exports: open_path(), reveal()
# ---
import os
import subprocess
import sys
from pathlib import Path


def open_path(path) -> None:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if sys.platform == "win32":
        os.startfile(str(p))
    else:
        subprocess.Popen(["xdg-open", str(p)])


def reveal(path) -> None:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if sys.platform == "win32":
        if p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            open_path(p)
    else:
        open_path(p.parent)
