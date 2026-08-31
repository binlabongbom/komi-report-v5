from __future__ import annotations

import base64
import json

import pytest

from services.offline_license_keys import (
    OfflineLicensePublicKeyConfigurationError,
    load_offline_license_public_keys,
    parse_offline_license_public_keys,
    public_key_candidates,
)


def _public_key(value: int = 7) -> str:
    return base64.urlsafe_b64encode(bytes([value]) * 32).decode("ascii").rstrip("=")


def _payload() -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "algorithm": "Ed25519",
            "keys": [
                {"kid": "komi-offline-2026", "public_key_base64url": _public_key()}
            ],
        }
    ).encode()


def test_parses_strict_public_only_key_bundle() -> None:
    assert parse_offline_license_public_keys(_payload()) == {
        "komi-offline-2026": _public_key()
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"private_key": "forbidden"}),
        lambda data: data["keys"][0].update({"private_key": "forbidden"}),
        lambda data: data.update({"algorithm": "RSA"}),
        lambda data: data.update({"keys": []}),
        lambda data: data["keys"][0].update({"public_key_base64url": "short"}),
        lambda data: data["keys"][0].update(
            {"public_key_base64url": "+" + _public_key()[1:]}
        ),
    ],
)
def test_rejects_invalid_or_secret_bearing_bundle(mutation) -> None:
    data = json.loads(_payload())
    mutation(data)
    with pytest.raises(OfflineLicensePublicKeyConfigurationError):
        parse_offline_license_public_keys(json.dumps(data).encode())


def test_loads_explicit_public_key_file(tmp_path) -> None:
    path = tmp_path / "keys.json"
    path.write_bytes(_payload())
    assert load_offline_license_public_keys(
        {"KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_FILE": str(path)}
    ) == {"komi-offline-2026": _public_key()}


def test_missing_public_key_file_returns_empty_mapping(tmp_path) -> None:
    assert load_offline_license_public_keys(
        {"KOMI_PROJECT_ROOT": str(tmp_path)}
    ) == {}


def test_explicit_missing_public_key_file_fails_closed(tmp_path) -> None:
    with pytest.raises(OfflineLicensePublicKeyConfigurationError):
        load_offline_license_public_keys(
            {"KOMI_OFFLINE_LICENSE_PUBLIC_KEYS_FILE": str(tmp_path / "missing.json")}
        )


def test_duplicate_json_field_is_rejected() -> None:
    raw = _payload().replace(b'"algorithm": "Ed25519",', b'"algorithm": "Ed25519", "algorithm": "Ed25519",')
    with pytest.raises(OfflineLicensePublicKeyConfigurationError):
        parse_offline_license_public_keys(raw)


def test_bundle_candidate_is_runtime_config_path(tmp_path) -> None:
    candidates = public_key_candidates({}, bundle_root=tmp_path)
    assert candidates[0] == (
        tmp_path / "runtime-config" / "public-verification-keys.json"
    )
