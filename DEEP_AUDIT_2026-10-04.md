# AutoDraft vNext 1.0.1 — Deep Release Audit

This release was audited from the user-supplied `100.zip` baseline. The audit covered backend source/tests, migrations, API route/client wiring, Word Office.js lifecycle and capability gating, Intake security/validation, OCR command compatibility, release hygiene, and current upstream documentation for Microsoft Word APIs, Ollama structured output, asyncpg JSON codecs, FastAPI uploads, and OCRmyPDF.

## Corrections made during this audit

- Added a tenant-bootstrap mapping for anonymous public Intake tokens so non-default organizations remain reachable when PostgreSQL RLS is active.
- Made HTTP audit logging tolerate authenticated users that do not yet have an `app_users` row.
- Corrected Word content-control event lifetime handling: tracked objects, same-context handler removal, and exact changed-control ID reloads.
- Corrected normalized grounding offset mapping when source text has leading whitespace/NBSP and made an existing binding ID verify its wrapped text before being considered healthy.
- Reconciliation now recognizes both raw UUID binding tags and legacy `autodraft:<uuid>` tags.
- Removed the stale Outlook/Contoso unified manifest and Outlook mailbox command code from the Word release.
- Removed an unused frontend `/api/jobs/{id}` client call that had no backend route; updated stale evaluation defaults and model documentation.
- Core `/api/health/ready` now stays ready when only AI is offline; `/api/health/ai` remains the dedicated AI dependency gate.
- Hardened Intake: HTML-safe error rendering, multi-select answer support, server-side numeric/select/boolean/pattern validation, lawyer-authenticated file download, and one-current-file-per-question semantics.
- Updated OCRmyPDF invocation to the current `--mode skip` syntax.
- Hardened production manifest URL transformation so host/origin entries are transformed consistently.

## Automated evidence in this environment

- Python source compile: passed.
- Backend tests: 55+ tests expected after audit; live count is recorded by the release run. Real PostgreSQL tests are opt-in and skip without `AUTODRAFT_TEST_DATABASE_URL`.
- Golden corpus: semantic precision 1.00, recall 1.00, F1 1.00, duplicate rate 0.00 on the checked-in deterministic scored fixtures.
- Release source audit: passed before packaging.
- TypeScript parse/static pass: no diagnostics other than unavailable installed npm packages / Office globals in this sandbox.
- `npm ci --offline` cannot complete here because `yoctocolors-cjs@2.1.3` is not in the local npm cache; therefore a real npm/Vitest/webpack build is not claimed here.

## Runtime gates still required on the target Mac

A source audit cannot prove Microsoft Word host behavior, a real PostgreSQL migration, local Ollama inference, or OCRmyPDF execution when those runtimes are not available in the build sandbox. Before calling this production-ready, run `scripts/release-gate.sh`, `scripts/run-real-environment-gates.sh`, then the documented Mac Word smoke suite using a disposable/test database and the configured `qwen3:4b` Ollama model.
