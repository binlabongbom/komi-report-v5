from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from komi_version import APP_VERSION
from services.v5_2_contract_metadata import CONTRACT_SHA256, CONTRACT_VERSION
from tools.build_customer_delivery import CustomerDeliveryError, build_delivery
from tools.build_windows_rc import CUSTOMER_INSTALLER_NAME, CUSTOMER_README


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _customer_candidates(tmp_path: Path, commit: str) -> tuple[Path, Path]:
    macos = tmp_path / "macos"
    windows = tmp_path / "windows"
    macos.mkdir()
    windows.mkdir()
    version_tag = APP_VERSION.replace(".", "_")
    mac_zip = macos / f"KOMI_Report_V{version_tag}_macOS_arm64.zip"
    mac_zip.write_bytes(b"synthetic mac customer package")
    (macos / "MACOS_MANIFEST.json").write_text(
        json.dumps(
            {
                "version": APP_VERSION,
                "contract_version": CONTRACT_VERSION,
                "contract_sha256": CONTRACT_SHA256,
                "source_commit": commit,
                "release_profile": "customer-production-behavior",
                "artifact_identity": f"mac-{commit[:12]}",
                "artifacts": [
                    {
                        "name": mac_zip.name,
                        "sha256": _digest(mac_zip),
                        "size": mac_zip.stat().st_size,
                    }
                ],
                "signing": "ad-hoc-blocked",
                "gatekeeper": "rejected-blocked",
                "smoke": {"graceful_exit": True},
                "registration_runtime": "schema3-ed25519-public-client-no-shared-bootstrap",
                "registration_bootstrap": "not-applicable-schema3",
                "joint_staging_e2e": {"state": "verified", "verified": True},
            }
        ),
        encoding="utf-8",
    )
    installer = windows / CUSTOMER_INSTALLER_NAME
    installer.write_bytes(b"synthetic windows customer installer")
    (windows / "WINDOWS_MANIFEST.json").write_text(
        json.dumps(
            {
                "version": APP_VERSION,
                "contract_version": CONTRACT_VERSION,
                "contract_sha256": CONTRACT_SHA256,
                "source_commit": commit,
                "release_profile": "customer-production-behavior",
                "artifact_identity": f"windows-{commit[:12]}",
                "artifact": installer.name,
                "artifact_sha256": _digest(installer),
                "build_environment": "windows-arm64-vm-preflight",
                "signing": "unsigned-blocked",
                "registration_runtime": "schema3-ed25519-public-client-no-shared-bootstrap",
                "registration_bootstrap": "not-applicable-schema3",
                "joint_staging_e2e": {"state": "verified", "verified": True},
            }
        ),
        encoding="utf-8",
    )
    (windows / "WINDOWS_UAT_EVIDENCE.json").write_text(
        json.dumps(
            {
                "clean_install": True,
                "first_run": True,
                "restart": True,
                "tray": True,
                "auto_start": True,
                "lan_web": True,
                "uninstall_reinstall": True,
                "data_preservation": True,
                "native_x64": False,
            }
        ),
        encoding="utf-8",
    )
    return macos, windows


def test_windows_customer_profile_is_not_labelled_pilot_or_lab():
    from komi_version import APP_VERSION
    assert CUSTOMER_INSTALLER_NAME == f"KOMI_Report_V{APP_VERSION.replace('.', '_')}_Windows_x64_Online_Installer.exe"
    assert "customer release package" in CUSTOMER_README.casefold()
    assert "production Desktop" in CUSTOMER_README
    assert "Unsigned Pilot Candidate" not in CUSTOMER_README
    assert "Virtual Printer auto-" in CUSTOMER_README
    assert "Update telemetry" in CUSTOMER_README
    assert "schema-3 Ed25519 public-client" in CUSTOMER_README
    assert "no shared/master bootstrap key" in CUSTOMER_README


def test_customer_delivery_holds_unsigned_arm_vm_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    commit = "a" * 40
    macos, windows = _customer_candidates(tmp_path, commit)
    docs = tmp_path / "docs"
    docs.mkdir()
    for name in (
        "CUSTOMER_RELEASE_NOTES.md",
        "CUSTOMER_INSTALL_GUIDE.md",
        "CUSTOMER_GUIDE_V5_2.md",
        "RELEASE_SUPPORT_AND_RECOVERY.md",
        "REGISTRATION_DATA_NOTICE.md",
    ):
        (docs / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr("tools.build_customer_delivery.PROJECT_ROOT", tmp_path)

    archive, manifest = build_delivery(
        macos,
        windows,
        tmp_path / "delivery",
        expected_commit=commit,
        approved_source_gate="b" * 40,
        assembly_commit="c" * 40,
        registration_blocker="Live Registration HTTP 422 serial_number allow-list mismatch",
    )

    assert manifest["release_decision"] == "HOLD"
    assert manifest["production_go"] is False
    assert manifest["contract_version"] == CONTRACT_VERSION
    assert manifest["contract_sha256"] == CONTRACT_SHA256
    assert manifest["registration_runtime"] == (
        "schema3-ed25519-public-client-no-shared-bootstrap"
    )
    assert any("Developer ID" in item for item in manifest["blockers"])
    assert any("native Windows x64" in item for item in manifest["blockers"])
    assert any("Authenticode" in item for item in manifest["blockers"])
    assert any("HTTP 422" in item for item in manifest["blockers"])
    assert manifest["registration_endpoint"] == "https://www.dmskm.com"
    assert manifest["registration_decision"] == "hold"
    assert manifest["approved_phase5_source_gate"] == "b" * 40
    assert manifest["assembly_commit"] == "c" * 40
    assert manifest["delivery_sha256"] == _digest(archive)
    assert manifest["version"] == APP_VERSION
    assert archive.name.startswith(
        f"KOMI_Report_V{APP_VERSION.replace('.', '_')}_Customer_Release_"
    )
    with zipfile.ZipFile(archive) as packaged:
        names = set(packaged.namelist())
    assert "macos/MACOS_MANIFEST.json" in names
    assert "windows/WINDOWS_MANIFEST.json" in names
    assert "docs/CUSTOMER_INSTALL_GUIDE.md" in names
    assert "docs/CUSTOMER_GUIDE_V5_2.md" in names
    assert "CUSTOMER_RELEASE_MANIFEST.json" in names


def test_customer_delivery_rejects_cross_platform_source_mismatch(tmp_path: Path):
    commit = "a" * 40
    macos, windows = _customer_candidates(tmp_path, commit)
    manifest_path = windows / "WINDOWS_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = "b" * 40
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CustomerDeliveryError, match="Windows manifest source/version mismatch"):
        build_delivery(macos, windows, tmp_path / "delivery", expected_commit=commit)


def test_customer_delivery_rejects_contract_identity_mismatch(tmp_path: Path):
    commit = "a" * 40
    macos, windows = _customer_candidates(tmp_path, commit)
    manifest_path = windows / "WINDOWS_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contract_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(CustomerDeliveryError, match="shared-contract identity mismatch"):
        build_delivery(macos, windows, tmp_path / "delivery", expected_commit=commit)


def test_macos_customer_builder_records_real_distribution_checks():
    builder = (
        Path(__file__).parents[1] / "tools" / "build_macos_customer.py"
    ).read_text(encoding="utf-8")
    for command in (
        "codesign",
        "--entitlements",
        "spctl",
        "hdiutil",
        "PyInstaller",
        "--smoke-test",
        "cyclonedx_sbom",
    ):
        assert command in builder
