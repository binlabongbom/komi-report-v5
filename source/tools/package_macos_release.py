"""Package the already-built local macOS app without publishing it."""

from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path

from tools.build_local_release import _included_files
from tools.release_safety import assert_release_safe, assert_zip_safe, git_identity

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION = tomllib.loads(
    (PROJECT_ROOT / "source" / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
APP_BUNDLE = PROJECT_ROOT / "source" / "dist" / f"KOMI Report V{VERSION}.app"
RELEASE_DIR = PROJECT_ROOT / "release"
ARCHIVE = RELEASE_DIR / "KOMI_Report_V5_macOS_arm64_Local.zip"
CHECKSUM = ARCHIVE.with_suffix(ARCHIVE.suffix + ".sha256")
MANIFEST = RELEASE_DIR / "MACOS_MANIFEST.json"


def package_macos_app() -> tuple[Path, str]:
    assert_release_safe(_included_files(), root=PROJECT_ROOT)
    executable = APP_BUNDLE / "Contents" / "MacOS" / f"KOMI Report V{VERSION}"
    info_plist = APP_BUNDLE / "Contents" / "Info.plist"
    if not executable.is_file() or not info_plist.is_file():
        raise FileNotFoundError("build the PyInstaller app before packaging")

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE.unlink(missing_ok=True)
    subprocess.run(
        [
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(APP_BUNDLE),
            str(ARCHIVE),
        ],
        check=True,
    )
    assert_zip_safe(ARCHIVE, scan_secrets=False)
    digest = hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    CHECKSUM.write_text(f"{digest}  {ARCHIVE.name}\n", encoding="utf-8")
    with info_plist.open("rb") as stream:
        info = plistlib.load(stream)
    commit, source_state = git_identity(PROJECT_ROOT)
    payload = {
        "version": VERSION,
        "artifact": ARCHIVE.name,
        "artifact_identity": f"komi-report-v5-macos-arm64-{VERSION}-{commit[:12]}",
        "git_commit": commit,
        "source_state": source_state,
        "sha256": digest,
        "bundle_identifier": info.get("CFBundleIdentifier"),
        "bundle_version": info.get("CFBundleVersion"),
        "short_version": info.get("CFBundleShortVersionString"),
        "architecture": "arm64",
        "signing": "ad-hoc",
        "notarized": False,
        "publish_state": "local-only",
        "build_time": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return ARCHIVE, digest


if __name__ == "__main__":
    archive, sha256 = package_macos_app()
    print(f"{archive}\nsha256={sha256}")
