from __future__ import annotations

from tools import run_web_servers


def test_web_shortcut_opens_existing_service_without_starting_duplicate(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(run_web_servers, "_port_open", lambda _host, port: port in {3000, 8766})
    monkeypatch.setattr(run_web_servers, "_https_open", lambda _host, port: port == 3000)
    monkeypatch.setattr(run_web_servers.webbrowser, "open", opened.append)

    result = run_web_servers.run(tmp_path / "source", tmp_path / "runtime")

    assert result == 0
    assert opened == ["https://127.0.0.1:3000"]


def test_web_shortcut_refuses_half_running_service(tmp_path, monkeypatch):
    monkeypatch.setattr(run_web_servers, "_port_open", lambda _host, port: port == 3000)
    monkeypatch.setattr(run_web_servers, "_https_open", lambda _host, _port: False)

    try:
        run_web_servers.run(tmp_path / "source", tmp_path / "runtime")
    except RuntimeError as error:
        assert "เพียงบางส่วน" in str(error)
    else:
        raise AssertionError("partial service must not start a duplicate")


def test_standalone_runtime_requires_node_not_npm(tmp_path, monkeypatch):
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    source.mkdir()
    (runtime / ".next").mkdir(parents=True)
    (runtime / ".next" / "BUILD_ID").write_text("build\n", encoding="utf-8")
    (runtime / "server.js").write_text("server\n", encoding="utf-8")
    monkeypatch.setattr(run_web_servers, "_port_open", lambda *_args: False)
    monkeypatch.setattr(run_web_servers, "_https_open", lambda *_args: False)
    monkeypatch.setattr(run_web_servers.shutil, "which", lambda name: None)

    try:
        run_web_servers.run(source, runtime, open_browser=False)
    except RuntimeError as error:
        assert "Node.js runtime" in str(error)
    else:
        raise AssertionError("standalone runtime without node must fail closed")


def test_web_shortcut_uses_persisted_custom_https_port(tmp_path, monkeypatch):
    from services.web_access import update_web_runtime_values

    opened = []
    runtime = tmp_path / "runtime"
    update_web_runtime_values(runtime / ".env.local", {"KOMI_WEB_PORT": "3443"})
    monkeypatch.setattr(run_web_servers, "_port_open", lambda _host, port: port in {3443, 8766})
    monkeypatch.setattr(run_web_servers, "_https_open", lambda _host, port: port == 3443)
    monkeypatch.setattr(run_web_servers.webbrowser, "open", opened.append)
    assert run_web_servers.run(tmp_path / "source", runtime) == 0
    assert opened == ["https://127.0.0.1:3443"]


def test_source_worker_passes_runtime_access_and_custom_port_to_next(tmp_path, monkeypatch):
    from services.web_access import update_web_runtime_values

    runtime = tmp_path / "runtime"
    (runtime / ".next").mkdir(parents=True)
    (runtime / ".next" / "BUILD_ID").write_text("build")
    update_web_runtime_values(runtime / ".env.local", {
        "KOMI_WEB_PORT": "3443", "KOMI_WEB_REPORT_PASSWORDLESS": "1",
    })
    monkeypatch.setattr(run_web_servers, "_port_open", lambda *_args: False)
    monkeypatch.setattr(run_web_servers.shutil, "which", lambda name: name)
    monkeypatch.setattr(run_web_servers, "_wait_for_port", lambda *_args: None)
    monkeypatch.setattr(run_web_servers, "_process_alive", lambda _pid: False)
    calls = []
    ready_ports = []

    class Process:
        returncode = None
        def poll(self):
            return self.returncode
        def terminate(self):
            self.returncode = 0
        def wait(self, timeout):
            return self.returncode

    def popen(command, **kwargs):
        calls.append((command, dict(kwargs["env"])))
        return Process()

    monkeypatch.setattr(run_web_servers.subprocess, "Popen", popen)
    monkeypatch.setattr(run_web_servers, "_wait_for_https", lambda _host, port, _process: ready_ports.append(port))
    assert run_web_servers.run(tmp_path / "source", runtime, open_browser=False, parent_pid=123) == 0
    assert calls[1][1]["KOMI_WEB_PORT"] == "3443"
    assert calls[1][1]["KOMI_WEB_REPORT_PASSWORDLESS"] == "1"
    assert ready_ports == [3443]
