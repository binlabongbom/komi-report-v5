from __future__ import annotations

import argparse
import sys
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from services.web_access import ensure_web_access  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create or migrate the machine-local KOMI Web login."
    )
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--migrate-from", type=Path)
    args = parser.parse_args()

    values = ensure_web_access(args.env_file, migrate_from=args.migrate_from)
    print(f"Web Login: {values['KOMI_WEB_USER']}")
    print("Access Code: จัดการจาก Desktop Settings (ไม่แสดงรหัสใน Log)")
    print(f"Credential file (local machine): {args.env_file.expanduser().resolve()}")


if __name__ == "__main__":
    main()
