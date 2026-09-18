"""Startup ordering tests using report doubles; no database or network reads."""

from types import SimpleNamespace

import pytest
from PyQt6.QtWidgets import QApplication

import app


@pytest.fixture(autouse=True)
def isolated_database():
    # Override the suite's database fixture: these orchestration tests need none.
    yield


def test_splash_starts_overview_without_opening_other_pages():
    events = []
    report = SimpleNamespace(prepare_overview=lambda: events.append("overview request"))
    window = SimpleNamespace(
        _reports_index=2,
        _load_deferred_page=lambda index: events.append(("load", index)) or report,
    )
    splash = SimpleNamespace(set_message=lambda message: events.append(message))

    app.MainWindow._prepare_reports_overview(window, splash)

    assert events == ["กำลังเตรียม Reports Overview...", ("load", 2), "overview request"]


def test_startup_refresh_completes_before_splash_report_prefetch():
    events = []
    report = SimpleNamespace(prepare_overview=lambda: events.append("overview request"))
    window = SimpleNamespace(
        _startup_refresh_pending=True,
        _reports_index=2,
        _refresh_all=lambda: events.append("initial refresh"),
        _load_deferred_page=lambda _index: report,
    )
    splash = SimpleNamespace(set_message=lambda _message: None)

    app.MainWindow._prepare_reports_overview(window, splash)

    assert events == ["initial refresh", "overview request"]
    assert window._startup_refresh_pending is False
    # Re-entering preparation must not invalidate the snapshot generation again.
    app.MainWindow._prepare_reports_overview(window, splash)
    assert events.count("initial refresh") == 1


def test_preparation_without_splash_preserves_deferred_initial_refresh():
    window = SimpleNamespace(
        _startup_refresh_pending=True,
        _reports_index=2,
        _load_deferred_page=lambda _index: object(),
    )

    app.MainWindow._prepare_reports_overview(window)

    assert window._startup_refresh_pending is True


