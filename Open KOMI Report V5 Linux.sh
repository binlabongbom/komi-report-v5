#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SOURCE_ROOT="$PROJECT_ROOT/source"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
RUNTIME_ROOT="$DATA_HOME/komi-report-v5/runtime-linux"
PYTHON_BIN="$RUNTIME_ROOT/bin/python"
STAMP_FILE="$RUNTIME_ROOT/.komi-dependencies.sha256"
LAUNCH_MODE="${1:-desktop}"

if [[ "$LAUNCH_MODE" != "desktop" && "$LAUNCH_MODE" != "doctor" ]]; then
  echo "Usage: $0 [desktop|doctor]" >&2
  exit 2
fi

if [[ ! -f "$SOURCE_ROOT/app.py" || ! -f "$SOURCE_ROOT/pyproject.toml" ]]; then
  echo "KOMI Report V5: canonical source not found: $SOURCE_ROOT" >&2
  exit 1
fi

dependency_hash="$(sha256sum "$SOURCE_ROOT/pyproject.toml" "$SOURCE_ROOT/uv.lock" | sha256sum | awk '{print $1}')"
installed_hash=""
[[ -f "$STAMP_FILE" ]] && installed_hash="$(<"$STAMP_FILE")"

if [[ ! -x "$PYTHON_BIN" || "$dependency_hash" != "$installed_hash" ]]; then
  mkdir -p "$RUNTIME_ROOT"
  if command -v uv >/dev/null 2>&1; then
    echo "Preparing the Linux runtime outside the source tree..."
    UV_PROJECT_ENVIRONMENT="$RUNTIME_ROOT" uv sync \
      --project "$SOURCE_ROOT" --python 3.11 --no-dev --locked
  else
    command -v python3 >/dev/null 2>&1 || {
      echo "Python 3.11+ or uv is required." >&2
      exit 1
    }
    python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
      echo "Python 3.11 or newer is required." >&2
      exit 1
    }
    [[ -x "$PYTHON_BIN" ]] || python3 -m venv "$RUNTIME_ROOT"
    "$PYTHON_BIN" -m pip install --disable-pip-version-check -r "$SOURCE_ROOT/requirements.txt"
  fi
  printf '%s' "$dependency_hash" > "$STAMP_FILE"
fi

export KOMI_PROJECT_ROOT="$PROJECT_ROOT"
export KOMI_SOURCE_ROOT="$SOURCE_ROOT"
export PYTHONDONTWRITEBYTECODE=1

"$PYTHON_BIN" "$SOURCE_ROOT/tools/launch_doctor.py" "$LAUNCH_MODE" || {
  echo "The canonical source is unavailable or incomplete in Projects/dev." >&2
  exit 1
}

[[ "$LAUNCH_MODE" == "doctor" ]] && exit 0

cd "$SOURCE_ROOT"
exec "$PYTHON_BIN" "$SOURCE_ROOT/app.py"
