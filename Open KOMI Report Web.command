#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd -P)"
SOURCE_ROOT="$PROJECT_ROOT/source"
WEB_SOURCE="$PROJECT_ROOT/web"
PYTHON_BIN="$HOME/Library/Application Support/KOMI Report V5/runtime-macos/bin/python"
WEB_RUNTIME="$HOME/Library/Application Support/KOMI Report V5/web-runtime"

"$PROJECT_ROOT/Open KOMI Report V5.command" doctor || {
  echo "เตรียม Python runtime ของ macOS ไม่สำเร็จ"
  read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
  exit 1
}

"$PYTHON_BIN" "$SOURCE_ROOT/tools/launch_doctor.py" web || {
  echo "อ่าน Web source กลางจาก Projects/dev ไม่สำเร็จ"
  read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
  exit 1
}

"$PYTHON_BIN" "$SOURCE_ROOT/tools/prepare_web_runtime.py" \
  --source "$WEB_SOURCE" \
  --runtime "$WEB_RUNTIME" \
  --legacy-env "$WEB_SOURCE/.env.local" || {
  echo "เตรียม Web runtime ไม่สำเร็จ"
  read -k 1 "?กดปุ่มใดก็ได้เพื่อปิด..."
  exit 1
}

export KOMI_PROJECT_ROOT="$PROJECT_ROOT"
export KOMI_SOURCE_ROOT="$SOURCE_ROOT"
export PYTHONDONTWRITEBYTECODE=1

exec "$PYTHON_BIN" "$SOURCE_ROOT/tools/run_web_servers.py" \
  --source "$SOURCE_ROOT" \
  --runtime "$WEB_RUNTIME"
