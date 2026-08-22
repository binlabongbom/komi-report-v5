#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd -P)"
exec "$PROJECT_ROOT/Open KOMI Report V5.command" lab
