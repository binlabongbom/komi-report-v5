from __future__ import annotations

import secrets

from komi_snmp_profiler.credential_store import (
    DEFAULT_ADMIN_USERNAME,
    AdminCredential,
    SessionCredentialStore,
)


def test_session_store_keeps_credential_only_in_memory_until_clear() -> None:
    store = SessionCredentialStore()
    credential = AdminCredential(password=secrets.token_urlsafe(18))

    store.save("10.0.0.5", credential)
    assert store.load("10.0.0.5") == credential

    store.clear()
    assert store.load("10.0.0.5") is None


def test_session_store_delete_is_host_scoped() -> None:
    store = SessionCredentialStore()
    first = AdminCredential(password=secrets.token_urlsafe(18))
    second = AdminCredential(password=secrets.token_urlsafe(18))
    store.save("10.0.0.5", first)
    store.save("10.0.0.6", second)

    store.delete("10.0.0.5")

    assert store.load("10.0.0.5") is None
    assert store.load("10.0.0.6") == second


def test_session_store_requires_explicit_credential_for_new_hosts() -> None:
    store = SessionCredentialStore()

    assert store.load("10.0.0.5") is None
    assert DEFAULT_ADMIN_USERNAME == "administrator"


def test_admin_credential_rejects_a_different_username() -> None:
    try:
        AdminCredential(username="operator", password=secrets.token_urlsafe(18))
    except ValueError as err:
        assert "Administrator" in str(err)
    else:
        raise AssertionError("non-Administrator username must be rejected")
