"""Fail-closed version alignment gate for current V5.2 build metadata."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from komi_version import APP_VERSION, require_v5_2
from services.v5_2_contract import CONTRACT_SHA256

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "source"


def assert_v5_2_version_alignment() -> None:
    expected = require_v5_2(APP_VERSION)
    project = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    web_package = json.loads((PROJECT_ROOT / "web" / "package.json").read_text(encoding="utf-8"))
    web_lock = json.loads((PROJECT_ROOT / "web" / "package-lock.json").read_text(encoding="utf-8"))
    spec = (SOURCE_ROOT / "app.spec").read_text(encoding="utf-8")
    config = (SOURCE_ROOT / "config.py").read_text(encoding="utf-8")
    uv_lock = (SOURCE_ROOT / "uv.lock").read_text(encoding="utf-8")
    installer = (PROJECT_ROOT / "packaging" / "windows" / "KOMI_Report_V5.iss").read_text(
        encoding="utf-8"
    )
    contract = PROJECT_ROOT / "docs" / "V5_2_HOST_API_IMPLEMENTATION_REQUEST.md"
    major, minor, patch = (int(part) for part in expected.split("."))
    bundle_version = str(major * 10_000 + minor * 100 + patch)
    mismatches: list[str] = []
    checks = {
        "pyproject": project["project"]["version"] == expected,
        "web package": web_package.get("version") == expected,
        "web lock": web_lock.get("version") == expected,
        "web lock root": web_lock.get("packages", {}).get("", {}).get("version") == expected,
        "bundle short version": f'CFBundleShortVersionString": "{expected}"' in spec,
        "bundle build version": f'CFBundleVersion": "{bundle_version}"' in spec,
        "uv lock project": bool(
            re.search(
                rf'\[\[package\]\]\s+name = "komi-report-v5"\s+version = "{re.escape(expected)}"',
                uv_lock,
            )
        ),
        "config authority import": bool(
            re.search(r"from komi_version import APP_VERSION", config)
            and re.search(r"APP_VER\s*=\s*APP_VERSION", config)
            and re.search(r"PACKAGE_VERSION\s*=\s*APP_VERSION", config)
        ),
        "windows installer": bool(
            f'#define AppVersion "{expected}"' in installer
            and f"VersionInfoVersion={expected}.0" in installer
            and f"VersionInfoProductVersion={expected}" in installer
        ),
        "shared contract checksum": bool(
            contract.is_file() and hashlib.sha256(contract.read_bytes()).hexdigest() == CONTRACT_SHA256
        ),
    }
    for label, matches in checks.items():
        if not matches:
            mismatches.append(label)
    if mismatches:
        raise RuntimeError("V5.2 version metadata mismatch: " + ", ".join(mismatches))


if __name__ == "__main__":
    assert_v5_2_version_alignment()
    print(f"KOMI Report version gate PASS: {APP_VERSION}")
