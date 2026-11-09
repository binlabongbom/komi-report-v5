import pytest

from komi_snmp_profiler.connectors import (
    WebConnectionAuthenticationError, WebCounterCollection,
)
from komi_snmp_profiler.credential_store import AdminCredential
from komi_snmp_profiler.device_profiles import (
    TlsCompatibility, WebMeterProtocol, resolve_device_meter_profile,
)
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.models import WebAuthState


@pytest.mark.parametrize('model', ['bizhub 287', 'KONICA MINOLTA bizhub 287', 'KM bizhub287'])
def test_exact_287_routes_to_admin_xml_without_legacy_tls_or_factory_passwords(model):
    profile = resolve_device_meter_profile(model)
    assert profile.profile_id == 'bizhub-287-admin-legacy-xml'
    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN
    assert profile.web_scheme == 'https'
    assert profile.tls_compatibility == TlsCompatibility.DEFAULT
    assert not profile.allow_factory_admin_credentials
    assert profile.preferred_total_oid == ''


@pytest.mark.parametrize('model', ['bizhub C287', 'bizhub 287i', 'bizhub 2870', 'Other 287'])
def test_287_profile_does_not_capture_other_models(model):
    assert resolve_device_meter_profile(model).profile_id == 'generic'


class Store:
    def __init__(self, credential=None):
        self.credential = credential

    def load(self, host):
        assert host == 'printer.invalid'
        return self.credential


class UnusedConnector:
    def collect_result(self, *args, **kwargs):
        raise AssertionError('No public or modern JSON probe is allowed for this profile')

    def collect_with_credential(self, *args, **kwargs):
        raise AssertionError('No unconfigured login attempt is allowed')


def test_287_without_configured_account_stops_before_any_login_or_public_probe():
    unused = UnusedConnector()
    reader = MeterReader(Store(), public_connector=unused, admin_connector=unused,
                         legacy_admin_connector=unused,
                         public_factory_credentials=(AdminCredential(password='synthetic-only'),))
    with pytest.raises(WebConnectionAuthenticationError) as got:
        reader.read('printer.invalid', model='bizhub 287')
    assert got.value.diagnostic_code == 'admin_required'
    assert 'ยังไม่ได้ลองเข้าสู่ระบบ' in str(got.value)


@pytest.mark.parametrize('rejected', [False, True])
def test_287_uses_only_the_configured_admin_account_once(rejected):
    credential = AdminCredential(password='synthetic-only')
    calls = []

    class Legacy:
        def collect_with_credential(self, host, account, *, scheme):
            calls.append((host, account, scheme))
            if rejected:
                raise WebConnectionAuthenticationError('synthetic rejection')
            return WebCounterCollection((), 'web_connection_legacy_xml_admin', WebAuthState.ADMIN)

    unused = UnusedConnector()
    reader = MeterReader(Store(credential), public_connector=unused, admin_connector=unused,
                         legacy_public_connector=unused, legacy_admin_connector=Legacy(),
                         public_factory_credentials=(AdminCredential(password='unused-synthetic'),))
    if rejected:
        with pytest.raises(WebConnectionAuthenticationError, match='synthetic rejection'):
            reader.read('printer.invalid', model='bizhub 287')
    else:
        result = reader.read('printer.invalid', model='bizhub 287')
        assert result.auth_state == WebAuthState.ADMIN
        assert result.source == 'web_connection_legacy_xml_admin'
    assert calls == [('printer.invalid', credential, 'https')]


@pytest.mark.parametrize('model', ['bizhub C368', 'bizhub C458'])
def test_existing_c368_c458_protocol_policy_is_unchanged(model):
    profile = resolve_device_meter_profile(model)
    assert profile.web_protocol == WebMeterProtocol.LEGACY_XML_ADMIN
    assert profile.tls_compatibility == TlsCompatibility.TLS11_LEGACY
    assert profile.allow_factory_admin_credentials
