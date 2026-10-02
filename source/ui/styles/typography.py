"""Qt font construction using the shared platform-aware tokens."""

from PyQt6.QtGui import QFont

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