@pytest.mark.parametrize("quitting", [False, True])
def test_report_jobs_shutdown_only_on_actual_exit(monkeypatch, quitting):
    events = []
    monkeypatch.setattr(app, "get_cfg", lambda *_args: "1")
    monkeypatch.setattr(app.QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
    window = SimpleNamespace(
        _quitting=quitting,
        _background_started=False,
        pg_history=SimpleNamespace(shutdown_report_loading=lambda: events.append("report shutdown")),
        tray=SimpleNamespace(showMessage=lambda *_args: None),
        polling=SimpleNamespace(stop=lambda: events.append("polling stop")),
        registration=SimpleNamespace(stop=lambda: None),
        web_service=SimpleNamespace(stop=lambda: None),
        hide=lambda: events.append("hidden"),
    )
    event = SimpleNamespace(
        accept=lambda: events.append("accepted"),
        ignore=lambda: events.append("ignored"),
    )

    app.MainWindow.closeEvent(window, event)

    assert events == (["report shutdown", "polling stop", "accepted"] if quitting else ["hidden", "ignored"])


def test_prewarm_yields_between_users_and_printers_and_only_schedules_once(monkeypatch):
    timers = []
    events = []

    class Timer:
        def __init__(self, parent):
            self.parent = parent
            self.timeout = SimpleNamespace(connect=lambda callback: setattr(self, "callback", callback))
            timers.append(self)

        def setSingleShot(self, value):
            assert value is True

        def start(self, delay):
            self.delay = delay

    monkeypatch.setattr(app, "QTimer", Timer)
    window = SimpleNamespace(_prewarm_reports_tab=lambda index: events.append(index))

    app.MainWindow._schedule_reports_prewarm(window)
    app.MainWindow._schedule_reports_prewarm(window)

    assert events == []  # scheduling must leave the UI event loop available
    assert len(timers) == 2
    assert 0 < timers[0].delay < timers[1].delay
    assert all(timer.parent is window for timer in timers)
    timers[0].callback()
    assert events == [1]
    timers[1].callback()
    assert events == [1, 2]


def test_prewarm_uses_loaded_report_and_stops_when_quitting():
    requested = []
    window = SimpleNamespace(
        pg_history=SimpleNamespace(prewarm_tab=requested.append),
        _quitting=False,
    )
    app.MainWindow._prewarm_reports_tab(window, 1)
    window._quitting = True
    app.MainWindow._prewarm_reports_tab(window, 2)
    assert requested == [1]


def test_show_schedules_after_window_is_visible():
    events = []
    window = SimpleNamespace(
        showMaximized=lambda: events.append("shown"),
        raise_=lambda: events.append("raised"),
        activateWindow=lambda: events.append("activated"),
        _schedule_reports_prewarm=lambda: events.append("scheduled"),
    )

    app.MainWindow._show_main_window(window)

    assert events == ["shown", "raised", "activated", "scheduled"]


def test_reports_open_hook_runs_after_navigation_and_refresh():
    events = []
    buttons = [SimpleNamespace(set_active=lambda _active: None) for _ in range(5)]
    # SimpleNamespace value equality would make every button match index zero.
    for index, button in enumerate(buttons):
        button.index = index
    window = SimpleNamespace(
        nav_btns=buttons,
        _settings_index=3,
        _deferred_pages={},
        _reports_index=2,
        _ui_ready=True,
        stack=SimpleNamespace(
            currentIndex=lambda: 0,
            setCurrentIndex=lambda index: events.append(("selected", index)),
        ),
        _load_deferred_page=lambda index: events.append(("load", index)),
        _refresh_visible_page=lambda: events.append("refresh"),
        pg_history=SimpleNamespace(on_reports_opened=lambda: events.append("opened")),
    )

    app.MainWindow._nav(window, buttons[2])

    assert events == [("selected", 2), "refresh", "opened"]


def test_missing_optional_report_interfaces_are_harmless():
    window = SimpleNamespace(
        _reports_index=2,
        _load_deferred_page=lambda _index: object(),
    )
    app.MainWindow._prepare_reports_overview(window)
    app.MainWindow._prewarm_reports_tab(window, 1)


def test_visible_reports_reuses_prefetched_generation(monkeypatch):
    events = []
    report = SimpleNamespace(
        refresh_visible_cached=lambda: events.append("cached"),
        refresh_visible=lambda: events.append("forced"),
        refresh=lambda: events.append("legacy"),
    )
    window = SimpleNamespace(
        stack=SimpleNamespace(currentIndex=lambda: 0),
        _dirty_pages={0},
        _page_widgets=[report],
    )
    monkeypatch.setattr(app, "apply_language", lambda _page: None)
    monkeypatch.setattr(app.QTimer, "singleShot", lambda _delay, callback: callback())

    app.MainWindow._refresh_visible_page(window)
    app.MainWindow._refresh_visible_page(window)

    assert events == ["cached"]
    assert not window._dirty_pages


def test_data_updates_invalidate_reports_before_visible_refresh(monkeypatch):
    events = []
    window = SimpleNamespace(
        _data=[None, None, None],
        _background_started=False,
        _page_widgets=[object(), object(), object()],
        _dirty_pages=set(),
        pg_history=SimpleNamespace(invalidate_data=lambda: events.append("invalidate")),
        _refresh_visible_page=lambda: events.append("refresh"),
        status_lbl=SimpleNamespace(setText=lambda _text: None),
    )
    monkeypatch.setattr(app, "get_last_two", lambda _index: (None, None))
    monkeypatch.setattr(app, "get_latest_read_date", lambda: None)

    app.MainWindow._refresh_all(window)

    assert events == ["invalidate", "refresh"]
    assert window._dirty_pages == {0, 1, 2}


def test_splash_uses_indeterminate_activity_without_percentage():
    qt_app = QApplication.instance() or QApplication([])
    splash = app.SplashScreen()
    try:
        splash.show()
        qt_app.processEvents()
        assert splash._activity.isVisible()
        assert splash._activity.minimum() == splash._activity.maximum() == 0
        assert splash._activity.isTextVisible() is False
        splash.set_message("กำลังเตรียม Reports Overview...")
        assert "Reports Overview" in splash._msg_lbl.text()
    finally:
        splash.close()
