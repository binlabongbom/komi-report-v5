"""Persistent source access with short-lived, IP-bound request tokens.

Desktop and Agent enable continuous joining by default. The source remains
open across joins and restarts; each client acquires/renews its own request
without repeated user approval. Explicit off remains available. Temporary
windows are retained for compatibility, not offered as the default UI flow.
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
    diagnostic_code = 'peer_authorization'


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
    continuous: bool = False,
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
                "schema": 2,
                "disabled": False,
                "always_open": bool(always_open),
                "continuous": bool(continuous),
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
        previous = _read_state(path)
        _write_state(path, {"schema": 2, "disabled": True, "always_open": False,
                            "installation_id": previous.get("installation_id", ""),
                            "claims": {}, "used": True, "window_expires_at": 0.0})


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
                "เครื่องต้นทางปิดรับสมาชิกอยู่ ตรวจการตั้งค่าสิทธิ์เข้ากลุ่ม"
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
    history_transfer: bool = False,
    enrollment_transfer: bool = False,
) -> None:
    """Atomically consume a claimed capability before returning the snapshot."""

    value = _validate_token(token)
    remote = str(requester_ip or "").strip()
    identity = str(installation_id or "").strip()
    current = float(time.time() if now is None else now)
    path = state_path()
    with _state_lock(path):
        payload = _read_state(path)
        if enrollment_transfer and payload.get('continuous') is not True:
            raise PeerSyncAuthorizationError('เครื่องต้นทางยังไม่ได้เปิดรับสมาชิกต่อเนื่อง ตรวจการตั้งค่าสิทธิ์เข้ากลุ่ม')
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
            if history_transfer:
                _grant_history_transfer(payload, value, remote, current)
            if enrollment_transfer:
                _grant_enrollment_transfer(payload, value, remote, current)
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
        if history_transfer:
            _grant_history_transfer(payload, value, remote, current)
        if enrollment_transfer:
            _grant_enrollment_transfer(payload, value, remote, current)
        _write_state(path, payload)


def _grant_enrollment_transfer(payload, token, remote, now):
    grants = {k: v for k, v in payload.get('enrollment_transfers', {}).items()
              if v.get('expires_at', 0) > now}
    if len(grants) >= 128:
        raise PeerSyncAuthorizationError('มีคำขอเข้ากลุ่มมากเกินไป กรุณาลองใหม่')
    grants[_token_digest(token)] = {'requester_ip': remote,
        'expires_at': now + PAIRING_WINDOW_SECONDS, 'binding': None}
    payload['enrollment_transfers'] = grants


def enrollment_grant(token, requester_ip, installation_id, *, binding=None, now=None):
    """A separately approved, bounded handoff; never upgrade an old copy grant.

    Retries keep the same member key, group and immutable settings head. Closing
    the window or changing the installation invalidates every pending handoff.
    """
    value = _validate_token(token)
    current = float(time.time() if now is None else now)
    path = state_path()
    with _state_lock(path):
        payload = _read_state(path)
        grant = payload.get('enrollment_transfers', {}).get(_token_digest(value), {})
        if (payload.get('disabled') or not payload.get('continuous')
                or not installation_id or payload.get('installation_id') != installation_id
                or grant.get('requester_ip') != requester_ip or grant.get('expires_at', 0) <= current):
            raise PeerSyncAuthorizationError('คำขอเข้ากลุ่มหมดอายุหรือไม่ถูกต้อง กรุณาลองใหม่')
        if binding is not None:
            if grant.get('binding') not in (None, binding):
                raise PeerSyncAuthorizationError('คำขอเข้ากลุ่มเปลี่ยนจากรายการที่อนุญาต')
            grant['binding'] = binding
            _write_state(path, payload)
        return grant.get('binding')


def _grant_history_transfer(payload, token, remote, now):
    grants = {key: value for key, value in payload.get("history_transfers", {}).items()
              if float(value.get("expires_at", 0)) > now}
    if len(grants) >= 128:
        raise PeerSyncAuthorizationError("มีการรับประวัติพร้อมกันจำนวนมาก กรุณาลองใหม่")
    grants[_token_digest(token)] = {"requester_ip": remote, "expires_at": now + PAIRING_WINDOW_SECONDS, "head": ""}
    payload["history_transfers"] = grants


def history_transfer_head(token, requester_ip, installation_id, *, bind_head=None, now=None):
    """Read/bind a short-lived capability for one immutable history only.

    Repeating pages is allowed; reusing the token for setup or another revision
    is not. Closing pairing or changing installation invalidates these grants.
    """
    value = _validate_token(token)
    current = float(time.time() if now is None else now)
    path = state_path()
    with _state_lock(path):
        payload = _read_state(path)
        grant = payload.get("history_transfers", {}).get(_token_digest(value), {})
        if (payload.get("disabled") or payload.get("installation_id") != installation_id
                or not installation_id or grant.get("requester_ip") != requester_ip
                or float(grant.get("expires_at", 0)) <= current):
            raise PeerSyncAuthorizationError("สิทธิ์รับประวัติหมดอายุหรือไม่ถูกต้อง")
        head = grant.get("head", "")
        if bind_head is not None:
            if (not isinstance(bind_head, str) or len(bind_head) != 64
                    or any(c not in "0123456789abcdef" for c in bind_head)
                    or head not in ("", bind_head)):
                raise PeerSyncAuthorizationError("สิทธิ์นี้ใช้ได้เฉพาะประวัติชุดที่เริ่มรับไว้")
            grant["head"] = bind_head
            _write_state(path, payload)
            head = bind_head
        return head

def ensure_pairing_default(installation_id: str, *, primary: bool = True, continuous: bool = False, now: float | None = None) -> bool:
    """Migrate a Primary to persistent approval once; preserve explicit choices.

    Legacy 'off' was represented by no file, so it cannot be distinguished from
    a never-configured default. Schema 2 persists an explicit disabled state.
    Never replace live claims on an ordinary restart.
    """
    if not primary:
        return False
    identity = str(installation_id or "").strip()
    if not identity:
        return False
    path = state_path()
    current = float(time.time() if now is None else now)
    with _state_lock(path):
        payload = _read_state(path)
        if path.exists() and not payload:
            raise PeerSyncAuthorizationError("สถานะ Peer Sync เสียหาย กรุณาตั้งค่าใหม่โดยผู้ดูแล")
        if payload.get("schema") == 2 and payload.get("installation_id") == identity:
            if continuous and not payload.get('continuous_default_migrated'):
                # Upgrade the former timed/copy-only default without discarding
                # live requests. A deliberate off setting remains off.
                payload.update(continuous=True, always_open=not bool(payload.get('disabled')),
                               continuous_default_migrated=True)
                _write_state(path, payload)
                return True
            return False
        if payload.get("schema") == 2:
            disabled = bool(payload.get("disabled"))
            always = (continuous or bool(payload.get("always_open"))) and not disabled
        else:
            disabled, always = False, True
        _write_state(path, {
            "schema": 2, "disabled": disabled, "always_open": always,
            "claims": {}, "window_expires_at": 0.0,
            "installation_id": identity, "requester_ip": "", "token_sha256": "",
            "token_expires_at": 0.0, "used": False,
            "default_migrated_at": current,
            "continuous": continuous,
            "continuous_default_migrated": continuous,
        })
    return True
