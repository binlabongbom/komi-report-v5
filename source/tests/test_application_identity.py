from __future__ import annotations

from services.application_identity import (
    APPLICATION_DISPLAY_NAME,
    APPLICATION_ORGANIZATION,
    WINDOWS_APP_USER_MODEL_ID,
    configure_qt_application_identity,
    configure_windows_process_identity,
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


def test_qt_application_identity_does_not_fall_back_to_python() -> None:
    application = _FakeQtApplication()

    configure_qt_application_identity(application, version="5.2.5")

    assert application.values == {
        "name": APPLICATION_DISPLAY_NAME,
        "display_name": APPLICATION_DISPLAY_NAME,
        "version": "5.2.5",
        "organization": APPLICATION_ORGANIZATION,
    }
