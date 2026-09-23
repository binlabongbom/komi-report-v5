"""Startup dispatch through the real shell/coordinator, with no worker I/O."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from concurrent.futures import Future
from datetime import timedelta
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QStackedWidget, QWidget

import app
from services.background_polling import BackgroundPollingCoordinator
from services.device_config import DeviceConfig, DeviceConfigRepository


# Keep QApplication alive through process shutdown; native Windows Qt can
# crash when Python destroys it between function-scoped fixture instances.
_qt_app_keepalive = None


class _Registration(QObject):
    status_changed = pyqtSignal(str)

    def __init__(self, *_args, parent=None):
        super().__init__(parent)
        self.eligible = True
        self.reason = "registered"

    def usage_eligibility(self):
        return self.eligible, self.reason

    def start(self):
        pass

    def stop(self):
        pass

    def configuration_changed(self):
        pass

    def meter_observed(self, _slot):
        raise AssertionError("No meter result should be produced by these dispatch tests")


class _Page(QWidget):
    sync_requested = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.sync_button = QPushButton(self)
        self.btn_sync_now = self.sync_button

    def sync_completed(self):
        pass


class _NoDeviceIO:
    def read(self, *_args, **_kwargs):
        raise AssertionError("Startup tests must never read a printer")


class _CapturingExecutor:
    def __init__(self):
        self.requests = []
        self.futures = []

    def submit(self, _operation, device, force_web):
        self.requests.append((device.slot, force_web))
        future = Future()
        self.futures.append(future)
        return future

    def complete(self):
        for future in self.futures:
            if not future.done():
                future.set_result(False)

    def shutdown(self, **_kwargs):
        pass


def _settle():
    QApplication.processEvents()
    QTest.qWait(20)
    QApplication.processEvents()


@pytest.fixture
def startup_window(monkeypatch):
    global _qt_app_keepalive
    qt_app = QApplication.instance() or QApplication([])
    _qt_app_keepalive = qt_app
    repository = DeviceConfigRepository()
    repository.replace_all([
        DeviceConfig(0, "Synthetic A", "192.0.2.10"),
        DeviceConfig(1, "Synthetic B", "192.0.2.11"),
        DeviceConfig(2, "Disabled", "192.0.2.12", enabled=False),
    ])
    executor = _CapturingExecutor()

    def make_polling(*, parent):
        coordinator = BackgroundPollingCoordinator(
            repository, parent=parent, probe=_NoDeviceIO(), reader=_NoDeviceIO(),
        )
        coordinator.executor.shutdown(wait=False)
        coordinator.executor = executor
        return coordinator

    def build_ui(window):
        window.status_lbl = QLabel(window)
        window.pg_import = _Page(window)
        window.pg_overview = _Page(window)
        window.stack = QStackedWidget(window)
        window.stack.addWidget(window.pg_overview)
        window._page_widgets = [window.pg_overview]

    monkeypatch.setattr(app, "V52RuntimeCoordinator", _Registration)
    monkeypatch.setattr(app, "BackgroundPollingCoordinator", make_polling)
    monkeypatch.setattr(app, "load_offline_license_public_keys", lambda: {})
    monkeypatch.setattr(app, "web_service_manager", lambda: SimpleNamespace(
        start=lambda: SimpleNamespace(state="disabled", detail="synthetic"), stop=lambda: None,
    ))
    monkeypatch.setattr(app.MainWindow, "_build_ui", build_ui)
    monkeypatch.setattr(app.MainWindow, "_build_tray", lambda self: setattr(self, "tray", SimpleNamespace(hide=lambda: None)))
    monkeypatch.setattr(app.MainWindow, "_install_network_recovery_monitor", lambda self: None)
    monkeypatch.setattr(app.MainWindow, "_update_sidebar_layout", lambda self: None)
    monkeypatch.setattr(app.MainWindow, "_fit_to_available_screen", lambda self, **kwargs: None)
    window = app.MainWindow()
    yield window, executor
    window._quitting = True
    executor.complete()
    window.close()
    qt_app.processEvents()
    _settle()
    # Flush QObject destruction before monkeypatch restores the shell methods.
    # Closing a window only hides it; delayed native destruction between tests
    # can leave its child timers and signal callbacks alive on Windows.
    window._startup_poll_timer.stop()
    window._refresh_timer.stop()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


def test_startup_waits_for_configured_services_and_fresh_status_then_dispatches_once(startup_window, caplog):
    window, executor = startup_window
    window.registration.status_changed.emit("registered")
    _settle()
    assert executor.requests == []  # The setup path has not started services yet.
    window.start_background_services()
    _settle()
    assert executor.requests == []  # A persisted eligible state is not fresh status.
    with caplog.at_level("INFO", logger="app"):
        window.registration.status_changed.emit("registered")
        assert executor.requests == [], "Startup dispatch must yield to the Qt event loop"
        _settle()
        assert executor.requests == [(0, True), (1, True)]
        executor.complete()
        window.start_background_services()
        window.registration.status_changed.emit("registered")
        window.show()
        window.hide()
        window._refresh_all()
        window.show()
        _settle()
    # The independent 250 ms scheduled tick can fire while the window paints
    # on a slower VM. Only forced reads belong to this startup one-shot.
    assert [request for request in executor.requests if request[1]] == [(0, True), (1, True)]
    events = [record for record in caplog.records if getattr(record, "event", "") == "startup_sync_requested"]
    assert len(events) == 1


@pytest.mark.parametrize("reason", ["deactivated", "offline_license_expired", "registration_unavailable"])
def test_startup_stays_pending_while_ineligible_and_runs_once_on_reactivation(startup_window, reason):
    window, executor = startup_window
    window.start_background_services()
    window.registration.eligible = False
    window.registration.reason = reason
    window.registration.status_changed.emit(reason)
    _settle()
    assert executor.requests == []
    assert window.polling.is_paused
    window.registration.eligible = True
    window.registration.reason = "offline_license"
    window.registration.status_changed.emit("offline_license")
    _settle()
    assert executor.requests == [(0, True), (1, True)]


def test_startup_rechecks_eligibility_when_queued_status_is_revoked(startup_window):
    window, executor = startup_window
    window.start_background_services()
    window.registration.status_changed.emit("registered")
    window.registration.eligible = False
    window.registration.reason = "deactivated"
    _settle()
    assert executor.requests == []
    assert window.polling.is_paused
    window.registration.eligible = True
    window.registration.status_changed.emit("registered")
    _settle()
    assert executor.requests == [(0, True), (1, True)]


def test_quitting_cancels_queued_startup_dispatch(startup_window):
    window, executor = startup_window
    window.start_background_services()
    window.registration.status_changed.emit("registered")
    window._quitting = True
    _settle()
    assert executor.requests == []


@pytest.mark.parametrize("first_poll", ["manual", "scheduled"])
def test_startup_reuses_active_slot_guard_and_preserves_later_sync(startup_window, first_poll):
    window, executor = startup_window
    window.start_background_services()
    window.registration.status_changed.emit("registered")
    window.polling.machine.policy = SimpleNamespace(snmp_interval_at=lambda *_args: timedelta(minutes=5))
    if first_poll == "manual":
        window._request_manual_poll(0)
        assert executor.requests == [(0, True)]
    else:
        window.polling.tick()
        assert executor.requests == [(0, False), (1, False)]
    before = list(executor.requests)
    _settle()
    expected = before + ([(1, True)] if first_poll == "manual" else [])
    assert executor.requests == expected
    window.polling.tick()
    assert executor.requests == expected
    executor.complete()
    window._request_manual_poll(1)
    assert executor.requests[-1] == (1, True)
    executor.complete()
    window.polling.last_poll.clear()
    window.polling.tick()
    assert executor.requests[-2:] == [(0, False), (1, False)]
