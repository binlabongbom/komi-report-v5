# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from tools.release_safety import FORBIDDEN_SUFFIXES


web_datas = []
node_binaries = []
offline_public_keys = os.environ.get(
    "KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_BUILD_FILE", ""
).strip()
if offline_public_keys:
    public_keys_path = Path(offline_public_keys)
    if not public_keys_path.is_file():
        raise ValueError("KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_BUILD_FILE does not exist")
    web_datas.append(
        (str(public_keys_path), "runtime-config")
    )
if sys.platform == "darwin":
    web_standalone = Path("../web/.next/standalone")
    web_static = Path("../web/.next/static")
    web_server = Path("../web/server.mjs")
    node_runtime = os.environ.get("KOMI_NODE_RUNTIME_BUILD_FILE", "").strip()
    if not (web_standalone / ".next" / "BUILD_ID").is_file():
        raise ValueError("Run the Web production build before packaging macOS")
    if not node_runtime or not Path(node_runtime).is_file():
        raise ValueError("KOMI_NODE_RUNTIME_BUILD_FILE is required for macOS packaging")
    web_datas.extend(
        [
            (str(web_standalone), "web-runtime-seed"),
            (str(web_static), "web-runtime-seed/.next/static"),
            (str(web_server), "web-runtime-seed"),
        ]
    )
    node_binaries.append((node_runtime, "node-runtime"))


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=node_binaries,
    datas=[
        ('logo.png', '.'),   # โลโก้แสดงใน sidebar
        ('Logo.ico', '.'),   # ไอคอนโปรแกรม
        ('../docs/sync-rule-flowchart.html', 'docs'),
        ('../docs/sync-rule-flowchart.png', 'docs'),
        ('../docs/data-storage-overview.html', 'docs'),
        ('../docs/data-storage-overview.png', 'docs'),
    ] + web_datas,
    hiddenimports=['tools.check_parser', 'web_api'] + collect_submodules('pysnmp'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hooks/no_bytecode.py'],
    excludes=[
        'tkinter', 'unittest', 'doctest', 'pdb', 'lib2to3',
        'test', 'idlelib', 'turtle', 'turtledemo', 'curses',
        'difflib', 'ftplib', 'imaplib', 'poplib',
        'smtplib', 'telnetlib', 'xmlrpc',
    ],
    noarchive=False,
    optimize=2,
)
# Release artifacts must not contain DB/CSV/log/env/credential-style files,
# including package test data and optional color-map assets collected by hooks.
a.datas = [
    item
    for item in a.datas
    if not any(str(item[0]).casefold().endswith(suffix) for suffix in FORBIDDEN_SUFFIXES)
]
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    # macOS onedir bundle: launch is fast and Qt plugins remain inspectable.
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="KOMI Report V5.2.15",
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
        name="KOMI Report V5.2.15",
    )
    app = BUNDLE(
        collected,
        name="KOMI Report V5.2.15.app",
        icon="Logo.icns",
        bundle_identifier="com.komiminolta.komireportv5",
        info_plist={
            "CFBundleDisplayName": "KOMI Report V5.2.15",
            "CFBundleShortVersionString": "5.2.15",
            "CFBundleVersion": "50215",
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
        name="KOMI Report V5.2.15",
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
        name="KOMI Report V5.2.15",
    )
