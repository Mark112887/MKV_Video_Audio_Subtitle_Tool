# -*- mode: python ; coding: utf-8 -*-
"""MKV Video Audio & Subtitle Tool — PyInstaller build spec."""

import os, sys
try:
    spec_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    spec_dir = os.getcwd()

a = Analysis(
    ['MKV_Video_Audio_Subtitle_Tool.py'],
    pathex=[spec_dir],
    binaries=[
        ('mkvinfo.exe', '.'),
        ('mkvmerge.exe', '.'),
        ('mkvpropedit.exe', '.'),
    ],
    datas=[],
    hiddenimports=['win32gui', 'win32con'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter.dnd'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MKV Video Audio & Subtitle Tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_window=False,
    icon=None,
    uac_admin=False,
)
