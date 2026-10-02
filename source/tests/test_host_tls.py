"""Exercise the actual Host verifier; never install a test root in the OS."""
import ssl
from urllib.error import URLError
from urllib.request import Request

import pytest

from services import host_tls, registration_client, setup_connectivity, v5_2_client
from services.registration_errors import tls_verification_detail
from test_monitoring_tls import tls_server  # noqa: F401 - shared local TLS fixture


@pytest.mark.parametrize("tls_server", ["valid", "expired", "wrong_hostname", "untrusted"], indirect=True)
@pytest.mark.parametrize("consumer", ["diagnostic", "v52", "registration"])
def test_host_native_tls_rejects_invalid_peers_before_http(tls_server, consumer, monkeypatch):
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    context = host_tls.create_host_tls_context()
    if tls_server.scenario != "untrusted":
        context.load_verify_locations(cadata=tls_server.ca_pem)
    module = {"diagnostic": setup_connectivity, "v52": v5_2_client,
              "registration": registration_client}[consumer]
    monkeypatch.setattr(module, "create_host_tls_context", lambda: context)
    if consumer == "diagnostic":
        request = lambda: setup_connectivity._request_status(Request(tls_server.url, method="HEAD"), 3)
        errors = (URLError, ssl.SSLCertVerificationError)
    else:
        transport = (v5_2_client.UrllibV52Transport() if consumer == "v52"
                     else registration_client.UrllibRegistrationTransport())
        request = lambda: transport.request(url=tls_server.url, headers={}, body=b"{}", timeout=3).status
        errors = (v5_2_client.V52NetworkError, registration_client.NetworkTransportError)
    if tls_server.valid:
        assert request() == (405 if consumer == "diagnostic" else 200)
        assert tls_server.received == (["HEAD"] if consumer == "diagnostic" else ["POST"])
    else:
        with pytest.raises(errors):
            request()
        assert tls_server.received == []


def test_host_context_does_not_replace_global_or_lan_ssl():
    original = ssl.SSLContext
    context = host_tls.create_host_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert ssl.SSLContext is original
    assert type(ssl.create_default_context()) is original


@pytest.mark.parametrize("code,label", [(20, "issuer_not_found"), (10, "certificate_expired"),
    (0x800B0109, "untrusted_root"), (0x800B010F, "hostname_mismatch"), (9999, "certificate_validation_failed")])
def test_tls_diagnostic_only_exposes_numeric_code_and_fixed_label(code, label):
    error = ssl.SSLCertVerificationError("private company data must never appear")
    error.verify_code = code
    error.verify_message = "private certificate subject"
    def requester(*_args):
        raise URLError(error)
    report = setup_connectivity.check_setup_connectivity(
        resolver=lambda *_a, **_kw: [], requester=requester)
    text = report.support_text()
    assert not report.ok
    assert f"Verify code: {code}" in text
    assert label in text
    assert "private" not in text
    assert "TLS verifier: " + host_tls.host_tls_backend() in text


def test_tls_diagnostic_handles_circular_and_missing_errors():
    error = URLError("private")
    error.reason = error
    assert tls_verification_detail(error) == ""
    assert tls_verification_detail(ssl.SSLCertVerificationError("private")) == ""
