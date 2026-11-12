# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent
datas = [(str(PROJECT_ROOT / 'webapp' / 'static'), 'webapp/static'), (str(PROJECT_ROOT / 'icon' / 'app.ico'), 'icon')]
datas += collect_data_files('cpca')


a = Analysis(
    [str(PROJECT_ROOT / 'win_tray' / 'tray_app.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl', 'uvicorn.protocols.websockets.auto', 'uvicorn.protocols.websockets.wsproto_impl', 'uvicorn.lifespan.on', 'pystray._win32'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(PROJECT_ROOT / 'win_tray' / 'rthook_cpca.py')],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LabelPrintAssistant-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(PROJECT_ROOT / 'icon' / 'app.ico')],
)
