from io import BytesIO
from urllib.error import HTTPError

import pytest

from komi_snmp_profiler.connectors import (
    ReadOnlyWebConnectionSession, TlsPolicy, WebConnectionCounterConnector,
    WebConnectionError, WebConnectionUnsupportedError,
)
from komi_snmp_profiler.models import WebAuthState
from services.support_diagnostics import diagnostic_report

TOTAL_XML = b'<MFP><UserCounterInfo><TotalCounterList><TotalCounter><Type>Total</Type><Count>42</Count></TotalCounter></TotalCounterList></UserCounterInfo></MFP>'


def connector_for(html, *, status=404, xml=TOTAL_XML):
    calls = []
    sessions = []

    class Session(ReadOnlyWebConnectionSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

            class Opener:
                def open(self, request, timeout):
                    calls.append((request.method, request.full_url, request.data))
                    if request.full_url.endswith('/index.html'):
                        return BytesIO(html)
                    if request.full_url.endswith('/system_counter.xml'):
                        return BytesIO(xml)
                    raise HTTPError(request.full_url, status, 'Synthetic response', {}, None)

            self.opener = Opener()

    return WebConnectionCounterConnector(session_factory=Session), calls, sessions


@pytest.mark.parametrize('link', [b'system_counter.xml', b'./system_counter.xml', b'/wcd/system_counter.xml'])
def test_advertised_public_counter_is_read_once_with_same_session_and_tls(link):
    connector, calls, sessions = connector_for(b'<a href="' + link + b'">Counter</a>')
    result = connector.collect_result('printer.invalid')
    assert result.source == 'web_connection_legacy_xml_public'
    assert result.auth_state == WebAuthState.PUBLIC
    assert [(v.canonical_field, v.count) for v in result.counters] == [('counter.total.total', 42)]
    assert [url for _, url, _ in calls] == [
        'https://printer.invalid/wcd/index.html',
        'https://printer.invalid/wcd/api/AppReqGetCustomData/_A-00-00001',
        'https://printer.invalid/wcd/system_counter.xml',
    ]
    assert all(method == 'GET' and data is None for method, _, data in calls)
    assert len(sessions) == 1 and sessions[0].tls_policy == TlsPolicy()
    assert len(sessions[0].cookies) == 0


@pytest.mark.parametrize('html', [
    b'<html>no advertised counter</html>',
    b'<a href="http://printer.invalid/wcd/system_counter.xml">Counter</a>',
    b'<a href="https://other.invalid/wcd/system_counter.xml">Counter</a>',
    b'<a href="//other.invalid/wcd/system_counter.xml">Counter</a>',
    b'<a href="a_system_counter.xml">Admin Counter</a>',
    b'<a href="system_counter.xml?admin=1">Counter</a>',
    b'<base href="https://other.invalid/"><a href="system_counter.xml">Counter</a>',
    b'<script>var path="system_counter.xml";</script>',
])
def test_missing_or_untrusted_advertisement_never_probes_legacy(html):
    connector, calls, _ = connector_for(html)
    with pytest.raises(WebConnectionUnsupportedError):
        connector.collect_result('printer.invalid')
    assert len(calls) == 2


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_only_missing_endpoint_can_use_advertised_counter(status):
    connector, calls, _ = connector_for(b'<a href="system_counter.xml">Counter</a>', status=status)
    with pytest.raises(WebConnectionError):
        connector.collect_result('printer.invalid')
    assert len(calls) == 2


def test_advertised_endpoint_must_return_valid_aggregate_counter():
    connector, calls, _ = connector_for(b'<a href="system_counter.xml">Counter</a>', xml=b'<html>Login</html>')
    with pytest.raises(WebConnectionError, match='aggregate Total Meter'):
        connector.collect_result('printer.invalid')
    assert len(calls) == 3 and all(method == 'GET' for method, _, _ in calls)


def test_printer_404_guidance_and_profile_evidence_are_separate_from_host_api():
    error = HTTPError('https://printer.invalid/wcd/api/example', 404, 'Not Found', {}, None)
    error.diagnostic_profile = 'generic'
    error.diagnostic_protocol = 'modern_json'
    report = diagnostic_report(error, stage='WEB / Setup', computer='synthetic')
    assert 'เปิดหน้า Counter ผ่านเมนูปกติ' in report
    assert 'ฝั่ง Host ต้องมี route API' not in report
    assert 'profile=generic' in report and 'protocol=modern_json' in report
    assert 'ยังไม่ยืนยันว่า firmware ไม่รองรับ' in report
    assert 'ฝั่ง Host ต้องมี route API' in diagnostic_report(error, stage='HOST / API', computer='synthetic')
