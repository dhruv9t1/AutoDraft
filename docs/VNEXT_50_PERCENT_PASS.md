# AutoDraft vNext — 50% Reliability Pass

This release intentionally implements only the first high-value half of the Reliability Architecture Plan. It is **not** the final vNext architecture and deliberately leaves the second half for a later ZIP so changes remain reviewable and testable.

## Implemented in this pass

### Reliability / data contracts
- asyncpg pool-level `json` / `jsonb` codecs so JSONB is decoded to Python data structures centrally.
- Request/correlation IDs are included in controlled application errors.
- Known database transport failures are surfaced as `DATABASE_UNAVAILABLE` instead of an unexplained generic error.
- Added JSONB codec regression coverage and a golden-corpus foundation.

### AI subsystem
- Added a central `AIGateway` facade in front of Ollama.
- Added typed AI errors: provider unavailable, model unavailable, timeout, invalid output and context-too-large.
- Added `/api/health/live`, `/api/health/ready`, and `/api/health/ai`.
- Readiness now verifies reachability, configured model availability and a small structured-output probe.
- vNext default models are `qwen3:4b`, with separate field/drafting/review configuration hooks.
- Known AI dependency failures return controlled typed responses.

### Field detection safety
- Detection now fails closed when an extraction chunk fails instead of treating partial/deterministic output as successful fields.
- Detection status contract is now: `completed`, `completed_with_review`, `no_fields`, `unavailable`, `failed`.
- Progressive SSE chunks are UI progress only. Word is not mutated until the authoritative complete result is available.
- Removed the old color-only emergency-success path after an AI failure.
- Existing semantic deduplication, stable binding UUIDs and deterministic grounding remain in place.

### Word reliability foundation
- Added a `WordOperationQueue` and routed the main drafting renderer and wrapping pipeline through it.
- Added a centralized Word capability service for WordApi 1.4/1.5, custom XML, content-control events, comments, compressed capture and desktop track-changes capability checks.
- Existing post-wrap tag reconciliation remains the source of truthful Linked / Needs review state.

### Lawyer-owned Intake
- Removed the hard-coded fallback questionnaire completely.
- AI-generated questions are explicitly unapproved suggestions.
- Added a blank-questionnaire path and lawyer controls to add, edit, delete and approve questions.
- Added explicit required/optional controls and safe question types for this pass.
- Publishing is blocked while any AI suggestion remains unapproved.
- Public intake form now exposes Required/Optional text, `required` / `aria-required`, field-specific validation summary and better server-error handling.
- Client answers are **not** auto-imported into matter facts. The lawyer selects reviewed answers before import.

### Template lifecycle
- Completing the current document no longer creates a reusable template.
- Saving a reusable template is a separate explicit action.
- Added template duplication alongside existing rename/delete.

### Frontend service foundation
- Added a central typed `apiClient` and migrated the workspace service to it.
- Existing drafting/review states and truthful citation states are retained.

## Intentionally deferred to the second half

- Full thin-`main.py` router/service/repository/domain decomposition.
- Complete structural `DocumentSegment` model and explicit normalized shadow-document abstraction.
- Full immutable `BindingPlan { operations, conflicts, canCommit }` implementation across every Word mutation.
- Routing every remaining Office.js call through the Word operation queue.
- Content-control change/delete event handling and full startup reconciliation.
- Full compressed DOCX template snapshots and Matter Documents repository/open-in-Word workflow.
- Intake sections, drag/drop reordering, versioning, conditional display and file uploads.
- Matter fact conflict-resolution UI and derived-fact system.
- Full canonical `DraftResult` Pydantic model across every drafting route.
- Native Word review comments and Track Changes integration.
- Complete 16-document golden corpus with precision/recall/F1 thresholds.
- Full real-environment fault injection with PostgreSQL/Ollama/Word hosts.
- Production authentication/RBAC/RLS/storage hardening.

## Validation performed for this ZIP

- Python source compile/AST validation: passed.
- Backend regression suite: **34 passed, 1 skipped** using a test-only asyncpg import shim because the execution sandbox does not have `asyncpg` installed. The skipped test is the opt-in real PostgreSQL JSONB integration gate, which requires `AUTODRAFT_TEST_DATABASE_URL`.
- Backend application import using the same test-only shim: passed; new health routes are registered.
- TypeScript compiler was run with the globally available compiler. After filtering only errors caused by unavailable `node_modules` / Office typings, there were **no code-level diagnostics** from this pass.
- `npm ci --offline` could not complete because `yoctocolors-cjs@2.1.3` was not present in the sandbox cache. Therefore webpack/Vitest are **not claimed as run** here.
- Real PostgreSQL, Ollama `qwen3:4b`, and Microsoft Word end-to-end checks still belong to the local release-candidate pass.
