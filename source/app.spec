# -*- mode: python ; coding: utf-8 -*-

import sys

from PyInstaller.utils.hooks import collect_submodules


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('logo.png', '.'),   # โลโก้แสดงใน sidebar
        ('Logo.ico', '.'),   # ไอคอนโปรแกรม
        ('../docs/sync-rule-flowchart.html', 'docs'),
        ('../docs/sync-rule-flowchart.png', 'docs'),
        ('../docs/data-storage-overview.html', 'docs'),
        ('../docs/data-storage-overview.png', 'docs'),
    ],
    hiddenimports=['tools.check_parser'] + collect_submodules('pysnmp'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hooks/no_bytecode.py'],
    excludes=[
        'tkinter', 'unittest', 'doctest', 'pdb', 'lib2to3',
        'test', 'idlelib', 'turtle', 'turtledemo', 'curses',
        'difflib', 'ftplib', 'imaplib', 'poplib',
        'smtplib', 'telnetlib', 'xmlrpc', 'distutils',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS onedir bundle: launch is fast and Qt plugins remain inspectable.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="KOMI Report V5.1.0",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="KOMI Report V5.1.0",
    )
    app = BUNDLE(
        collected,
        name="KOMI Report V5.1.0.app",
        icon="Logo.icns",
        bundle_identifier="com.komiminolta.komireportv5",
        info_plist={
            "CFBundleDisplayName": "KOMI Report V5.1.0",
            "CFBundleShortVersionString": "5.1.0",
            "CFBundleVersion": "50100",
            "LSBackgroundOnly": False,
            "NSHighResolutionCapable": True,
        },
    )
else:
    # Windows onedir build avoids extracting the complete Qt/Python runtime on
    # every launch. Distribute the folder (or an installer made from it); the
    # customer still starts the single EXE inside it.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="KOMI Report V5.1.0",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon="Logo.ico",
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="KOMI Report V5.1.0",
    )
