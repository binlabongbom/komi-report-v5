from __future__ import annotations

from services import web_service


class _Process:
    def __init__(self) -> None:
        self.returncode = None
        self.terminated = 0

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def test_manager_starts_worker_from_shared_project_and_stops_with_desktop(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "source" / "tools").mkdir(parents=True)
    (project / "source" / "tools" / "web_service_worker.py").write_text("worker", encoding="utf-8")
    (project / "web").mkdir()
    (project / "web" / "package-lock.json").write_text("{}", encoding="utf-8")
    data_home = tmp_path / "data"
    process = _Process()
    calls = []
    monkeypatch.setattr(web_service, "app_data_home", lambda: data_home)
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(web_service.subprocess, "Popen", fake_popen)
    manager = web_service.WebServiceManager(project)
    status = manager.start()

    assert status.state == "starting"
    assert calls[0][0][1] == str(project / "source" / "tools" / "web_service_worker.py")
    assert calls[0][0][calls[0][0].index("--project-root") + 1] == str(project)
    assert calls[0][1]["cwd"] == project / "source"

    stopped = manager.stop()
    assert process.terminated == 1
    assert stopped.state == "stopped"


def test_status_detects_already_running_external_service(tmp_path, monkeypatch):
    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path)
    monkeypatch.setattr(web_service, "_port_open", lambda port: port in {3000, 8766})
    monkeypatch.setattr(web_service, "_lan_ip", lambda: "192.0.2.20")

    status = web_service.WebServiceManager(tmp_path / "project").status()

    assert status.state == "external"
    assert status.local_url == "https://127.0.0.1:3000"
    assert status.lan_url == "https://192.0.2.20:3000"


def test_manager_restarts_owned_worker(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "source" / "tools").mkdir(parents=True)
    (project / "source" / "tools" / "web_service_worker.py").write_text("worker", encoding="utf-8")
    (project / "web").mkdir()
    (project / "web" / "package-lock.json").write_text("{}", encoding="utf-8")
    processes = [_Process(), _Process()]
    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path / "data")
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)
    monkeypatch.setattr(web_service.subprocess, "Popen", lambda *_args, **_kwargs: processes.pop(0))
    manager = web_service.WebServiceManager(project)

    manager.start()
    status = manager.restart()

    assert status.state == "starting"
    assert len(processes) == 0
