"""Shared explicit quit choice for the desktop and background agent."""
from PyQt6.QtWidgets import QMessageBox
from i18n import tr


def confirm_meter_collection_exit(parent=None, *, tray_unavailable=False):
    message = tr(
        "แนะนำให้เปิดโปรแกรมทิ้งไว้เพื่อให้ระบบสามารถบันทึกมิเตอร์เครื่องได้ "
        "หากปิดโปรแกรม ระบบจะไม่สามารถแยกมิเตอร์ในช่วงเวลาดังกล่าวได้",
        "Keep the application running so it can record printer meters. If you quit, "
        "the system cannot separate meter usage for the time it is closed.",
    )
    if tray_unavailable:
        message = tr("ไม่พบ System Tray จึงไม่สามารถซ่อนหน้าต่างได้\n\n",
                     "No system tray is available, so the window cannot be hidden.\n\n") + message
    dialog = QMessageBox(parent)
    dialog.setWindowTitle(tr("ปิดโปรแกรม", "Quit application"))
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText(message)
    keep = dialog.addButton(tr("เปิดทำงานต่อ", "Keep running"), QMessageBox.ButtonRole.RejectRole)
    quit_button = dialog.addButton(tr("ปิดโปรแกรม", "Quit application"), QMessageBox.ButtonRole.DestructiveRole)
    dialog.setDefaultButton(keep)
    dialog.setEscapeButton(keep)
    dialog.exec()
    return dialog.clickedButton() is quit_button
