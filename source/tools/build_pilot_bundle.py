"""Build a traceable unsigned Pilot bundle from verified RC evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from tools.release_safety import assert_zip_safe

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PILOT_ARCHIVE_NAME = "KOMI_Report_V5_1_0_Unsigned_Pilot.zip"
PILOT_MANIFEST_NAME = "PILOT_MANIFEST.json"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)
REQUIRED_EVIDENCE = (
    "RC_MANIFEST.json",
    "CHECKSUMS.sha256",
    "FILE_INVENTORY.json",
    "SBOM.cdx.json",
)
PILOT_DOCS = (
    "PILOT_RELEASE_CHECKLIST.md",
    "RELEASE_SUPPORT_AND_RECOVERY.md",
    "REGISTRATION_DATA_NOTICE.md",
)
ALLOWED_UNSIGNED_STATES = frozenset({"unsigned-blocked", "unverified-blocked"})


class PilotContractError(RuntimeError):
    """A Pilot evidence condition is missing or inconsistent."""


@dataclass(frozen=True)
class VerifiedCandidate:
    installer: Path
    installer_sha256: str
    source_commit: str
    signing: Literal["unsigned-blocked", "unverified-blocked"]
    manifest: dict[str, object]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotContractError(f"invalid Pilot evidence JSON: {path.name}") from error
    if not isinstance(payload, dict):
        raise PilotContractError(f"Pilot evidence must be a JSON object: {path.name}")
    return payload


def verify_candidate(rc_dir: Path, *, expected_commit: str) -> VerifiedCandidate:
    for name in REQUIRED_EVIDENCE:
        if not (rc_dir / name).is_file():
            raise PilotContractError(f"required RC evidence is missing: {name}")

    manifest = _load_json(rc_dir / "RC_MANIFEST.json")
    source_commit = str(manifest.get("source_commit", "")).strip().casefold()
    if source_commit != expected_commit.strip().casefold():
        raise PilotContractError("RC source commit does not match the approved integration commit")
    if str(manifest.get("version", "")) != "5.1.0":
        raise PilotContractError("Pilot requires KOMI Report version 5.1.0")
    if manifest.get("production_go") is not False:
        raise PilotContractError("RC manifest must keep production_go=false")
    if manifest.get("registration_runtime") != "fail-closed-no-policy-artefact":
        raise PilotContractError("Registration runtime is not fail-closed")
    if manifest.get("update_runtime") != "absent-phase-3-deferred":
        raise PilotContractError("Phase 3 Update runtime must be absent")

    signing = str(manifest.get("signing", ""))
    if signing not in ALLOWED_UNSIGNED_STATES:
        raise PilotContractError("Pilot builder accepts only an explicitly unsigned candidate")

    artifact_name = str(manifest.get("artifact", "")).strip()
    installer = rc_dir / artifact_name
    if not artifact_name or not installer.is_file():
        raise PilotContractError("RC installer named by the manifest is missing")
    actual_sha256 = sha256_file(installer)
    if actual_sha256 != str(manifest.get("artifact_sha256", "")).strip().casefold():
        raise PilotContractError("RC installer SHA256 does not match the manifest")

    checksum_line = (rc_dir / "CHECKSUMS.sha256").read_text(encoding="ascii").strip()
    if checksum_line != f"{actual_sha256}  {artifact_name}":
        raise PilotContractError("RC checksum sidecar does not match the installer")

    return VerifiedCandidate(
        installer=installer,
        installer_sha256=actual_sha256,
        source_commit=source_commit,
        signing=cast(Literal["unsigned-blocked", "unverified-blocked"], signing),
        manifest=manifest,
    )


def build_pilot_bundle(
    rc_dir: Path,
    output_dir: Path,
    *,
    expected_commit: str,
    registration_e2e: Literal["passed-staging", "hold-missing-verified-staging"],
) -> tuple[Path, dict[str, object]]:
    candidate = verify_candidate(rc_dir, expected_commit=expected_commit)
    docs = [PROJECT_ROOT / "docs" / name for name in PILOT_DOCS]
    missing_docs = [path.name for path in docs if not path.is_file()]
    if missing_docs:
        raise PilotContractError("Pilot guide is missing: " + ", ".join(missing_docs))

    release_decision = "PILOT GO" if registration_e2e == "passed-staging" else "HOLD"
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / PILOT_ARCHIVE_NAME
    manifest = {
        "schema_version": 1,
        "product": "KOMI Report V5",
        "version": "5.1.0",
        "pilot_artifact": archive.name,
        "source_commit": candidate.source_commit,
        "installer": candidate.installer.name,
        "installer_sha256": candidate.installer_sha256,
        "signing": candidate.signing,
        "publisher_warning": "Unsigned installer; Windows may display Unknown publisher. Verify SHA256 before use.",
        "registration_e2e": registration_e2e,
        "release_decision": release_decision,
        "production_go": False,
        "update_runtime": "absent-phase-3-deferred",
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    members = [candidate.installer]
    members.extend(rc_dir / name for name in REQUIRED_EVIDENCE)
    members.extend(docs)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in members:
            info = zipfile.ZipInfo(path.name, ZIP_TIMESTAMP)
            info.external_attr = (stat.S_IMODE(path.stat().st_mode) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, path.read_bytes(), compresslevel=9)
        manifest_info = zipfile.ZipInfo(PILOT_MANIFEST_NAME, ZIP_TIMESTAMP)
        manifest_info.external_attr = 0o644 << 16
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        output.writestr(
            manifest_info,
            (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            compresslevel=9,
        )
    assert_zip_safe(archive)

    archive_sha256 = sha256_file(archive)
    manifest["pilot_artifact_sha256"] = archive_sha256
    (output_dir / PILOT_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / f"{archive.name}.sha256").write_text(
        f"{archive_sha256}  {archive.name}\n",
        encoding="ascii",
    )
    return archive, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the KOMI Report V5.1 unsigned Pilot bundle")
    parser.add_argument("--rc-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--registration-e2e",
        choices=("passed-staging", "hold-missing-verified-staging"),
        required=True,
    )
    args = parser.parse_args()
    archive, manifest = build_pilot_bundle(
        args.rc_dir.resolve(),
        args.output.resolve(),
        expected_commit=args.source_commit,
        registration_e2e=args.registration_e2e,
    )
    print(f"pilot={archive}")
    print(f"sha256={manifest['pilot_artifact_sha256']}")
    print(f"decision={manifest['release_decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
