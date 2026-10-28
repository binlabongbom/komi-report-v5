#!/usr/bin/env bash
# Install dependencies in a fresh, explicit location; never start the application.
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cloud_root="${1:?Usage: bash tools/ci/setup_cloud.sh /absolute/new/setup-directory}"
[[ "$cloud_root" = /* && ! -e "$cloud_root" ]] || { echo 'Use a new absolute directory'; exit 2; }
mkdir -p "$cloud_root"
export UV_CACHE_DIR="$cloud_root/cache/uv"
export UV_PYTHON_INSTALL_DIR="$cloud_root/python"
export UV_PROJECT_ENVIRONMENT="$cloud_root/venv"
export npm_config_cache="$cloud_root/cache/npm"
export npm_config_update_notifier=false
export NEXT_TELEMETRY_DISABLED=1
python_version="$(cat "$project_root/.python-version")"
node_version="$(cat "$project_root/.node-version")"
if [[ "$(node --version 2>/dev/null || true)" != "v$node_version" || "$(npm --version 2>/dev/null || true)" != '12.1.0' ]]; then
  # A scoped official Linux toolchain; do not replace system binaries or read credentials.
  python3 - "$cloud_root" "$node_version" <<'PY'
import hashlib
import pathlib
import platform
import sys
import tarfile
import urllib.request
if sys.platform != 'linux' or platform.machine() != 'x86_64':
    raise SystemExit('Automatic Node setup supports Linux x64; provide pinned Node/npm on PATH elsewhere.')
root = pathlib.Path(sys.argv[1])
version = sys.argv[2]
name = f'node-v{version}-linux-x64.tar.xz'
base = f'https://nodejs.org/dist/v{version}/'
with urllib.request.urlopen(base + 'SHASUMS256.txt', timeout=60) as response:
    checksums = response.read().decode()
expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1] == name)
urllib.request.urlretrieve(base + name, root / name)
if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
    raise SystemExit('Node archive checksum mismatch')
with tarfile.open(root / name) as archive:
    archive.extractall(root, filter='data')
PY
  export PATH="$cloud_root/node-v$node_version-linux-x64/bin:$PATH"
  npm install --global npm@12.1.0 --prefix "$cloud_root/node-v$node_version-linux-x64"
fi
node_bin="$(dirname "$(command -v node)")"
uv sync --project "$project_root/source" --python "$python_version" --locked --extra dev --group dev
mkdir "$cloud_root/web"
git -C "$project_root" archive HEAD web | tar -x -C "$cloud_root/web" --strip-components=1
(cd "$cloud_root/web" && npm ci)
{
  printf 'export PATH=%q:%q/bin:$PATH\n' "$node_bin" "$cloud_root/venv"
  printf 'export UV_CACHE_DIR=%q\n' "$UV_CACHE_DIR"
  printf 'export UV_PYTHON_INSTALL_DIR=%q\n' "$UV_PYTHON_INSTALL_DIR"
  printf 'export UV_PROJECT_ENVIRONMENT=%q\n' "$UV_PROJECT_ENVIRONMENT"
  printf 'export npm_config_cache=%q\n' "$npm_config_cache"
  printf 'export PYTHONDONTWRITEBYTECODE=1 NEXT_TELEMETRY_DISABLED=1\n'
} > "$cloud_root/activate.sh"
echo "Activate pinned tools: source $cloud_root/activate.sh"
echo "Ready: $cloud_root/venv/bin/python tools/ci/check_cloud.py --web-modules $cloud_root/web/node_modules --output /absolute/new/evidence-directory"
