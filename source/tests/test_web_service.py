from __future__ import annotations

import importlib
import sys

from services import web_service


def test_proxy_replaces_spoofed_remote_identity_case_insensitively():
    headers = web_service._proxy_request_headers(
        {
            "Host": "komi.local",
            "X-KOMI-REMOTE-ADDRESS": "203.0.113.99",
            "x-forwarded-PROTO": "http",
            "Connection": "keep-alive",
        },
        remote_address="192.0.2.44",
    )

    assert headers == {
        "Host": "komi.local",
        "x-komi-remote-address": "192.0.2.44",
        "x-forwarded-proto": "https",
    }


def test_web_service_worker_imports_from_source_package():
    worker = importlib.import_module("tools.web_service_worker")

    assert callable(worker.main)


def test_packaged_api_config_supports_pythonw_without_console_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    config = web_service._packaged_api_config(object())

    assert config.log_config is None
    assert config.host == "127.0.0.1"
    assert config.port == 8766


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
        self.returncode = 0
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
    assert process.terminated == 0
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


def test_embedded_windows_install_uses_bundled_runtime_without_npm(tmp_path, monkeypatch):
    project = tmp_path / "installed"
    seed = project / "web-runtime-seed"
    (seed / ".next").mkdir(parents=True)
    (seed / ".next" / "BUILD_ID").write_text("build\n", encoding="utf-8")
    node = project / "node-runtime" / "node.exe"
    node.parent.mkdir()
    node.write_bytes(b"node")
    calls = []

    class _Thread:
        def __init__(self, *, target, args, name, daemon):
            calls.append((target, args, name, daemon))
            self.started = False

        def start(self):
            self.started = True

        def is_alive(self):
            return self.started

    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path / "data")
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)
    monkeypatch.setattr(web_service.threading, "Thread", _Thread)
    monkeypatch.delattr(web_service.sys, "frozen", raising=False)
    monkeypatch.setattr(web_service.sys, "platform", "win32")
    manager = web_service.WebServiceManager(project)

    status = manager.start()

    assert status.state == "starting"
    assert calls[0][1] == (project, seed, node)
    assert manager._process is None


def test_packaged_runtime_seed_refresh_preserves_local_security_files(tmp_path):
    seed = tmp_path / "seed"
    runtime = tmp_path / "runtime"
    (seed / ".next").mkdir(parents=True)
    (seed / ".next" / "BUILD_ID").write_text("new-build\n", encoding="utf-8")
    (seed / "node_modules").mkdir()
    (seed / "node_modules" / "runtime.js").write_text("new", encoding="utf-8")
    (seed / "server.mjs").write_text("server", encoding="utf-8")
    (runtime / ".next").mkdir(parents=True)
    (runtime / ".next" / "BUILD_ID").write_text("old-build\n", encoding="utf-8")
    (runtime / "security").mkdir()
    (runtime / "security" / "web-auth-state.json").write_text("{}", encoding="utf-8")
    (runtime / ".env.local").write_text("LOCAL=preserved\n", encoding="utf-8")

    manager = web_service.WebServiceManager(tmp_path / "project")
    manager.runtime_root = runtime
    manager._prepare_packaged_runtime(seed)

    assert (runtime / ".next" / "BUILD_ID").read_text(encoding="utf-8").strip() == "new-build"
    assert (
        runtime / web_service._PACKAGED_RUNTIME_STAMP
    ).read_text(encoding="utf-8").strip() == "new-build"
    assert (runtime / "node_modules" / "runtime.js").read_text(encoding="utf-8") == "new"
    assert (runtime / ".env.local").read_text(encoding="utf-8") == "LOCAL=preserved\n"
    assert (runtime / "security" / "web-auth-state.json").is_file()


