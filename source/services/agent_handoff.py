"""Two-phase desktop-to-agent handoff, using a private temporary rendezvous."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from time import monotonic

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from database import get_db_path
from services.autostart import launch_command


def clean_rendezvous(directory: Path) -> None:
    # Remove only our known protocol files; never recursively delete a path.
    for name in ("ready", "commit", "cancel"):
        (directory / name).unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


class AgentHandoff(QObject):
    ready = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.directory = Path(tempfile.mkdtemp(prefix="komi-agent-handoff-"))
        self.process = None
        self.committed = False
        self.cancelled = False
        self.ready_received = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.check)

    def start(self):
        if self.process is not None or self.cancelled:
            return
        self.deadline = monotonic() + 30
        environment = os.environ.copy()
        environment["KOMI_DB_PATH"] = str(Path(get_db_path()).resolve())
        try:
            self.process = subprocess.Popen(
                [*launch_command(), "--tray", "--handoff", str(self.directory)],
                env=environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            self.cancelled = True
            clean_rendezvous(self.directory)
            self.failed.emit("launch_failed")
            return
        self.timer.start()

    def check(self):
        if self.cancelled or self.committed or self.ready_received:
            return
        if self.process.poll() is not None:
            self.timer.stop()
            self.cancelled = True
            clean_rendezvous(self.directory)
            self.failed.emit("agent_exited")
        elif (self.directory / "ready").is_file():
            self.timer.stop()
            self.ready_received = True
            self.ready.emit()
        elif monotonic() >= self.deadline:
            self.cancel()
            self.failed.emit("timeout")

    def commit(self) -> bool:
        if self.committed:
            return True
        if self.cancelled or not self.ready_received:
            return False
        if self.process is None or self.process.poll() is not None:
            self.cancel()
            return False
        try:
            (self.directory / "commit").touch()
        except OSError:
            self.cancel()
            return False
        self.committed = True
        return True

    def cancel(self):
        self.timer.stop()
        if not self.committed:
            self.cancelled = True
            try:
                (self.directory / "cancel").touch()
            except OSError:
                pass
            if self.process is None or self.process.poll() is not None:
                clean_rendezvous(self.directory)
