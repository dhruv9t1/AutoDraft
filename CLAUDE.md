# Word Add-in Project

## Project Structure
- `word-extension/` — Frontend: React 18 + TypeScript, Fluent UI v9, Webpack, Office.js
- `backend/` — Backend: Python 3.11+ (FastAPI), PostgreSQL (asyncpg), Ollama-compatible AI

## Frontend Commands
- Build: `cd word-extension && npm run build`
- Dev server: `cd word-extension && npm run dev-server`
- Lint: `cd word-extension && npm run lint`
- Lint fix: `cd word-extension && npm run lint:fix`
- No test runner configured

## Backend Commands
- Install: `cd backend && pip install -r requirements.txt`
- Test: `cd backend && pytest -q`
- Run: `cd backend && python run.py`

## Frontend Coding Conventions
- React: `import * as React from "react"` (not default import)
- Fluent UI v9: destructured named imports from `@fluentui/react-components`
- Components: PascalCase, use `lazy()` for code splitting large components
- Services: camelCase files in `word-extension/src/services/`
- Types: PascalCase interfaces, no `I` prefix, in `types.ts`
- Styles: `makeStyles` from Fluent UI
- tsconfig enforces: `noUnusedParameters`, `noImplicitReturns`
- Target: modern Microsoft Word webviews (WebView2 / current supported Office hosts); IE 11 is not supported by React 18

## Backend Coding Conventions
- See `backend/CLAUDE.md` for details
- Python 3.11+, FastAPI, Pydantic v2 camelCase aliases, standard logging

## Variable identification & wrapping rules

These rules govern the end-to-end pipeline that turns AI-identified spans into
Word content controls in the document while preserving the source text. Observed behaviour
violations have caused real bugs (variables silently dropped, ghost form
fields, parent spans failing to wrap when their children are wrapped first).

### Keep both versions: parent and child spans coexist

The product requirement is to **keep all identified variables**, including
both a wider label-anchored span (e.g. `Cheque No.: 123456`) and a bare span
sitting inside it (`123456`). Substring-overlap dedup is intentionally
disabled.

What this means in code:
- **Backend** (`backend/app/ollama_service.py` + `backend/app/post_processing.py`):
  deterministic anchors and LLM candidates are merged without substring-overlap
  deletion. Exact span duplicates are removed, while the same current text at
  different source positions or under different semantic field names is preserved
  (for example Invoice No. `192` and Delivery Challan No. `192`).
- **Frontend** (`word-extension/src/services/documentExtraction.ts` +
  `App.tsx` step-4 merge + `TemplateCreationForm.tsx` streaming reconcile and
  batch fallback): mirror the backend. Only `dedupVariablesByOriginalText`
  runs. Do NOT call `dedupSubstringOverlap`.
- The two functions stay defined as named exports so any future path can opt
  in, but no current call site uses them.

### Wrapping rule: immutable structural binding plan, longest claim wins

The production wrapping path is `wrapVariablesWithBindingPlan` in
`word-extension/src/services/wrappingPipeline.ts`. The older flat-text helpers
remain only as compatibility/test utilities; they are not the production
mutator.

1. `extractDocumentStructure()` builds the canonical document representation
   used both for extraction and binding. It includes body paragraphs, table
   cells, and primary headers/footers in deterministic segment order. Segments
   in the same Word story are separated by one character; different stories
   use a one-character hard boundary in the planner so matching cannot bridge
   unrelated Word stories while backend source offsets stay numerically aligned.
2. `buildBindingPlan()` is pure and does not mutate Word. It grounds each
   eligible variable against that structure, resolves repeated values by source
   position when needed, applies longest-wins overlap resolution, and records
   per-variable conflicts. A variable that cannot be grounded, is ambiguous,
   or crosses an unsupported story boundary is skipped without blocking other
   safe bindings. An existing content control with the same immutable binding
   ID but unexpected text remains a blocking integrity conflict.
3. `commitBindingPlan()` is the only mutation stage. It creates controls with
   immutable binding IDs, verifies the exact controls/text after insertion,
   persists occurrence/control/location evidence in the AutoDraft manifest, and
   rolls back exactly the controls created by the failed transaction if either
   Word verification or manifest persistence fails.
4. `wrapVariablesWithBindingPlan()` reports real planner outcomes:
   `missedFlat` counts ungrounded variables, `missedRange` counts ambiguous or
   unsupported structural ranges, and `skippedAlreadyWrapped` includes verified
   pre-existing bindings, longest-wins overlap skips, and review-only rows.

Variable list membership is unchanged by longest-wins overlap handling. Parent
and child candidates may both remain visible in the form/template data even
when only the longest overlapping span owns the Word content control.

The compatibility export `wrapVariablesViaFlatText` forwards to the binding-plan
implementation for older code, but new production callers must use
`wrapVariablesWithBindingPlan`.

### Confidence semantics

- Deterministic-extractor hits (Phase 1, regex-based) emit
  `confidenceScore: 1.0`.
- LLM hits emit a value in `[0, 1)` set by the model.
- The `1.0` value is the deterministic-extractor signature — use it when
  filters need to exempt extractor hits (e.g. the list-marker filter must not
  drop a real PIN code from the regex extractor just because it's six digits).
