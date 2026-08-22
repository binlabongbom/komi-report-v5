from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from tools.build_pilot_bundle import (
    PILOT_MANIFEST_NAME,
    PilotContractError,
    build_pilot_bundle,
    verify_candidate,
)


def _candidate(tmp_path, *, commit: str = "a" * 40, signing: str = "unsigned-blocked"):
    rc_dir = tmp_path / "rc"
    rc_dir.mkdir()
    installer = rc_dir / "KOMI_Report_V5_1_0_Windows_x64_RC.exe"
    installer.write_bytes(b"synthetic unsigned installer")
    digest = hashlib.sha256(installer.read_bytes()).hexdigest()
    manifest = {
        "version": "5.1.0",
        "artifact": installer.name,
        "artifact_sha256": digest,
        "source_commit": commit,
        "source_state": "archive-clean",
        "signing": signing,
        "registration_runtime": "fail-closed-no-policy-artefact",
        "update_runtime": "absent-phase-3-deferred",
        "production_go": False,
    }
    (rc_dir / "RC_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    (rc_dir / "CHECKSUMS.sha256").write_text(
        f"{digest}  {installer.name}\n", encoding="ascii"
    )
    (rc_dir / "FILE_INVENTORY.json").write_text("[]\n", encoding="utf-8")
    (rc_dir / "SBOM.cdx.json").write_text("{}\n", encoding="utf-8")
    return rc_dir, commit


def test_candidate_requires_exact_commit_checksum_and_unsigned_state(tmp_path):
    rc_dir, commit = _candidate(tmp_path)

    candidate = verify_candidate(rc_dir, expected_commit=commit)

    assert candidate.source_commit == commit
    assert candidate.signing == "unsigned-blocked"
    with pytest.raises(PilotContractError, match="source commit"):
        verify_candidate(rc_dir, expected_commit="b" * 40)

    rc_dir.joinpath("CHECKSUMS.sha256").write_text("mismatch\n", encoding="ascii")
    with pytest.raises(PilotContractError, match="checksum sidecar"):
        verify_candidate(rc_dir, expected_commit=commit)


def test_pilot_bundle_is_traceable_and_holds_without_staging(tmp_path, monkeypatch):
    rc_dir, commit = _candidate(tmp_path)
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    for name in (
        "PILOT_RELEASE_CHECKLIST.md",
        "RELEASE_SUPPORT_AND_RECOVERY.md",
        "REGISTRATION_DATA_NOTICE.md",
    ):
        (docs_root / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr("tools.build_pilot_bundle.PROJECT_ROOT", tmp_path)

    archive, manifest = build_pilot_bundle(
        rc_dir,
        tmp_path / "pilot",
        expected_commit=commit,
        registration_e2e="hold-missing-verified-staging",
    )

    assert manifest["release_decision"] == "HOLD"
    assert manifest["production_go"] is False
    assert manifest["signing"] == "unsigned-blocked"
    assert manifest["pilot_artifact_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as packaged:
        names = set(packaged.namelist())
        embedded = json.loads(packaged.read(PILOT_MANIFEST_NAME))
    assert {
        "KOMI_Report_V5_1_0_Windows_x64_RC.exe",
        "RC_MANIFEST.json",
        "CHECKSUMS.sha256",
        "FILE_INVENTORY.json",
        "SBOM.cdx.json",
        "PILOT_RELEASE_CHECKLIST.md",
        "RELEASE_SUPPORT_AND_RECOVERY.md",
        "REGISTRATION_DATA_NOTICE.md",
        PILOT_MANIFEST_NAME,
    } <= names
    assert embedded["release_decision"] == "HOLD"
    assert "Unknown publisher" in embedded["publisher_warning"]


def test_pilot_go_requires_recorded_staging_e2e(tmp_path, monkeypatch):
    rc_dir, commit = _candidate(tmp_path, signing="unverified-blocked")
    docs_root = tmp_path / "docs"
    docs_root.mkdir()
    for name in (
        "PILOT_RELEASE_CHECKLIST.md",
        "RELEASE_SUPPORT_AND_RECOVERY.md",
        "REGISTRATION_DATA_NOTICE.md",
    ):
        (docs_root / name).write_text(f"# {name}\n", encoding="utf-8")
    monkeypatch.setattr("tools.build_pilot_bundle.PROJECT_ROOT", tmp_path)

    _archive, manifest = build_pilot_bundle(
        rc_dir,
        tmp_path / "pilot",
        expected_commit=commit,
        registration_e2e="passed-staging",
    )

    assert manifest["release_decision"] == "PILOT GO"
    assert manifest["production_go"] is False
