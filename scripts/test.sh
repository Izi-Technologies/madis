#!/usr/bin/env bash
# Run Madis Mako contract tests. Pure Mako — no C bridge needed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAKO_BIN="${MAKO_BIN:-mako}"
PATH_ARG="${1:-tests}"
shift || true
exec "$MAKO_BIN" test "$PATH_ARG" --backend c "$@"
