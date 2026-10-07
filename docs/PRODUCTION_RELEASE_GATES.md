# AutoDraft production release gates

A release must **not** be labelled production-ready from unit/static tests, source-tree tests, or a previously tested build. Real-host evidence is valid only for the exact immutable ZIP that is being released.

## Stage 1 — create the immutable candidate

Set the production Office/Entra manifest values and build the candidate once:

```bash
export AUTODRAFT_ENTRA_CLIENT_ID='...'
export AUTODRAFT_ENTRA_RESOURCE_URI='api://...'
export AUTODRAFT_ADDIN_ORIGIN='https://...'
scripts/prepare-production-candidate.sh /path/to/AutoDraft-production-candidate.zip
```

The script prints the candidate SHA-256. **Do not rebuild or modify the ZIP after this point.** Test Word Windows and Mac using this exact candidate and copy `docs/WORD_E2E_EVIDENCE.example.json` to a separate evidence file. Record the exact SHA-256 in `releaseSha256`, concrete OS/Word builds, execution time, and mark a gate `true` only after that gate passes on the real host.

## Stage 2 — certify the exact candidate bytes

The verification stage extracts the candidate and reruns the real gates from those packaged bytes. It fails closed unless both the non-owner runtime PostgreSQL role and separate migration-owner database are provided:

```bash
export AUTODRAFT_TEST_DATABASE_URL='postgresql://...runtime-role...'
export AUTODRAFT_TEST_MIGRATION_DATABASE_URL='postgresql://...migration-owner...'
export AUTODRAFT_OCR_SMOKE_INPUT='/path/to/real-scanned-gujarati-english.pdf'
export AUTODRAFT_OCR_SMOKE_EXPECT='known text from fixture'
export AUTODRAFT_WORD_E2E_EVIDENCE='/path/to/completed-word-evidence.json'
export AUTODRAFT_RELEASE_ZIP='/path/to/AutoDraft-production-candidate.zip'
scripts/verify-production-candidate.sh
```

The verifier computes the candidate SHA-256 and requires the Word evidence `releaseSha256` to match it exactly. It then runs, from a fresh extraction of that exact ZIP:

- Python compilation and the complete backend test suite, including opt-in real PostgreSQL migration/RLS/FK adversarial gates.
- Deterministic golden corpus evaluation.
- Live Ollama fault-injection/readiness checks.
- A real scanned Gujarati/English OCR smoke test.
- Clean `npm ci`, TypeScript typecheck, Vitest, webpack production build, and production manifest validation.
- Completed Word for Windows and Word for Mac E2E evidence bound to the candidate hash.
- Packaged ZIP integrity and release audit.

On success it writes `<candidate>.production-gate-evidence.json` (or `AUTODRAFT_PRODUCTION_GATE_EVIDENCE_OUT`) containing the exact SHA-256 and machine-readable pass state.

## Word E2E minimum matrix

The evidence must cover manifest loading on Windows and Mac, Office SSO, Custom XML, compressed document capture, `createDocument`, binding insertion, repeated occurrences, exact rollback, edit/delete events, newly-added binding events, reconciliation corruption, comments, Track Changes, and opening a generated Matter Document.

Evidence from a different ZIP hash is rejected. This prevents a source change, rebuild, or repackaging step from inheriting certification that belongs to older bytes.
