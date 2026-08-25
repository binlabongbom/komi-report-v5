from __future__ import annotations

from pathlib import Path

from services.registration_bootstrap import (
    BUNDLED_BOOTSTRAP_FILENAME,
    provision_registration_bootstrap,
)
from services.registration_policy import (
    REQUIRED_NOTICE_FIELDS,
    PrivacyNotice,
    RegistrationRuntimePolicy,
)
from services.registration_vault import SessionRegistrationSecretStore


class RecordingStore(SessionRegistrationSecretStore):
    def __init__(self) -> None:
        super().__init__()
        self.saved_references: list[str] = []

    def save(self, reference: str, secret: str) -> None:
        self.saved_references.append(reference)
        super().save(reference, secret)


def _production_policy():
    return RegistrationRuntimePolicy(
        base_url="https://legacy-v51.invalid.example",
        environment="production",
        bootstrap_mode="vault_header",
        bootstrap_header="X-Synthetic-Legacy-Bootstrap",
        bootstrap_ref="registration-bootstrap-reference",
        notice=PrivacyNotice(
            version="legacy-v51-test",
            approved=True,
            purpose="Synthetic legacy V5.1 bootstrap test",
            fields=REQUIRED_NOTICE_FIELDS,
            retention="Synthetic retention",
            deletion_contact="privacy@example.invalid",
            legal_basis="Synthetic legacy test",
            access_export="Synthetic legacy test",
            approval_reference="SYNTHETIC-LEGACY-TEST",
            approved_at="2026-08-22T00:00:00Z",
            approval_owner="Synthetic Test",
        ),
        request_timeout_seconds=15,
    )


def test_packaged_bootstrap_is_provisioned_to_vault_without_returning_value(tmp_path: Path):
    packaged = tmp_path / BUNDLED_BOOTSTRAP_FILENAME
    packaged.write_text("synthetic-limited-bootstrap\n", encoding="utf-8")
    store = RecordingStore()

    state = provision_registration_bootstrap(
        _production_policy(),
        vault=store,
        environ={"KOMI_REGISTRATION_BOOTSTRAP_FILE": str(packaged)},
        legacy_loader=lambda: None,
    )

    assert state == "provisioned"
    assert store.saved_references == ["registration-bootstrap-reference"]
    assert store.load("registration-bootstrap-reference") == "synthetic-limited-bootstrap"


def test_existing_vault_value_is_never_overwritten(tmp_path: Path):
    packaged = tmp_path / BUNDLED_BOOTSTRAP_FILENAME
    packaged.write_text("replacement-must-not-win", encoding="utf-8")
    store = RecordingStore()
    store.save("registration-bootstrap-reference", "existing-vault-value")
    store.saved_references.clear()

    state = provision_registration_bootstrap(
        _production_policy(),
        vault=store,
        environ={"KOMI_REGISTRATION_BOOTSTRAP_FILE": str(packaged)},
        legacy_loader=lambda: "legacy-must-not-win",
    )

    assert state == "already-provisioned"
    assert store.saved_references == []
    assert store.load("registration-bootstrap-reference") == "existing-vault-value"


def test_legacy_tested_key_can_migrate_without_exposing_it():
    store = RecordingStore()

    state = provision_registration_bootstrap(
        _production_policy(),
        vault=store,
        environ={},
        legacy_loader=lambda: "synthetic-legacy-bootstrap",
    )

    assert state == "provisioned"
    assert store.load("registration-bootstrap-reference") == "synthetic-legacy-bootstrap"


def test_missing_or_invalid_bootstrap_remains_fail_closed(tmp_path: Path):
    invalid = tmp_path / BUNDLED_BOOTSTRAP_FILENAME
    invalid.write_bytes(b"\x00not-text")
    store = RecordingStore()

    state = provision_registration_bootstrap(
        _production_policy(),
        vault=store,
        environ={"KOMI_REGISTRATION_BOOTSTRAP_FILE": str(invalid)},
        legacy_loader=lambda: None,
    )

    assert state == "bootstrap-unavailable"
    assert store.saved_references == []
