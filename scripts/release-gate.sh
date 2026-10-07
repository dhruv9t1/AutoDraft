#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/../AutoDraft-vNext-Complete.zip}"
cd "$ROOT/backend"
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.evaluate_golden_corpus >/tmp/autodraft-golden.json
cd "$ROOT/word-extension"
if [[ "${AUTODRAFT_SKIP_NPM_CI:-0}" != "1" ]]; then
  if [[ ! -f package-lock.json ]]; then npm install --package-lock-only --ignore-scripts; fi
  npm ci
fi
npx tsc --noEmit
npm test
npm run build:dev
cd "$ROOT"
python scripts/audit-release.py "$ROOT"
"$ROOT/scripts/make-release-zip.sh" "$OUT" >/dev/null
unzip -t "$OUT" >/dev/null
python scripts/audit-release.py "$OUT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
unzip -q "$OUT" -d "$TMP"
EXTRACTED="$TMP/$(basename "$ROOT")"
cd "$EXTRACTED/backend"
python -m compileall -q app scripts tests
python -m pytest -q
cd "$EXTRACTED/word-extension"
npm ci
npx tsc --noEmit
npm test
npm run build:dev
cd "$ROOT"
if command -v shasum >/dev/null; then shasum -a 256 "$OUT"; else sha256sum "$OUT"; fi
