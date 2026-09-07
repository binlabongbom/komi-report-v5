"""Desktop work-area and sidebar regressions, using the isolated test database."""

from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication, QStyle, QStyleOptionButton

import app as app_module
from config import SIDEBAR_WIDTH
from i18n import ENGLISH, THAI


@pytest.fixture
def window(monkeypatch):
    qt_app = QApplication.instance() or QApplication([])
    screen_type = type(qt_app.primaryScreen())
    monkeypatch.setattr(screen_type, "availableGeometry", lambda _screen: QRect(0, 24, 1440, 784))
    monkeypatch.setattr(app_module.MainWindow, "_build_tray", lambda view: setattr(view, "tray", SimpleNamespace()))
    monkeypatch.setattr(app_module.MainWindow, "_install_network_recovery_monitor", lambda _view: None)
    view = app_module.MainWindow()
    view.show()
    qt_app.processEvents()
    yield view
    view._quitting = True
    view.close()
    qt_app.processEvents()


def test_first_window_fits_available_workarea_with_native_frame(window):
    available = window.screen().availableGeometry()
    assert available.contains(window.frameGeometry())
    assert window.minimumHeight() <= 560


@pytest.mark.parametrize("language", [THAI, ENGLISH])
@pytest.mark.parametrize("width,sidebar_width", [(1024, 200), (1280, 200), (1440, SIDEBAR_WIDTH)])
def test_sidebar_text_and_footer_fit_at_both_sizes(window, language, width, sidebar_width):
    window.resize(width, 560)
    window.language_combo.setCurrentIndex(window.language_combo.findData(language))
    QApplication.processEvents()

    assert window.sidebar.width() == sidebar_width
    title = window._sidebar_logo_title
    assert title.fontMetrics().horizontalAdvance(title.text()) <= title.contentsRect().width()
    for button in window.nav_btns:
        option = QStyleOptionButton()
        option.initFrom(button)
        content = button.style().subElementRect(QStyle.SubElement.SE_PushButtonContents, option, button)
        assert button.fontMetrics().horizontalAdvance(button.text()) <= content.width(), button.text()
    assert window.status_lbl.geometry().bottom() <= window.sidebar.height()
    assert window.language_combo.geometry().bottom() < window.status_lbl.geometry().top()


def test_workarea_change_shrinks_and_repositions_existing_window(window, monkeypatch):
    window.resize(1380, 740)
    window.move(400, 300)
    available = QRect(0, 24, 1024, 614)
    monkeypatch.setattr(type(window.screen()), "availableGeometry", lambda _screen: available)

    window.screen().availableGeometryChanged.emit(available)
    QApplication.processEvents()

    assert available.contains(window.frameGeometry())
    assert window.minimumHeight() <= 560
    assert window.sidebar.width() == 200


def test_screen_change_rebinds_geometry_notifications(window):
    screen = window.screen()
    window._watch_layout_screen(None)
    window._watch_layout_screen(screen)
    window.resize(1280, 900)
    screen.availableGeometryChanged.emit(screen.availableGeometry())
    QApplication.processEvents()
    assert screen.availableGeometry().contains(window.frameGeometry())
