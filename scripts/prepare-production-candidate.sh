#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/../AutoDraft-production-candidate.zip}"

: "${AUTODRAFT_ENTRA_CLIENT_ID:?Set AUTODRAFT_ENTRA_CLIENT_ID}"
: "${AUTODRAFT_ENTRA_RESOURCE_URI:?Set AUTODRAFT_ENTRA_RESOURCE_URI}"
: "${AUTODRAFT_ADDIN_ORIGIN:?Set AUTODRAFT_ADDIN_ORIGIN to the production https origin}"

cd "$ROOT"
echo "== Render production Office/Entra manifest =="
python scripts/render-production-manifest.py

echo "== Ensure frontend lockfile exists for immutable candidate =="
cd "$ROOT/word-extension"
if [[ ! -f package-lock.json ]]; then npm install --package-lock-only --ignore-scripts; fi
cd "$ROOT"

echo "== Source release audit =="
python scripts/audit-release.py "$ROOT"

echo "== Build immutable production candidate =="
"$ROOT/scripts/make-release-zip.sh" "$OUT" >/dev/null
unzip -t "$OUT" >/dev/null
python scripts/audit-release.py "$OUT"

if command -v shasum >/dev/null; then
  SHA="$(shasum -a 256 "$OUT" | awk '{print $1}')"
else
  SHA="$(sha256sum "$OUT" | awk '{print $1}')"
fi
cat <<MSG
PRODUCTION CANDIDATE CREATED
ZIP: $OUT
SHA256: $SHA

Do not modify or rebuild this ZIP after real-host testing starts.
Record this SHA256 in docs/WORD_E2E_EVIDENCE.example.json-derived evidence as releaseSha256,
run Word Windows/Mac E2E against this exact ZIP, then execute:
  AUTODRAFT_RELEASE_ZIP="$OUT" scripts/verify-production-candidate.sh
MSG
