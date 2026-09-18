"""Prepare and run KOMI Web as a child of the Desktop application."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from tools.prepare_web_runtime import prepare
from tools.run_web_servers import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Run KOMI Web for the Desktop application.")
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--parent-pid", required=True, type=int)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    web_source = project_root / "web"
    legacy_env = web_source / ".env.local"
    prepare(web_source, args.runtime, legacy_env if legacy_env.is_file() else None)
    if args.stop_file is not None and args.stop_file.exists():
        return 0
    return run(
        project_root / "source",
        args.runtime,
        open_browser=False,
        parent_pid=args.parent_pid,
        stop_file=args.stop_file,
    )


if __name__ == "__main__":
    raise SystemExit(main())
