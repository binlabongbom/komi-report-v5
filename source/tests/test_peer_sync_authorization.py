from __future__ import annotations

import json

import pytest

from services import peer_sync_authorization as authorization


@pytest.fixture
def isolated_state(tmp_path, monkeypatch):
    path = tmp_path / "peer-sync.json"
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(path))
    return path


def test_capability_is_hashed_ip_bound_single_use_and_installation_bound(isolated_state):
    token = authorization.new_claim_token()
    authorization.open_pairing_window("primary-1", now=100.0)

    remaining = authorization.claim_pairing_window(token, "192.0.2.20", now=101.0)

    assert remaining == 299
    stored = json.loads(isolated_state.read_text(encoding="utf-8"))
    assert token not in isolated_state.read_text(encoding="utf-8")
    assert stored["token_sha256"]
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(
            token,
            "192.0.2.21",
            "primary-1",
            now=102.0,
        )
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(
            token,
            "192.0.2.20",
            "different-primary",
            now=102.0,
        )

    authorization.consume_pairing_token(
        token,
        "192.0.2.20",
        "primary-1",
        now=102.0,
    )

    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(
            token,
            "192.0.2.20",
            "primary-1",
            now=103.0,
        )


def test_first_claimant_excludes_other_secondary(isolated_state):
    first = authorization.new_claim_token()
    second = authorization.new_claim_token()
    authorization.open_pairing_window("primary-1", now=100.0)
    authorization.claim_pairing_window(first, "192.0.2.20", now=101.0)

    with pytest.raises(authorization.PeerSyncAuthorizationError, match="เครื่องอื่น"):
        authorization.claim_pairing_window(second, "192.0.2.21", now=102.0)


def test_expired_or_closed_window_fails_closed(isolated_state):
    token = authorization.new_claim_token()
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.claim_pairing_window(token, "192.0.2.20", now=100.0)

    authorization.open_pairing_window("primary-1", now=100.0, ttl_seconds=30)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.claim_pairing_window(token, "192.0.2.20", now=131.0)


def test_always_open_survives_restart_and_accepts_independent_single_use_claims(isolated_state):
    import os
    import subprocess
    import sys
    from pathlib import Path

    authorization.open_pairing_window("primary-1", now=100, always_open=True)
    result = subprocess.run(
        [sys.executable, "-c", "import os,sys; sys.path.insert(0,os.getcwd()); from services.peer_sync_authorization import pairing_window_status; assert pairing_window_status().always_open"],
        cwd=Path(__file__).resolve().parents[1], env=os.environ.copy(), capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert authorization.pairing_window_status(now=100000).always_open
    first, second = authorization.new_claim_token(), authorization.new_claim_token()
    authorization.claim_pairing_window(first, "192.0.2.20", now=100000)
    authorization.claim_pairing_window(second, "192.0.2.21", now=100000)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(first, "192.0.2.21", "primary-1", now=100001)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(first, "192.0.2.20", "other", now=100001)
    authorization.consume_pairing_token(first, "192.0.2.20", "primary-1", now=100001)
    authorization.consume_pairing_token(second, "192.0.2.21", "primary-1", now=100001)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(first, "192.0.2.20", "primary-1", now=100002)
    assert authorization.pairing_window_status(now=100002).open


def test_always_open_tokens_expire_and_off_revokes_pending_tokens(isolated_state):
    authorization.open_pairing_window("primary-1", now=100, always_open=True)
    token = authorization.new_claim_token()
    authorization.claim_pairing_window(token, "192.0.2.20", now=101)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(token, "192.0.2.20", "primary-1", now=402)
    fresh = authorization.new_claim_token()
    authorization.claim_pairing_window(fresh, "192.0.2.20", now=403)
    authorization.close_pairing_window()
    assert not authorization.pairing_window_status(now=404).open
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(fresh, "192.0.2.20", "primary-1", now=404)
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.claim_pairing_window(fresh, "192.0.2.20", now=404)


def test_switching_always_to_temporary_expires_normally(isolated_state):
    authorization.open_pairing_window("primary-1", now=100, always_open=True)
    token = authorization.new_claim_token()
    authorization.claim_pairing_window(token, "192.0.2.20", now=101)
    authorization.open_pairing_window("primary-1", now=200)
    assert not authorization.pairing_window_status(now=201).always_open
    with pytest.raises(authorization.PeerSyncAuthorizationError):
        authorization.consume_pairing_token(token, "192.0.2.20", "primary-1", now=201)
    assert not authorization.pairing_window_status(now=501).open
