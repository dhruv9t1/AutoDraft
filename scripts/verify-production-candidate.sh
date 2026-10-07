#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="${1:-${AUTODRAFT_RELEASE_ZIP:-}}"
[[ -n "$ZIP" ]] || { echo "FAIL - pass the exact production candidate ZIP or set AUTODRAFT_RELEASE_ZIP" >&2; exit 2; }
ZIP="$(cd "$(dirname "$ZIP")" && pwd)/$(basename "$ZIP")"
[[ -f "$ZIP" ]] || { echo "FAIL - release ZIP does not exist: $ZIP" >&2; exit 2; }

: "${AUTODRAFT_TEST_DATABASE_URL:?Set AUTODRAFT_TEST_DATABASE_URL to the non-owner runtime-role disposable PostgreSQL DB}"
: "${AUTODRAFT_TEST_MIGRATION_DATABASE_URL:?Set AUTODRAFT_TEST_MIGRATION_DATABASE_URL to the disposable migration-owner PostgreSQL DB}"
: "${AUTODRAFT_OCR_SMOKE_INPUT:?Set AUTODRAFT_OCR_SMOKE_INPUT to a genuinely scanned Gujarati/English fixture}"
: "${AUTODRAFT_OCR_SMOKE_EXPECT:?Set AUTODRAFT_OCR_SMOKE_EXPECT to known expected text}"
: "${AUTODRAFT_WORD_E2E_EVIDENCE:?Set AUTODRAFT_WORD_E2E_EVIDENCE to completed Windows/Mac evidence JSON}"

if command -v shasum >/dev/null; then
  SHA="$(shasum -a 256 "$ZIP" | awk '{print $1}')"
else
  SHA="$(sha256sum "$ZIP" | awk '{print $1}')"
fi
export AUTODRAFT_RELEASE_SHA256="$SHA"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
unzip -t "$ZIP" >/dev/null
unzip -q "$ZIP" -d "$TMP"
EXTRACTED="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"
[[ -n "$EXTRACTED" ]] || { echo "FAIL - ZIP did not contain a project directory" >&2; exit 1; }

STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "== Candidate identity =="
echo "ZIP: $ZIP"
echo "SHA256: $SHA"

echo "== Backend compile + complete pytest, including real PostgreSQL adversarial gates =="
cd "$EXTRACTED/backend"
python -m compileall -q app scripts tests
python -m pytest -q
python -m scripts.evaluate_golden_corpus
python -m scripts.fault_injection_live
python -m scripts.ocr_smoke

echo "== Frontend clean-room install/type/test/build =="
cd "$EXTRACTED/word-extension"
rm -rf node_modules dist
npm ci
npx tsc --noEmit
npm test
npm run build
npm run validate:production-manifest

echo "== Word Windows/Mac evidence bound to this exact candidate hash =="
cd "$EXTRACTED"
python scripts/verify-word-e2e-evidence.py

echo "== Candidate audit =="
python scripts/audit-release.py "$ZIP"

EVIDENCE="${AUTODRAFT_PRODUCTION_GATE_EVIDENCE_OUT:-${ZIP%.zip}.production-gate-evidence.json}"
FINISHED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python - "$EVIDENCE" "$ZIP" "$SHA" "$STARTED" "$FINISHED" <<'PY'
import json,sys
from pathlib import Path
out,zip_path,sha,started,finished=sys.argv[1:]
payload={
  "schemaVersion":1,
  "releaseZip":str(Path(zip_path).resolve()),
  "releaseSha256":sha,
  "startedAt":started,
  "completedAt":finished,
  "result":"passed",
  "gates":{
    "realPostgresMigrationsRlsFk":True,
    "backendTests":True,
    "goldenCorpus":True,
    "liveOllamaFaultInjection":True,
    "realGujaratiEnglishOcr":True,
    "cleanFrontendNpmCiTypecheckVitestWebpack":True,
    "productionManifest":True,
    "wordWindowsMacE2e":True,
    "packagedZipAudit":True,
  }
}
Path(out).write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
print(f"Evidence: {out}")
PY

echo "REAL PRODUCTION CANDIDATE GATES PASSED: $SHA"
