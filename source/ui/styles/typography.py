"""Qt font construction using the shared platform-aware tokens."""

from PyQt6.QtGui import QFont, QFontDatabase

from . import tokens


def fnt(size: int = tokens.F_LG, bold: bool = False, mono: bool = False) -> QFont:
    """
    สร้าง QFont — cross-platform (Windows/macOS/Linux)
    mono=True ใช้ฟอนต์ตระกูล monospace สำหรับตัวเลข
    """
    family = tokens.MONO_FONT_FAMILY if mono else tokens.UI_FONT_FAMILY
    f = QFont(family, size)
    if bold:
        f.setBold(True)
    return f


def windows_settings_font_family() -> str | None:
    """Prefer one installed Thai UI font for whole Settings text runs on Windows."""
    if not tokens.IS_WINDOWS:
        return None
    installed = {name.casefold() for name in QFontDatabase.families(QFontDatabase.WritingSystem.Thai)}
    return next(
        (family for family in ("Leelawadee UI", "Noto Sans Thai", "Tahoma") if family.casefold() in installed),
        None,
    )
