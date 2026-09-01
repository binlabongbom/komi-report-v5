"""Build and inspect the macOS KOMI Report V5.2 customer package.

The application always uses the production runtime path. Signing, Gatekeeper
and notarization are evidence gates: an ad-hoc artifact remains useful for
internal installation checks but can never be promoted to RELEASE READY.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import datetime
from pathlib import Path, PurePosixPath

from services.v5_2_contract_metadata import CONTRACT_SHA256, CONTRACT_VERSION
from tools.release_evidence import (
    ReleaseContractError,
    cyclonedx_sbom,
    file_inventory,
    load_joint_e2e_evidence,
    sha256_file,
)
from tools.release_safety import assert_zip_safe, git_identity

SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_ROOT.parent
VERSION = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]
APP_NAME = f"KOMI Report V{VERSION}"
APP_BUNDLE = SOURCE_ROOT / "dist" / f"{APP_NAME}.app"
DEFAULT_OUTPUT = PROJECT_ROOT / "release" / "macos-customer"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
LEGACY_REGISTRATION_BOOTSTRAP_FILENAME = "komi-registration-bootstrap.dat"
WEB_RUNTIME_SEED_ROOTS = (
    PurePosixPath("Contents/Frameworks/web-runtime-seed"),
    PurePosixPath("Contents/Resources/web-runtime-seed"),
)


class MacCustomerBuildError(RuntimeError):
    """A fail-closed customer packaging prerequisite is missing."""


def _run(
    command: list[str],
    *,
    check: bool = False,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def require_macos_arm64() -> None:
    if sys.platform != "darwin" or platform.machine().casefold() != "arm64":
        raise MacCustomerBuildError(
            f"macOS arm64 target-native build required; got {sys.platform}/{platform.machine()}"
        )


def require_clean_source(expected_commit: str) -> tuple[str, str]:
    commit, source_state = git_identity(PROJECT_ROOT)
    expected_commit = expected_commit.strip().casefold()
    if expected_commit and not COMMIT_RE.fullmatch(expected_commit):
        raise MacCustomerBuildError("--expected-source-commit must be a full Git commit")
    if source_state != "clean":
        raise MacCustomerBuildError("macOS customer build requires a clean committed source tree")
    if expected_commit and commit != expected_commit:
        raise MacCustomerBuildError(
            f"approved source mismatch: expected {expected_commit}, got {commit}"
        )
    return commit, source_state


def build_app() -> None:
    env = os.environ.copy()
    # Schema 3 creates an Ed25519 installation identity locally. Never
    # inherit the legacy shared-bootstrap build hook from an operator shell.
    env.pop("KOMI_REGISTRATION_BOOTSTRAP_BUILD_FILE", None)
    _run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "app.spec"],
        cwd=SOURCE_ROOT,
        env=env,
        check=True,
        timeout=1800,
    )


def _main_executable(app_bundle: Path) -> Path:
    executable = app_bundle / "Contents" / "MacOS" / APP_NAME
    info_plist = app_bundle / "Contents" / "Info.plist"
    if not executable.is_file() or not info_plist.is_file():
        raise MacCustomerBuildError("PyInstaller app bundle is incomplete")
    return executable


def smoke_test(app_bundle: Path) -> dict[str, object]:
    executable = _main_executable(app_bundle)
    with tempfile.TemporaryDirectory(prefix="komi-macos-customer-smoke-") as temp:
        app_home = Path(temp) / "app-home"
        env = os.environ.copy()
        env.update(
            {
                "KOMI_APP_HOME": str(app_home),
                "KOMI_DB_PATH": str(app_home / "KOMI_Report_V5.db"),
                "KOMI_LOG_DIR": str(app_home / "logs"),
                "PYTHONDONTWRITEBYTECODE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        result = _run([str(executable), "--smoke-test"], env=env, timeout=120)
        return {
            "command": "bundle-main-executable --smoke-test",
            "exit_code": result.returncode,
            "database_created": (app_home / "KOMI_Report_V5.db").is_file(),
            "graceful_exit": result.returncode == 0,
            "stdout_tail": result.stdout[-1000:],
            "stderr_tail": result.stderr[-1000:],
        }


def inspect_signing(app_bundle: Path) -> dict[str, object]:
    verify = _run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=4", str(app_bundle)]
    )
    details = _run(
        ["/usr/bin/codesign", "-dvvv", "--entitlements", ":-", str(app_bundle)]
    )
    gatekeeper = _run(["/usr/sbin/spctl", "-a", "-vv", "--type", "execute", str(app_bundle)])
    detail_text = (details.stdout + details.stderr).strip()
    gatekeeper_text = (gatekeeper.stdout + gatekeeper.stderr).strip()
    developer_id = "Authority=Developer ID Application:" in detail_text
    ad_hoc = "Signature=adhoc" in detail_text or "TeamIdentifier=not set" in detail_text
    notarized = gatekeeper.returncode == 0 and "Notarized Developer ID" in gatekeeper_text
    if verify.returncode == 0 and developer_id and notarized:
        state = "developer-id-notarized-verified"
    elif verify.returncode == 0 and ad_hoc:
        state = "ad-hoc-blocked"
    elif verify.returncode == 0:
        state = "signed-unverified-blocked"
    else:
        state = "unsigned-or-invalid-blocked"
    return {
        "state": state,
        "codesign_verify_exit": verify.returncode,
        "codesign_details": detail_text,
        "gatekeeper_exit": gatekeeper.returncode,
        "gatekeeper_details": gatekeeper_text,
        "developer_id": developer_id,
        "notarized": notarized,
    }


def inspect_structure(app_bundle: Path) -> dict[str, object]:
    executable = _main_executable(app_bundle)
    with (app_bundle / "Contents" / "Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    file_result = _run(["/usr/bin/file", str(executable)], check=True)
    lipo_result = _run(["/usr/bin/lipo", "-archs", str(executable)], check=True)
    nested_code = [
        path.relative_to(app_bundle).as_posix()
        for path in sorted(app_bundle.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
        and (path.suffix.casefold() in {".dylib", ".so"} or ".framework/" in path.as_posix())
    ]
    return {
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "bundle_version": info.get("CFBundleVersion"),
        "short_version": info.get("CFBundleShortVersionString"),
        "display_name": info.get("CFBundleDisplayName"),
        "main_executable": executable.relative_to(app_bundle).as_posix(),
        "file_identity": file_result.stdout.strip(),
        "architectures": lipo_result.stdout.strip().split(),
        "nested_code_count": len(nested_code),
        "nested_code": nested_code,
    }


def packaged_runtime_dependency_roots(app_bundle: Path) -> tuple[str, ...]:
    """Return only the dependency roots produced inside this exact app ZIP."""

    archive_bundle_roots = (
        PurePosixPath(app_bundle.name),
        PurePosixPath("__MACOSX") / app_bundle.name,
    )
    return tuple(
        (bundle_root / runtime_root / dependency).as_posix()
        for bundle_root in archive_bundle_roots
        for runtime_root in WEB_RUNTIME_SEED_ROOTS
        for dependency in (".next", "node_modules")
    )


def create_archives(app_bundle: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    version_tag = VERSION.replace(".", "_")
    archive = output_dir / f"KOMI_Report_V{version_tag}_macOS_arm64.zip"
    dmg = output_dir / f"KOMI_Report_V{version_tag}_macOS_arm64.dmg"
    archive.unlink(missing_ok=True)
    dmg.unlink(missing_ok=True)
    _run(
        [
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app_bundle),
            str(archive),
        ],
        check=True,
        timeout=1800,
    )
    assert_zip_safe(
        archive,
        allowed_packaged_dependency_roots=packaged_runtime_dependency_roots(app_bundle),
    )
    with tempfile.TemporaryDirectory(prefix="komi-macos-dmg-") as temp:
        stage = Path(temp) / APP_NAME
        stage.mkdir()
        _run(["/usr/bin/ditto", str(app_bundle), str(stage / app_bundle.name)], check=True)
        (stage / "Applications").symlink_to("/Applications")
        _run(
            [
                "/usr/bin/hdiutil",
                "create",
                "-ov",
                "-format",
                "UDZO",
                "-volname",
                APP_NAME,
                "-srcfolder",
                str(stage),
                str(dmg),
            ],
            check=True,
            timeout=1800,
        )
    return archive, dmg


def build_customer_package(
    output_dir: Path,
    *,
    expected_commit: str = "",
    skip_build: bool = False,
    joint_e2e_evidence_file: Path | None = None,
) -> dict[str, object]:
    require_macos_arm64()
    commit, source_state = require_clean_source(expected_commit)
    try:
        joint_e2e = load_joint_e2e_evidence(
            joint_e2e_evidence_file,
            version=VERSION,
            source_commit=commit,
        )
    except ReleaseContractError as exc:
        raise MacCustomerBuildError(str(exc)) from exc
    if not skip_build:
        build_app()
    packaged_bootstrap = tuple(APP_BUNDLE.rglob(LEGACY_REGISTRATION_BOOTSTRAP_FILENAME))
    if packaged_bootstrap:
        raise MacCustomerBuildError("macOS bundle contains a forbidden legacy Registration bootstrap")
    packaged_offline_public_keys = tuple(
        APP_BUNDLE.rglob("public-verification-keys.json")
    )
    structure = inspect_structure(APP_BUNDLE)
    if structure["short_version"] != VERSION or structure["architectures"] != ["arm64"]:
        raise MacCustomerBuildError(
            f"bundle version or architecture does not match V{VERSION} arm64"
        )
    smoke = smoke_test(APP_BUNDLE)
    if not smoke["graceful_exit"]:
        raise MacCustomerBuildError("built macOS app failed the isolated smoke test")
    signing = inspect_signing(APP_BUNDLE)
    archive, dmg = create_archives(APP_BUNDLE, output_dir)
    inventory = file_inventory(APP_BUNDLE)
    (output_dir / "FILE_INVENTORY.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    sbom = cyclonedx_sbom(
        version=VERSION,
        source_commit=commit,
        requirements_lock=SOURCE_ROOT / "requirements.lock.txt",
        package_lock=PROJECT_ROOT / "web" / "package-lock.json",
    )
    (output_dir / "SBOM.cdx.json").write_text(
        json.dumps(sbom, indent=2) + "\n", encoding="utf-8"
    )
    checksums = {archive.name: sha256_file(archive), dmg.name: sha256_file(dmg)}
    (output_dir / "CHECKSUMS.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()),
        encoding="ascii",
    )
    signing_evidence = (
        f"codesign_state={signing['state']}\n"
        f"codesign_verify_exit={signing['codesign_verify_exit']}\n"
        f"gatekeeper_exit={signing['gatekeeper_exit']}\n"
        f"developer_id={str(signing['developer_id']).lower()}\n"
        f"notarized={str(signing['notarized']).lower()}\n\n"
        f"codesign -dvvv --entitlements :-\n{signing['codesign_details']}\n\n"
        f"spctl -a -vv\n{signing['gatekeeper_details']}\n"
    )
    (output_dir / "SIGNING_EVIDENCE.txt").write_text(signing_evidence, encoding="utf-8")
    blockers = ["Production GO requires explicit external approval; packaging never self-promotes"]
    if signing["state"] != "developer-id-notarized-verified":
        blockers.append("macOS Developer ID signing/notarization is not verified")
    if joint_e2e["verified"] is not True:
        blockers.append("Joint Desktop-Staging E2E evidence is missing or did not pass")
    if not packaged_offline_public_keys:
        blockers.append("Host Offline License public verification key is not bundled")
    manifest = {
        "schema_version": 1,
        "product": "KOMI Report V5",
        "version": VERSION,
        "contract_version": CONTRACT_VERSION,
        "contract_sha256": CONTRACT_SHA256,
        "release_profile": "customer-production-behavior",
        "source_commit": commit,
        "source_state": source_state,
        "target": "macOS arm64",
        "build_environment": f"macos-{platform.mac_ver()[0]}-arm64-native",
        "artifact_identity": f"komi-report-v5-macos-arm64-customer-{VERSION}-{commit[:12]}",
        "artifacts": [
            {"name": name, "sha256": digest, "size": (output_dir / name).stat().st_size}
            for name, digest in checksums.items()
        ],
        "file_count": len(inventory),
        "file_inventory": "FILE_INVENTORY.json",
        "sbom": "SBOM.cdx.json",
        "signing_evidence": "SIGNING_EVIDENCE.txt",
        "signing": signing["state"],
        "notarized": signing["notarized"],
        "gatekeeper": "accepted" if signing["gatekeeper_exit"] == 0 else "rejected-blocked",
        "structure": structure,
        "smoke": smoke,
        "registration_runtime": "schema3-ed25519-public-client-no-shared-bootstrap",
        "registration_bootstrap": "not-applicable-schema3",
        "offline_license_public_keys": (
            "bundled-public-only"
            if packaged_offline_public_keys
            else "absent-online-only"
        ),
        "joint_staging_e2e": joint_e2e,
        "update_runtime": "absent-phase-3-deferred",
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "release_decision": "HOLD",
        "production_go": False,
        "blockers": blockers,
    }
    (output_dir / "MACOS_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Build KOMI Report V{VERSION} macOS customer package"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--expected-source-commit", default="")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--joint-e2e-evidence",
        type=Path,
        help="Sanitized Joint Desktop-Staging E2E JSON; missing evidence produces a HOLD candidate",
    )
    args = parser.parse_args()
    manifest = build_customer_package(
        args.output.resolve(),
        expected_commit=args.expected_source_commit,
        skip_build=args.skip_build,
        joint_e2e_evidence_file=args.joint_e2e_evidence,
    )
    for artifact in manifest["artifacts"]:
        print(f"artifact={artifact['name']} size={artifact['size']} sha256={artifact['sha256']}")
    print(f"signing={manifest['signing']}")
    print(f"release_decision={manifest['release_decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
