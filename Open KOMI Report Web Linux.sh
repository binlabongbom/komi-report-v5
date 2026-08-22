#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_ROOT="$PROJECT_ROOT/source"
WEB_SOURCE="$PROJECT_ROOT/web"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
PYTHON_BIN="$DATA_HOME/komi-report-v5/runtime-linux/bin/python"
WEB_RUNTIME="$DATA_HOME/komi-report-v5/web-runtime"

"$PROJECT_ROOT/Open KOMI Report V5 Linux.sh" doctor || {
  echo "Preparing the Linux Python runtime failed." >&2
  exit 1
}

"$PYTHON_BIN" "$SOURCE_ROOT/tools/launch_doctor.py" web || {
  echo "The shared Web source is unavailable. Keep the OneDrive source folder offline." >&2
  exit 1
}

"$PYTHON_BIN" "$SOURCE_ROOT/tools/prepare_web_runtime.py" \
  --source "$WEB_SOURCE" \
  --runtime "$WEB_RUNTIME" \
  --legacy-env "$WEB_SOURCE/.env.local" || {
  echo "Preparing the machine-local Web runtime failed." >&2
  exit 1
}

export KOMI_PROJECT_ROOT="$PROJECT_ROOT"
export KOMI_SOURCE_ROOT="$SOURCE_ROOT"
export PYTHONDONTWRITEBYTECODE=1

exec "$PYTHON_BIN" "$SOURCE_ROOT/tools/run_web_servers.py" \
  --source "$SOURCE_ROOT" \
  --runtime "$WEB_RUNTIME"
