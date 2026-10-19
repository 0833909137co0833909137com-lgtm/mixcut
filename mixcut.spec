# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the MixCut macOS (Apple Silicon) desktop app.

Build on a Mac (or the GitHub Actions macos-14 runner):
    pyinstaller mixcut.spec
Result: dist/MixCut.app
"""
from PyInstaller.utils.hooks import collect_all

datas = [
    ("models/clip-vit-b32-laion.bin", "models"),
    ("styles.yaml", "."),
    ("fonts/DejaVuSans.ttf", "fonts"),
]
binaries = [
    ("bin/ffmpeg", "bin"),
]
hiddenimports = []

for pkg in ["torch", "torchvision", "open_clip", "faster_whisper",
            "ctranslate2", "onnxruntime", "av", "numpy", "PIL"]:
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MixCut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch="arm64",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MixCut",
)
app = BUNDLE(
    coll,
    name="MixCut.app",
    bundle_identifier="com.mixcut.app",
    info_plist={
        "NSHighResolutionCapable": "True",
        "LSMinimumSystemVersion": "12.0",
    },
)
