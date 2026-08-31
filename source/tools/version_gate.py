"""Fail-closed version alignment gate for current V5.2 build metadata."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from komi_version import APP_VERSION, require_v5_2  # noqa: E402
from services.v5_2_contract_metadata import CONTRACT_SHA256  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _embedded_v5_2_versions(text: str) -> set[str]:
    return set(re.findall(r"\b5\.2\.\d+\b", text))


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
    windows_builder = (SOURCE_ROOT / "tools" / "build_windows_rc.py").read_text(
        encoding="utf-8"
    )
    macos_builder = (SOURCE_ROOT / "tools" / "build_macos_customer.py").read_text(
        encoding="utf-8"
    )
    customer_delivery_builder = (
        SOURCE_ROOT / "tools" / "build_customer_delivery.py"
    ).read_text(encoding="utf-8")
    support_guide = (PROJECT_ROOT / "docs" / "RELEASE_SUPPORT_AND_RECOVERY.md").read_text(
        encoding="utf-8"
    )
    release_notes = (PROJECT_ROOT / "docs" / "CUSTOMER_RELEASE_NOTES.md").read_text(
        encoding="utf-8"
    )
    pilot_checklist = (PROJECT_ROOT / "docs" / "PILOT_RELEASE_CHECKLIST.md").read_text(
        encoding="utf-8"
    )
    release_runbook = (PROJECT_ROOT / "docs" / "RELEASE_RUNBOOK.md").read_text(
        encoding="utf-8"
    )
    customer_install_guide = (PROJECT_ROOT / "docs" / "CUSTOMER_INSTALL_GUIDE.md").read_text(
        encoding="utf-8"
    )
    customer_guide = (PROJECT_ROOT / "docs" / "CUSTOMER_GUIDE_V5_2.md").read_text(
        encoding="utf-8"
    )
    customer_guide_builder = (
        PROJECT_ROOT / "docs" / "customer-guide" / "build_customer_guide_v52.py"
    ).read_text(encoding="utf-8")
    contract = PROJECT_ROOT / "docs" / "V5_2_HOST_API_IMPLEMENTATION_REQUEST.md"
    major, minor, patch = (int(part) for part in expected.split("."))
    bundle_version = str(major * 10_000 + minor * 100 + patch)
    mismatches: list[str] = []
    checks = {
        "pyproject": project["project"]["version"] == expected,
        "web package": web_package.get("version") == expected,
        "web lock": web_lock.get("version") == expected,
        "web lock root": web_lock.get("packages", {}).get("", {}).get("version") == expected,
        "bundle executable name": bool(
            f'name="KOMI Report V{expected}"' in spec
            and _embedded_v5_2_versions(spec) == {expected}
        ),
        "bundle app name": f'name="KOMI Report V{expected}.app"' in spec,
        "bundle display name": f'CFBundleDisplayName": "KOMI Report V{expected}"' in spec,
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
            and f'KOMI_Report_V{expected.replace(".", "_")}_Windows_x64_RC' in installer
            and f"KOMI Report V{expected} Release Candidate" in installer
            and _embedded_v5_2_versions(installer) == {expected}
        ),
        "windows builder version derived": bool(
            'VERSION_TAG = VERSION.replace(".", "_")' in windows_builder
            and 'INSTALLER_NAME = f"KOMI_Report_V{VERSION_TAG}_Windows_x64_RC.exe"'
            in windows_builder
            and 'CUSTOMER_INSTALLER_NAME = f"KOMI_Report_V{VERSION_TAG}_Windows_x64_Installer.exe"'
            in windows_builder
            and not _embedded_v5_2_versions(windows_builder)
        ),
        "macos builder version derived": bool(
            'APP_NAME = f"KOMI Report V{VERSION}"' in macos_builder
            and 'version_tag = VERSION.replace(".", "_")' in macos_builder
            and not _embedded_v5_2_versions(macos_builder)
        ),
        "customer delivery version derived": bool(
            'VERSION_TAG = VERSION.replace(".", "_")' in customer_delivery_builder
            and 'f"KOMI_Report_V{VERSION_TAG}_Customer_Release_' in customer_delivery_builder
            and 'description=f"Assemble the V{VERSION} customer delivery"'
            in customer_delivery_builder
            and not _embedded_v5_2_versions(customer_delivery_builder)
        ),
        "support guide version": support_guide.startswith(
            f"# KOMI Report V{expected} — Support, Recovery and Rollback"
        )
        and _embedded_v5_2_versions(support_guide) == {expected},
        "customer release notes version": release_notes.startswith(
            f"# KOMI Report V{expected} — Customer Release Notes"
        ),
        "pilot checklist version": pilot_checklist.startswith(
            f"# KOMI Report V{expected} — Unsigned Pilot Checklist"
        ),
        "release runbook version": f"version authorities equal `{expected}`" in release_runbook,
        "customer install guide version": customer_install_guide.startswith(
            f"# KOMI Report V{expected} — คู่มือติดตั้ง ย้ายเครื่อง และกู้คืนข้อมูล"
        ),
        "customer guide version": customer_guide.startswith(
            f"# KOMI Report V{expected} — คู่มือผู้ใช้งาน"
        ),
        "customer guide builder version derived": bool(
            'OUTPUT = HERE / f"KOMI_Report_V{VERSION}_' in customer_guide_builder
            and 'header.add_run(f"KOMI Report V{VERSION}' in customer_guide_builder
            and not _embedded_v5_2_versions(customer_guide_builder)
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
