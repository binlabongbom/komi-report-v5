"""Build the self-contained Windows x64 V5.2 Release Candidate.

The command never publishes, signs or adds an Update runtime. Windows ARM VM
execution is explicitly a preflight and can never be labelled native x64
evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

from services.offline_license_keys import (
    PUBLIC_KEYS_FILENAME,
    parse_offline_license_public_keys,
)
from tools.build_local_release import (
    SOURCE_ARCHIVE_IDENTITY_NAME,
    SOURCE_COMMIT_NAME,
    SourceArchiveIdentityError,
    assert_extracted_source_archive_identity,
)
from tools.package_windows_test_kit import (
    DOC_FILES,
    PACKAGE_DIRS,
    ROOT_FILES,
    copy_python_tree,
    download_python_runtime,
    download_wheelhouse,
    install_windows_dependencies,
)
from tools.release_evidence import (
    ReleaseContractError,
    assert_native_payload_safe,
    assert_no_update_runtime_paths,
    assert_registration_fail_closed_payload,
    build_environment_label,
    load_joint_e2e_evidence,
    require_windows_x64,
    write_release_evidence,
)
from tools.release_safety import FORBIDDEN_SUFFIXES, git_identity

SOURCE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SOURCE_ROOT.parent
VERSION = tomllib.loads((SOURCE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]
RELEASE_ROOT = PROJECT_ROOT / "release" / "windows-x64-rc"
PAYLOAD_NAME = f"KOMI Report V{VERSION}"
VERSION_TAG = VERSION.replace(".", "_")
INSTALLER_NAME = f"KOMI_Report_V{VERSION_TAG}_Windows_x64_RC.exe"
CUSTOMER_INSTALLER_NAME = f"KOMI_Report_V{VERSION_TAG}_Windows_x64_Installer.exe"
INNO_SCRIPT = PROJECT_ROOT / "packaging" / "windows" / "KOMI_Report_V5.iss"
NODE_VERSION = "24.18.0"
NODE_ARCHIVE = f"node-v{NODE_VERSION}-win-x64.zip"
NODE_DIST_ROOT = f"https://nodejs.org/dist/v{NODE_VERSION}"
NODE_ARCHIVE_URL = f"{NODE_DIST_ROOT}/{NODE_ARCHIVE}"
NODE_CHECKSUM_URL = f"{NODE_DIST_ROOT}/SHASUMS256.txt"
WEB_EXCLUDED_DIRS = {".next", "node_modules", "__pycache__"}
SOURCE_MANIFEST = ".komi-web-source-files.json"
DEPENDENCY_STAMP = ".komi-web-dependencies.sha256"
BUILD_STAMP = ".komi-web-build.sha256"
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

RUNTIME_TOOL_FILES = (
    "__init__.py",
    "check_parser.py",
    "db_recovery.py",
    "default_profiles.json",
    "init_web_access.py",
    "prepare_web_runtime.py",
    "run_web_servers.py",
    "web_service_worker.py",
)

START_CMD = r"""@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" >nul 2>&1 || (
  echo [ERROR] Unable to open the KOMI Report V5 installation folder.
  pause
  exit /b 1
)
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "KOMI_PROJECT_ROOT=%~dp0"
set "PATH=%~dp0node-runtime;%PATH%"
set "KOMI_WEB_RUNTIME=%LOCALAPPDATA%\KOMI Report V5\web-runtime"

if not exist "runtime\pythonw.exe" (
  echo [ERROR] The bundled Python x64 runtime is missing.
  pause
  popd
  exit /b 1
)
if not exist "node-runtime\node.exe" (
  echo [ERROR] The bundled Node.js x64 runtime is missing.
  pause
  popd
  exit /b 1
)
if not exist "%KOMI_WEB_RUNTIME%\.next\BUILD_ID" (
  mkdir "%KOMI_WEB_RUNTIME%" >nul 2>&1
  robocopy "web-runtime-seed" "%KOMI_WEB_RUNTIME%" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1 >nul
  if errorlevel 8 (
    echo [ERROR] Unable to initialize the local Web runtime.
    pause
    popd
    exit /b 1
  )
)

