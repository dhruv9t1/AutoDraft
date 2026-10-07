# AutoDraft vNext cumulative release validation — 2026-10-04

Baseline: `AutoDraft-vNext-Foundation-2026-10-03.zip` supplied by the user.

## Cumulative functionality integrated

- Explicit-save-only fresh AutoDraft lifecycle; no database template before **Save Empty Template & Complete**.
- Local-only rename/manual-field behavior for unsaved drafts, with saved-template persistence retained.
- One extraction job per logical run, SSE event delivery, 10-second heartbeats, same-job polling fallback, AbortController/DELETE cancellation.
- Direct SSE heartbeat/disconnect cleanup and Ollama per-chunk task cancellation.
- Conservative same-span semantic-family deduplication after generic-name enrichment.
- Local Gujarati + English OCR jobs for PDF/JPG/JPEG/PNG/TIF/TIFF with OCRmyPDF/Tesseract checks, searchable PDF output, full text extraction, Word import, cancellation and temp-session expiry cleanup.
- Backend-relative `.env`, `qwen3:4b` documented default, Ollama `/api/tags` readiness diagnostics.
- SQLx-aware/checksum-aware/advisory-lock Python migration runner; idempotent legacy FK migration.
- Python upload/OCR dependencies and reproducible release ZIP script.

## Checks run in the build sandbox

- `python3 -m compileall -q app scripts tests` — PASS.
- Backend tests excluding runtime-import gate, using installed dependencies only — **17 passed**.
- Full backend suite with a test-only minimal `asyncpg` import stub because `asyncpg` is not installed in this sandbox — **26 passed**.
- `bash -n scripts/make-release-zip.sh` — PASS.
- `bash -n word-extension/scripts/verify.sh` — PASS.
- TypeScript compiler parsed the complete source. After excluding diagnostics caused solely by unavailable `node_modules`, Office typings, and Node typings, there were **no code-level TypeScript diagnostics**.

## Environment-limited checks not claimed

This sandbox has no external package access, so `npm ci` could not complete and a real webpack/Vitest run was not possible here. `asyncpg` could likewise not be installed from PyPI. A real PostgreSQL server, Ollama model, OCRmyPDF/Tesseract installation, and Microsoft Word host are not available in this build environment.

Before production use, run `word-extension/scripts/verify.sh` with normal dependencies installed, then perform the Word/PostgreSQL/Ollama/OCR smoke checks in `RELEASE_CHECKS.md` and `backend/SETUP.md`.
