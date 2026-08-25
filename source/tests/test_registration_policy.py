from __future__ import annotations

import json

import pytest

from services.registration_policy import (
    BUILT_IN_NOTICE_VERSION,
    REQUIRED_NOTICE_FIELDS,
    load_registration_policy,
)


def _artefact(**overrides):
    payload = {
        "base_url": "https://staging.invalid.example",
        "environment": "staging",
        "bootstrap": {
            "mode": "vault_header",
            "header": "X-Synthetic-Bootstrap",
            "vault_ref": "registration-bootstrap-reference",
        },
        "privacy_notice": {
            "version": "notice-2026-08",
            "approved": True,
            "purpose": "Synthetic registration test",
            "fields": sorted(REQUIRED_NOTICE_FIELDS),
            "retention": "Synthetic retention",
            "deletion_contact": "privacy@example.invalid",
            "legal_basis": "Synthetic legal basis",
            "access_export": "Synthetic access/export workflow",
            "approval_reference": "SYNTHETIC-DPO-TEST-REFERENCE",
            "approved_at": "2026-08-22T00:00:00+00:00",
            "approval_owner": "Synthetic Test Approver",
        },
        "request_timeout_seconds": 15,
    }
    payload.update(overrides)
    return payload


def test_v5_2_has_no_legacy_built_in_production_bootstrap_policy():
    policy = load_registration_policy({})

    assert policy is None
    assert BUILT_IN_NOTICE_VERSION == "KOMI-REG-2026-08-25-V52"


def test_diagnostic_environment_can_explicitly_disable_built_in_policy():
    assert load_registration_policy({"KOMI_REGISTRATION_DISABLED": "1"}) is None


def test_policy_loader_requires_complete_typed_artefact(tmp_path):
    path = tmp_path / "registration-policy.json"
    path.write_text(json.dumps(_artefact()), encoding="utf-8")

    policy = load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})

    assert policy is not None
    assert policy.notice.complete is True
    assert policy.sending_blocker(
        accepted_notice_version="notice-2026-08",
        accepted_at="2026-08-22T01:00:00+00:00",
    ) == ""


def test_production_policy_rejects_anonymous_bootstrap(tmp_path):
    path = tmp_path / "registration-policy.json"
    payload = _artefact(environment="production")
    payload["bootstrap"]["mode"] = "anonymous"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Anonymous registration"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})


def test_unapproved_or_incomplete_notice_blocks_sending(tmp_path):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["privacy_notice"]["approved"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")

    policy = load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})

    assert policy is not None
    assert policy.sending_blocker(
        accepted_notice_version="notice-2026-08",
        accepted_at="2026-08-22T01:00:00+00:00",
    ) == "privacy_notice_unapproved"


def test_policy_artefact_rejects_unexpected_bootstrap_value_field(tmp_path):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["bootstrap"]["unexpected_value"] = "synthetic"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="bootstrap policy fields"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})


@pytest.mark.parametrize(
    "base_url",
    (
        "https://" + "synthetic-user" + "@example.invalid",
        "https://example.invalid?redirect=elsewhere",
        "https://example.invalid#fragment",
        "https://example.invalid:invalid-port",
    ),
)
def test_policy_rejects_ambiguous_or_credential_bearing_url(tmp_path, base_url):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["base_url"] = base_url
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Registration API URL"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})


@pytest.mark.parametrize("timeout", (0, 61, float("inf"), float("nan"), 10**1_000))
def test_policy_rejects_unsafe_timeout(tmp_path, timeout):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["request_timeout_seconds"] = timeout
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="timeout"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})


@pytest.mark.parametrize("timeout", (None, [], True))
def test_policy_rejects_non_numeric_timeout_as_policy_error(tmp_path, timeout):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["request_timeout_seconds"] = timeout
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="timeout"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})


def test_notice_with_extra_field_never_enables_sender(tmp_path):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["privacy_notice"]["fields"].append("ip_address")
    path.write_text(json.dumps(payload), encoding="utf-8")

    policy = load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})

    assert policy is not None
    assert policy.notice.complete is False
    assert policy.sending_blocker(
        accepted_notice_version=policy.notice.version,
        accepted_at="2026-08-22T01:00:00+00:00",
    ) == "privacy_notice_unapproved"


@pytest.mark.parametrize(
    "header",
    ("Idempotency-Key", "Authorization", "Content-Type", "Host", "Bad Header"),
)
def test_policy_rejects_reserved_or_invalid_bootstrap_header(tmp_path, header):
    path = tmp_path / "registration-policy.json"
    payload = _artefact()
    payload["bootstrap"]["header"] = header
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="header"):
        load_registration_policy({"KOMI_REGISTRATION_POLICY_FILE": str(path)})
