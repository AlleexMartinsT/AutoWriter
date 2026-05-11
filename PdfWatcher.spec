# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_dir = Path(SPECPATH).resolve()
datas = [('favicon.ico', '.')]
if (project_dir / 'message_template.txt').exists():
    datas.append(('message_template.txt', '.'))
if (project_dir / 'credentials.json').exists():
    datas.append(('credentials.json', '.'))

a = Analysis(
    ['downloads_pdf_mover.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pystray',
        'PIL',
        'PIL.Image',
        'pypdf',
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
    ],
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
    name='PdfWatcher',
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
    icon=['favicon.ico'],
)
