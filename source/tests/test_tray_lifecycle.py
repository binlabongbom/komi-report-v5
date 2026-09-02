from __future__ import annotations

import app


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