start "" "runtime\pythonw.exe" "source\app.py"
set "KOMI_EXIT_CODE=%errorlevel%"
popd
exit /b %KOMI_EXIT_CODE%
"""

START_VBS = r"""Option Explicit
Dim shell, fileSystem, installRoot, command
Set shell = CreateObject("WScript.Shell")
Set fileSystem = CreateObject("Scripting.FileSystemObject")
installRoot = fileSystem.GetParentFolderName(WScript.ScriptFullName)
command = Chr(34) & installRoot & "\START_KOMI_REPORT.cmd" & Chr(34)
shell.Run command, 0, False
"""


def write_hidden_launcher(path: Path) -> None:
    """Write Windows Script Host source without a UTF-8 BOM.

    Legacy Windows Script Host treats the UTF-8 BOM as an invalid VBScript
    character. The launcher is ASCII-only by design so it works on supported
    Windows 10/11 hosts without showing a console window.
    """

    path.write_text(START_VBS, encoding="ascii", newline="\r\n")

START_DEBUG_CMD = r"""@echo off
setlocal
chcp 65001 >nul
pushd "%~dp0" >nul 2>&1 || exit /b 1
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONUTF8=1"
set "KOMI_PROJECT_ROOT=%~dp0"
set "PATH=%~dp0node-runtime;%PATH%"
"runtime\python.exe" "source\app.py"
set "KOMI_EXIT_CODE=%errorlevel%"
echo.
echo KOMI Report V5 exited with code %KOMI_EXIT_CODE%.
pause
popd
exit /b %KOMI_EXIT_CODE%
"""

README = f"""KOMI Report V{VERSION} — Windows x64 Unsigned Pilot Candidate

Target: Windows 10/11 x64
Runtime: bundled CPython 3.11 x64 and Node.js {{node_version}} LTS x64

This RC includes Desktop, local SQLite, OS-vault integration and LAN Web HTTPS.
It does not include an Update client, updater, remote update command or Update telemetry.
Registration uses schema 3 with a per-installation Ed25519 identity generated
locally. No shared/master bootstrap key is packaged in this artifact.

PUBLISHER WARNING: this installer is not code-signed. Windows can display
"Unknown publisher" or "Publisher could not be verified". Verify the SHA-256
sidecar before installation and use this package only for the controlled Pilot.
This is not a signed Production release.

User data is stored outside the installation directory. Uninstall removes program files only.
Follow docs/PILOT_RELEASE_CHECKLIST.md and docs/RELEASE_SUPPORT_AND_RECOVERY.md
before installation, upgrade, restore, rollback or data cleanup.
"""

CUSTOMER_README = f"""KOMI Report V{VERSION} — Windows Customer Release Package

Target runtime: Windows 10/11 x64
Build evidence: {{build_evidence}}
Runtime: bundled CPython 3.11 x64 and Node.js {{node_version}} LTS x64

This package runs the production Desktop, local SQLite, OS-vault integration
and LAN Web HTTPS behavior. It contains no Lab/test/demo/Virtual Printer auto-
injection and no Update client, updater, remote command or Update telemetry.
Registration uses the V5.2 schema-3 Ed25519 public-client contract. Each
installation creates its own key pair and stores the private key in Windows
Credential Manager; no shared/master bootstrap key is embedded in the EXE.
Registration fails closed if OS-vault provisioning or the API contract is
unavailable.

PUBLISHER WARNING: this installer is not code-signed. Windows can display
"Unknown publisher" or "Publisher could not be verified". Verify the SHA-256
sidecar before installation. The unsigned state blocks RELEASE READY even
though the application payload uses production behavior.