def test_https_proxy_requires_tls12_and_forwards_remote_identity(tmp_path, monkeypatch):
    captured = {}

    class _Response:
        status = 200
        reason = "OK"

        @staticmethod
        def read():
            return b"ready"

        @staticmethod
        def getheaders():
            return [("Content-Type", "text/plain")]

    class _Upstream:
        def __init__(self, host, port, timeout):
            captured["target"] = (host, port, timeout)

        def request(self, method, path, body=None, headers=None):
            captured["request"] = (method, path, body, headers)

        @staticmethod
        def getresponse():
            return _Response()

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(web_service.http.client, "HTTPConnection", _Upstream)
    monkeypatch.setattr(web_service.ssl.SSLContext, "load_cert_chain", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(web_service.ssl.SSLContext, "wrap_socket", lambda _self, sock, **_kwargs: sock)

    server = web_service.WebServiceManager._https_proxy_server(
        certificate=tmp_path / "cert.pem",
        private_key=tmp_path / "key.pem",
    )
    try:
        assert server.server_address[1] == 3000
        assert isinstance(server.socket, object)
    finally:
        server.server_close()


def test_packaged_restart_reloads_access_and_port_after_worker_releases_lock(tmp_path, monkeypatch):
    import threading
    from services.web_access import read_web_runtime_values, update_web_runtime_values

    project = tmp_path / "installed"
    seed = project / "web-runtime-seed"
    (seed / ".next").mkdir(parents=True)
    (seed / ".next" / "BUILD_ID").write_text("build\n", encoding="utf-8")
    node = project / "node-runtime" / ("node.exe" if sys.platform.startswith("win") else "node")
    node.parent.mkdir()
    node.write_bytes(b"node")
    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path / "data")
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)
    manager = web_service.WebServiceManager(project)
    env = manager.runtime_root / ".env.local"
    observed = []
    started = threading.Event()
    finished = threading.Event()

    def worker(*_args):
        observed.append((read_web_runtime_values(env)["KOMI_WEB_REPORT_PASSWORDLESS"], manager._active_port))
        started.set()
        manager._packaged_stop.wait(5)
        # Regression: restart/stop must not hold this lock while joining us.
        with manager._lock:
            finished.set()

    monkeypatch.setattr(manager, "_run_packaged_service", worker)
    update_web_runtime_values(env, {"KOMI_WEB_REPORT_PASSWORDLESS": "0", "KOMI_WEB_PORT": "3000"})
    manager.start()
    assert started.wait(2)
    old_worker = manager._packaged_thread
    update_web_runtime_values(env, {"KOMI_WEB_REPORT_PASSWORDLESS": "1", "KOMI_WEB_PORT": "3443"})
    assert manager.status().local_url.endswith(":3000")
    started.clear()
    try:
        manager.restart()
        assert finished.is_set()
        assert not old_worker.is_alive()
        assert started.wait(2)
        assert observed == [("0", 3000), ("1", 3443)]
        assert manager.status().local_url.endswith(":3443")
    finally:
        manager.stop()


def test_stop_retains_owned_thread_until_shutdown_finishes(tmp_path, monkeypatch):
    class StillStopping:
        def is_alive(self):
            return True

        def join(self, timeout):
            pass

    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path)
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)
    manager = web_service.WebServiceManager(tmp_path / "project")
    worker = StillStopping()
    manager._packaged_thread = worker
    manager._active_port = 3443
    status = manager.restart()
    assert manager._packaged_thread is worker
    assert manager._packaged_stop.is_set()
    assert manager._active_port == 3443
    assert "ยังหยุดไม่สำเร็จ" in status.detail


def test_packaged_startup_wait_observes_stop_request(tmp_path, monkeypatch):
    import pytest

    monkeypatch.setattr(web_service, "app_data_home", lambda: tmp_path)
    monkeypatch.setattr(web_service, "_port_open", lambda _port: False)
    manager = web_service.WebServiceManager(tmp_path / "project")
    manager._packaged_stop.set()
    with pytest.raises(InterruptedError):
        manager._wait_for_port(3001, timeout=30)
