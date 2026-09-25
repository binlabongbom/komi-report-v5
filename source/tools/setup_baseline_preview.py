"""Open the isolated setup design preview, reusing the main pricing widget."""
import os
from pathlib import Path
import sys
import tempfile

SOURCE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE_ROOT))

if __name__ == "__main__":
    # Set runtime paths before shared pricing imports; no live DB is selected.
    with tempfile.TemporaryDirectory(prefix="komi-meter-step-preview-") as sandbox:
        for key, value in {
            "KOMI_APP_HOME": sandbox,
            "KOMI_DB_PATH": str(Path(sandbox) / "unused-preview.sqlite3"),
            "KOMI_LOG_DIR": str(Path(sandbox) / "logs"),
            "KOMI_RUNTIME_CONFIG": str(Path(sandbox) / "runtime.toml"),
        }.items():
            os.environ[key] = value
        from tools.previews.setup_baseline import main
        raise SystemExit(main())
