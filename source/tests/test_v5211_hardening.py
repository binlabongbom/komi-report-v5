"""No live Host traffic, OS credentials or customer databases in this suite."""
from __future__ import annotations
import errno
import json
import socket
import ssl
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import URLError
import pytest

from services import build_edition
from services import peer_sync_authorization as peer
from services.registration_errors import (
    SUPPORT_CODES, RegistrationNetworkError, classify_network_error,
    error_message, safe_support_code,
)
from services.v5_2_client import V52ContractClient, V52NetworkError, V52RuntimeConfig, UrllibV52Transport
from services.v5_2_outbox import request_fingerprint
from services.v5_2_runtime import V52RuntimeCoordinator, V52RuntimeProcessor
from services.v5_2_runtime_state import V52RuntimeStateRepository


@pytest.mark.parametrize(("error", "code"), [
    (socket.gaierror(-2, "private hostname"), "dns_error"),
    (URLError(socket.gaierror(-2, "private hostname")), "dns_error"),
    (TimeoutError("private address"), "connection_timeout"),
    (URLError(TimeoutError()), "connection_timeout"),
    (ConnectionRefusedError(), "connection_refused"),
    (ConnectionResetError(), "connection_reset"),
    (OSError(errno.ENETUNREACH, "private route"), "network_unreachable"),
    (ssl.SSLCertVerificationError(1, "private certificate"), "tls_certificate_error"),
    (URLError(ssl.SSLCertVerificationError(1, "private certificate")), "tls_certificate_error"),
    (ssl.SSLError(1, "private TLS data"), "tls_error"),
    (URLError("untyped transport error containing synthetic private data"), "offline"),
])
def test_typed_network_classification_without_leaking_errors(error, code):
    assert classify_network_error(error) == code
    assert str(RegistrationNetworkError(code)) == code
    assert "private" not in " ".join(error_message(code))


def test_unknown_support_code_is_redacted():
    assert safe_support_code("Bearer private-secret") == "needs_review"
    assert str(V52NetworkError("Bearer private-secret")) == "offline"


@pytest.mark.parametrize("code", sorted(SUPPORT_CODES))
def test_support_code_survives_both_runtime_allowlists(code):
    assert V52RuntimeProcessor._curated_error(code, retryable=True) == code
    assert V52RuntimeStateRepository._curated_support_code(code) == code


def test_transport_classifies_tls_and_does_not_weaken_certificate_checks():
    transport = UrllibV52Transport()
    transport._opener = SimpleNamespace(open=Mock(side_effect=URLError(ssl.SSLCertVerificationError(1, "redact me"))))
    with pytest.raises(V52NetworkError) as raised:
        transport.request(url="https://example.invalid/api", headers={}, body=b"{}", timeout=1)
    assert raised.value.code == "tls_certificate_error"
    assert "redact me" not in str(raised.value)


def _operation():
    return SimpleNamespace(payload={}, request_fingerprint=request_fingerprint({}),
                           idempotency_key="test-operation", event_type="register")


def test_client_retains_network_reason_for_repairable_tls_failure():
    transport = SimpleNamespace(request=Mock(side_effect=V52NetworkError("tls_certificate_error")))
    result = V52ContractClient(V52RuntimeConfig("https://example.invalid", "production"), transport=transport).send(_operation())
    assert result.error_code == "tls_certificate_error"
    assert result.retryable and result.retry_after_seconds == 300


@pytest.mark.parametrize("event_type", ["register", "status", "meter"])
def test_offline_edition_blocks_all_host_transport(event_type, monkeypatch):
    monkeypatch.setattr(build_edition, "BUILD_EDITION", "offline")
    transport = SimpleNamespace(request=Mock(side_effect=AssertionError("must not send")))
    operation = _operation()
    operation.event_type = event_type
    result = V52ContractClient(V52RuntimeConfig("https://example.invalid", "production"), transport=transport).send(operation)
    assert not result.success and result.error_code == "offline_edition"
    transport.request.assert_not_called()


def test_offline_edition_cannot_switch_runtime_to_online(monkeypatch):
    monkeypatch.setattr(build_edition, "BUILD_EDITION", "offline")
    with pytest.raises(ValueError, match="Offline"):
        V52RuntimeCoordinator.set_mode(SimpleNamespace(), "online")


