#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd -P)"
SOURCE_ROOT="$PROJECT_ROOT/source"
RUNTIME_ROOT="$HOME/Library/Application Support/KOMI Report V5/runtime-macos"
PYTHON_BIN="$RUNTIME_ROOT/bin/python"
STAMP_FILE="$RUNTIME_ROOT/.komi-dependencies.sha256"
LAUNCH_MODE="${1:-desktop}"

if [[ "$LAUNCH_MODE" != "desktop" && "$LAUNCH_MODE" != "doctor" && "$LAUNCH_MODE" != "lab" ]]; then
  echo "Usage: $0 [desktop|doctor|lab]"
  exit 2
fi

if [[ ! -f "$SOURCE_ROOT/app.py" || ! -f "$SOURCE_ROOT/pyproject.toml" ]]; then
  echo "ไม่พบ source กลางของ KOMI Report V5"
  echo "$SOURCE_ROOT"
  read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
  exit 1
fi

dependency_hash="$(/usr/bin/shasum -a 256 "$SOURCE_ROOT/pyproject.toml" "$SOURCE_ROOT/uv.lock" | /usr/bin/shasum -a 256 | /usr/bin/awk '{print $1}')"
installed_hash=""
[[ -f "$STAMP_FILE" ]] && installed_hash="$(<"$STAMP_FILE")"

if [[ ! -x "$PYTHON_BIN" || "$dependency_hash" != "$installed_hash" ]]; then
  mkdir -p "$RUNTIME_ROOT"
  if command -v uv >/dev/null 2>&1; then
    echo "กำลังเตรียม runtime macOS แยกจาก source..."
    UV_PROJECT_ENVIRONMENT="$RUNTIME_ROOT" uv sync \
      --project "$SOURCE_ROOT" --python 3.11 --no-dev --locked
  else
    if ! command -v python3 >/dev/null 2>&1; then
      echo "ไม่พบ Python 3.11+ หรือ uv กรุณาติดตั้ง Python ก่อน"
      read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
      exit 1
    fi
    python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' || {
      echo "Python ต้องเป็นเวอร์ชัน 3.11 ขึ้นไป"
      read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
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

DOCTOR_MODE="$LAUNCH_MODE"
[[ "$LAUNCH_MODE" == "lab" ]] && DOCTOR_MODE="desktop"
"$PYTHON_BIN" "$SOURCE_ROOT/tools/launch_doctor.py" "$DOCTOR_MODE" || {
  echo "เปิด source กลางไม่ได้ ตรวจว่าโฟลเดอร์ source ใน Projects/dev อยู่ครบ"
  read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
  exit 1
}

[[ "$LAUNCH_MODE" == "doctor" ]] && exit 0

cd "$SOURCE_ROOT"
if [[ "$LAUNCH_MODE" == "lab" ]]; then
  exec "$PYTHON_BIN" "$SOURCE_ROOT/tools/setup_lab.py"
fi
exec "$PYTHON_BIN" "$SOURCE_ROOT/app.py"
