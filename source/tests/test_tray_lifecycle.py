from __future__ import annotations

import app
import pytest


class _Event:
    def __init__(self) -> None:
        self.accepted = False
        self.ignored = False

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.ignored = True


class _Polling:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1


class _Registration(_Polling):
    def __init__(self) -> None:
        super().__init__()
        self.configuration_changes = 0
        self.network_recoveries = 0

    def configuration_changed(self) -> None:
        self.configuration_changes += 1

    def network_recovered(self) -> None:
        self.network_recoveries += 1


class _Tray:
    def __init__(self) -> None:
        self.messages: list[tuple] = []

    def showMessage(self, *args) -> None:
        self.messages.append(args)


class _WebService:
    def __init__(self) -> None:
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return type("Status", (), {"state": "starting", "detail": "test"})()

    def stop(self):
        self.stopped += 1


class _WindowDouble:
    _stop_ui_work = app.MainWindow._stop_ui_work
    def __init__(self) -> None:
        self._quitting = False
        self._background_started = False
        self.polling = _Polling()
        self.registration = _Registration()
        self.web_service = _WebService()
        self.tray = _Tray()
        self.hidden = 0
        self.maximized = 0
        self.raised = 0
        self.activated = 0
        self.allow_exit = True

    def hide(self) -> None:
        self.hidden += 1

    def showMaximized(self) -> None:
        self.maximized += 1

    def raise_(self) -> None:
        self.raised += 1

    def activateWindow(self) -> None:
        self.activated += 1

    def _show_main_window(self) -> None:
        app.MainWindow._show_main_window(self)

    def _apply_registration_collection_gate(self) -> None:
        pass

    def _confirm_discard_settings_on_exit(self) -> bool:
        return self.allow_exit


def test_shutdown_discards_late_refresh_requests_and_queued_page_callback(monkeypatch):
    from types import SimpleNamespace
    window = _WindowDouble()
    refreshed, callbacks, stopped = [], [], []
    window._refresh_timer = SimpleNamespace(start=lambda: refreshed.append("timer"), stop=lambda: stopped.append("refresh"))
    window._startup_poll_timer = SimpleNamespace(stop=lambda: stopped.append("startup"))
    window.pg_history = SimpleNamespace(shutdown_report_loading=lambda: stopped.append("reports"))
    window._dirty_pages = {0}
    window.stack = SimpleNamespace(currentIndex=lambda: 0)
    window._page_widgets = [SimpleNamespace(refresh_visible_cached=lambda: refreshed.append("page"))]
    monkeypatch.setattr(app, "apply_language", lambda page: None)
    monkeypatch.setattr(app.QTimer, "singleShot", lambda delay, callback: callbacks.append(callback))
    app.MainWindow._refresh_visible_page(window)
    window._quitting = True
    window._stop_ui_work()
    window._stop_ui_work()
    callbacks[0]()
    app.MainWindow._schedule_refresh_all(window)
    app.MainWindow._device_updated(window, 0)
    app.MainWindow._refresh_all(window)
    assert stopped == ["refresh", "startup", "reports"]
    assert refreshed == []


def test_close_hides_to_tray_without_stopping_polling(monkeypatch):
    window = _WindowDouble()
    event = _Event()
    monkeypatch.setattr(app.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)

    app.MainWindow.closeEvent(window, event)

    assert window.hidden == 1
    assert window.polling.stopped == 0
    assert window.registration.stopped == 0
    assert event.ignored is True
    assert event.accepted is False
    assert len(window.tray.messages) == 1


def test_close_really_exits_when_tray_is_unavailable(monkeypatch):
    window = _WindowDouble()
    event = _Event()
    monkeypatch.setattr(app.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)

    app.MainWindow.closeEvent(window, event)

    assert window.polling.stopped == 1
    assert window.registration.stopped == 1
    assert window.web_service.stopped == 1
    assert event.accepted is True


def test_source_close_waits_for_agent_without_hiding_or_stopping(monkeypatch):
    window = _WindowDouble()
    window._background_started = True
    handoffs = []
    window._begin_agent_handoff = lambda: handoffs.append(True)
    event = _Event()
    monkeypatch.setattr(app.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)
    app.MainWindow.closeEvent(window, event)
    assert handoffs == [True]
    assert window.hidden == window.polling.stopped == window.registration.stopped == 0
    assert event.ignored and not event.accepted


