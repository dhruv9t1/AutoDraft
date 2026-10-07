# AutoDraft 1.1 lawyer-firm port — validation record

Date: 2026-10-04

## Scope

This record covers the lawyer-firm-inspired extraction and System-1 architecture added on top of the deep-audited AutoDraft 1.0.1 baseline. The implementation ledger is `docs/LAWYER_FIRM_ARCHITECTURE_PORT_2026-10-04.md`.

## Automated checks completed in the build sandbox

- Backend test suite: **65 passed, 2 skipped**.
- The two skipped tests are opt-in real-PostgreSQL integration gates and require `AUTODRAFT_TEST_DATABASE_URL`.
- Candidate-labelled evaluation: **candidate recall 1.000**.
- Deterministic decided-case accuracy in the candidate fixture: **1.000 (3 decided cases)**. Ambiguous labels are intentionally not forced into a rule decision.
- Existing deterministic golden corpus: **precision 1.000, recall 1.000, F1 1.000, duplicate rate 0.000** on the scored fixtures.
- Python compile validation: passed.
- Release source audit: passed after removing generated test/bytecode caches.
- TypeScript static source check: **0 code-level diagnostics** after classifying diagnostics caused solely by unavailable installed npm/Office typings in this sandbox.

## Frontend package limitation in this sandbox

`npm ci --offline --ignore-scripts` cannot complete because `yoctocolors-cjs@2.1.3` is not present in the local npm cache. Therefore this validation record does **not** claim that Vitest or webpack ran in this sandbox. The release keeps `node_modules` out of the archive.

## Real-environment gates not claimed here

A real deployment still needs the existing release procedure for:

- PostgreSQL migration/RLS integration against a disposable real database;
- Ollama `qwen3:4b` readiness and structured-output smoke;
- Microsoft Word host behavior on the target Mac/Windows version;
- OCRmyPDF/Tesseract `guj+eng` executable smoke;
- optional hosted Jev provider contract, authentication, data-processing approval, latency, and calibration if `SYSTEM1_PROVIDER=jev` is enabled.

Jev remains `off` by default, so the new release does not gain a mandatory external AI dependency.

## Safety invariants covered by permanent tests/source checks

- offset-normalized matching retains source offsets;
- Gujarati/Devanagari decimal digit folding is comparison-only;
- textual candidate grouping never merges source occurrences;
- active legacy Indian-font runs are detected;
- organization boilerplate is rejected by the deterministic decision layer;
- ambiguous candidates remain visible for review;
- review-only/rejected candidates are excluded from backend wrapping plans;
- the Word wrapping path independently filters review-only/rejected candidates;
- raw Auto Detect calls the Unicode/legacy-font preflight;
- System-2 failure only exposes explicitly marked review-only previews and produces an empty wrapping plan;
- direct DOCX diagnostics preserve body/header/footer paragraph stories.
