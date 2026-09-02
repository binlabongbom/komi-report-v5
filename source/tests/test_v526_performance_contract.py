from pathlib import Path


def _app_source() -> str:
    return (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")


def test_startup_paints_before_background_services():
    source = _app_source()
    body = source.split("def show_configured_application() -> None:", 1)[1].split("def cancel_first_setup()", 1)[0]
    assert body.index("win._show_main_window()") < body.index("win.start_background_services()")
    assert "QTimer.singleShot(0, finish_startup)" in body


def test_initial_database_refresh_is_deferred_until_after_first_paint():
    source = _app_source()
    constructor = source.split("class MainWindow(QMainWindow):", 1)[1].split("def _build_ui", 1)[0]
    assert "self._startup_refresh_pending = True" in constructor
    assert "self._refresh_all()  # ดึงข้อมูลจาก DB" not in constructor


def test_deferred_navigation_switches_host_before_page_construction():
    source = _app_source()
    nav = source.split("def _nav(self, clicked_btn: NavButton):", 1)[1].split("def _schedule_refresh_all", 1)[0]
    assert nav.index("self.stack.setCurrentIndex(idx)") < nav.index("QTimer.singleShot(0")
    assert "_finish_deferred_navigation" in nav
