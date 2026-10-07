# Decisions (ADR Intel)

> Synthesized from classified ADR sources. None of the 14 ingested docs were classified as ADR; this file is intentionally empty of formal architectural decisions. Implicit decisions captured from SPEC/PRD `Decision log` sections are listed below as **non-locked, derived** entries for downstream traceability only — they should be promoted to formal ADRs by the roadmapper if they need locking.

---

## Derived (non-ADR) decisions

### D-001: Do NOT rebuild the LLM variable-extraction pipeline from scratch
- source: docs/DETERMINISM_AND_ACCURACY_TRACK.md (Decision log, 2026-05-05)
- type: derived (SPEC-level decision, not a formal ADR)
- locked: false
- scope: backend/src/ollama.rs, LLM pipeline architecture
- statement: Existing `ollama.rs` already implements deterministic chunking, multi-tier validation, list-marker filtering, substring-overlap dedup, JSON sanitization, and streaming. New work must bolt onto it rather than replace it.

### D-002: Sequence cheap deterministic wins before fine-tuning
- source: docs/DETERMINISM_AND_ACCURACY_TRACK.md (Decision log, 2026-05-05)
- type: derived
- locked: false
- scope: LLM determinism / accuracy roadmap ordering
- statement: Phases 0–2 (sampling lockdown, regex extractors, multi-pass critic) ship before Phase 4 (Qwen 2.5-3B fine-tune). Inverts LLM_TRAINING_PLAN's GPU-first sequencing.

### D-003: Target F1 ≥ 0.95 + human-in-loop, not 100% accuracy
- source: docs/DETERMINISM_AND_ACCURACY_TRACK.md (Decision log, 2026-05-05; Honest framing)
- type: derived
- locked: false
- scope: variable-extraction success criteria
- statement: Open-ended legal-doc variable identification cannot be 100% pure-function-accurate. Practical 100% comes from user confirmation in the Word UI (the user is the final gate).

### D-004: Variables can be added/edited manually in the document
- source: docs/clarifying_questions_answers.md (§6), docs/Journey_1.1_Create_New_Template_PRD.md (FR006 AC6.3, Out of Scope §8)
- type: derived
- locked: false
- scope: variable editing UX
- statement: Users do NOT get a separate variable-management UI. Manual edits happen in-document using the variable-bracket format and are extracted on save.

### D-005: One template per session per document
- source: docs/clarifying_questions_answers.md (§4), docs/business-docs/journey-1-q&a.md (§4), docs/Journey_1.1_Create_New_Template_PRD.md (FR010)
- type: derived
- locked: false
- scope: template creation lifecycle
- statement: Users cannot create multiple templates from the same document in one session. Previous template auto-saves before a second creation attempt.

### D-006: User confirmation required before variables persist
- source: docs/business-docs/Scope, behavior & goal.md (§4 Q12), docs/Journey_1.1_Create_New_Template_PRD.md (FR007)
- type: derived
- locked: false
- scope: template creation flow
- statement: Identified variables MUST require explicit user confirmation (checkbox) before "Create Template" can be enabled.

### D-007: Single-screen layout for template creation form
- source: docs/clarifying_questions_answers.md (§2), docs/Journey_1.1_Create_New_Template_PRD.md (FR001 AC1.3, FR002 AC2.5), docs/stories/1-template-creation-form-ui.md (AC3)
- type: derived
- locked: false
- scope: TemplateCreationForm UI
- statement: All metadata fields (name, type, subtype, description) must be displayed on the same screen. No multi-step wizard.

### D-008: ≥80% AI variable-detection threshold gates UX path
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR004, NFR004), docs/business-docs/01-project-overview.mdc (Journey 1.1 step 4)
- type: derived
- locked: false
- scope: AI variable detection acceptance
- statement: AI must identify ≥80% of variables. Below threshold → prompt user to define manually (fallback to manual entry).

---

**Note for roadmapper:** No source document carries a `locked: true` flag. If any of D-001 through D-008 needs hard-block precedence, promote it to a formal ADR with `locked: true` before subsequent ingest cycles.

---

## User-resolved decisions (2026-05-05 ingest)

These resolve WARNINGS surfaced by the doc-conflict engine. They override the divergent source documents and MUST be treated as authoritative by the roadmapper.

### D-009: Variable token format is `{variable name}` (curly braces)
- source: user resolution at /gsd-ingest-docs run, 2026-05-05
- supersedes: docs/Journey_1.1_Create_New_Template_PRD.md FR006 (`[variable name]`); docs/business-docs/01-project-overview.mdc Journey 1.1 step 6 (`[variable name]`); shipped implementation in word-extension/src/services/documentExtraction.ts (`[[variable name]]`)
- type: user-locked
- locked: true
- scope: variable token rendering, extraction regex, persisted templates
- statement: The single canonical variable token in document text is `{variable name}` (single curly braces). Migration required:
  1. Update PRD FR006 + project-overview to specify curly braces.
  2. Confirm Story 3 narrative form is canonical.
  3. Migrate `documentExtraction.ts` regex from `/\[\[([^\]]+)\]\]/g` to `/\{([^}]+)\}/g`.
  4. Audit any persisted template content for the legacy `[[…]]` form and provide a one-shot migration.

### D-010: Template merge behavior is in-place append
- source: user resolution at /gsd-ingest-docs run, 2026-05-05
- supersedes: docs/business-docs/Scope, behavior & goal.md §4 Q11 (fork-on-edit); §4 Q13 (merge/union)
- aligns-with: docs/business-docs/01-project-overview.mdc Journey 1.2 step 7
- type: user-locked
- locked: true
- scope: cross-journey template-update flow (Journey 1.2)
- statement: When a user adds or edits variables in a document tied to an existing template, the new variables are appended in-place to the existing template's variable set. The template_id is retained — no fork, no union semantics, no immutability constraint. Roadmapper must generate Journey 1.2 acceptance criteria using this single policy.
