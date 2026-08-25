from __future__ import annotations

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
