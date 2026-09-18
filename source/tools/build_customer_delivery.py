"""Assemble the current cross-platform customer delivery with a fail-closed decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tomllib
import zipfile
from datetime import datetime
from pathlib import Path

from services.v5_2_contract_metadata import CONTRACT_SHA256, CONTRACT_VERSION
from tools.release_safety import assert_zip_safe

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "source"
VERSION = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]
VERSION_TAG = VERSION.replace(".", "_")
DOCS = (
    "CUSTOMER_RELEASE_NOTES.md",
    "CUSTOMER_INSTALL_GUIDE.md",
    "CUSTOMER_GUIDE_V5_2.md",
    "RELEASE_SUPPORT_AND_RECOVERY.md",
    "REGISTRATION_DATA_NOTICE.md",
)


class CustomerDeliveryError(RuntimeError):
    """A provenance or checksum contract is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CustomerDeliveryError(f"invalid or missing evidence: {path.name}") from exc
    if not isinstance(payload, dict):
        raise CustomerDeliveryError(f"evidence must be an object: {path.name}")
    return payload


def verify_macos(root: Path, expected_commit: str) -> tuple[dict[str, object], list[str]]:
    manifest = _load_json(root / "MACOS_MANIFEST.json")
    if manifest.get("version") != VERSION or manifest.get("source_commit") != expected_commit:
        raise CustomerDeliveryError("macOS manifest source/version mismatch")
    if manifest.get("release_profile") != "customer-production-behavior":
        raise CustomerDeliveryError("macOS artifact is not the customer production-behavior profile")
    if (
        manifest.get("registration_runtime")
        != "schema3-ed25519-public-client-no-shared-bootstrap"
        or manifest.get("registration_bootstrap") != "not-applicable-schema3"
    ):
        raise CustomerDeliveryError("macOS manifest contains a legacy Registration bootstrap contract")
    if (
        manifest.get("contract_version") != CONTRACT_VERSION
        or manifest.get("contract_sha256") != CONTRACT_SHA256
    ):
        raise CustomerDeliveryError("macOS manifest shared-contract identity mismatch")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise CustomerDeliveryError("macOS artifacts are missing")
    for item in artifacts:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise CustomerDeliveryError("macOS artifact entry is invalid")
        artifact = root / str(item["name"])
        if not artifact.is_file() or _sha256(artifact) != item.get("sha256"):
            raise CustomerDeliveryError(f"macOS artifact checksum mismatch: {artifact.name}")
    blockers: list[str] = []
    if manifest.get("signing") != "developer-id-notarized-verified":
        blockers.append("macOS Developer ID signing/notarization is not verified")
    if manifest.get("gatekeeper") != "accepted":
        blockers.append("macOS Gatekeeper rejected the artifact")
    smoke = manifest.get("smoke")
    if not isinstance(smoke, dict) or smoke.get("graceful_exit") is not True:
        blockers.append("macOS bundle smoke/graceful exit did not pass")
    joint_e2e = manifest.get("joint_staging_e2e")
    if not isinstance(joint_e2e, dict) or joint_e2e.get("verified") is not True:
        blockers.append("macOS Joint Desktop-Staging E2E evidence is missing or did not pass")
    return manifest, blockers


def verify_windows(root: Path, expected_commit: str) -> tuple[dict[str, object], list[str]]:
    manifest = _load_json(root / "WINDOWS_MANIFEST.json")
    if manifest.get("version") != VERSION or manifest.get("source_commit") != expected_commit:
        raise CustomerDeliveryError("Windows manifest source/version mismatch")
    if manifest.get("release_profile") != "customer-production-behavior":
        raise CustomerDeliveryError("Windows artifact is not the customer production-behavior profile")
    if (
        manifest.get("registration_runtime")
        != "schema3-ed25519-public-client-no-shared-bootstrap"
        or manifest.get("registration_bootstrap") != "not-applicable-schema3"
    ):
        raise CustomerDeliveryError("Windows manifest contains a legacy Registration bootstrap contract")
    if (
        manifest.get("contract_version") != CONTRACT_VERSION
        or manifest.get("contract_sha256") != CONTRACT_SHA256
    ):
        raise CustomerDeliveryError("Windows manifest shared-contract identity mismatch")
    artifact = root / str(manifest.get("artifact", ""))
    if not artifact.is_file() or _sha256(artifact) != manifest.get("artifact_sha256"):
        raise CustomerDeliveryError("Windows installer checksum mismatch")
    blockers: list[str] = []
    if manifest.get("build_environment") != "windows-x64-native":
        blockers.append("Windows build/UAT is not native Windows x64 evidence")
    if manifest.get("signing") != "verified":
        blockers.append("Windows Authenticode is not verified")
    uat_path = root / "WINDOWS_UAT_EVIDENCE.json"
    if not uat_path.is_file():
        blockers.append("Windows install/restart/Tray/Auto-start/LAN Web/recovery UAT evidence is missing")
    else:
        uat = _load_json(uat_path)
        required = (
            "clean_install",
            "first_run",
            "restart",
            "tray",
            "auto_start",
            "lan_web",
            "uninstall_reinstall",
            "data_preservation",
        )
        failed = [name for name in required if uat.get(name) is not True]
        if failed:
            blockers.append("Windows UAT incomplete: " + ", ".join(failed))
        if uat.get("native_x64") is not True:
            blockers.append("Windows UAT evidence is VM/ARM preflight, not native x64")
    joint_e2e = manifest.get("joint_staging_e2e")
    if not isinstance(joint_e2e, dict) or joint_e2e.get("verified") is not True:
        blockers.append("Windows Joint Desktop-Staging E2E evidence is missing or did not pass")
    return manifest, blockers


