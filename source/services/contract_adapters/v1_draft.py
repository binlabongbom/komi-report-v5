"""V5.2 shared canonical JSON and raw-key Ed25519 adapter.

The external representation is unpadded base64url of the raw 32-byte Ed25519
public key. Business payload builders depend only on this seam.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    candidate = value.strip().encode("ascii")
    return base64.urlsafe_b64decode(candidate + b"=" * (-len(candidate) % 4))


class DraftV1SigningAdapter:
    contract_adapter_version = "v5.2-shared-r2"

    @staticmethod
    def canonical_bytes(
        payload: Mapping[str, object], *, exclude_fields: frozenset[str] = frozenset()
    ) -> bytes:
        normalized = {str(key): value for key, value in payload.items() if key not in exclude_fields}
        return json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def sign_envelope(
        self,
        payload: Mapping[str, object],
        *,
        signature_field: str,
        private_key: Ed25519PrivateKey,
    ) -> str:
        canonical = self.canonical_bytes(payload, exclude_fields=frozenset({signature_field}))
        return _encode(private_key.sign(canonical))

    def verify_envelope(
        self,
        payload: Mapping[str, object],
        *,
        signature_field: str,
        public_key_base64url: str,
    ) -> bool:
        signature = payload.get(signature_field)
        if not isinstance(signature, str) or not signature:
            return False
        try:
            public_key = Ed25519PublicKey.from_public_bytes(_decode(public_key_base64url))
            public_key.verify(
                _decode(signature),
                self.canonical_bytes(payload, exclude_fields=frozenset({signature_field})),
            )
        except (InvalidSignature, TypeError, ValueError):
            return False
        return True
