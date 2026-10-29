"""Synthetic protocol-routing checks, without device compatibility claims."""
import sqlite3
from dataclasses import replace

import pytest

from database import init_db, set_db_path
from komi_snmp_profiler.connectors import WebConnectionAuthenticationError, WebCounterCollection
from komi_snmp_profiler.credential_store import AdminCredential, SessionCredentialStore
from komi_snmp_profiler.device_profiles import resolve_device_meter_profile, TlsCompatibility
from komi_snmp_profiler.meter import MeterReader
from komi_snmp_profiler.models import WebAuthState
from migrations import _migration_035_web_protocol
from services.device_config import DeviceConfig, DeviceConfigRepository, DatabaseCredentialStore
from ui.setup.workers import device_test_key


class Never:
    def collect_result(self, *a, **kw):
        pytest.fail('Unexpected public/JSON read')

    def collect_with_credential(self, *a, **kw):
        pytest.fail('Unexpected login')


@pytest.mark.parametrize('model', ['bizhub 287', 'bizhub 367', 'bizhub 457', 'Future XML'])
@pytest.mark.parametrize('protocol', ['legacy_xml_public', 'legacy_xml_admin'])
def test_explicit_protocol_overrides_model_without_guessing_tls(model, protocol):
    profile = resolve_device_meter_profile(model, web_protocol=protocol)
    assert profile.web_protocol == protocol
    assert not profile.allow_factory_admin_credentials
    assert profile.tls_compatibility == TlsCompatibility.DEFAULT
    assert profile.web_scheme == 'https'


@pytest.mark.parametrize('model', ['bizhub 367', 'bizhub 457', 'Future XML'])
def test_unknown_auto_is_not_claimed_compatible(model):
    assert resolve_device_meter_profile(model).profile_id == 'generic'


def test_public_xml_never_uses_stored_admin_credentials():
    store = SessionCredentialStore()
    store.save('printer.invalid', AdminCredential(password='synthetic-only'))
    calls = []

    class Public:
        def collect_result(self, host, *, scheme):
            calls.append((host, scheme))
            return WebCounterCollection((), 'web_connection_legacy_xml_public', WebAuthState.PUBLIC)

    reader = MeterReader(store, public_connector=Never(), admin_connector=Never(),
                        legacy_admin_connector=Never(), legacy_public_connector=Public())
    result = reader.read('printer.invalid', model='bizhub 287', web_protocol='legacy_xml_public')
    assert result.auth_state == WebAuthState.PUBLIC
    assert calls == [('printer.invalid', 'https')]


@pytest.mark.parametrize('rejected', [False, True])
def test_explicit_admin_uses_single_selected_account_without_public_fallback(rejected):
    store = SessionCredentialStore()
    account = AdminCredential(password='synthetic-only')
    store.save('printer.invalid', account)
    calls = []

    class Admin:
        def collect_with_credential(self, host, credential, *, scheme):
            calls.append(credential)
            if rejected:
                raise WebConnectionAuthenticationError('synthetic rejection')
            return WebCounterCollection((), 'xml', WebAuthState.ADMIN)

    reader = MeterReader(store, public_connector=Never(), admin_connector=Never(),
                        legacy_admin_connector=Admin(), legacy_public_connector=Never())
    if rejected:
        with pytest.raises(WebConnectionAuthenticationError):
            reader.read('printer.invalid', model='bizhub 367', web_protocol='legacy_xml_admin')
    else:
        assert reader.read('printer.invalid', web_protocol='legacy_xml_admin').auth_state == WebAuthState.ADMIN
    assert calls == [account]


def test_explicit_admin_without_credentials_stops_before_network():
    reader = MeterReader(SessionCredentialStore(), public_connector=Never(), admin_connector=Never(),
                        legacy_admin_connector=Never(), legacy_public_connector=Never())
    with pytest.raises(WebConnectionAuthenticationError) as error:
        reader.read('printer.invalid', web_protocol='legacy_xml_admin')
    assert error.value.diagnostic_code == 'admin_required'


def test_protocol_survives_repository_restart_and_runtime_provider(tmp_path):
    set_db_path(tmp_path / 'synthetic.db')
    init_db()
    store = SessionCredentialStore()
    repo = DeviceConfigRepository(store)
    device = DeviceConfig(0, 'Synthetic', 'printer.invalid', web_protocol='legacy_xml_admin')
    repo.replace_all([device])
    restarted = DeviceConfigRepository(store)
    assert restarted.get(0).web_protocol == 'legacy_xml_admin'
    assert restarted.list()[0].web_protocol == 'legacy_xml_admin'
    reader = MeterReader(DatabaseCredentialStore(restarted), legacy_admin_connector=Never(),
                        public_connector=Never(), admin_connector=Never())
    with pytest.raises(WebConnectionAuthenticationError) as error:
        reader.read('printer.invalid', model='bizhub 457')
    assert error.value.diagnostic_code == 'admin_required'
    assert device_test_key(device) != device_test_key(replace(device, web_protocol='auto'))
    repo.replace_all([replace(device, web_protocol='auto')])
    assert restarted.get(0).web_protocol == 'auto'


def test_upgrade_preserves_old_device_and_defaults_auto():
    with sqlite3.connect(':memory:') as conn:
        conn.execute('CREATE TABLE devices(slot INTEGER, host TEXT)')
        conn.execute("INSERT INTO devices VALUES(0, 'printer.invalid')")
        _migration_035_web_protocol(conn)
        _migration_035_web_protocol(conn)
        assert conn.execute('SELECT * FROM devices').fetchone() == (0, 'printer.invalid', 'auto')


def test_invalid_protocol_rejected_before_network():
    with pytest.raises(ValueError):
        DeviceConfig(0, 'Synthetic', 'printer.invalid', web_protocol='guess_paths')
    with pytest.raises(ValueError):
        MeterReader(SessionCredentialStore()).read('printer.invalid', web_protocol='guess_paths')
