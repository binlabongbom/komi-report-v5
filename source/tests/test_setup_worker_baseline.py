"""Test the worker-to-baseline identity boundary without printer/network access."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from komi_snmp_profiler.models import MeterReading, WebAuthState, WebCounterValue
from services.device_config import DeviceConfig
from services.setup_meter_baselines import SetupMeterBaselines
from ui.setup.workers import DeviceTestWorker


def result_reading(host):
    return MeterReading.create(host, [
        WebCounterValue("counter.total.total", "Total", 100, "Total", "fixture/total"),
        WebCounterValue("counter.print.total", "Print", 100, "Print", "fixture/print"),
        WebCounterValue("counter.print.full_color_total", "Print Color", 100, "Print", "fixture/print/color"),
        WebCounterValue("counter.print.bw_total", "Print B&W", 0, "Print", "fixture/print/bw"),
        WebCounterValue("counter.copy.total", "Copy", 0, "Copy", "fixture/copy"),
        WebCounterValue("counter.copy.full_color_total", "Copy Color", 0, "Copy", "fixture/copy/color"),
        WebCounterValue("counter.copy.bw_total", "Copy B&W", 0, "Copy", "fixture/copy/bw"),
    ], "synthetic-worker", WebAuthState.ADMIN)


def configure_worker_mocks(monkeypatch, *, wrong_host=None):
    monkeypatch.setattr("ui.setup.workers.SnmpTotalProbe.read", lambda *_args: SimpleNamespace(
        model="KONICA MINOLTA bizhub C450i", serial="FIXTURE-NEW-1", total=100,
        total_oid="1.2.3", oid_values=(("1.2.3", "100"),)))
    seen = []
    def read(_reader, host, **_kwargs):
        seen.append(host)
        return result_reading(wrong_host or host)
    monkeypatch.setattr("ui.setup.workers.MeterReader.read", read)
    return seen


def test_custom_web_port_result_binds_to_configured_host_for_meter_confirmation(monkeypatch):
    seen = configure_worker_mocks(monkeypatch)
    config = DeviceConfig(0, "Synthetic", "192.0.2.10")
    result = DeviceTestWorker([config], web_port=8443)._test(config)
    assert seen == ["192.0.2.10:8443"]
    assert result["meter_reading"].host == config.host
    verified = replace(config, serial=result["serial"])
    evidence = SetupMeterBaselines.capture(verified, result["meter_reading"])
    SetupMeterBaselines.validate_evidence(verified, evidence)


def test_custom_port_never_normalizes_an_unexpected_reading_host(monkeypatch):
    configure_worker_mocks(monkeypatch, wrong_host="192.0.2.99:8443")
    config = DeviceConfig(0, "Synthetic", "192.0.2.10")
    result = DeviceTestWorker([config], web_port=8443)._test(config)
    assert result["meter_reading"].host == "192.0.2.99:8443"
    with pytest.raises(ValueError, match="Serial"):
        SetupMeterBaselines.capture(replace(config, serial=result["serial"]), result["meter_reading"])


def test_standard_port_preserves_the_reading_and_connection_identity(monkeypatch):
    seen = configure_worker_mocks(monkeypatch)
    config = DeviceConfig(0, "Synthetic", "192.0.2.10")
    result = DeviceTestWorker([config])._test(config)
    assert seen == [config.host]
    assert result["meter_reading"].host == config.host
    assert result["tls_mode"] == "system"


@pytest.mark.parametrize("existing_history", [False, True])
def test_cached_serial_cannot_authorize_new_baseline_when_current_probe_failed(existing_history):
    from PyQt6.QtWidgets import QApplication
    from services.device_config import DeviceConfigRepository
    from ui.setup.wizard import SetupWizardV5
    from ui.setup.workers import DeviceTestResult

    app = QApplication.instance() or QApplication([])
    config = DeviceConfig(0, "Cached printer", "192.0.2.10", serial="CACHED-SERIAL",
        last_success_at="2026-09-01T00:00:00+00:00" if existing_history else None)
    DeviceConfigRepository().replace_all([config])
    wizard = SetupWizardV5(legacy_source_paths=[])
    wizard._test_result(DeviceTestResult(wizard._test_generation, config.host, 0,
        {"online": True, "web_ok": True, "serial": "", "model": "",
         "total": 100, "meter_reading": result_reading(config.host)}))
    assert not wizard._meter_evidence
    assert "Serial" in wizard.results[0]["meter_error"]
    wizard._refresh_meter_step()
    assert wizard._meter_step_required is not existing_history
    assert wizard.meter_step.ready is existing_history
    if not existing_history:
        assert not wizard.meter_step.confirmation.isEnabled()
    wizard.close()
    app.processEvents()
