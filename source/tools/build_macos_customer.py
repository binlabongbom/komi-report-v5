"""Build and inspect the macOS KOMI Report V5.2 customer package.

The application always uses the production runtime path. Signing, Gatekeeper
and notarization are evidence gates: an ad-hoc artifact remains useful for
internal installation checks but can never be promoted to RELEASE READY.
"""

from __future__ import annotations

import argparse
import dis
import json
import os
import platform
import plistlib
import re
import subprocess
import sys
import tarfile
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


def edition_label(edition: str) -> str:
    if edition not in {"normal", "offline"}:
        raise MacCustomerBuildError("Invalid build edition")
    return "Offline" if edition == "offline" else "Online"


def edition_bundle(edition: str) -> Path:
    edition_label(edition)
    return SOURCE_ROOT / "dist" / edition / f"{APP_NAME}.app"


def frozen_edition(app_bundle: Path) -> str:
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(_main_executable(app_bundle)))
    pyz = archive.open_embedded_archive("PYZ.pyz")
    code = pyz.extract("services.build_edition")
    instructions = list(dis.get_instructions(code))
    for previous, current in zip(instructions, instructions[1:], strict=False):
        if current.opname == "STORE_NAME" and current.argval == "BUILD_EDITION":
            if previous.opname == "LOAD_CONST" and previous.argval in {"normal", "offline"}:
                return previous.argval
    raise MacCustomerBuildError("Frozen build edition is missing or invalid")


def verify_build_receipt(app_bundle: Path, edition: str, commit: str) -> None:
    receipt_path = app_bundle.parent / "BUILD_RECEIPT.json"
    if not receipt_path.is_file():
        raise MacCustomerBuildError("Build receipt missing; rebuild instead of --skip-build")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("edition") != edition or receipt.get("source_commit") != commit
            or receipt.get("executable_sha256") != sha256_file(_main_executable(app_bundle))
            or frozen_edition(app_bundle) != edition):
        raise MacCustomerBuildError("Bundle edition/source does not match requested build")


