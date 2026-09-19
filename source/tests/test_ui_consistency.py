from PyQt6.QtWidgets import QApplication, QPushButton, QWidget
from PyQt6.QtTest import QTest
from time import monotonic

from config import BUTTON_HEIGHT, BUTTON_ICON_SIZE, BUTTON_LARGE_HEIGHT, BUTTON_LINK_HEIGHT
from ui_consistency import ButtonSystem, install_button_system


def test_button_system_normalizes_geometry_and_radius():
    app = QApplication.instance() or QApplication([])
    install_button_system(app)
    root = QWidget()
    standard = QPushButton("Save", root)
    standard.setFixedHeight(25)
    large = QPushButton("Choose a setup mode", root)
    large.setMinimumHeight(50)
    icon = QPushButton("⚙", root)
    icon.setFixedSize(30, 30)
    calendar = QPushButton("📅", root)
    calendar.setProperty("uiButtonRole", "compact-icon")
    export = QPushButton("Export to Excel", root)
    export.setProperty("uiButtonRole", "compact")
    link = QPushButton("Settings", root)
    link.setStyleSheet("background:transparent;border:none;text-decoration:underline;")

    for button in (standard, large, icon, calendar, export, link):
        button.show()
    root.show()
    app.processEvents()

    assert standard.height() == BUTTON_HEIGHT
    assert large.height() == BUTTON_LARGE_HEIGHT
    assert icon.width() == icon.height() == BUTTON_ICON_SIZE
    assert calendar.width() == calendar.height() == 24
    assert export.height() == 28
    assert link.height() == BUTTON_LINK_HEIGHT
    # Helper buttons must keep an empty local stylesheet so the application
    # primary and disabled selectors remain effective.
    assert standard.styleSheet() == ""
    assert "border-radius: 8px" in icon.styleSheet() or icon.styleSheet() == ""
    assert standard.graphicsEffect() is not None


def test_short_text_button_is_not_misclassified_from_temporary_width():
    _app = QApplication.instance() or QApplication([])
    button = QPushButton("OK")
    # Native QMessageBox buttons can briefly report this width before their
    # platform layout is complete.  Width alone must not turn a text action
    # into a square icon button.
    button.resize(20, 20)

    assert ButtonSystem._role(button) == "standard"


def test_import_primary_button_keeps_enabled_and_disabled_colors():
    from app import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.stack.setCurrentIndex(1)
    window.show()
    app.processEvents()
    button = window.pg_import.sync_button

    enabled_image = button.grab().toImage()
    assert enabled_image.pixelColor(10, 10).name() == "#0065a3"

    button.setEnabled(False)
    app.processEvents()
    disabled_image = button.grab().toImage()
    assert disabled_image.pixelColor(10, 10).name() == "#edf1f5"

    window._quitting = True
    window.close()


def test_heavy_pages_are_constructed_on_first_navigation():
    from app import MainWindow, _DeferredPage
    from pages import PageManual
    from v5_pages import PageHistoryV5, PageSettingsV5

    _app = QApplication.instance() or QApplication([])
    window = MainWindow()

    assert all(
        isinstance(window._page_widgets[index], _DeferredPage)
        for index in range(2, 5)
    )

    expected = (PageHistoryV5, PageSettingsV5, PageManual)
    for index, page_type in zip(range(2, 5), expected, strict=True):
        window._nav(window.nav_btns[index])
        deadline = monotonic() + 3
        while isinstance(window._page_widgets[index], _DeferredPage) and monotonic() < deadline:
            QTest.qWait(10)
        assert isinstance(window._page_widgets[index], page_type)

    window._quitting = True
    window.close()


def test_sidebar_navigation_warns_and_preserves_settings_draft(monkeypatch):
    import app as app_module

    qt_app = QApplication.instance() or QApplication([])
    window = app_module.MainWindow()
    window._nav(window.nav_btns[window._settings_index])
    deadline = monotonic() + 3
    while not hasattr(window.pg_settings, "fleet_content") and monotonic() < deadline:
        QTest.qWait(10)
    settings = window.pg_settings
    settings.fleet_content._set_active_editor("billing")
    settings.fleet_content.waste.setValue(8.5)
    assert settings.has_unsaved_changes()

    replies = iter(
        (
            app_module.QMessageBox.StandardButton.No,
            app_module.QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        app_module.QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(replies),
    )

    window._nav(window.nav_btns[0])
    assert window.stack.currentIndex() == window._settings_index
    assert settings.fleet_content.waste.value() == 8.5

    window._nav(window.nav_btns[0])
    assert window.stack.currentIndex() == 0
    assert settings.has_unsaved_changes()
    assert settings.fleet_content.waste.value() == 8.5

    settings.discard_unsaved_changes()
    window._quitting = True
    window.close()
    qt_app.processEvents()