def test_handoff_confirmation_does_not_discard_draft_before_commit(monkeypatch):
    from types import SimpleNamespace
    window = _WindowDouble()
    discarded = []
    page = SimpleNamespace(discard_unsaved_changes=lambda: discarded.append(True))
    window._settings_page_with_draft = lambda: page
    monkeypatch.setattr(app.QMessageBox, "question", lambda *args: app.QMessageBox.StandardButton.Discard)
    assert app.MainWindow._confirm_discard_settings_on_exit(window, discard=False)
    assert not discarded
    assert app.MainWindow._confirm_discard_settings_on_exit(window)
    assert discarded == [True]


def test_reopening_window_cancels_uncommitted_handoff():
    from types import SimpleNamespace
    window = _WindowDouble()
    cancelled = []
    window._agent_handoff = SimpleNamespace(
        committed=False, cancel=lambda: cancelled.append(True), deleteLater=lambda: None,
    )
    app.MainWindow._show_from_tray(window)
    assert cancelled == [True]
    assert window._agent_handoff is None
    assert window.maximized == 1


def test_close_keeps_app_open_when_settings_draft_is_not_discarded(monkeypatch):
    window = _WindowDouble()
    window.allow_exit = False
    event = _Event()
    monkeypatch.setattr(app.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)

    app.MainWindow.closeEvent(window, event)

    assert window.polling.stopped == 0
    assert window.registration.stopped == 0
    assert window.web_service.stopped == 0
    assert event.ignored is True
    assert event.accepted is False


def test_background_start_is_idempotent_and_activation_restores_maximized_window():
    window = _WindowDouble()
    app.MainWindow.start_background_services(window)
    app.MainWindow.start_background_services(window)
    app.MainWindow._show_from_tray(window)

    assert window.polling.started == 1
    assert window.registration.started == 1
    assert window.registration.configuration_changes == 1
    assert window.web_service.started == 1
    assert (window.maximized, window.raised, window.activated) == (1, 1, 1)


def test_os_network_recovery_only_wakes_runtime_on_disconnected_to_connected_transition():
    window = _WindowDouble()
    window._last_network_reachability = app.QNetworkInformation.Reachability.Unknown

    app.MainWindow._network_reachability_changed(
        window, app.QNetworkInformation.Reachability.Online
    )
    app.MainWindow._network_reachability_changed(
        window, app.QNetworkInformation.Reachability.Site
    )
    app.MainWindow._network_reachability_changed(
        window, app.QNetworkInformation.Reachability.Disconnected
    )
    app.MainWindow._network_reachability_changed(
        window, app.QNetworkInformation.Reachability.Local
    )

    assert window.registration.network_recoveries == 2


def test_macos_27_uses_click_only_tray_to_avoid_status_menu_crash(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    monkeypatch.setattr(app.platform, "mac_ver", lambda: ("27.0", (0, 0, 0), ""))

    assert app._disable_tray_context_menu_for_current_macos() is True


def test_older_macos_keeps_the_context_menu(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    monkeypatch.setattr(app.platform, "mac_ver", lambda: ("26.6", (0, 0, 0), ""))

    assert app._disable_tray_context_menu_for_current_macos() is False


@pytest.mark.parametrize("confirm,discard,expected", [
    (False, True, 0), (True, False, 0), (True, True, 1),
])
def test_tray_stop_requires_confirmation_and_preserves_unsaved_draft(monkeypatch, confirm, discard, expected):
    window = _WindowDouble()
    window.allow_exit = discard
    questions, quits = [], []

    def question(*args):
        questions.append(args)
        return app.QMessageBox.StandardButton.Yes if confirm else app.QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(app.QMessageBox, "question", question)
    monkeypatch.setattr(app.QApplication, "instance", lambda: type("Application", (), {"quit": lambda self: quits.append(True)})())
    app.MainWindow._exit_application(window)
    assert questions[0][-1] == app.QMessageBox.StandardButton.Cancel
    assert window.polling.stopped == expected
    assert window.registration.stopped == expected
    assert window.web_service.stopped == expected
    assert len(quits) == expected
    assert window._quitting == bool(expected)
    if expected:
        app.MainWindow._exit_application(window)
        assert len(questions) == 1
        assert len(quits) == 1
