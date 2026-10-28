"""Discover desktop tests and run small fresh pytest processes on Windows/Qt.

The runner never builds installers or reads a saved production data directory.
JSON collection, per-batch outcomes and JUnit XML make omitted/crashed cases
visible, including when pytest itself exits before producing a test summary.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "source"
TESTS = SOURCE / "tests"
SUPPORT = Path(__file__).resolve().parent
EXCLUDED_FILES = {
    "test_phase4_release_candidate.py": "Release artifact assembly belongs to release validation.",
    "test_phase5_pilot_release.py": "Release artifact assembly belongs to release validation.",
    "test_phase6_customer_release.py": "Release artifact assembly belongs to release validation.",
    "test_release_builder.py": "Release packaging is outside the desktop regression job.",
    "test_prepare_web_runtime.py": "Web runtime packaging is outside the desktop regression job.",
}
OUTCOME_NAMES = ("passed", "failed", "skipped", "error", "xfailed", "xpassed")


def discover_files(selected: list[str] | None = None) -> list[Path]:
    available = {
        path.relative_to(TESTS).as_posix(): path
        for path in sorted(TESTS.rglob("test_*.py"))
        if path.name not in EXCLUDED_FILES
    }
    if not selected:
        return list(available.values())
    found = []
    for name in selected:
        normalized = name.replace("\\", "/")
        if normalized.startswith("source/tests/"):
            normalized = normalized.removeprefix("source/tests/")
        elif normalized.startswith("tests/"):
            normalized = normalized.removeprefix("tests/")
        if not normalized.endswith(".py"):
            normalized += ".py"
        if normalized not in available:
            raise ValueError(f"Unknown desktop test file: {name}")
        found.append(available[normalized])
    if len(found) != len(set(found)):
        raise ValueError("Select each test file only once")
    return found


def batches(nodeids: list[str], size: int) -> list[list[str]]:
    if not 1 <= size <= 100:
        raise ValueError("Batch size must be between 1 and 100")
    if not nodeids or len(nodeids) != len(set(nodeids)):
        raise ValueError("Collection must contain unique test cases and cannot be empty")
    return [nodeids[start:start + size] for start in range(0, len(nodeids), size)]


def isolated_environment(runtime: Path) -> dict[str, str]:
    runtime.mkdir(parents=True, exist_ok=True)
    # Inherited developer pytest filters can otherwise turn a full run into a
    # silently selected subset. Application overrides must also come only from
    # this runner, including paths read before pytest fixtures are installed.
    env = {
        name: value for name, value in os.environ.items()
        if not name.startswith("KOMI_") and name not in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS")
    }
    home = runtime / "home"
    roaming = home / "AppData" / "Roaming"
    local = home / "AppData" / "Local"
    for directory in (home, roaming, local):
        directory.mkdir(parents=True, exist_ok=True)
    runtime_config = runtime / "runtime.toml"
    # Use the normal config layer for the bootstrap database. A DB_PATH
    # environment override would mask database changes saved by Setup tests.
    runtime_config.write_text(
        "[runtime]\ndb_path = " + json.dumps(str(runtime / "bootstrap.sqlite3")) + "\n",
        encoding="utf8",
    )
    # Set absolute paths before database/runtime_config imports, including the
    # collection process (pytest fixtures have not run during collection).
    env.update({
        "PYTHONPATH": os.pathsep.join((str(SUPPORT), str(SOURCE))),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "QT_QPA_PLATFORM": "offscreen",
        "KOMI_DISCOVERY_DISABLED": "1",
        "KOMI_CI_NETWORK": "loopback",
        "KOMI_APP_HOME": str(runtime),
        "KOMI_PROJECT_ROOT": str(ROOT),
        "KOMI_V46_DATABASE": str(runtime / "absent-legacy.sqlite3"),
        "KOMI_LOG_DIR": str(runtime / "logs"),
        "KOMI_RUNTIME_CONFIG": str(runtime_config),
        "KOMI_PEER_SYNC_STATE_FILE": str(runtime / "peer-state.json"),
        "USERPROFILE": str(home),
        "HOME": str(home),
        "APPDATA": str(roaming),
        "LOCALAPPDATA": str(local),
    })
    env.pop("KOMI_CI_COLLECTION", None)
    env.pop("KOMI_CI_OUTCOMES", None)
    return env


def run_pytest(arguments: list[str], log: Path, env: dict[str, str], timeout: int) -> dict:
    started = time.monotonic()
    command = [sys.executable, "-m", "pytest", "-p", "desktop_ci_plugin", *arguments]
    with log.open("w", encoding="utf8") as stream:
        options = (
            {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt" else {"start_new_session": True}
        )
        process = subprocess.Popen(
            command, cwd=SOURCE, env=env, stdout=stream, stderr=subprocess.STDOUT, **options,
        )
        try:
            code: int | str = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = "timeout"
            # Terminate only this owned test process and its children. A hung
            # fixture must not leave a background server behind after a batch.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=stream, stderr=subprocess.STDOUT, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            process.wait()
    return {"exit_code": code, "seconds": round(time.monotonic() - started, 2), "log": log.name}


def batch_complete(planned: list[str], result: dict, outcomes: dict) -> bool:
    return (
        result["exit_code"] == 0
        and outcomes.get("exit_code") == 0
        and set(outcomes.get("executed_nodeids", [])) == set(planned)
        and not any(outcomes.get("counts", {}).get(name, 0) for name in ("failed", "error", "xpassed"))
        and not any(outcomes.get("subtest_counts", {}).get(name, 0) for name in ("failed", "error", "xpassed"))
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", nargs="+", help="Specific names under source/tests, with or without .py")
    parser.add_argument("--batch-size", type=int, default=8, help="Maximum cases per fresh pytest process (default: 8)")
    parser.add_argument("--timeout", type=int, default=240, help="Seconds allowed per collection/batch process")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs" / (
        "desktop-ci-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    ))
    args = parser.parse_args(argv)
    if not 1 <= args.batch_size <= 100 or args.timeout < 1:
        parser.error("Use a batch size from 1 to 100 and a positive timeout")
    try:
        files = discover_files(args.files)
    except ValueError as error:
        parser.error(str(error))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "results.json"
    if manifest_path.exists():
        parser.error("Use a new output directory; existing regression evidence is never overwritten")
    runtime = Path(tempfile.mkdtemp(prefix="komi-desktop-ci-"))
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    state = {
        "source_commit": revision.stdout.strip(),
        "python": sys.version,
        "files": [path.relative_to(ROOT).as_posix() for path in files],
        "excluded_release_files": EXCLUDED_FILES,
        "batch_size": args.batch_size,
        "runtime_directory": str(runtime),
        "network_policy": "Python loopback only; discovery disabled",
        "complete": False,
        "results": [],
    }

    def save() -> None:
        manifest_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf8")

    save()
    collection_path = output / "collection.json"
    env = isolated_environment(runtime / "collection")
    env["KOMI_CI_COLLECTION"] = str(collection_path)
    state["collection"] = run_pytest(
        [*[path.relative_to(SOURCE).as_posix() for path in files], "--collect-only", "-q"],
        output / "collection.log", env, args.timeout,
    )
    if state["collection"]["exit_code"] != 0 or not collection_path.exists():
        save()
        print(f"Collection failed; see {output / 'collection.log'}", flush=True)
        return 1
    nodeids = json.loads(collection_path.read_text(encoding="utf8"))["nodeids"]
    try:
        plan = batches(nodeids, args.batch_size)
    except ValueError as error:
        state["collection_error"] = str(error)
        save()
        return 1
    state["collected"] = len(nodeids)
    save()
    print(f"Collected {len(nodeids)} tests in {len(files)} files; {len(plan)} fresh processes", flush=True)
    for index, selected in enumerate(plan, 1):
        prefix = f"batch-{index:03}"
        outcome_path = output / f"{prefix}.json"
        env = isolated_environment(runtime / prefix)
        env["KOMI_CI_OUTCOMES"] = str(outcome_path)
        result = run_pytest(
            [*selected, "-q", "--tb=short", "-o", "faulthandler_timeout=90", f"--junitxml={output / (prefix + '.xml')}"],
            output / f"{prefix}.log", env, args.timeout,
        )
        try:
            outcomes = json.loads(outcome_path.read_text(encoding="utf8")) if outcome_path.exists() else {}
        except (OSError, ValueError) as error:
            outcomes = {"evidence_error": str(error)}
        result.update({"batch": index, "planned_nodeids": selected, "outcomes": outcomes})
        result["successful"] = batch_complete(selected, result, outcomes)
        state["results"].append(result)
        save()
        print(f"{index}/{len(plan)}: exit={result['exit_code']}; {outcomes.get('counts', {})}", flush=True)
        if not result["successful"]:
            # Keep diagnosis available through ordinary job logs even when an
            # artifact download is unavailable. These tests use synthetic data.
            detail = (output / f"{prefix}.log").read_text(encoding="utf8", errors="replace")
            print(f"--- Failed {prefix} log (last 16000 characters) ---\n{detail[-16000:]}", flush=True)
    executed = {node for row in state["results"] for node in row["outcomes"].get("executed_nodeids", [])}
    state["missing_nodeids"] = sorted(set(nodeids) - executed)
    state["unexpected_nodeids"] = sorted(executed - set(nodeids))
    state["counts"] = {
        name: sum(row["outcomes"].get("counts", {}).get(name, 0) for row in state["results"])
        for name in OUTCOME_NAMES
    }
    state["subtest_counts"] = {
        name: sum(row["outcomes"].get("subtest_counts", {}).get(name, 0) for row in state["results"])
        for name in OUTCOME_NAMES
    }
    state["complete"] = True
    state["successful"] = (
        all(row["successful"] for row in state["results"])
        and not state["missing_nodeids"] and not state["unexpected_nodeids"]
    )
    save()
    print(f"Results: {manifest_path}\n{state['counts']}", flush=True)
    return 0 if state["successful"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
