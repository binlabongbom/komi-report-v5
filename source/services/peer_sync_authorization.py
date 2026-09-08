"""User-approved Primary-to-Secondary setup sync with short-lived claim tokens.

The Secondary never asks for a password.  Instead, a user on the Primary opens
an approval window for five minutes.  The first LAN requester may claim that
window with a 256-bit random token.  Only a hash is stored, the claim is bound
to the request IP and current Primary installation, and the token is consumed
before the setup snapshot is returned. Persistent approval is an explicit option;
its independently claimed tokens still expire and can only be consumed once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from runtime_config import RUNTIME_SETTINGS

PAIRING_WINDOW_SECONDS = 5 * 60
MIN_TOKEN_BYTES = 32
_LOCK_WAIT_SECONDS = 2.0
_STALE_LOCK_SECONDS = 10.0


class PeerSyncAuthorizationError(RuntimeError):
    """The requested peer-sync capability is absent, expired, or invalid."""


@dataclass(frozen=True)
class PairingWindowStatus:
    open: bool
    seconds_remaining: int
    claimed: bool
    always_open: bool = False


def state_path() -> Path:
    override = os.environ.get("KOMI_PEER_SYNC_STATE_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve(strict=False)
    return RUNTIME_SETTINGS.app_home / "security" / "peer-sync-authorization.json"


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_claim_token() -> str:
    """Return at least 256 bits of CSPRNG material for a Secondary claim."""

    return secrets.token_urlsafe(MIN_TOKEN_BYTES)


def _validate_token(token: object) -> str:
    value = str(token or "")
    if len(value) < 43 or len(value) > 256:
        raise PeerSyncAuthorizationError("Peer Sync token ไม่ถูกต้อง")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise PeerSyncAuthorizationError("Peer Sync token ไม่ถูกต้อง") from exc
    return value


@contextmanager
def _state_lock(path: Path):
    """Small cross-process lock used for atomic claim/consume transitions."""

    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            os.write(descriptor, f"{os.getpid()} {time.time():.6f}".encode("ascii"))
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > _STALE_LOCK_SECONDS
            except FileNotFoundError:
                stale = False
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise PeerSyncAuthorizationError(
                    "ระบบอนุญาต Peer Sync กำลังถูกใช้งาน"
                ) from None
            time.sleep(0.02)
    try:
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _read_state(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


def open_pairing_window(
    installation_id: str,
    *,
    now: float | None = None,
    ttl_seconds: int = PAIRING_WINDOW_SECONDS,
    always_open: bool = False,
) -> PairingWindowStatus:
    """Replace any previous claim with one explicit Primary approval window."""

    identity = str(installation_id or "").strip()
    if not identity:
        raise PeerSyncAuthorizationError("เครื่อง Primary ยังไม่มี Installation ID")
    current = float(time.time() if now is None else now)
    ttl = max(30, min(PAIRING_WINDOW_SECONDS, int(ttl_seconds)))
    path = state_path()
    with _state_lock(path):
        _write_state(
            path,
            {
                "schema": 1,
                "always_open": bool(always_open),
                "claims": {},
                "window_expires_at": current + ttl,
                "installation_id": identity,
                "requester_ip": "",
                "token_sha256": "",
                "token_expires_at": 0.0,
                "used": False,
            },
        )
    return PairingWindowStatus(open=True, seconds_remaining=0 if always_open else ttl, claimed=False, always_open=always_open)


def close_pairing_window() -> None:
    path = state_path()
    with _state_lock(path):
        path.unlink(missing_ok=True)


def pairing_window_status(*, now: float | None = None) -> PairingWindowStatus:
    current = float(time.time() if now is None else now)
    payload = _read_state(state_path())
    if payload.get("always_open") is True and payload.get("installation_id"):
        claims = payload.get("claims", {})
        return PairingWindowStatus(
            open=True, seconds_remaining=0, always_open=True,
            claimed=any(float(claim.get("expires_at", 0)) > current for claim in claims.values()),
        )
    expiry = float(payload.get("window_expires_at") or 0)
    used = bool(payload.get("used"))
    remaining = max(0, int(expiry - current + 0.999))
    return PairingWindowStatus(
        open=remaining > 0 and not used,
        seconds_remaining=remaining if not used else 0,
        claimed=bool(payload.get("token_sha256")) and not used,
    )


def claim_pairing_window(
    token: object,
    requester_ip: str,
    *,
    now: float | None = None,
) -> int:
    """Bind the open window to one IP and a client-generated token hash."""

    value = _validate_token(token)
    remote = str(requester_ip or "").strip()
    if not remote:
        raise PeerSyncAuthorizationError("ไม่พบ IP ของเครื่อง Secondary")
    current = float(time.time() if now is None else now)
    path = state_path()
    with _state_lock(path):
        payload = _read_state(path)
        if payload.get("always_open") is True and payload.get("installation_id"):
            claims = {
                digest: claim for digest, claim in payload.get("claims", {}).items()
                if float(claim.get("expires_at", 0)) > current
            }
            digest = _token_digest(value)
            existing = claims.get(digest)
            if existing is not None and existing.get("requester_ip") != remote:
                raise PeerSyncAuthorizationError("สิทธิ์ Sync ถูกเครื่องอื่นรับไปแล้ว")
            if existing is None:
                if len(claims) >= 128:
                    raise PeerSyncAuthorizationError("มีคำขอ Sync จำนวนมาก กรุณาลองอีกครั้ง")
                claims[digest] = {"requester_ip": remote, "expires_at": current + PAIRING_WINDOW_SECONDS}
            payload["claims"] = claims
            _write_state(path, payload)
            return max(1, int(float(claims[digest]["expires_at"]) - current))
        expiry = float(payload.get("window_expires_at") or 0)
        if expiry <= current or bool(payload.get("used")):
            raise PeerSyncAuthorizationError(
                "บนเครื่อง Primary ให้กดอนุญาต Secondary Sync 5 นาที"
            )
        existing_ip = str(payload.get("requester_ip") or "")
        existing_hash = str(payload.get("token_sha256") or "")
        digest = _token_digest(value)
        if existing_ip or existing_hash:
            if existing_ip != remote or not hmac.compare_digest(existing_hash, digest):
                raise PeerSyncAuthorizationError("สิทธิ์ Sync ถูกเครื่องอื่นรับไปแล้ว")
        else:
            payload["requester_ip"] = remote
            payload["token_sha256"] = digest
            payload["token_expires_at"] = min(
                expiry,
                current + PAIRING_WINDOW_SECONDS,
            )
            _write_state(path, payload)
        token_expiry = float(payload.get("token_expires_at") or expiry)
        return max(1, int(token_expiry - current))


def consume_pairing_token(
    token: object,
    requester_ip: str,
    installation_id: str,
    *,
    now: float | None = None,
) -> None:
    """Atomically consume a claimed capability before returning the snapshot."""

    value = _validate_token(token)
    remote = str(requester_ip or "").strip()
    identity = str(installation_id or "").strip()
    current = float(time.time() if now is None else now)
    path = state_path()
    with _state_lock(path):
        payload = _read_state(path)
        if payload.get("always_open") is True:
            digest = _token_digest(value)
            claims = payload.get("claims", {})
            claim = claims.get(digest, {})
            if not (
                float(claim.get("expires_at", 0)) > current
                and claim.get("requester_ip") == remote
                and payload.get("installation_id") == identity
            ):
                raise PeerSyncAuthorizationError("สิทธิ์ Secondary Sync หมดอายุหรือไม่ถูกต้อง")
            del claims[digest]
            payload["claims"] = claims
            _write_state(path, payload)
            return
        valid = (
            not bool(payload.get("used"))
            and float(payload.get("window_expires_at") or 0) > current
            and float(payload.get("token_expires_at") or 0) > current
            and str(payload.get("requester_ip") or "") == remote
            and str(payload.get("installation_id") or "") == identity
            and hmac.compare_digest(
                str(payload.get("token_sha256") or ""),
                _token_digest(value),
            )
        )
        if not valid:
            raise PeerSyncAuthorizationError("สิทธิ์ Secondary Sync หมดอายุหรือไม่ถูกต้อง")
        # Single-use is committed before the caller builds or serializes data.
        payload["used"] = True
        payload["token_sha256"] = ""
        payload["token_expires_at"] = 0.0
        _write_state(path, payload)
