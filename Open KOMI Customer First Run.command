#!/bin/zsh
set -eu

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd -P)"
CUSTOMER_UAT_ROOT="$HOME/KOMI Report V5/Customer First Run UAT"

mkdir -p "$CUSTOMER_UAT_ROOT"
export KOMI_DB_PATH="$CUSTOMER_UAT_ROOT/KOMI_Report_V5.db"

# This is a clean, persistent customer database with real LAN discovery.
# It deliberately does not enable Virtual Printer or Lab ports.
exec "$PROJECT_ROOT/Open KOMI Report V5.command" desktop
