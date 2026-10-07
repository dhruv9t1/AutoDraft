# AutoDraft vNext implementation status

This build is a reliability-focused foundation, not a claim that the entire long-term AutoDraft roadmap is complete.

## Implemented in this build

- Fixed the confirmed `/api/intake/generate` `re` NameError and added a route regression test.
- General-purpose detector defaults to the locally validated `qwen3:4b`, with an optional second-stage verifier model (`qwen3:8b`). Both remain environment-overridable.
- Repeated-text anchoring now respects the model-returned source position instead of silently taking the first occurrence.
- Optional second-stage field classification can reject headings, labels, and static text without changing source spans.
- User-facing model-confidence percentages removed from field/form/template UX.
- Matter list/create/open/update foundation and matter-fact upsert behavior.
- Drafting workspace now supports existing matters, separate action loading states, structured Document Review, actionable missing-information dialog, and truthful citation status copy.
- Verified matter authorities are forwarded to drafting only when authority use is opted in.
- Template rename and soft-delete lifecycle controls.
- Current-document completion is independent of reusable-template saving and no longer strips Word field controls.
- Reusable-layout recovery can capture the currently open Word document as a master after explicit confirmation.
- Stable UUID binding IDs remain the programmatic Word identity; manual field creation now verifies the resulting control before persistence.
- Reusable-template capture now uses binding IDs rather than display labels, so field renames do not break master capture.
- Document-wide control reconciliation includes headers/footers instead of checking only body controls.
- AutoDraft Custom XML manifest foundation stores document/template/matter/binding identity inside supported Word files on a best-effort basis.
- Citation verification semantics now distinguish no citations, not checked, needs verification, partial verification, and verified.
- Final semantic verification no longer emits generic `Semantic review issue` messages.
- Lifecycle migration adds template soft-delete, matter archive support, and fact update timestamps.
- Fresh AutoDrafts are now in-memory/Word-only until **Save Empty Template & Complete**; Back/cancel creates no template row.
- Unsaved AutoDraft rename/manual-field operations remain local until explicit save; saved-template editing keeps the existing persistence path.
- Variable extraction now uses a single backend job with SSE events + 10-second heartbeats and polling fallback against the same job, preventing duplicate Ollama work on stream failure.
- HTTP/Word cancellation propagates through the extraction job into unfinished per-chunk Ollama tasks.
- Same-span duplicates are collapsed by semantic family after generic-name enrichment, while same-value fields at different positions remain distinct.
- Local PDF/image OCR supports Gujarati + English (`guj+eng`) through OCRmyPDF/Tesseract, generates a searchable PDF, exposes extracted text, and can import that text into Word.
- Backend `.env` resolution is anchored to the backend directory; startup validates the configured Ollama model through `/api/tags`.
- Migration execution is advisory-lock/checksum aware, understands prior SQLx history, and the legacy FK migration is idempotent.

## Existing strong foundations preserved

- deterministic grounding and UUID5 backend binding IDs;
- body/table/header/footer Word mapping;
- whitespace/punctuation tolerant constrained search;
- longest-first overlap handling;
- cross-paragraph Word range construction;
- fact ledger / prompt-injection markers;
- advisory citation sanitization;
- drafting plan → draft → review pipeline;
- OOXML restore snapshot for destructive draft replacement;
- dedicated production webhook dispatcher with leasing, signing, idempotency, retries, attempt history, and dead-letter handling.

## Not yet claimed as complete

The following items still require additional engineering or real production/Word-host validation before they should be represented as finished:

- production research provider for authoritative Indian legal sources;
- dependency-graph intake requirements beyond the general workflow engine;
- uploaded document knowledge/RAG ingestion beyond OCR/import and Matter Documents;
- production PDF conversion for headless generated artifacts (v1.3 deliberately generates DOCX only);
- serverless/self-hosted production inference deployment;
- full browser/Word end-to-end tests across Mac, Windows, and Word Web;
- live release gates against real PostgreSQL, Ollama, OCRmyPDF/Tesseract, and Microsoft Word on the target machine.

## Validation required on the developer machine

