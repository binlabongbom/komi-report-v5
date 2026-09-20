from __future__ import annotations

from services.installation_identity import (
    installation_private_key_reference,
    load_or_create_installation_identity,
)
from services.registration_vault import SessionRegistrationSecretStore


def test_installation_identity_is_stable_and_private_key_stays_in_vault():
    vault = SessionRegistrationSecretStore()

    first = load_or_create_installation_identity(vault, "install-v52")
    second = load_or_create_installation_identity(vault, "install-v52")

    assert first.public_key_base64url == second.public_key_base64url
    assert first.sign(b"synthetic-message") == second.sign(b"synthetic-message")
    assert vault.load(installation_private_key_reference("install-v52"))
    assert "private" not in repr(first).casefold()


def test_installation_identity_fails_closed_when_vault_material_is_invalid():
    vault = SessionRegistrationSecretStore()
    vault.save(installation_private_key_reference("install-v52"), "not-a-private-key")

    try:
        load_or_create_installation_identity(vault, "install-v52")
    except ValueError as err:
        assert "invalid" in str(err).casefold()
    else:
        raise AssertionError("invalid private key must fail closed")


def test_existing_only_load_does_not_create_a_new_identity():
    import pytest
    vault = SessionRegistrationSecretStore()
    with pytest.raises(PermissionError, match='recovery'):
        load_or_create_installation_identity(vault, 'restored', create_if_missing=False)
    assert vault.load(installation_private_key_reference('restored')) is None
    created = load_or_create_installation_identity(vault, 'restored')
    assert load_or_create_installation_identity(vault, 'restored', create_if_missing=False) == created
