# AutoDraft v1.2 Clio Integration Validation — 2026-10-05

Baseline: user-supplied `AutoDraft-v1.1-LawyerFirm-Integrated-2026-10-04.zip`.
Baseline SHA-256: `b2a95671033f71cb2b4f75cbc934fee291755439d755b1f624492ba8bdac98e2`.

## Scope implemented

- durable Contacts and matter-specific Participant roles;
- Practice Areas and practice-area-specific Matter Stages, separate from fixed matter status;
- stage-change timestamps / days-in-stage display;
- semantic Field Definitions separated from typed Matter/Contact values;
- deterministic required/choice/range/length/pattern validation;
- card/role field grouping metadata;
- additive bridge from existing conflict-aware `matter_facts` into the canonical field layer;
- versioned Document Sets that pin immutable template-version snapshots;
- enforced Selection → Population → Review → Completed generation-run lifecycle;
- transactional tenant-scoped domain-event/outbox foundation;
- admin/owner gating for firm-level schema configuration; and
- Word taskpane controls for practice/stage, contacts/participants, field cards/values, document sets, generation-run state, and matter activity.

See `docs/CLIO_ARCHITECTURE_PORT_2026-10-05.md` for architecture details and deliberate non-goals.

## Candidate-archive clean-room verification

A candidate release ZIP was created from the release tree, audited, integrity-tested, extracted into a new directory, and the following checks were rerun against the extracted bytes:

- Backend compile: **passed**.
- Backend pytest: **80 passed, 2 skipped**.
  - The skipped tests are the existing disposable-real-PostgreSQL environment gates.
  - Tests were run with the existing external test-only `asyncpg` shim because this sandbox does not have the real `asyncpg` package installed. The shim is not included in the ZIP.
- Golden corpus: **precision 1.000 / recall 1.000 / F1 1.000 / duplicate rate 0.000** on the deterministic scored fixtures.
- Lawyer-Firm candidate benchmark: **candidate recall 1.000 / rule decision accuracy 1.000 (3 decided cases)**.
- TypeScript static source check: **0 code-level diagnostics** after separating the diagnostics caused solely by unavailable installed packages/Office declarations. The only TypeScript error codes were missing-module/global/type-environment codes (`TS2304`, `TS2307`, `TS2503`, `TS2580`).
- Source release audit: **passed** after clean extraction.
- Candidate ZIP integrity (`unzip -t`): **passed**.
- Candidate ZIP audit: **passed**.

## Environment-gated checks not claimed

- `npm ci --offline` could not complete because `yoctocolors-cjs@2.1.3` is not present in the sandbox npm cache. Therefore Vitest and webpack are **not claimed as run** in this environment.
- No disposable PostgreSQL server/`asyncpg` runtime is installed here, so the migration/RLS integration gates remain skipped rather than falsely reported as passed.
- Microsoft Word, Ollama, OCRmyPDF/Tesseract, and optional Jev provider host/runtime smoke tests require the developer environment and are not claimed here.

## Release hygiene

The release audit rejects `.env`, `.git`, `.venv`, `node_modules`, Python caches, private `.docx/.pdf` files outside test fixtures, and common secret patterns. The candidate release tree and archive both passed that audit.
