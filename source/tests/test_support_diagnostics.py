import errno
import ssl
from urllib.error import HTTPError, URLError

import pytest
from PyQt6.QtWidgets import QApplication, QMessageBox, QPushButton
from PyQt6.QtTest import QTest

from services.support_diagnostics import diagnose, diagnostic_report, safe_text, with_diagnostic
from komi_snmp_profiler.connectors import (
    WebConnectionError, WebConnectionAuthenticationError, WebConnectionSessionBusyError,
    WebConnectionTlsError,
)


@pytest.mark.parametrize('error,code', [
    (TimeoutError(), 'connection_timeout'),
    (ConnectionRefusedError(), 'connection_refused'),
    (ConnectionResetError(), 'connection_reset'),
    (PermissionError(errno.EACCES, 'denied'), 'file_permission'),
    (PermissionError('Peer rejected authorization'), 'access_denied'),
    (OSError(errno.ENOSPC, 'full'), 'disk_full'),
    (FileNotFoundError(), 'file_missing'),
    (WebConnectionAuthenticationError('rejected'), 'auth_rejected'),
    (WebConnectionSessionBusyError('busy'), 'session_busy'),
    (HTTPError('https://printer/',403,'',{},None), 'http_forbidden'),
    (HTTPError('https://printer/',404,'',{},None), 'endpoint_missing'),
    (HTTPError('https://printer/',407,'',{},None), 'proxy_auth'),
    (HTTPError('https://printer/',503,'',{},None), 'server_error'),
])
def test_failure_categories_do_not_guess_from_text(error, code):
    assert diagnose(error).code == code
    assert diagnose(RuntimeError('TLS password incorrect')).code == 'operation_failed'


def test_nested_tls_error_is_not_password_or_confirmed_disabled_pki():
    root = ssl.SSLError(1, 'TLS alert')
    wrapped = URLError(root)
    outer = WebConnectionError('failed')
    outer.__cause__ = wrapped
    diagnostic = diagnose(outer)
    assert diagnostic.code == 'tls_handshake'
    report = diagnostic.report(stage='WEB', target='printer:443')
    assert 'ไม่ยืนยันว่า PKI ปิดอยู่' in report
    assert 'User mode และ Admin mode' in report
    assert 'SSLError' in report
    host_report = diagnostic_report(outer, stage='HOST / API', computer='not collected')
    assert 'Code: host_tls_handshake' in host_report
    assert 'ไม่เกี่ยวกับ PKI' in host_report


def test_prior_auth_fallback_context_does_not_override_current_tls_failure():
    error = WebConnectionTlsError('failed on Admin request')
    error.__context__ = WebConnectionAuthenticationError('Public user requires Admin')
    assert diagnose(error).code == 'tls_handshake'


def test_unclassified_failure_preserves_sanitized_original_evidence():
    report = diagnostic_report(RuntimeError('parser field missing; token=private'), stage='parse')
    assert 'parser field missing' in report
    assert 'private' not in report
    assert 'Code: operation_failed' in report


def test_missing_worker_exception_does_not_crash_warning():
    assert 'Code: operation_failed' in with_diagnostic('Incomplete peer result', None, 'Sync')
    assert 'Incomplete peer result' in diagnostic_report('Incomplete peer result', stage='Sync')


def test_request_failure_captures_admin_route_without_post_body():
    from komi_snmp_profiler.connectors import ReadOnlyWebConnectionSession

    class FailingOpener:
        def open(self, request, timeout):
            raise URLError(ConnectionRefusedError())

    session = ReadOnlyWebConnectionSession('192.0.2.10')
    session.opener = FailingOpener()
    session._diagnostic_mode = 'Admin'
    with pytest.raises(WebConnectionError) as caught:
        session._request('login.cgi?token=private', method='POST', data=b'password=private')
    report = diagnostic_report(caught.value, stage='WEB')
    assert 'Code: connection_refused' in report
    assert 'request_mode=Admin' in report
    assert 'POST https://192.0.2.10' in report
    assert '/login.cgi' in report
    assert 'private' not in report


@pytest.mark.parametrize('number,expected', [
    (10,'certificate_expired'), (20,'certificate_trust'), (62,'certificate_name'),
    (23,'certificate_revoked'), (0x800B0101,'certificate_period'),
    (0x800B010F,'certificate_name'), (0x80092013,'certificate_revocation_unavailable'),
])
def test_certificate_verifier_code_survives_wrapping(number, expected):
    root = ssl.SSLCertVerificationError(1,'failed')
    root.verify_code = number
    wrapper = WebConnectionTlsError('failed')
    wrapper.__cause__ = URLError(root)
    diagnostic = diagnose(wrapper)
    assert diagnostic.code == expected
    assert f'verify_code={number}' in diagnostic.evidence


def test_persisted_diagnostic_keeps_code_and_does_not_expose_url_secrets():
    error = ConnectionRefusedError()
    error.diagnostic_endpoint = 'POST https://admin:password@printer:443/login.cgi?token=secret'
    text = diagnostic_report(error, stage='WEB', target=error.diagnostic_endpoint)
    assert diagnose(text).code == 'connection_refused'
    assert 'password' not in text and 'secret' not in text and 'token=' not in text
    assert 'printer:443/login.cgi' in text
    assert 'hunter2' not in safe_text('password=hunter2 community=private')


def test_pipeline_copied_failure_retains_evidence_and_reader():
    from services.pipeline_log import PipelineLogStore
    event = PipelineLogStore().append(stage='WEB',action='read',host='192.0.2.1',
                                     value=ConnectionRefusedError(),status='error')
    assert 'Code: connection_refused' in event.diagnostic
    assert '192.0.2.1' in event.diagnostic
    assert event.computer_name in event.diagnostic


_app = None

def test_warning_copy_does_not_close_dialog_and_preserves_typed_cause():
    global _app
    _app = QApplication.instance() or QApplication([])
    from ui.warning_diagnostics import install_warning_diagnostics
    install_warning_diagnostics(_app)
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle('Export failed')
    box.setText(with_diagnostic('Save failed', PermissionError(errno.EACCES, 'denied'), 'Export Excel'))
    box.show()
    QTest.qWait(40)
    button = box.findChild(QPushButton,'copy_warning_diagnostic')
    assert button is not None
    button.click()
    assert 'Code: file_permission' in QApplication.clipboard().text()
    assert 'Error Code: KOMI-FILE-001' in QApplication.clipboard().text()
    assert 'KOMI-FILE-001' in box.informativeText()
    assert box.isVisible()
    box.close()


def test_peer_errors_are_not_file_permission_or_printer_timeout():
    from services.peer_transport_factory import PeerRecoveryRequired
    from services.shared_web_read import SharedReadExpired
    assert diagnose(PeerRecoveryRequired('member_key_missing')).code == 'peer_recovery'
    assert diagnose(SharedReadExpired('job-1')).code == 'shared_read_expired'


@pytest.mark.parametrize('payload,expected', [
    (b'<form action="login.cgi"><input type="password"></form>', 'auth_rejected'),
    (b'authentication failed', 'auth_rejected'),
    (b'incorrect password', 'password_rejected'),
])
def test_only_explicit_password_rejection_is_reported_as_wrong_password(payload, expected):
    from komi_snmp_profiler.connectors import LegacyAuthenticatedWebConnectionCounterConnector
    with pytest.raises(WebConnectionAuthenticationError) as caught:
        LegacyAuthenticatedWebConnectionCounterConnector._raise_for_legacy_login_response(payload)
    assert diagnose(caught.value).code == expected
