from PyInstaller.utils.hooks import collect_all


openvr_datas, openvr_binaries, openvr_hiddenimports = collect_all("openvr")
pyglet_datas, pyglet_binaries, pyglet_hiddenimports = collect_all("pyglet")

datas = openvr_datas + pyglet_datas
binaries = openvr_binaries + pyglet_binaries
hiddenimports = openvr_hiddenimports + pyglet_hiddenimports


a = Analysis(
    ["main.py"],
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
    a.binaries,
    a.datas,
    [],
    name="bikeheadvr",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="bikeheadvr.ico",
)
