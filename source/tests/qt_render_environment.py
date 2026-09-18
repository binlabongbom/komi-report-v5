"""Match the packaged application's fonts when Qt offscreen has no OS fonts."""

import os
import sys
from pathlib import Path


def configure_offscreen_fonts(app):
    if sys.platform != "win32" or app.platformName() != "offscreen":
        return
    from PyQt6.QtGui import QFont, QFontDatabase
    from config import DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE

    if not QFontDatabase.families():
        fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "leelawui.ttf", "leelauib.ttf", "seguisym.ttf"):
            QFontDatabase.addApplicationFont(str(fonts / name))
    app.setFont(QFont(DEFAULT_FONT_NAME, DEFAULT_FONT_SIZE))
