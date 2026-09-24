"""Prevent false-green CI results and accidental printer/Internet traffic."""

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tools" / "ci"
SPEC = importlib.util.spec_from_file_location("desktop_ci_runner", SUPPORT / "run_desktop_tests.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_batch_plan_preserves_every_case_without_repeating_qt_state():
    cases = [f"tests/test_sample.py::test_case[{index}]" for index in range(29)]
    plan = runner.batches(cases, 12)
    assert list(map(len, plan)) == [12, 12, 5]
    assert [node for batch in plan for node in batch] == cases
    with pytest.raises(ValueError):
        runner.batches([], 12)
    with pytest.raises(ValueError):
        runner.batches([cases[0], cases[0]], 12)


@pytest.mark.parametrize("process_code, report_code, executed, failed, expected", [
    (0, 0, ["first", "second"], 0, True),
    (0, 0, ["first"], 0, False),
    (0, 0, ["first", "second", "unplanned"], 0, False),
    (1, 0, ["first", "second"], 0, False),
    ("timeout", 0, ["first", "second"], 0, False),
    (0, 1, ["first", "second"], 0, False),
    (0, 0, ["first", "second"], 1, False),
])
def test_ci_does_not_pass_missing_crashed_or_failed_cases(process_code, report_code, executed, failed, expected):
    outcomes = {"exit_code": report_code, "executed_nodeids": executed, "counts": {"failed": failed}}
    assert runner.batch_complete(["first", "second"], {"exit_code": process_code}, outcomes) is expected


def test_custom_selection_cannot_escape_the_test_directory_or_include_release_builders():
    assert runner.discover_files(["test_report_models"])[0].name == "test_report_models.py"
    for selection in ("../../app", "test_release_builder", "missing_test"):
        with pytest.raises(ValueError):
            runner.discover_files([selection])
    with pytest.raises(ValueError):
        runner.discover_files(["test_report_models", "test_report_models.py"])


def test_runner_overrides_production_paths_before_collection(tmp_path, monkeypatch):
    monkeypatch.setenv("KOMI_DB_PATH", "production.sqlite3")
    monkeypatch.setenv("KOMI_APP_HOME", "production-home")
    monkeypatch.setenv("KOMI_V46_DATABASE", "production-legacy.sqlite3")
    monkeypatch.setenv("KOMI_UNEXPECTED_OVERRIDE", "production-value")
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k only_one_case")
    monkeypatch.setenv("PYTEST_PLUGINS", "untrusted_developer_plugin")
    env = runner.isolated_environment(tmp_path / "synthetic")
    assert "KOMI_DB_PATH" not in env
    config = tomllib.loads(Path(env["KOMI_RUNTIME_CONFIG"]).read_text(encoding="utf8"))
    assert Path(config["runtime"]["db_path"]).parent == tmp_path / "synthetic"
    assert Path(env["KOMI_APP_HOME"]) == tmp_path / "synthetic"
    assert env["KOMI_DISCOVERY_DISABLED"] == "1"
    assert env["KOMI_CI_NETWORK"] == "loopback"
    assert env["KOMI_PROJECT_ROOT"] == str(ROOT)
    assert Path(env["KOMI_V46_DATABASE"]).parent == tmp_path / "synthetic"
    assert not Path(env["KOMI_V46_DATABASE"]).exists()
    for name in ("USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"):
        assert Path(env[name]).is_relative_to(tmp_path / "synthetic")
        assert Path(env[name]).is_dir()
    for name in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "KOMI_UNEXPECTED_OVERRIDE"):
        assert name not in env
    assert os.environ["KOMI_DB_PATH"] == "production.sqlite3"
    assert os.environ["PYTEST_ADDOPTS"] == "-k only_one_case"


def test_network_guard_allows_loopback_but_blocks_external_dns_and_connections(tmp_path):
    script = """
import socket
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    with socket.create_connection(listener.getsockname(), timeout=1) as client:
        connection, _ = listener.accept()
        connection.close()
for operation in (
    lambda: socket.getaddrinfo('printer.example.invalid', 443),
    lambda: socket.create_connection(('198.51.100.1', 443), timeout=1),
    lambda: socket.socket().bind(('198.51.100.1', 0)),
    lambda: socket.socket(type=socket.SOCK_DGRAM).sendto(b'test', ('198.51.100.1', 443)),
):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError('Non-loopback traffic was not blocked')
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env=runner.isolated_environment(tmp_path / "network"),
        capture_output=True, text=True, encoding="utf8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_wildcard_udp_bind_is_restricted_to_loopback_and_local_discovery_still_works(tmp_path):
    script = """