Run `word-extension/scripts/verify.sh` after installing the real frontend and backend dependencies. Then perform the Word-host smoke test described in `RELEASE_CHECKS.md` on macOS Word before treating the build as release-ready.


## vNext 50% reliability pass — 2026-10-04

This tree includes the intentionally scoped first half of the vNext reliability architecture. See `docs/VNEXT_50_PERCENT_PASS.md` for implemented/deferred items and validation evidence. The remaining half is deliberately not folded into this ZIP.


## AutoDraft 1.1 lawyer-firm architecture port — 2026-10-04

- Added offset-preserving Unicode candidate normalization with Indian digit folding.
- Added direct DOCX body/header/footer diagnostics and pre-Unicode Indian-font detection.
- Added high-recall ordered deterministic candidates plus non-destructive variant/repetition grouping.
- Added tenant-scoped organization boilerplate registry and authenticated API.
- Added provider-neutral Rules → optional Jev System-1 → Qwen System-2 → lawyer-review decision routing.
- Jev is disabled by default and failures safely abstain.
- Ambiguous candidates remain visible as `needs_review` and cannot enter backend or Word wrapping plans.
- System-2 outages expose only explicitly marked review-only candidate previews and never modify Word.
- Added candidate-level labelled evaluation fixtures and permanent backend/frontend seam regression checks.

See `docs/LAWYER_FIRM_ARCHITECTURE_PORT_2026-10-04.md`.

## AutoDraft 1.2 Clio-inspired legal-data port — 2026-10-05

- Added durable Contacts and matter-specific legal Participant roles instead of flattening parties into fact strings.
- Added Practice Areas and admin-owned Matter Stages while preserving the fixed matter status lifecycle.
- Added stable semantic Field Definitions separated from typed Matter/Contact values, with deterministic definition-level validation.
- Existing conflict-aware `matter_facts` are bridged additively into canonical field definitions/values; unresolved conflict candidates are not promoted.
- Added role/card-style field groups and taskpane configuration/value editing.
- Added versioned Document Sets that pin immutable template versions when published.
- Added enforced Selection → Population → Review → Completed generation-run lifecycle.
- Added tenant-scoped transactional domain events/outbox plus a dedicated webhook delivery worker with retry/dead-letter handling.
- Added taskpane matter activity, practice/stage, contacts/participants, field cards, and document-set controls.

See `docs/CLIO_ARCHITECTURE_PORT_2026-10-05.md` and `CLIO_INTEGRATION_VALIDATION_2026-10-05.md`.


## AutoDraft 1.3 Gavel-inspired automation port — 2026-10-05

- Added one safe JSON expression AST used for branching, calculations, template conditions, and repeat collection expressions; no Python `eval`, SQL, or model execution is available to expressions.
- Added immutable Workflow Versions and version-pinned internal/client Workflow Sessions with hashed public bearer-token routing.
- Added reusable calculations, question/page visibility conditions, required-field evaluation, repeaters, and nested repeaters.
- Added Word content-control regions for conditional and repeating document blocks through the centralized Word operation queue.
- Added version-pinned Template Automation blueprints and DOCX-package preflight that blocks missing field/condition/repeater regions before publication.
- Added headless DOCX rendering for individual immutable template versions and published Document Set versions, including conditions and nested repeaters.
- Added generation artifacts and optional Matter Document persistence with SHA-256 provenance/real byte size.
- Added cross-matter/cross-document-set safety checks when combining generation runs and workflow sessions.
- Added explicit lawyer-controlled workflow-data promotion into existing canonical matter field definitions; completion alone never mutates canonical matter data.
- Added taskpane Workflow/Automation UI and a public workflow page; raw JSON blueprint editing preserves temporarily-invalid text until Save/Preflight/Publish validation.
- Added Gavel-specific regression coverage for expression safety, workflow versioning, nested repeaters, preflight/rendering, public tokens, promotion boundaries, and generation consistency.

See `docs/GAVEL_ARCHITECTURE_PORT_2026-10-05.md` and `GAVEL_INTEGRATION_VALIDATION_2026-10-05.md`.
