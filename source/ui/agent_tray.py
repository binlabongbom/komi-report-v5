"""Small tray surface for the agent; never imports the desktop/report modules."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import subprocess
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu, QMessageBox, QSystemTrayIcon

from ui.quit_confirmation import confirm_meter_collection_exit
from database import get_db_path
from i18n import tr
from services.application_identity import load_application_icon


def launch_desktop() -> None:
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(root / "app.py"))
    environment = os.environ.copy()
    environment["KOMI_DB_PATH"] = str(Path(get_db_path()).resolve())
    subprocess.Popen(
        command, cwd=str(root), env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class AgentTray(QObject):
    def __init__(self, stop, *, open_desktop=launch_desktop, parent=None):
        super().__init__(parent)
        self._stop = stop
        self._open_desktop = open_desktop
        self._stopping = False
        self._dialog = None
        self.tray = QSystemTrayIcon(load_application_icon(), self)
        self.tray.setToolTip(tr("KOMI Report V5 · ทำงานเบื้องหลัง", "KOMI Report V5 · Background agent"))
        self.menu = QMenu()
        self.open_action = QAction(tr("เปิดโปรแกรม", "Open application"), self)
        self.open_action.triggered.connect(self.open)
        self.menu.addAction(self.open_action)
        self.menu.addSeparator()
        self.stop_action = QAction(tr("หยุดโปรแกรมทั้งหมด", "Stop everything"), self)
        self.stop_action.triggered.connect(self.confirm_stop)
        self.menu.addAction(self.stop_action)
        # Keep the desktop's macOS 27 workaround: clicking opens a small dialog
        # instead of showing the native status menu that crashes on that OS.
        try:
            self._dialog_menu = sys.platform == "darwin" and int((platform.mac_ver()[0] or "0").split(".")[0]) >= 27
        except ValueError:
            self._dialog_menu = False
        if not self._dialog_menu:
            self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self._launch_cooldown = QTimer(self)
        self._launch_cooldown.setSingleShot(True)
        self._launch_cooldown.timeout.connect(lambda: self.open_action.setEnabled(not self._stopping))

    def _activated(self, reason):
        if reason not in {QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick}:
            return
        if self._dialog_menu:
            if self._dialog is not None:
                self._dialog.raise_()
                return
            dialog = QMessageBox()
            self._dialog = dialog
            dialog.setWindowTitle("KOMI Report V5")
            dialog.setText(tr("โปรแกรมทำงานเบื้องหลัง", "The agent is running in the background"))
            open_button = dialog.addButton(self.open_action.text(), QMessageBox.ButtonRole.AcceptRole)
            stop_button = dialog.addButton(self.stop_action.text(), QMessageBox.ButtonRole.DestructiveRole)
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            def finished(_result):
                clicked = dialog.clickedButton()
                self._dialog = None
                dialog.deleteLater()
                if clicked is open_button:
                    self.open()
                elif clicked is stop_button:
                    self.confirm_stop()
            dialog.finished.connect(finished)
            dialog.open()
        else:
            self.open()

    def open(self):
        if self._stopping or not self.open_action.isEnabled():
            return
        try:
            self._open_desktop()
        except OSError:
            QMessageBox.warning(None, "KOMI Report V5", tr(
                "เปิดหน้าต่างหลักไม่สำเร็จ Agent ยังทำงานอยู่ กรุณาลองใหม่",
                "Could not open the desktop. The agent is still running. Please try again.",
            ))
            return
        # The desktop requests takeover after acquiring its own lock. Do not
        # stop collection here: the child may fail before it is ready.
        self.open_action.setEnabled(False)
        self._launch_cooldown.start(5000)

    def confirm_stop(self):
        if self._stopping:
            return
        if not confirm_meter_collection_exit():
            return
        self._stopping = True
        self.open_action.setEnabled(False)
        self.stop_action.setEnabled(False)
        self.tray.hide()
        self._stop()

    def close(self):
        self._launch_cooldown.stop()
        self.tray.hide()
        self.menu.close()
        if self._dialog is not None:
            self._dialog.reject()