def build_delivery(
    macos_root: Path,
    windows_root: Path,
    output_root: Path,
    *,
    expected_commit: str,
    approved_source_gate: str = "",
    assembly_commit: str = "",
    registration_blocker: str = "",
) -> tuple[Path, dict[str, object]]:
    macos_manifest, macos_blockers = verify_macos(macos_root, expected_commit)
    windows_manifest, windows_blockers = verify_windows(windows_root, expected_commit)
    blockers = macos_blockers + windows_blockers
    if registration_blocker:
        blockers.append(registration_blocker)
    blockers.append("Production GO requires explicit external approval; packaging never self-promotes")
    decision = "HOLD"
    staging = output_root / "staging"
    if staging.exists():
        shutil.rmtree(staging)
    (staging / "macos").mkdir(parents=True)
    (staging / "windows").mkdir(parents=True)
    (staging / "docs").mkdir(parents=True)
    for path in macos_root.iterdir():
        if path.is_file():
            shutil.copy2(path, staging / "macos" / path.name)
    for path in windows_root.iterdir():
        if path.is_file():
            shutil.copy2(path, staging / "windows" / path.name)
    for name in DOCS:
        source = PROJECT_ROOT / "docs" / name
        if not source.is_file():
            raise CustomerDeliveryError(f"required customer document is missing: {name}")
        shutil.copy2(source, staging / "docs" / name)
    from tools.customer_manual import copy_updated_manual
    copy_updated_manual(PROJECT_ROOT, staging / 'docs')
    manifest = {
        "schema_version": 1,
        "product": "KOMI Report V5",
        "version": VERSION,
        "contract_version": CONTRACT_VERSION,
        "contract_sha256": CONTRACT_SHA256,
        "source_commit": expected_commit,
        "approved_phase5_source_gate": approved_source_gate or expected_commit,
        "assembly_commit": assembly_commit or expected_commit,
        "release_profile": "customer-production-behavior",
        "macos_artifact_identity": macos_manifest.get("artifact_identity"),
        "windows_artifact_identity": windows_manifest.get("artifact_identity"),
        "registration_runtime": "schema3-ed25519-public-client-no-shared-bootstrap",
        "registration_endpoint": "https://www.dmskm.com",
        "registration_decision": (
            "passed"
            if not registration_blocker
            and isinstance(macos_manifest.get("joint_staging_e2e"), dict)
            and macos_manifest["joint_staging_e2e"].get("verified") is True
            and isinstance(windows_manifest.get("joint_staging_e2e"), dict)
            and windows_manifest["joint_staging_e2e"].get("verified") is True
            else "hold"
        ),
        "joint_staging_e2e": {
            "macos": macos_manifest.get("joint_staging_e2e"),
            "windows": windows_manifest.get("joint_staging_e2e"),
        },
        "update_runtime": "absent-phase-3-deferred",
        "release_decision": decision,
        "production_go": False,
        "blockers": blockers,
        "assembled_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (staging / "CUSTOMER_RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    output_root.mkdir(parents=True, exist_ok=True)
    archive = output_root / (
        f"KOMI_Report_V{VERSION_TAG}_Customer_Release_{decision.replace(' ', '_')}.zip"
    )
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix()):
            if path.is_file():
                zipped.write(path, path.relative_to(staging))
    assert_zip_safe(archive)
    manifest["delivery_artifact"] = archive.name
    manifest["delivery_sha256"] = _sha256(archive)
    manifest["delivery_size"] = archive.stat().st_size
    (output_root / "CUSTOMER_RELEASE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_root / "CHECKSUMS.sha256").write_text(
        f"{manifest['delivery_sha256']}  {archive.name}\n", encoding="ascii"
    )
    return archive, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Assemble the V{VERSION} customer delivery")
    parser.add_argument("--macos", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--approved-source-gate", default="")
    parser.add_argument("--assembly-commit", default="")
    parser.add_argument("--registration-blocker", default="")
    args = parser.parse_args()
    archive, manifest = build_delivery(
        args.macos.resolve(),
        args.windows.resolve(),
        args.output.resolve(),
        expected_commit=args.expected_source_commit.strip().casefold(),
        approved_source_gate=args.approved_source_gate.strip().casefold(),
        assembly_commit=args.assembly_commit.strip().casefold(),
        registration_blocker=args.registration_blocker.strip(),
    )
    print(f"delivery={archive}")
    print(f"sha256={manifest['delivery_sha256']}")
    print(f"release_decision={manifest['release_decision']}")
    for blocker in manifest["blockers"]:
        print(f"blocker={blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
