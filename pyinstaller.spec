# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VidComp (Windows one-folder build).

Build with::

    pyinstaller pyinstaller.spec

Output: ``dist/VidComp/VidComp.exe``

Notes
-----
* Bundles PySide6, OpenCV, imagehash, Pillow, numpy and scikit-image.
* Does NOT bundle ffmpeg / ffprobe / fpcalc — the user installs those
  separately and adds them to PATH (see README).
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

hidden = []
hidden += collect_submodules("PySide6")
hidden += collect_submodules("imagehash")
hidden += collect_submodules("PIL")

datas = []
# Include scikit-image data files (needed by some submodules).
try:
    datas += collect_data_files("skimage")
except Exception:
    pass

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PyQt5",
        "PyQt6",
        "pytest",
        "tests",
        "matplotlib",
        "IPython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VidComp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # leave UPX off — AVs flag UPX-packed binaries
    console=False,              # GUI app — no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VidComp",
)