def test_edition_cannot_be_changed_by_environment(monkeypatch):
    monkeypatch.setattr(build_edition, "BUILD_EDITION", "offline")
    monkeypatch.setenv("KOMI_BUILD_EDITION", "normal")
    assert build_edition.is_offline_edition()


@pytest.fixture
def peer_state(tmp_path, monkeypatch):
    path = tmp_path / "authorization.json"
    monkeypatch.setenv("KOMI_PEER_SYNC_STATE_FILE", str(path))
    return path


def test_primary_fresh_install_is_persistent(peer_state):
    assert peer.ensure_pairing_default("primary", now=1)
    status = peer.pairing_window_status(now=100000)
    assert status.open and status.always_open


def test_restart_does_not_reset_inflight_claim(peer_state):
    peer.ensure_pairing_default("primary", now=1)
    token = peer.new_claim_token()
    peer.claim_pairing_window(token, "10.0.0.2", now=2)
    before = peer_state.read_bytes()
    assert not peer.ensure_pairing_default("primary", now=3)
    assert peer_state.read_bytes() == before
    peer.consume_pairing_token(token, "10.0.0.2", "primary", now=4)
    with pytest.raises(peer.PeerSyncAuthorizationError):
        peer.consume_pairing_token(token, "10.0.0.2", "primary", now=4)


def test_explicit_off_survives_restart_and_identity_change(peer_state):
    peer.ensure_pairing_default("primary", now=1)
    peer.close_pairing_window()
    assert not peer.ensure_pairing_default("primary", now=2)
    assert not peer.pairing_window_status(now=2).open
    peer.ensure_pairing_default("replacement", now=3)
    assert not peer.pairing_window_status(now=3).open


def test_legacy_default_migrates_once(peer_state):
    peer_state.write_text(json.dumps({"schema": 1, "installation_id": "primary", "always_open": False, "window_expires_at": 1}), encoding="utf-8")
    assert peer.ensure_pairing_default("primary", now=2)
    assert peer.pairing_window_status(now=9999).always_open


def test_secondary_does_not_self_enable_primary_approval(peer_state):
    assert not peer.ensure_pairing_default("secondary", primary=False)
    assert not peer_state.exists()


def test_corrupt_state_does_not_silently_grant_access(peer_state):
    peer_state.write_text("{broken", encoding="utf-8")
    with pytest.raises(peer.PeerSyncAuthorizationError):
        peer.ensure_pairing_default("primary")


def test_token_remains_bound_to_ip_identity_and_expiry(peer_state):
    peer.ensure_pairing_default("primary", now=1)
    token = peer.new_claim_token()
    peer.claim_pairing_window(token, "10.0.0.2", now=2)
    for ip, identity, now in [("10.0.0.3", "primary", 3), ("10.0.0.2", "other", 3), ("10.0.0.2", "primary", 999)]:
        with pytest.raises(peer.PeerSyncAuthorizationError):
            peer.consume_pairing_token(token, ip, identity, now=now)


def _wizard(snapshot):
    return SimpleNamespace(
        _registration_in_progress=True,
        registration_runtime=SimpleNamespace(snapshot=lambda: snapshot),
        _registration_deadline=datetime.now().astimezone() - timedelta(seconds=30),
        registration_result_copy=SimpleNamespace(setText=Mock()),
        _registration_succeeded=Mock(), _show_registration_failure=Mock(),
    )


def test_late_registration_success_is_not_reported_as_offline():
    from v5_pages import SetupWizardV5
    snapshot = {"status": "retrying", "support_code": "offline", "request_in_progress": True}
    wizard = _wizard(snapshot)
    SetupWizardV5._poll_registration_result(wizard)
    wizard._show_registration_failure.assert_not_called()
    snapshot.update(status="registered", support_code="", request_in_progress=False)
    SetupWizardV5._poll_registration_result(wizard)
    wizard._registration_succeeded.assert_called_once()


def test_ui_deadline_without_result_keeps_observing():
    from v5_pages import SetupWizardV5
    wizard = _wizard({"status": "waiting_for_internet", "support_code": ""})
    SetupWizardV5._poll_registration_result(wizard)
    wizard._show_registration_failure.assert_not_called()
    wizard.registration_result_copy.setText.assert_called_once()


def test_cancelled_dialog_ignores_late_result():
    from v5_pages import SetupWizardV5
    wizard = _wizard({"status": "registered"})
    wizard._registration_in_progress = False
    SetupWizardV5._poll_registration_result(wizard)
    wizard._registration_succeeded.assert_not_called()
