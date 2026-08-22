"""Prepare and run KOMI Web as a child of the Desktop application."""

from __future__ import annotations

import argparse
from pathlib import Path

from prepare_web_runtime import prepare
from run_web_servers import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run KOMI Web for the Desktop application.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--parent-pid", required=True, type=int)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    web_source = project_root / "web"
    legacy_env = web_source / ".env.local"
    prepare(web_source, args.runtime, legacy_env if legacy_env.is_file() else None)
    return run(
        project_root / "source",
        args.runtime,
        open_browser=False,
        parent_pid=args.parent_pid,
    )


if __name__ == "__main__":
    raise SystemExit(main())