User data is stored outside the installation directory. Uninstall removes
program files only. Follow docs/CUSTOMER_RELEASE_NOTES.md and
docs/RELEASE_SUPPORT_AND_RECOVERY.md before install, recovery or rollback.
"""


def _download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_node_runtime(destination: Path) -> str:
    """Install the official Node.js Windows x64 ZIP after checksum verification."""

    with tempfile.TemporaryDirectory(prefix="komi-node-runtime-") as temp:
        temp_root = Path(temp)
        archive = temp_root / NODE_ARCHIVE
        sums = temp_root / "SHASUMS256.txt"
        _download(NODE_ARCHIVE_URL, archive)
        _download(NODE_CHECKSUM_URL, sums)
        expected = ""
        for line in sums.read_text(encoding="utf-8").splitlines():
            fields = line.split()
            if len(fields) >= 2 and fields[-1].lstrip("*") == NODE_ARCHIVE:
                expected = fields[0].casefold()
                break
        actual = _sha256(archive)
        if not expected or actual != expected:
            raise ReleaseContractError("Official Node.js archive checksum verification failed")
        extracted = temp_root / "extracted"
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(extracted)
        roots = [path for path in extracted.iterdir() if path.is_dir()]
        if len(roots) != 1 or not (roots[0] / "node.exe").is_file():
            raise ReleaseContractError("Official Node.js archive layout is invalid")
        shutil.copytree(roots[0], destination)
        return actual


def _copy_authored_web(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for path in authored_files(source):
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _is_authored_web_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in WEB_EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name.startswith(".env") and path.name.endswith(".local"):
        return False
    return not path.name.endswith(".tsbuildinfo")


def authored_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file() and _is_authored_web_file(path, root)),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def source_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in authored_files(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _node_command(node_root: Path, name: str) -> Path:
    command = node_root / name
    if not command.is_file():
        raise ReleaseContractError(f"Bundled Node command is missing: {name}")
    return command


def remove_forbidden_dependency_assets(root: Path) -> int:
    """Remove non-runtime package assets forbidden by the release contract."""

    removed = 0
    for path in root.rglob("*"):
        suffixes = {suffix.casefold() for suffix in path.suffixes}
        if path.is_file() and suffixes.intersection(FORBIDDEN_SUFFIXES):
            path.unlink()
            removed += 1
    return removed


def remove_node_build_tooling(node_root: Path) -> int:
    """Keep only the Node runtime after the Web standalone seed is built."""

    removed = 0
    for name in (
        "node_modules",
        "corepack",
        "corepack.cmd",
        "npm",
        "npm.cmd",
        "npx",
        "npx.cmd",
    ):
        path = node_root / name
        if path.is_dir():
            removed += sum(1 for item in path.rglob("*") if item.is_file())
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
            removed += 1
    return removed


def build_web_runtime_seed(*, payload_root: Path, node_root: Path) -> None:
    web_source = PROJECT_ROOT / "web"
    authored_destination = payload_root / "web"
    _copy_authored_web(web_source, authored_destination)

    with tempfile.TemporaryDirectory(prefix="komi-web-build-") as temp:
        build_root = Path(temp) / "web"
        _copy_authored_web(web_source, build_root)
        environment = os.environ.copy()
        environment["PATH"] = str(node_root) + os.pathsep + environment.get("PATH", "")
        npm = _node_command(node_root, "npm.cmd")
        subprocess.run([str(npm), "ci"], cwd=build_root, env=environment, check=True)
        subprocess.run([str(npm), "run", "build"], cwd=build_root, env=environment, check=True)

        standalone = build_root / ".next" / "standalone"
        if not (standalone / "node_modules" / "next").is_dir():
            raise ReleaseContractError("Next standalone production runtime was not produced")
        seed = payload_root / "web-runtime-seed"
        shutil.copytree(standalone, seed)
        _copy_authored_web(web_source, seed)
        static = build_root / ".next" / "static"
        shutil.copytree(static, seed / ".next" / "static", dirs_exist_ok=True)
        public = build_root / "public"
        if public.is_dir():
            shutil.copytree(public, seed / "public", dirs_exist_ok=True)

    manifest = [path.relative_to(web_source).as_posix() for path in authored_files(web_source)]
    (seed / SOURCE_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    dependency_hash = hashlib.sha256((web_source / "package-lock.json").read_bytes()).hexdigest()
    (seed / DEPENDENCY_STAMP).write_text(dependency_hash + "\n", encoding="utf-8")
    (seed / BUILD_STAMP).write_text(source_hash(web_source) + "\n", encoding="utf-8")


def build_payload(
    output_root: Path,
    *,
    customer_release: bool = False,
    build_evidence: str = "not-yet-classified",
) -> tuple[Path, dict[str, str]]:
    payload_root = output_root / "payload" / PAYLOAD_NAME
    if payload_root.exists():
        shutil.rmtree(payload_root)
    source_destination = payload_root / "source"
    source_destination.mkdir(parents=True)

    offline_public_keys = os.environ.get(
        "KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_BUILD_FILE", ""
    ).strip()
    offline_license_key_state = "absent-online-only"
    if offline_public_keys:
        public_keys_source = Path(offline_public_keys)
        try:
            raw_public_keys = public_keys_source.read_bytes()
        except OSError as exc:
            raise ReleaseContractError(
                "Offline License public verification key file cannot be read"
            ) from exc
        parse_offline_license_public_keys(raw_public_keys)
        public_keys_destination = payload_root / "runtime-config" / PUBLIC_KEYS_FILENAME
        public_keys_destination.parent.mkdir(parents=True, exist_ok=True)
        public_keys_destination.write_bytes(raw_public_keys)
        offline_license_key_state = "bundled-public-only"

    for filename in ROOT_FILES:
        source = SOURCE_ROOT / filename
        if source.is_file():
            shutil.copy2(source, source_destination / filename)
    for directory in PACKAGE_DIRS:
        copy_python_tree(SOURCE_ROOT / directory, source_destination / directory)
    tools_destination = source_destination / "tools"
    tools_destination.mkdir()
    for filename in RUNTIME_TOOL_FILES:
        shutil.copy2(SOURCE_ROOT / "tools" / filename, tools_destination / filename)

    docs_destination = payload_root / "docs"
    docs_destination.mkdir()
    for filename in DOC_FILES:
        source = PROJECT_ROOT / "docs" / filename
        if source.is_file():
            shutil.copy2(source, docs_destination / filename)
    recovery_guide = PROJECT_ROOT / "docs" / "RELEASE_SUPPORT_AND_RECOVERY.md"
    if recovery_guide.is_file():
        shutil.copy2(recovery_guide, docs_destination / recovery_guide.name)
    if customer_release:
        for filename in ("CUSTOMER_RELEASE_NOTES.md", "CUSTOMER_INSTALL_GUIDE.md"):
            source = PROJECT_ROOT / "docs" / filename
            if source.is_file():
                shutil.copy2(source, docs_destination / filename)
        manual_assets = PROJECT_ROOT / "docs" / "customer-guide" / "assets-v5.2"
        if not manual_assets.is_dir():
            raise ReleaseContractError("Customer guide screenshot assets are missing")
        shutil.copytree(
            manual_assets,
            docs_destination / "customer-guide" / "assets-v5.2",
        )

    runtime_root = payload_root / "runtime"
    python_runtime_sha256 = download_python_runtime(runtime_root)
    pth = runtime_root / "python311._pth"
    pth.write_text(
        "python311.zip\n.\n..\\source\nLib/site-packages\nimport site\n",
        encoding="utf-8",
        newline="\r\n",
    )
    with tempfile.TemporaryDirectory(prefix="komi-windows-wheelhouse-") as wheelhouse_temp:
        wheelhouse = Path(wheelhouse_temp)
        download_wheelhouse(wheelhouse)
        wheel_count = sum(1 for path in wheelhouse.glob("*.whl"))
        install_windows_dependencies(wheelhouse, runtime_root / "Lib" / "site-packages")
    removed_forbidden_assets = remove_forbidden_dependency_assets(
        runtime_root / "Lib" / "site-packages"
    )

    node_root = payload_root / "node-runtime"
    node_runtime_sha256 = install_node_runtime(node_root)
    build_web_runtime_seed(payload_root=payload_root, node_root=node_root)
    removed_node_build_tool_files = remove_node_build_tooling(node_root)

    (payload_root / "START_KOMI_REPORT.cmd").write_text(START_CMD, encoding="utf-8", newline="\r\n")
    write_hidden_launcher(payload_root / "START_KOMI_REPORT.vbs")
    (payload_root / "START_DEBUG.cmd").write_text(START_DEBUG_CMD, encoding="utf-8", newline="\r\n")
    readme = CUSTOMER_README if customer_release else README
    (payload_root / "README-WINDOWS.txt").write_text(
        readme.format(node_version=NODE_VERSION, build_evidence=build_evidence),
        encoding="utf-8-sig",
        newline="\r\n",
    )

    for cache in sorted(payload_root.rglob("__pycache__"), reverse=True):
        shutil.rmtree(cache)
    for bytecode in payload_root.rglob("*.py[co]"):
        bytecode.unlink()
    assert_native_payload_safe(payload_root)
    assert_no_update_runtime_paths(payload_root)
    assert_registration_fail_closed_payload(payload_root)
    return payload_root, {
        "python_runtime_sha256": python_runtime_sha256,
        "node_runtime_sha256": node_runtime_sha256,
        "removed_forbidden_dependency_assets": str(removed_forbidden_assets),
        "removed_node_build_tool_files": str(removed_node_build_tool_files),
        "wheel_count": str(wheel_count),
        "registration_bootstrap": "not-applicable-schema3",
        "offline_license_public_keys": offline_license_key_state,
    }


def find_iscc(explicit: Path | None = None) -> Path:
    candidates = [
        explicit,
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 7" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
    ]
    discovered = shutil.which("ISCC.exe") or shutil.which("iscc")
    if discovered:
        candidates.insert(0, Path(discovered))
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate
    raise ReleaseContractError("Inno Setup compiler is required to build the installer")


def compile_installer(
    *,
    payload_root: Path,
    output_root: Path,
    source_commit: str,
    iscc: Path,
    customer_release: bool = False,
) -> Path:
    installer_name = CUSTOMER_INSTALLER_NAME if customer_release else INSTALLER_NAME
    output_base = installer_name.removesuffix(".exe")
    description = (
        f"KOMI Report V{VERSION} Customer Release Package"
        if customer_release
        else f"KOMI Report V{VERSION} Release Candidate"
    )
    subprocess.run(
        [
            str(iscc),
            f"/DPayloadDir={payload_root}",
            f"/DOutputDir={output_root}",
            f"/DSourceCommit={source_commit}",
            f"/DOutputBaseFilename={output_base}",
            f"/DVersionInfoDescription={description}",
            str(INNO_SCRIPT),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    installer = output_root / installer_name
    if not installer.is_file():
        raise ReleaseContractError("Inno Setup did not produce the expected installer")
    return installer


def authenticode_status(installer: Path) -> str:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "(Get-AuthenticodeSignature -LiteralPath $args[0]).Status.ToString()",
        str(installer),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unverified-blocked"
    return "verified" if result.stdout.strip() == "Valid" else "unsigned-blocked"


def source_identity(explicit_commit: str = "") -> tuple[str, str]:
    explicit_commit = explicit_commit.strip().casefold()
    if explicit_commit and not COMMIT_RE.fullmatch(explicit_commit):
        raise ReleaseContractError("--source-commit must be a full 40-character Git commit")
    archive_markers = (
        PROJECT_ROOT / SOURCE_COMMIT_NAME,
        PROJECT_ROOT / SOURCE_ARCHIVE_IDENTITY_NAME,
    )
    if any(path.exists() for path in archive_markers):
        try:
            archive_identity = assert_extracted_source_archive_identity(PROJECT_ROOT)
        except SourceArchiveIdentityError as exc:
            raise ReleaseContractError(f"Source archive identity verification failed: {exc}") from exc
        archived_commit = str(archive_identity["git_commit"])
        if not COMMIT_RE.fullmatch(archived_commit):
            raise ReleaseContractError("Source archive commit is invalid")
        if explicit_commit and explicit_commit != archived_commit:
            raise ReleaseContractError("Source archive commit does not match --source-commit")
        return archived_commit, "archive-clean"
    if explicit_commit:
        raise ReleaseContractError("--source-commit requires matching SOURCE_COMMIT.txt in the source archive")
    return git_identity(PROJECT_ROOT)


def source_state_is_clean(source_state: str) -> bool:
    """Treat a verified source archive as equivalent to a clean Git checkout."""

    return source_state in {"clean", "archive-clean"}


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Build KOMI Report V{VERSION} Windows x64 RC")
    parser.add_argument("--output", type=Path, default=RELEASE_ROOT)
    parser.add_argument("--iscc", type=Path)
    parser.add_argument("--virtualized", action="store_true")
    parser.add_argument("--allow-arm64-vm-preflight", action="store_true")
    parser.add_argument("--allow-dirty-preflight", action="store_true")
    parser.add_argument("--source-commit", default="")
    parser.add_argument(
        "--customer-release",
        action="store_true",
        help="Build the production-behavior customer package profile (signing gate remains independent)",
    )
    parser.add_argument(
        "--joint-e2e-evidence",
        type=Path,
        help="Sanitized Joint Desktop-Staging E2E JSON; missing evidence produces a HOLD candidate",
    )
    args = parser.parse_args()

    machine = platform.machine()
    if args.allow_arm64_vm_preflight:
        if sys.platform != "win32" or machine.casefold() not in {"arm64", "aarch64"} or not args.virtualized:
            raise ReleaseContractError("ARM64 override is limited to an explicitly virtualized Windows preflight")
    else:
        require_windows_x64()

    commit, source_state = source_identity(args.source_commit)
    if not source_state_is_clean(source_state) and not args.allow_dirty_preflight:
        raise ReleaseContractError("RC build requires a clean committed source tree")
    output_root = args.output.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    environment = build_environment_label(
        platform_name=sys.platform,
        machine=machine,
        virtualized=args.virtualized,
    )
    joint_e2e = load_joint_e2e_evidence(
        args.joint_e2e_evidence,
        version=VERSION,
        source_commit=commit,
    )
    payload_root, runtime_evidence = build_payload(
        output_root,
        customer_release=args.customer_release,
        build_evidence=environment,
    )
    installer = compile_installer(
        payload_root=payload_root,
        output_root=output_root,
        source_commit=commit,
        iscc=find_iscc(args.iscc),
        customer_release=args.customer_release,
    )
    signing = authenticode_status(installer)
    manifest_name = "WINDOWS_MANIFEST.json" if args.customer_release else "RC_MANIFEST.json"
    manifest = write_release_evidence(
        artifact=installer,
        payload_root=payload_root,
        output_dir=output_root,
        version=VERSION,
        source_commit=commit,
        source_state=source_state,
        target="Windows 10/11 x64",
        build_environment=environment,
        signing=signing,
        requirements_lock=SOURCE_ROOT / "requirements-windows-x64.lock.txt",
        package_lock=PROJECT_ROOT / "web" / "package-lock.json",
        artifact_identity_prefix=(
            "komi-report-v5-windows-x64-customer"
            if args.customer_release
            else "komi-report-v5-windows-x64-rc"
        ),
        manifest_name=manifest_name,
        registration_runtime="schema3-ed25519-public-client-no-shared-bootstrap",
    )
    manifest["release_profile"] = "customer-production-behavior" if args.customer_release else "rc"
    manifest.update(runtime_evidence)
    manifest["joint_staging_e2e"] = joint_e2e
    blockers = ["Production GO requires explicit external approval; packaging never self-promotes"]
    if signing != "verified":
        blockers.append("Windows Authenticode is not verified")
    if environment != "windows-x64-native":
        blockers.append("Windows build evidence is not native Windows x64")
    if args.customer_release and joint_e2e["verified"] is not True:
        blockers.append("Joint Desktop-Staging E2E evidence is missing or did not pass")
    if runtime_evidence["offline_license_public_keys"] != "bundled-public-only":
        blockers.append("Host Offline License public verification key is not bundled")
    manifest["release_decision"] = "HOLD"
    manifest["production_go"] = False
    manifest["blockers"] = blockers
    (output_root / manifest_name).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"installer={installer}")
    print(f"sha256={manifest['artifact_sha256']}")
    print(f"environment={environment}")
    print(f"signing={signing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
