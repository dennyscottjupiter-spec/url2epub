# PyInstaller spec for the Windows desktop app: one windowed url2epub.exe.
# Build with build_exe.ps1 (or: python3 -m PyInstaller url2epub-desktop.spec --noconfirm).
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["desktop/url2epub_gui.py"],
    pathex=["desktop", "."],                 # core/ui packages + the url2epub.py engine
    hiddenimports=["url2epub"] + collect_submodules("x_client_transaction"),
    datas=[("desktop/assets", "assets")],    # window icon + About-page artwork
    # lxml/html5lib get pulled in by bs4's optional builders; the engine only uses html.parser
    excludes=["pytest", "PyInstaller", "IPython", "numpy", "matplotlib", "lxml", "html5lib", "PIL", "sv_ttk"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="url2epub",
    icon="desktop/assets/url2epub.ico",
    console=False,
    upx=False,
)
