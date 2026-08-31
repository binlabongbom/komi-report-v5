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