def build_app(edition: str, commit: str) -> Path:
    edition_label(edition)
    env = os.environ.copy()
    # Schema 3 creates an Ed25519 installation identity locally. Never
    # inherit the legacy shared-bootstrap build hook from an operator shell.
    env.pop("KOMI_REGISTRATION_BOOTSTRAP_BUILD_FILE", None)
    app_bundle = edition_bundle(edition)
    app_bundle.parent.mkdir(parents=True, exist_ok=True)
    (app_bundle.parent / "BUILD_RECEIPT.json").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"komi-macos-{edition}-") as temp:
        stage = Path(temp)
        archive_path = stage / "source.tar"
        _run(["git", "archive", "--format=tar", "-o", str(archive_path), commit],
             cwd=PROJECT_ROOT, check=True)
        with tarfile.open(archive_path) as archive:
            archive.extractall(stage, filter="data")
        (stage / "web" / ".next").symlink_to(PROJECT_ROOT / "web" / ".next", target_is_directory=True)
        edition_path = stage / "source" / "services" / "build_edition.py"
        source = edition_path.read_text(encoding="utf-8")
        if source.count('BUILD_EDITION = "normal"') != 1:
            raise MacCustomerBuildError("Unexpected staged build-edition authority")
        edition_path.write_text(source.replace('BUILD_EDITION = "normal"',
                               f'BUILD_EDITION = "{edition}"'), encoding="utf-8")
        result = _run(
            [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
             "--distpath", str(app_bundle.parent), "--workpath",
             str(SOURCE_ROOT / "build" / edition), "app.spec"],
            cwd=stage / "source", env=env, timeout=1800,
        )
        (app_bundle.parent / "BUILD_OUTPUT.txt").write_text(
            result.stdout + result.stderr, encoding="utf-8")
        result.check_returncode()
    if frozen_edition(app_bundle) != edition:
        raise MacCustomerBuildError("Built bundle has the wrong frozen edition")
    (app_bundle.parent / "BUILD_RECEIPT.json").write_text(json.dumps({
        "source_commit": commit, "edition": edition,
        "executable_sha256": sha256_file(_main_executable(app_bundle)),
    }, indent=2) + "\n", encoding="utf-8")
    return app_bundle


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
        env = {key: value for key, value in os.environ.items() if not key.startswith("KOMI_")}
        env.update(
            {
                "HOME": temp,
                "XDG_CONFIG_HOME": str(Path(temp) / "config"),
                "XDG_DATA_HOME": str(Path(temp) / "data"),
                "XDG_CACHE_HOME": str(Path(temp) / "cache"),
                "KOMI_APP_HOME": str(app_home),
                "KOMI_DB_PATH": str(app_home / "KOMI_Report_V5.db"),
                "KOMI_LOG_DIR": str(app_home / "logs"),
                "KOMI_RUNTIME_CONFIG": str(app_home / "runtime.toml"),
                "KOMI_V46_DATABASE": str(app_home / "absent.sqlite3"),
                "KOMI_DISCOVERY_DISABLED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            }
        )
        result = _run([str(executable), "--smoke-test"], env=env, timeout=120)
        evidence_path = app_home / "KOMI_Report_V5.edition-smoke.json"
        edition_evidence = json.loads(evidence_path.read_text()) if evidence_path.is_file() else {}
        return {
            "command": "bundle-main-executable --smoke-test",
            "exit_code": result.returncode,
            "database_created": (app_home / "KOMI_Report_V5.db").is_file(),
            "graceful_exit": result.returncode == 0 and bool(edition_evidence),
            "edition_evidence": edition_evidence,
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


def create_archives(app_bundle: Path, output_dir: Path, edition: str = "normal") -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    version_tag = VERSION.replace(".", "_")
    label = edition_label(edition)
    archive = output_dir / f"KOMI_Report_V{version_tag}_macOS_arm64_{label}.zip"
    dmg = output_dir / f"KOMI_Report_V{version_tag}_macOS_arm64_{label}.dmg"
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
    edition: str = "normal",
    joint_e2e_evidence_file: Path | None = None,
) -> dict[str, object]:
    require_macos_arm64()
    edition_label(edition)
    commit, source_state = require_clean_source(expected_commit)
    try:
        joint_e2e = load_joint_e2e_evidence(
            joint_e2e_evidence_file,
            version=VERSION,
            source_commit=commit,
        )
    except ReleaseContractError as exc:
        raise MacCustomerBuildError(str(exc)) from exc
    app_bundle = edition_bundle(edition) if skip_build else build_app(edition, commit)
    verify_build_receipt(app_bundle, edition, commit)
    packaged_bootstrap = tuple(app_bundle.rglob(LEGACY_REGISTRATION_BOOTSTRAP_FILENAME))
    if packaged_bootstrap:
        raise MacCustomerBuildError("macOS bundle contains a forbidden legacy Registration bootstrap")
    packaged_offline_public_keys = tuple(
        app_bundle.rglob("public-verification-keys.json")
    )
    structure = inspect_structure(app_bundle)
    if structure["short_version"] != VERSION or structure["architectures"] != ["arm64"]:
        raise MacCustomerBuildError(
            f"bundle version or architecture does not match V{VERSION} arm64"
        )
    smoke = smoke_test(app_bundle)
    if not smoke["graceful_exit"]:
        raise MacCustomerBuildError("built macOS app failed the isolated smoke test")
    signing = inspect_signing(app_bundle)
    archive, dmg = create_archives(app_bundle, output_dir, edition)
    inventory = file_inventory(app_bundle)
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
    if edition == "normal" and not packaged_offline_public_keys:
        blockers.append("Host Offline License public verification key is not bundled")
    manifest = {
        "schema_version": 1,
        "product": "KOMI Report V5",
        "version": VERSION,
        "edition": edition,
        "frozen_edition_verified": True,
        "external_host_traffic": "disabled" if edition == "offline" else "registration-status-meter",
        "contract_version": CONTRACT_VERSION,
        "contract_sha256": CONTRACT_SHA256,
        "release_profile": "customer-production-behavior",
        "source_commit": commit,
        "source_state": source_state,
        "target": "macOS arm64",
        "build_environment": f"macos-{platform.mac_ver()[0]}-arm64-native",
        "artifact_identity": f"komi-report-v5-macos-arm64-{edition}-{VERSION}-{commit[:12]}",
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
            "not-required-offline-edition" if edition == "offline" else "bundled-public-only"
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
    parser.add_argument("--edition", choices=("normal", "offline"), default="normal")
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
        edition=args.edition,
        joint_e2e_evidence_file=args.joint_e2e_evidence,
    )
    for artifact in manifest["artifacts"]:
        print(f"artifact={artifact['name']} size={artifact['size']} sha256={artifact['sha256']}")
    print(f"signing={manifest['signing']}")
    print(f"release_decision={manifest['release_decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
