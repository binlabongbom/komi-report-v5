#!/bin/zsh
set -eu

# Compatibility wrapper: the maintained launcher lives at the project root.
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
exec "$PROJECT_ROOT/Open KOMI Report V5.command" "$@"
