"""Stable desktop application identity shared by Qt and Windows Shell."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)

APPLICATION_DISPLAY_NAME = "KOMI Report V5"
APPLICATION_ORGANIZATION = "Konica Minolta"
WINDOWS_APP_USER_MODEL_ID = "KonicaMinolta.KOMIReport.V5"


class QtApplicationIdentity(Protocol):
    """Qt application metadata used before the first window is constructed."""

    def setApplicationName(self, name: str) -> None: ...

    def setApplicationDisplayName(self, name: str) -> None: ...

    def setApplicationVersion(self, version: str) -> None: ...

    def setOrganizationName(self, name: str) -> None: ...


NativeAppIdSetter = Callable[[str], int]


def _native_windows_app_id_setter(app_id: str) -> int:
    """Call the Windows Shell API without importing Windows-only DLLs elsewhere."""

    import ctypes

    setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    setter.argtypes = [ctypes.c_wchar_p]
    setter.restype = ctypes.c_long
    return int(setter(app_id))


def configure_windows_process_identity(
    *,
    platform_name: str | None = None,
    native_setter: NativeAppIdSetter | None = None,
) -> bool:
    """Set the process AppUserModelID before Qt presents any Windows UI.

    Branding must never prevent the meter application from starting, so a
    missing Shell API is logged and treated as a non-fatal configuration miss.
    """

    platform_id = platform_name or sys.platform
    if not platform_id.startswith("win"):
        return True

    setter = native_setter or _native_windows_app_id_setter
    try:
        hresult = setter(WINDOWS_APP_USER_MODEL_ID)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        log.warning("cannot set Windows AppUserModelID: %s", exc)
        return False

    if hresult != 0:
        log.warning("Windows AppUserModelID returned HRESULT %s", hresult)
        return False
    return True


def configure_qt_application_identity(
    application: QtApplicationIdentity,
    *,
    version: str,
) -> None:
    """Replace Qt's default ``python`` executable identity with KOMI branding."""

    application.setApplicationName(APPLICATION_DISPLAY_NAME)
    application.setApplicationDisplayName(APPLICATION_DISPLAY_NAME)
    application.setApplicationVersion(version)
    application.setOrganizationName(APPLICATION_ORGANIZATION)