import ipaddress
import socket
from local_network import install
install()  # Repeated installation must not recursively wrap bind.
addresses = [(socket.AF_INET, '0.0.0.0'), (socket.AF_INET, '')]
if socket.has_ipv6:
    addresses.extend([(socket.AF_INET6, '::'), (socket.AF_INET6, '')])
for family, host in addresses:
    with socket.socket(family, socket.SOCK_DGRAM) as listener:
        listener.bind((host, 0))
        listener.settimeout(1)
        assert ipaddress.ip_address(listener.getsockname()[0]).is_loopback
        with socket.socket(family, socket.SOCK_DGRAM) as sender:
            sender.sendto(b'local-only', listener.getsockname())
        assert listener.recvfrom(128)[0] == b'local-only'
"""
    result = subprocess.run(
        [sys.executable, "-c", script], env=runner.isolated_environment(tmp_path / "wildcard"),
        capture_output=True, text=True, encoding="utf8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_inherited_pytest_filters_cannot_hide_cases_from_collection_or_execution(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k selected")
    monkeypatch.setenv("PYTEST_PLUGINS", "nonexistent_developer_plugin")
    case = tmp_path / "test_unfiltered.py"
    case.write_text("def test_selected(): pass\ndef test_other(): pass\n", encoding="utf8")
    collection = tmp_path / "collection.json"
    outcomes = tmp_path / "outcomes.json"
    env = runner.isolated_environment(tmp_path / "unfiltered")
    env["KOMI_CI_COLLECTION"] = str(collection)
    env["KOMI_CI_OUTCOMES"] = str(outcomes)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "desktop_ci_plugin", str(case), "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf8", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    planned = json.loads(collection.read_text(encoding="utf8"))["nodeids"]
    evidence = json.loads(outcomes.read_text(encoding="utf8"))
    assert len(planned) == evidence["counts"]["passed"] == 2
    assert set(planned) == set(evidence["executed_nodeids"])


def test_pytest_evidence_distinguishes_pass_skip_xfail_failure_and_setup_error(tmp_path):
    case = tmp_path / "test_outcomes.py"
    case.write_text("""
import pytest
def test_pass(): pass
def test_skip(): pytest.skip('synthetic skip')
@pytest.mark.xfail(strict=True)
def test_xfail(): assert False
def test_failure(): assert False
@pytest.fixture
def broken(): raise RuntimeError('synthetic setup error')
def test_setup_error(broken): pass
""", encoding="utf8")
    outcome = tmp_path / "outcomes.json"
    env = runner.isolated_environment(tmp_path / "runtime")
    env["KOMI_CI_OUTCOMES"] = str(outcome)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "desktop_ci_plugin", str(case), "-q"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf8", timeout=40,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    evidence = json.loads(outcome.read_text(encoding="utf8"))
    assert evidence["counts"] == {"passed": 1, "failed": 1, "skipped": 1, "error": 1, "xfailed": 1, "xpassed": 0}
    assert len(evidence["executed_nodeids"]) == 5


@pytest.mark.parametrize("fail", [False, True])
def test_pytest_subtest_evidence_keeps_top_level_and_subtest_outcomes_separate(tmp_path, fail):
    case = tmp_path / "test_subtest_outcomes.py"
    case.write_text(f"""
import unittest
class Cases(unittest.TestCase):
    def test_subcases(self):
        for value in (1, 2):
            with self.subTest(value=value):
                assert not ({fail!r} and value == 2)
""", encoding="utf8")
    outcome = tmp_path / "outcomes.json"
    env = runner.isolated_environment(tmp_path / "subtests")
    env["KOMI_CI_OUTCOMES"] = str(outcome)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "desktop_ci_plugin", str(case), "-qq"],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf8", timeout=40,
    )
    assert result.returncode == int(fail), result.stdout + result.stderr
    evidence = json.loads(outcome.read_text(encoding="utf8"))
    # unittest reports its containing method as passed even when a subTest
    # failed; retain that fact, while the separate subtest failure fails CI.
    assert evidence["counts"]["passed"] == 1
    assert evidence["counts"]["failed"] == 0
    assert evidence["subtest_counts"]["passed"] == 2 - int(fail)
    assert evidence["subtest_counts"]["failed"] == int(fail)
    assert len(evidence["executed_nodeids"]) == 1
    assert runner.batch_complete(
        evidence["executed_nodeids"], {"exit_code": result.returncode}, evidence,
    ) is not fail
