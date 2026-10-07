from __future__ import annotations

import json
import os
import re
from pathlib import Path

REQUIRED = (
    "windowsManifestLoad",
    "macManifestLoad",
    "officeSso",
    "customXml",
    "compressedDocumentCapture",
    "createDocument",
    "bindingInsertion",
    "repeatedOccurrenceBinding",
    "exactRollback",
    "eventChangeDelete",
    "newBindingEvent",
    "reconciliationCorruption",
    "comments",
    "trackChanges",
    "generatedDocumentOpen",
)


def main() -> int:
    value = os.getenv("AUTODRAFT_WORD_E2E_EVIDENCE", "").strip()
    if not value:
        print("FAIL - AUTODRAFT_WORD_E2E_EVIDENCE is required")
        return 1
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        print(f"FAIL - Word evidence file does not exist: {path}")
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL - Word evidence is not valid JSON: {exc}")
        return 1
    environments = payload.get("environments") or {}
    if not environments.get("windows") or not environments.get("mac"):
        print("FAIL - Word evidence must record concrete Windows and Mac Word environments")
        return 1
    gates = payload.get("gates") or {}
    failed = [name for name in REQUIRED if gates.get(name) is not True]
    if failed:
        print("FAIL - Word E2E gates missing/failed: " + ", ".join(failed))
        return 1
    if not str(payload.get("executedAt") or "").strip():
        print("FAIL - Word evidence must include executedAt")
        return 1
    evidence_sha = str(payload.get("releaseSha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", evidence_sha):
        print("FAIL - Word evidence must include the exact 64-hex releaseSha256 tested in Word")
        return 1
    expected_sha = os.getenv("AUTODRAFT_RELEASE_SHA256", "").strip().lower()
    if expected_sha and evidence_sha != expected_sha:
        print(f"FAIL - Word evidence is for release {evidence_sha}, not candidate {expected_sha}")
        return 1
    print(f"PASS - real Word Windows/Mac E2E evidence is complete for release {evidence_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
