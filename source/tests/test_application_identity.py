from __future__ import annotations

from services.application_identity import (
    APPLICATION_DISPLAY_NAME,
    APPLICATION_ORGANIZATION,
    WINDOWS_APP_USER_MODEL_ID,
    configure_qt_application_identity,
    configure_windows_process_identity,
    configure_windows_window_identity,
    load_application_icon,
)


class _FakeQtApplication:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def setApplicationName(self, name: str) -> None:
        self.values["name"] = name

    def setApplicationDisplayName(self, name: str) -> None:
        self.values["display_name"] = name

    def setApplicationVersion(self, version: str) -> None:
        self.values["version"] = version

    def setOrganizationName(self, name: str) -> None:
        self.values["organization"] = name


def test_windows_process_identity_uses_stable_komi_app_id() -> None:
    calls: list[str] = []

    assert configure_windows_process_identity(
        platform_name="win32",
        native_setter=lambda app_id: calls.append(app_id) or 0,
    )
    assert calls == [WINDOWS_APP_USER_MODEL_ID]


def test_windows_process_identity_is_a_noop_on_other_platforms() -> None:
    calls: list[str] = []

    assert configure_windows_process_identity(
        platform_name="darwin",
        native_setter=lambda app_id: calls.append(app_id) or 0,
    )
    assert calls == []


def test_windows_process_identity_failure_does_not_block_startup() -> None:
    assert not configure_windows_process_identity(
        platform_name="win32",
        native_setter=lambda _app_id: -1,
    )


def test_windows_window_identity_sets_taskbar_app_id_and_icon() -> None:
    calls: list[tuple[int, dict[int, str]]] = []

    class Window:
        @staticmethod
        def winId() -> int:
            return 12345

    assert configure_windows_window_identity(
        Window(),
        platform_name="win32",
        property_setter=lambda hwnd, values: calls.append((hwnd, values)) or 0,
    )
    assert calls[0][0] == 12345
    assert calls[0][1][5] == WINDOWS_APP_USER_MODEL_ID
    assert calls[0][1][3].endswith("Logo.ico,0")


def test_windows_window_identity_is_a_noop_on_other_platforms() -> None:
    calls: list[object] = []

    assert configure_windows_window_identity(
        object(),
        platform_name="darwin",
        property_setter=lambda hwnd, values: calls.append((hwnd, values)) or 0,
    )
    assert calls == []


def test_qt_application_identity_does_not_fall_back_to_python() -> None:
    application = _FakeQtApplication()

    configure_qt_application_identity(application, version="5.2.5")

    assert application.values == {
        "name": APPLICATION_DISPLAY_NAME,
        "display_name": APPLICATION_DISPLAY_NAME,
        "version": "5.2.5",
        "organization": APPLICATION_ORGANIZATION,
    }


def test_window_icon_has_native_sizes_and_is_inherited_by_dialogs(tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QDialog

    app = QApplication.instance() or QApplication([])
    previous = app.windowIcon()
    monkeypatch.chdir(tmp_path)
    icon = load_application_icon()
    assert not icon.isNull()
    assert {16, 24, 32, 48, 256}.issubset({size.width() for size in icon.availableSizes()})
    try:
        app.setWindowIcon(icon)
        dialog = QDialog()
        assert dialog.windowIcon().cacheKey() == icon.cacheKey()
        for size in (16, 32, 48, 256):
            assert not dialog.windowIcon().pixmap(size, size).isNull()
        dialog.close()
    finally:
        app.setWindowIcon(previous)


def test_installer_shortcuts_use_the_running_app_identity():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    installer = (root / "packaging/windows/KOMI_Report_V5.iss").read_text(encoding="utf-8")
    assert f'#define AppUserModelId "{WINDOWS_APP_USER_MODEL_ID}"' in installer
    assert 'IconFilename: "{app}\\source\\Logo.ico"' in installer
