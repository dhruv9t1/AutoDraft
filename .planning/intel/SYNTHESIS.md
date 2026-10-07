# Synthesis Summary

> Single entry point for `gsd-roadmapper`. Points to per-type intel files and the conflicts report.

## Doc counts by type

- Total docs synthesized: **14**
- ADR: **0**
- SPEC: **9**
  - 6 implementation stories: `docs/stories/1-` through `6-`
  - `docs/DETERMINISM_AND_ACCURACY_TRACK.md`
  - `docs/LLM_TRAINING_PLAN.md`
  - `docs/indian-laws-vector-db-plan.md`
- PRD: **2**
  - `docs/Journey_1.1_Create_New_Template_PRD.md`
  - `docs/business-docs/Scope, behavior & goal.md`
- DOC: **3**
  - `docs/business-docs/01-project-overview.mdc`
  - `docs/clarifying_questions_answers.md`
  - `docs/business-docs/journey-1-q&a.md`
- UNKNOWN-low-confidence: 0

## Decisions

- Locked ADRs: **0** (no source carried `locked: true`; none classified as ADR)
- Derived (non-ADR) decisions captured: **8** (D-001 through D-008 in `decisions.md`) — flagged for promotion to formal ADRs by the roadmapper if hard locking is needed.

## Requirements

- Functional requirements (Journey 1.1): **10** — REQ-template-creation-form, REQ-template-metadata-input, REQ-auto-detect-variables-button, REQ-ai-variable-detection, REQ-variable-detection-display, REQ-variable-formatting, REQ-variable-confirmation, REQ-create-template-button, REQ-choose-existing-template, REQ-template-auto-save
- Non-functional requirements: **4** — REQ-nfr-performance, REQ-nfr-usability, REQ-nfr-reliability, REQ-nfr-accuracy
- Cross-journey behavioral requirements: **3** — REQ-cross-template-merge-behavior, REQ-cross-template-selection, REQ-cross-fallback-on-failure
- **Total: 17 requirements** (1 carries a competing-variants WARNING: REQ-variable-formatting; 1 carries a competing-variants WARNING: REQ-cross-template-merge-behavior)
- Open questions captured: 6 (PRD §11)
- Out-of-scope items consolidated: 8

## Constraints (SPEC intel)

- Total constraints: **9**
- Breakdown by type:
  - implementation: 5 (one per story 1.1–1.3, 1.5–1.6)
  - api-contract + schema + nfr: 1 (Story 1.4 template-save endpoint + variables table)
  - protocol + nfr (LLM determinism/accuracy): 1 (DETERMINISM_AND_ACCURACY_TRACK, 5 phases)
  - protocol + nfr + api-contract (LLM training): 1 (LLM_TRAINING_PLAN)
  - schema + api-contract + protocol (vector DB): 1 (indian-laws-vector-db-plan, orthogonal workstream)
- Story status breakdown: 1 completed (Story 1.1), 1 in-progress (Story 1.3), 4 drafted (1.2, 1.4, 1.5, 1.6)

## Context (DOC intel)

- Topics covered: **8** (Product Vision, User Journeys, Stakeholder Clarifications, Cross-journey behavioral clarifications, Technical Stack, Risk register, Dependencies between journeys, Out-of-band workstream)

## Conflicts

- BLOCKERS: **0**
- WARNINGS: **2**
  - `variable-format-divergence` — `[variable name]` vs `{variable name}` vs `[[variable name]]` across PRD, Story 1.3 narrative, and Story 1.3 implementation
  - `template-merge-divergence` — fork-on-edit vs variable merge vs in-place append for cross-journey template updates
- INFO (auto-resolved): **3**
  - LLM sampling parameter divergence (DETERMINISM_AND_ACCURACY_TRACK supersedes LLM_TRAINING_PLAN Modelfile)
  - LLM training data source (corrections table supersedes review_tool.py CLI)
  - indian-laws-vector-db-plan flagged as orthogonal workstream

## Cross-ref graph

- Cycle detection: **passed** (DFS, no cycles found)
- Max depth observed: 2 (story → PRD → project-overview)
- All `cross_refs` to source-code paths and image assets are non-doc and ignored for cycle purposes.

## Pointers

- Per-type intel:
  - `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/decisions.md`
  - `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/requirements.md`
  - `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/constraints.md`
  - `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/context.md`
- Conflicts report: `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/INGEST-CONFLICTS.md`
- Original classifications: `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/classifications/`
- Manifest: `/Users/sandeepmehta/Documents/GitHub/word-addin/.planning/intel/INGEST-MANIFEST.yaml`

## Status

**AWAITING USER** — 2 competing-variants WARNINGs require explicit user resolution before the roadmapper can route. Variable-format choice and cross-journey merge-behavior choice both gate the Journey 1.1/1.2/1.3 acceptance criteria.
