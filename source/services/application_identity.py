"""Stable desktop application identity shared by Qt and Windows Shell."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

APPLICATION_DISPLAY_NAME = "KOMI Report V5"
APPLICATION_ORGANIZATION = "Konica Minolta"
WINDOWS_APP_USER_MODEL_ID = "KonicaMinolta.KOMIReport.V5"
_APP_USER_MODEL_PROPERTY_FORMAT_ID = "9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"
_PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE = 3
_PKEY_APP_USER_MODEL_ID = 5


def application_icon_path() -> Path | None:
    """Return the first usable packaged icon path for the current runtime."""

    assets = Path(__file__).resolve().parents[1]
    for name in ("Logo.ico", "logo.png"):
        path = assets / name
        if path.is_file():
            return path
    return None


def load_application_icon():
    """Resolve the packaged multi-size icon independently of the working dir.

    PyInstaller preserves this module's path below its extraction directory;
    source/runtime installations use the same relative asset layout.
    """
    from PyQt6.QtGui import QIcon

    path = application_icon_path()
    if path is not None:
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon
    log.warning("KOMI application icon is missing from %s", Path(__file__).resolve().parents[1])
    return QIcon()


class QtApplicationIdentity(Protocol):
    """Qt application metadata used before the first window is constructed."""

    def setApplicationName(self, name: str) -> None: ...

    def setApplicationDisplayName(self, name: str) -> None: ...

    def setApplicationVersion(self, version: str) -> None: ...

    def setOrganizationName(self, name: str) -> None: ...


NativeAppIdSetter = Callable[[str], int]
NativeWindowPropertySetter = Callable[[int, dict[int, str]], int]


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


def _native_windows_window_property_setter(
    window_handle: int,
    values: dict[int, str],
) -> int:
    """Set AppUserModel window properties through the native IPropertyStore."""

    import ctypes
    import uuid
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = (
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        )

        @classmethod
        def parse(cls, value: str):
            raw = uuid.UUID(value).bytes_le
            return cls(
                int.from_bytes(raw[0:4], "little"),
                int.from_bytes(raw[4:6], "little"),
                int.from_bytes(raw[6:8], "little"),
                (ctypes.c_ubyte * 8).from_buffer_copy(raw[8:16]),
            )

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = (("fmtid", GUID), ("pid", wintypes.DWORD))

    class PROPVARIANT_VALUE(ctypes.Union):
        _fields_ = (
            ("pwszVal", ctypes.c_wchar_p),
            ("padding", ctypes.c_ubyte * 16),
        )

    class PROPVARIANT(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = (
            ("vt", wintypes.WORD),
            ("wReserved1", wintypes.WORD),
            ("wReserved2", wintypes.WORD),
            ("wReserved3", wintypes.WORD),
            ("value", PROPVARIANT_VALUE),
        )

    iid_property_store = GUID.parse("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")
    property_format = GUID.parse(_APP_USER_MODEL_PROPERTY_FORMAT_ID)
    property_store = ctypes.c_void_p()
    shell = ctypes.windll.shell32
    shell.SHGetPropertyStoreForWindow.argtypes = (
        wintypes.HWND,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
    )
    shell.SHGetPropertyStoreForWindow.restype = ctypes.c_long
    result = int(
        shell.SHGetPropertyStoreForWindow(
            wintypes.HWND(window_handle),
            ctypes.byref(iid_property_store),
            ctypes.byref(property_store),
        )
    )
    if result != 0 or not property_store.value:
        return result or -1

    vtable = ctypes.cast(
        property_store,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents
    method_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
    release = method_type(wintypes.ULONG, ctypes.c_void_p)(vtable[2])
    set_value = method_type(
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.POINTER(PROPERTYKEY),
        ctypes.POINTER(PROPVARIANT),
    )(vtable[6])
    commit = method_type(ctypes.c_long, ctypes.c_void_p)(vtable[7])
    try:
        for property_id, value in values.items():
            key = PROPERTYKEY(property_format, property_id)
            variant = PROPVARIANT()
            variant.vt = 31  # VT_LPWSTR
            variant.pwszVal = value
            result = int(
                set_value(property_store, ctypes.byref(key), ctypes.byref(variant))
            )
            if result != 0:
                return result
        return int(commit(property_store))
    finally:
        release(property_store)


def configure_windows_window_identity(
    window,
    *,
    platform_name: str | None = None,
    property_setter: NativeWindowPropertySetter | None = None,
) -> bool:
    """Bind one native window to KOMI's taskbar identity and icon.

    Qt correctly sets WM_GETICON, but Windows can still represent a window by
    the backing ``pythonw.exe`` when an explicit AppUserModelID has no relaunch
    icon property. Setting both window properties removes that fallback.
    """

    platform_id = platform_name or sys.platform
    if not platform_id.startswith("win"):
        return True
    icon = application_icon_path()
    if icon is None:
        log.warning("cannot set Windows taskbar identity: application icon is missing")
        return False
    try:
        window_handle = int(window.winId())
        setter = property_setter or _native_windows_window_property_setter
        hresult = setter(
            window_handle,
            {
                _PKEY_APP_USER_MODEL_ID: WINDOWS_APP_USER_MODEL_ID,
                _PKEY_APP_USER_MODEL_RELAUNCH_ICON_RESOURCE: f"{icon},0",
            },
        )
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        log.warning("cannot set Windows taskbar window identity: %s", exc)
        return False
    if hresult != 0:
        log.warning("Windows taskbar window identity returned HRESULT %s", hresult)
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
