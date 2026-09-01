# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
hiddenimports += collect_submodules('celery')
hiddenimports += collect_submodules('kombu')

# faster_whisper бандлит silero_vad.onnx (VAD-модель, используется всегда,
# vad_filter=True в pipeline/transcribe.py) как package data — PyInstaller
# не подхватывает его сам, без этого transcribe() падает с
# "ONNXRuntimeError: NO_SUCHFILE" при первом же вызове в собранном .exe.
datas = collect_data_files('faster_whisper')
datas += [('alembic', 'alembic'), ('alembic.ini', '.')]

a = Analysis(
    ['desktop_main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
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
    name='shorts-backend',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
