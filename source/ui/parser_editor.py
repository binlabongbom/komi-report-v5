"""Parser editor UI; owns its widgets and their lifecycle."""
from __future__ import annotations

from PyQt6.QtWidgets import QMessageBox

from services.support_diagnostics import with_diagnostic

_parser_editor_windows = []   # เก็บ reference ป้องกัน GC


def _open_check_parser():
    """เปิดหน้าต่าง Check Parser (ทำงานได้ทั้ง .py และ .exe)"""
    try:
        from tools.check_parser import ParserEditorWindow
        win = ParserEditorWindow()
        win.setAttribute(__import__('PyQt6.QtCore', fromlist=['Qt']).Qt.WidgetAttribute.WA_DeleteOnClose)
        _parser_editor_windows.append(win)
        win.destroyed.connect(lambda: _parser_editor_windows.remove(win)
                              if win in _parser_editor_windows else None)
        win.show()
    except Exception as e:
        QMessageBox.critical(None, "เปิด Check Parser ไม่ได้", with_diagnostic(str(e), e, "เปิด Check Parser ไม่ได้"))
