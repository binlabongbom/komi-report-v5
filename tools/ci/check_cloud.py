"""Run local Cloud checks without opening saved application data or credentials."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web-modules", type=Path, required=True,
                        help="Existing node_modules; no install or runtime .env is copied")
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    parser.add_argument("--full", action="store_true", help="All desktop-runner tests")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    modules = args.web_modules.resolve(strict=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("KOMI_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", NEXT_TELEMETRY_DISABLED="1",
               npm_config_update_notifier="false", npm_config_cache=str(output / "npm-cache"))
    result = {"commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "dirty_state": subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True),
              "python": sys.version,
              "node": subprocess.check_output(["node", "--version"], env=env, text=True).strip(),
              "npm": subprocess.check_output(["npm", "--version"], env=env, text=True).strip(),
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "steps": [], "complete": False}

    def save():
        (output / "cloud-results.json").write_text(json.dumps(result, indent=2) + "\n")

    def run(name, command, cwd=ROOT):
        with (output / f"{name}.log").open("w") as log:
            code = subprocess.run(command, cwd=cwd, env=env, stdout=log,
                                  stderr=subprocess.STDOUT, check=False).returncode
        result["steps"].append({"name": name, "exit_code": code})
        save()
        print(f"{name}: {'PASS' if code == 0 else 'FAIL'}", flush=True)

    save()
    run("version-gate", [sys.executable, "source/tools/version_gate.py"])
    run("runtime-lint", [sys.executable, "-m", "ruff", "check", "source", "--exclude", "tests",
                         "--select", "F401,F811,F821,F822,F823,F841"])
    run("harness-lint", [sys.executable, "-m", "ruff", "check", "tools/ci",
                         "--select", "F401,F811,F821,F822,F823,F841"])
    desktop = [sys.executable, "tools/ci/run_desktop_tests.py", "--output-dir", str(output / "desktop")]
    if not args.full:
        desktop += ["--files", "test_report_models", "test_runtime_config", "test_shared_ui_components", "test_web_api"]
    run("desktop", desktop)
    # Copy tracked source paths from the working tree, including edits, never .env/runtime state.
    with tempfile.TemporaryDirectory(prefix="komi-cloud-web-") as temp:
        web = Path(temp)
        files = subprocess.check_output(["git", "ls-files", "-z", "web"], cwd=ROOT).decode().split("\0")
        hashes = {}
        for name in filter(None, files):
            relative = Path(name).relative_to("web")
            if any(part.startswith(".env") or part in {"node_modules", ".next"} for part in relative.parts):
                raise RuntimeError(f"Unsafe tracked runtime path: {name}")
            destination = web / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
            hashes[name] = hashlib.sha256(destination.read_bytes()).hexdigest()
        result["web_source_sha256"] = hashes
        (web / "node_modules").symlink_to(modules, target_is_directory=True)
        for script in ("lint", "test:security", "test:numeric", "test:report-users", "build"):
            run("web-" + script.replace(":", "-"), ["npm", "run", script], web)
    result["complete"] = True
    save()
    return int(any(step["exit_code"] != 0 for step in result["steps"]))


if __name__ == "__main__":
    raise SystemExit(main())
