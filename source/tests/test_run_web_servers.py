from __future__ import annotations

from tools import run_web_servers


def test_web_shortcut_opens_existing_service_without_starting_duplicate(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(run_web_servers, "_port_open", lambda _host, port: port in {3000, 8766})
    monkeypatch.setattr(run_web_servers.webbrowser, "open", opened.append)

    result = run_web_servers.run(tmp_path / "source", tmp_path / "runtime")

    assert result == 0
    assert opened == ["http://127.0.0.1:3000"]


def test_web_shortcut_refuses_half_running_service(tmp_path, monkeypatch):
    monkeypatch.setattr(run_web_servers, "_port_open", lambda _host, port: port == 3000)

    try:
        run_web_servers.run(tmp_path / "source", tmp_path / "runtime")
    except RuntimeError as error:
        assert "เพียงบางส่วน" in str(error)
    else:
        raise AssertionError("partial service must not start a duplicate")
