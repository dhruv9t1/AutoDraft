#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/../AutoDraft-vNext-Complete.zip}"
NAME="$(basename "$ROOT")"
PARENT="$(dirname "$ROOT")"
rm -f "$OUT"
cd "$PARENT"
zip -qr "$OUT" "$NAME" \
  -x "$NAME/.git/*" \
     "$NAME/.env" "$NAME/*/.env" \
     "$NAME/.env.local" "$NAME/*/.env.local" \
     "$NAME/backend/.venv/*" \
     "$NAME/backend/.release-venv*" "$NAME/backend/.release-venv*/*" \
     "$NAME/**/__pycache__/*" \
     "$NAME/**/*.pyc" "$NAME/**/*.pyo" \
     "$NAME/**/.pytest_cache/*" \
     "$NAME/**/.mypy_cache/*" "$NAME/**/.ruff_cache/*" \
     "$NAME/word-extension/node_modules/*" \
     "$NAME/word-extension/dist/*" \
     "$NAME/word-extension/.office-addin-debugging-started" \
     "$NAME/*.DS_Store" "$NAME/**/.DS_Store"
echo "$OUT"
