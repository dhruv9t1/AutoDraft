## Conflict Detection Report

### BLOCKERS (0)

(none — no LOCKED-vs-LOCKED ADR contradictions; no UNKNOWN/low-confidence classifications; no cycles in the cross-ref graph)

### RESOLUTIONS (2026-05-05)

- variable-format-divergence → resolved by user: canonical token is `{variable name}` (curly braces). See decisions.md D-009. PRD FR006, project-overview, and `documentExtraction.ts` regex must be migrated.
- template-merge-divergence → resolved by user: in-place append (Journey 1.2 step 7). See decisions.md D-010. Scope §4 Q11 (fork) and §4 Q13 (union) are superseded.

### WARNINGS (2)

[WARNING] Variable-format divergence for REQ-variable-formatting (variable-format-divergence)
  Found: docs/Journey_1.1_Create_New_Template_PRD.md FR006 specifies "[variable name]" (single square brackets); docs/business-docs/01-project-overview.mdc Journey 1.1 step 6 also specifies "[variable name]" (single square brackets); docs/stories/3-variable-processing-and-display.md narrative/AC text says "{variable name}" (curly braces); docs/stories/3-variable-processing-and-display.md Dev Agent completion notes confirm the actual implementation in word-extension/src/services/documentExtraction.ts uses "[[variable name]]" (DOUBLE square brackets) via regex /\[\[([^\]]+)\]\]/g.
  Impact: Three incompatible token formats are documented for the same variable. Cross-journey consistency (Journey 1.1 → 1.2 → 1.3) and manual user-edit detection both depend on a single canonical format. Synthesizing one variant silently would either (a) invalidate already-shipped Story 1.1/1.3 implementation, or (b) contradict the PRD that the roadmapper will treat as authoritative.
  → Pick one canonical format and (1) update PRD FR006 + project-overview, (2) reconcile Story 1.3 narrative, (3) update / confirm the implementation regex. Recommend `[[variable name]]` if shipped code is to be preserved; otherwise migrate code to `[variable name]`.

[WARNING] Cross-journey template-update behavior contradiction for REQ-cross-template-merge-behavior (template-merge-divergence)
  Found: docs/business-docs/Scope, behavior & goal.md §4 Q11 says "always create new template if user adds or edits new variables in template" (fork-on-edit); same file §4 Q13 says "merge with existing ones" if a template already has variables; docs/business-docs/01-project-overview.mdc Journey 1.2 step 7 says "append new variables with old ones, against the template name in Database" (in-place append).
  Impact: Three semantically incompatible policies for what happens when variables change against an existing template — fork (new template), merge (variable-level union), or in-place append. Same precedence (PRD-vs-PRD vs DOC), so default ordering does not resolve. Roadmapper cannot generate Journey 1.2 acceptance criteria without picking one.
  → Choose one policy (recommend in-place append for V3 consistency with the canonical Journey 1.2 narrative) or split into two requirements with explicit branch conditions, before routing to gsd-roadmapper.

### INFO (3)

[INFO] Auto-resolved: SPEC vs SPEC LLM sampling parameter divergence (llm-sampling-divergence)
  Note: docs/LLM_TRAINING_PLAN.md §5.3 Modelfile specifies `temperature 0.1, top_p 0.9, top_k 40, repeat_penalty 1.1` for the deployed Ollama model; docs/DETERMINISM_AND_ACCURACY_TRACK.md Phase 0 + Phase 4 amendment 2 explicitly OVERRIDES these to `temperature 0, top_p 1, top_k 1, seed 42` and instructs "carry Phase 0 determinism into the Modelfile" (dated 2026-05-05 with explicit Decision Log entry). Both docs are SPEC; per the doc-conflict-engine, lower-precedence-wins-by-default does not apply (same level), but DETERMINISM_AND_ACCURACY_TRACK explicitly amends LLM_TRAINING_PLAN (companion-doc relationship declared in the document header) — treated as authorial supersession and auto-resolved. Synthesized intel uses DETERMINISM_AND_ACCURACY_TRACK values.

[INFO] Auto-resolved: SPEC training data source supersession
  Note: docs/LLM_TRAINING_PLAN.md §2.3 Step 3 specifies an interactive `scripts/review_tool.py` CLI as the gold-data source. docs/DETERMINISM_AND_ACCURACY_TRACK.md Phase 4 amendment 1 explicitly skips that CLI and substitutes the `variable_corrections` Postgres table populated by Phase 3 in-app correction capture. Authorial amendment in DETERMINISM_AND_ACCURACY_TRACK supersedes; intel reflects the table-driven path.

[INFO] Out-of-scope workstream noted, not conflicted
  Note: docs/indian-laws-vector-db-plan.md is a 20-week orthogonal workstream (vector DB for Indian legal corpus, sidebar search, citation generation). It does not conflict with Journey 1.1 template-creation but should be scoped as a distinct epic by the roadmapper rather than folded into the Journey 1.x flow. No precedence decision required.
