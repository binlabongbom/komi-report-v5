from __future__ import annotations

import pytest

from komi_snmp_profiler.models import ConnectionSettings


def test_connection_accepts_ipv4_and_v2c() -> None:
    settings = ConnectionSettings(host="192.168.1.50", community="public")
    assert settings.port == 161
    assert settings.version == "2c"


@pytest.mark.parametrize("host", ["", "not a hostname", "printer"])
def test_connection_rejects_bad_host(host: str) -> None:
    with pytest.raises(ValueError):
        ConnectionSettings(host=host, community="public")


def test_connection_rejects_empty_community() -> None:
    with pytest.raises(ValueError):
        ConnectionSettings(host="192.168.1.50", community="")


def test_v3_auth_priv_requires_user_and_passwords() -> None:
    with pytest.raises(ValueError):
        ConnectionSettings(host="192.168.1.50", community="", version="3")
    settings = ConnectionSettings(
        host="192.168.1.50",
        community="",
        version="3",
        v3_username="initial",
        v3_auth_password="auth-pass",
        v3_priv_password="priv-pass",
    )
    assert settings.v3_security_level == "authPriv"
