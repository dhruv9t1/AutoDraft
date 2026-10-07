# AutoDraft vNext — Remaining 50% Implementation

This document records the second implementation pass applied **directly on top of the supplied 50% ZIP**. It completes the deferred implementation boundary recorded in `VNEXT_50_PERCENT_PASS.md`; it does not replace that first-half history.

## Completed in the remaining-half pass

### Backend decomposition and contracts
- Reduced `app/main.py` to application construction, lifecycle, middleware, exception handling and router registration.
- Split documents/fields, templates, OCR, drafting/review, intake and matters into dedicated API modules.
- Added repository/service/domain modules for matter facts, Matter Documents, templates, Intake and field detection.
- Retained pool-level JSON/JSONB codecs, typed AI gateway/errors and request IDs from the first pass.
- Canonical `DraftResult` is now a Pydantic response contract for drafting routes.

### Structural Smart Field + binding transaction
- Added canonical structural `DocumentSegment` extraction for body, tables, headers and footers.
- Original Word text and normalized shadow text are retained separately.
- Added immutable binding/occurrence IDs and source coordinates.
- Added `BindingPlan { operations, conflicts, canCommit }` with deterministic grounding, repeated-value occurrence selection, overlap planning and existing-control checks.
- Word mutation does not begin when the plan contains a blocking conflict.
- Binding commit is serialized, rolls back newly inserted controls on failure and post-verifies expected tags **and expected text** before reporting success.

### Word reliability layer
- All tracked `Word.run()` operations are routed through the shared `WordOperationQueue`.
- Central capability service gates WordApi 1.4/1.5, custom XML, comments, compressed document capture and desktop Track Changes.
- Added startup reconciliation of embedded AutoDraft manifest versus live Word controls.
- Added capability-gated content-control changed/deleted event monitoring.
- Added a non-destructive Word reliability smoke suite accessible from the drafting workspace.
- Native Word comments are available for located review findings where supported.
- Track Changes insertion is offered only where the desktop capability is available.

### Full DOCX snapshots and Matter Documents
- Templates can persist versioned full compressed DOCX snapshots in addition to body OOXML fallback.
- Matter Documents are first-class persisted DOCX records with capture, list, open, rename and archive operations.
- Stored DOCX data is size-limited, Base64/ZIP validated, hashed, and handled as private server-side blob content.
- Word desktop can capture full compressed DOCX; supported hosts can open persisted DOCX through `Word.Application.createDocument(base64)`.

### Intake v2
- Added questionnaire templates, immutable versions, sections, questions and version-pinned client sessions.
- Sections and questions can be reordered; questions can move between sections.
- Conditional display rules are deterministic.
- Validation supports required/optional, min/max length, regex and allowed file extensions.
- File-upload questions are supported and stored privately.
- The public form renders section headings, Required/Optional labels, accessible field requirements and field-specific validation summaries.
- AI questions remain unapproved until the lawyer approves them.
- Editing after publication creates a new draft version; existing client sessions remain pinned to their published version.

### Matter facts
- Client/document facts preserve provenance and do not silently overwrite canonical values.
- Conflicts are first-class records with candidate values.
- UI allows the lawyer to select an existing candidate **or enter another value**.
- Added deterministic derived-fact rules using a small safe expression DSL (no `eval`, no model decision at runtime).

### Review / drafting
- Canonical structured drafting output carries missing information, review findings and citation status.
- Document Review findings have stable typed categories/severities.
- Citation status remains truthful (`not_applicable`, `not_checked`, `needs_verification`, `partially_verified`, `verified`).
- Native comments and capability-gated Track Changes are integrated without making them mandatory on unsupported hosts.

### Golden corpus and regression quality
- Golden corpus now contains 16 sanitized fixtures, including table-heavy, affidavit, agreement, complaint, invoice, header/footer, repeated values, split formatting, existing controls, nested tables, large 500-cell, multilingual and no-field cases.
- Added automated precision/recall/F1 and duplicate-rate gates.
- Deterministic scored fixtures currently measure 1.00 precision, 1.00 recall, 1.00 F1 and 0 duplicate rate. These numbers apply only to the checked-in deterministic fixtures; they are not claimed as universal product accuracy.

### Security / production hardening foundation
- Added organization/user/role context and HMAC-signed bearer-token mode alongside explicit local-development mode.
- Added RBAC checks for protected mutation routes.
- PostgreSQL tenant context is applied on every repository transaction/one-shot query.
- Tenant-owned create paths derive `organization_id` from the request-scoped PostgreSQL tenant setting.
- Added RLS policies and an explicit production hardening script to force RLS after deployment configuration.
- Expanded audit events with organization, actor, request ID and IP context.
- Added private DOCX/file validation and release archive secret/private-file scanning.

### Real-environment and release gates included
- `backend/scripts/fault_injection_live.py` exercises real Ollama/model/structured-output and optional real PostgreSQL failure paths.
- `scripts/run-real-environment-gates.sh` is the real-environment gate for PostgreSQL + Ollama + frontend toolchain.
- `scripts/release-gate.sh` performs source tests, corpus metrics, frontend checks, archive audit, packaging, fresh extraction and re-validation when all dependencies are available.
- `scripts/audit-release.py` rejects caches, dependencies, `.env`, secrets and private client document extensions outside approved fixtures.

## Validation performed in the build sandbox

- Python compile/AST checks: **passed**.
- Backend tests: **45 passed, 1 skipped**. The skipped test is the opt-in real PostgreSQL contract test because this sandbox does not expose a PostgreSQL test database.
- Golden corpus gate: **passed** (12 scored fixtures among 16 total; precision/recall/F1 1.00, duplicate rate 0).
- Source release audit: **passed**.
- TypeScript compiler: after filtering diagnostics caused solely by absent `node_modules` / Office declaration packages, **0 code-level diagnostics** remain.
- The sandbox does not contain `word-extension/node_modules`, so Vitest/webpack/Office manifest runtime validation cannot truthfully be claimed here. The included release scripts run those gates in a normal connected/local development environment.
- Real Word behavior, live PostgreSQL RLS behavior and live Ollama `qwen3:4b` behavior remain host/runtime gates; the code and scripts for those checks are included.

## Required local release-candidate check

Run from a machine with PostgreSQL, Ollama, Node/npm and Microsoft Word:

```bash
export AUTODRAFT_TEST_DATABASE_URL='postgresql://...'
# Configure backend/.env with qwen3:4b and security settings.

./scripts/run-real-environment-gates.sh
./scripts/release-gate.sh ../AutoDraft-vNext-Complete.zip
```

Then run the Word-host self-check and the manual smoke flow on Word for Mac/Windows before treating the artifact as a production release candidate.
