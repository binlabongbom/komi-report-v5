from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from komi_version import APP_VERSION, require_v5_2
from services.v5_2_contract_metadata import CONTRACT_SHA256, CONTRACT_VERSION
from tools.build_customer_delivery import VERSION as DELIVERY_VERSION
from tools.build_macos_customer import (
    APP_NAME as MACOS_APP_NAME,
)
from tools.build_macos_customer import (
    VERSION as MACOS_VERSION,
)
from tools.build_windows_rc import (
    CUSTOMER_INSTALLER_NAME,
    INSTALLER_NAME,
    PAYLOAD_NAME,
)
from tools.build_windows_rc import VERSION as WINDOWS_VERSION
from tools.release_evidence import ReleaseContractError, load_joint_e2e_evidence
from tools.version_gate import assert_v5_2_version_alignment


def test_v5_2_version_authority_is_5_2_2_and_all_current_metadata_matches():
    assert APP_VERSION == "5.2.2"
    assert_v5_2_version_alignment()


def test_native_build_identity_is_derived_from_current_version_authority():
    assert WINDOWS_VERSION == APP_VERSION
    assert MACOS_VERSION == APP_VERSION
    assert DELIVERY_VERSION == APP_VERSION
    assert PAYLOAD_NAME == "KOMI Report V5.2.2"
    assert MACOS_APP_NAME == "KOMI Report V5.2.2"
    assert INSTALLER_NAME == "KOMI_Report_V5_2_2_Windows_x64_RC.exe"
    assert CUSTOMER_INSTALLER_NAME == "KOMI_Report_V5_2_2_Windows_x64_Installer.exe"


def test_v5_2_version_authority_rejects_old_new_build_metadata():
    with pytest.raises(RuntimeError, match="5.2.x"):
        require_v5_2("5.1.0")


def test_v5_2_customer_artifact_builders_accept_evidence_input_without_legacy_bootstrap():
    tools_root = Path(__file__).parents[1] / "tools"
    for name in ("build_windows_rc.py", "build_macos_customer.py"):
        builder = (tools_root / name).read_text(encoding="utf-8")
        assert "--joint-e2e-evidence" in builder
        assert "--registration-bootstrap-file" not in builder
        assert "Final schema-3 auth vectors and Joint Staging" not in builder
        assert "production_go\"] = False" in builder or '"production_go": False' in builder


def test_joint_e2e_evidence_is_missing_hold_or_exact_identity_verified(tmp_path):
    commit = "a" * 40
    missing = load_joint_e2e_evidence(None, version=APP_VERSION, source_commit=commit)
    assert missing["state"] == "missing-blocked"
    assert missing["verified"] is False
    assert missing["contract_version"] == CONTRACT_VERSION
    assert missing["contract_sha256"] == CONTRACT_SHA256

    evidence_path = tmp_path / "joint-e2e.json"
    evidence_path.write_text(
        """
{
  "schema_version": 1,
  "product_version": "5.2.2",
  "source_commit": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "contract_version": "v5.2-shared-2026-08-25-r2",
  "contract_sha256": "4884a4a6fb798ef0c36c88daca09cf2ae5df66ff609139f812880ab7322413bd",
  "environment": "staging",
  "joint_e2e_passed": true,
  "dashboard_readback_passed": true,
  "cleanup_deactivate_passed": true
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    verified = load_joint_e2e_evidence(
        evidence_path,
        version=APP_VERSION,
        source_commit=commit,
    )
    assert verified["state"] == "verified"
    assert verified["verified"] is True
    assert isinstance(verified["evidence_sha256"], str)

    failed_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    failed_payload["dashboard_readback_passed"] = False
    evidence_path.write_text(json.dumps(failed_payload), encoding="utf-8")
    failed = load_joint_e2e_evidence(
        evidence_path,
        version=APP_VERSION,
        source_commit=commit,
    )
    assert failed["state"] == "failed-blocked"
    assert failed["verified"] is False

    with pytest.raises(ReleaseContractError, match="identity mismatch"):
        load_joint_e2e_evidence(
            evidence_path,
            version=APP_VERSION,
            source_commit="b" * 40,
        )


def test_windows_builder_metadata_import_does_not_require_runtime_crypto():
    source_root = Path(__file__).parents[1]
    blocker = """
import sys

class BlockRuntimeCrypto:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "cryptography" or fullname.startswith("cryptography."):
            raise ModuleNotFoundError("runtime crypto intentionally unavailable to build tooling")
        return None

sys.meta_path.insert(0, BlockRuntimeCrypto())
import tools.build_windows_rc
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source_root)
    result = subprocess.run(
        [sys.executable, "-c", blocker],
        cwd=source_root,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
