#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Compatibility entry point. The delegated verifier enforces these external gates:
# AUTODRAFT_TEST_DATABASE_URL, AUTODRAFT_TEST_MIGRATION_DATABASE_URL,
# AUTODRAFT_ENTRA_CLIENT_ID (used when preparing the candidate),
# AUTODRAFT_OCR_SMOKE_INPUT, and AUTODRAFT_WORD_E2E_EVIDENCE.
# The delegated exact-ZIP verifier runs: python -m scripts.fault_injection_live,
# python -m scripts.ocr_smoke, npm ci, and scripts/verify-word-e2e-evidence.py.
ZIP="${1:-${AUTODRAFT_RELEASE_ZIP:-}}"
if [[ -z "$ZIP" ]]; then
  cat >&2 <<MSG
FAIL - real environment gates must run against an immutable packaged candidate.
First create it with:
  scripts/prepare-production-candidate.sh /path/to/AutoDraft-production-candidate.zip
Then complete Word Windows/Mac evidence for that exact SHA-256 and run:
  scripts/run-real-environment-gates.sh /path/to/AutoDraft-production-candidate.zip
MSG
  exit 2
fi
exec "$ROOT/scripts/verify-production-candidate.sh" "$ZIP"
