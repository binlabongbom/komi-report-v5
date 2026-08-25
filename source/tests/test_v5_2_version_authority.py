from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from komi_version import APP_VERSION, require_v5_2
from tools.build_macos_customer import MacCustomerBuildError, build_customer_package
from tools.build_windows_rc import build_payload
from tools.release_evidence import ReleaseContractError
from tools.version_gate import assert_v5_2_version_alignment


def test_v5_2_version_authority_is_5_2_0_and_all_current_metadata_matches():
    assert APP_VERSION == "5.2.0"
    assert_v5_2_version_alignment()


def test_v5_2_version_authority_rejects_old_new_build_metadata():
    with pytest.raises(RuntimeError, match="5.2.x"):
        require_v5_2("5.1.0")


def test_v5_2_customer_artifact_builders_fail_closed_before_external_gates(tmp_path):
    with pytest.raises(ReleaseContractError, match="Joint Staging E2E"):
        build_payload(tmp_path / "windows", customer_release=True)
    with pytest.raises(MacCustomerBuildError, match="Joint Staging E2E"):
        build_customer_package(tmp_path / "macos")


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
