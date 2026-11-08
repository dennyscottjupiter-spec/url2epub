# ---
# purpose: Desktop entry point; makes the sibling packages importable and starts the Tk app
# exports: main()
# depends: ui/app.py
# ---
import ctypes
import os
import sys


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # crisp text on scaled displays
            # own taskbar identity, so the taskbar shows the url2epub icon instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("url2epub.desktop")
        except Exception:
            pass
    from ui.app import App

    App().mainloop()


if __name__ == "__main__":
    main()
