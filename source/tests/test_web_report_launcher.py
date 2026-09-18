from pathlib import Path

from PyQt6.QtWidgets import QApplication

from services.web_service import WebServiceStatus
from ui import web_report_launcher


class Service:
    def __init__(self):
        self.state = "starting"
        self.starts = 0

    def start(self):
        self.starts += 1

    def status(self):
        return WebServiceStatus(self.state, "https://127.0.0.1:3000", "https://192.0.2.10:3000", "status", Path("web.log"))


def test_web_shortcut_waits_for_service_and_opens_lan_once(monkeypatch):
    app = QApplication.instance() or QApplication([])
    service = Service()
    launcher = web_report_launcher.WebReportLauncher(service)
    opened = []
    monkeypatch.setattr(web_report_launcher.webbrowser, "open", opened.append)
    launcher.open()
    launcher.open()
    assert service.starts == 1
    assert not opened
    service.state = "running"
    launcher._check()
    assert opened == ["https://192.0.2.10:3000"]
    assert not launcher.timer.isActive()
    launcher.deleteLater()
    app.processEvents()


def test_failed_web_launch_stops_waiting_and_reports_log(monkeypatch):
    app = QApplication.instance() or QApplication([])
    service = Service()
    service.state = "failed"
    launcher = web_report_launcher.WebReportLauncher(service)
    failures = []
    launcher.failed.connect(failures.append)
    launcher.open()
    assert "web.log" in failures[0]
    assert not launcher.timer.isActive()
    launcher.deleteLater()
    app.processEvents()
