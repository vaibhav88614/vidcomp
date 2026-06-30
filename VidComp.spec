# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for VidComp.

Build with::

    pyinstaller --noconfirm VidComp.spec

This spec deliberately keeps the **console window** (``console=True``) so that
startup errors, debug prints and traceback output from ``--debug`` runs are all
visible in the terminal alongside the GUI.  The console also gets the same log
stream that is written to ``%APPDATA%/VidComp/logs/vidcomp.log``.

To produce a fully self-contained build, drop ``ffmpeg.exe``, ``ffprobe.exe``
and ``fpcalc.exe`` next to ``main.py`` before building; the snippet below will
pick them up automatically.
"""

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Optional: bundle external tools if they sit beside the spec file.
_here = os.path.dirname(os.path.abspath(SPEC))
_extra_binaries = []
for _exe in ("ffmpeg.exe", "ffprobe.exe", "fpcalc.exe"):
    _p = os.path.join(_here, _exe)
    if os.path.isfile(_p):
        _extra_binaries.append((_p, "."))

a = Analysis(
    ["main.py"],
    pathex=[_here],
    binaries=_extra_binaries,
    datas=[],
    hiddenimports=collect_submodules("vidcomp"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
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
    upx=False,
    console=True,            # <<< keep the console window for debug output
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
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
