# AutoDraft v1.3 — Gavel-inspired automation architecture

Date: 2026-10-05

This port layers Gavel-style workflow/document-automation concepts onto AutoDraft's existing v1.2 Clio-style canonical legal data and v1.1 extraction/binding architecture. It intentionally does **not** copy Gavel's product or private implementation. The implementation uses AutoDraft semantic field keys, immutable template versions, tenant RLS, and Word binding safety.

## Implemented architecture

### 1. One safe expression engine

`backend/app/domain/expressions.py` defines a bounded JSON AST used consistently by workflow visibility, calculations, template conditions, and repeat collection expressions. Supported operations include comparisons, AND/OR/NOT, existence checks, arithmetic, concatenation/coalescing, conditional expressions, date math, and formatting. Expressions can reference canonical matter data, workflow variables, and the current repeater item. Unknown operations, excessive depth, and excessive node counts are rejected. No `eval`, arbitrary Python, SQL, filesystem, or AI call is available to the expression language.

### 2. Versioned workflows and sessions

`workflows` owns workflow identity. `workflow_versions` stores immutable published definitions. Editing a published workflow creates/uses a later draft. `workflow_sessions` pin the exact workflow version that started them so later edits cannot change a live client/internal session.

A workflow definition contains ordered pages, questions, calculations, visibility conditions, and repeaters. Repeaters can contain repeaters, allowing nested collections such as companies → directors or children → assets.

Client-facing sessions use an unguessable token; the database stores only its SHA-256 hash. A minimal token-routing table exists outside tenant RLS only to bootstrap organization context, after which session data is read under the correct tenant setting.

### 3. Explicit legal-data promotion

Workflow answers/calculations do not automatically become canonical matter facts. Completion only freezes the workflow result. An authenticated lawyer can explicitly invoke `POST /api/workflow-sessions/{id}/apply-to-matter` after review. The promotion path:

- requires a completed session attached to a matter;
- considers exact semantic keys only;
- writes only to **existing active matter-scoped Field Definitions**;
- runs the normal deterministic field validation;
- records workflow provenance;
- reports unknown keys and rejected values instead of creating fields implicitly.

This preserves AutoDraft's legal-review boundary while still enabling Gavel-style data reuse.

### 4. Template automation blueprint

Each reusable template has an editable automation draft and can publish a blueprint against one immutable `template_version`. The blueprint has three primitives:

- **bindings** — a Word content-control tag rendered from a semantic key or expression;
- **conditions** — a tagged Word content-control region retained/removed by a boolean expression;
- **repeaters** — a tagged Word region cloned for every item in a collection or collection expression.

Nested repeaters evaluate against the current parent item, not the top-level matter object.

### 5. Word authoring and preflight

The taskpane can wrap the current selection as an AutoDraft condition or repeater using the centralized Word operation queue. Template preflight opens the saved DOCX package and verifies every referenced binding/condition/repeater tag before automation can be published. Missing regions block publication.

### 6. Headless DOCX generation

`POST /api/generation/headless` can render:

- one immutable template version; or
- a published Document Set version with its pinned immutable templates.

The renderer works on the DOCX package rather than requiring Word to be open. It replaces semantic bindings, removes false conditional regions, clones repeating regions recursively, and returns generated DOCX artifacts. Generated artifacts can also be saved as Matter Documents with checksum/byte-size provenance.

Generation enforces identity consistency: a Generation Run cannot be combined with another matter, another Document Set version, or an unrelated Workflow Session.

### 7. Generation scope deliberately not claimed

This release produces **DOCX only**. It does not claim production PDF conversion. A real PDF converter can later be placed behind an artifact conversion service without changing the workflow/template model.

The renderer is regression-tested against synthetic Open XML packages, but final Word-host fidelity still requires Mac/Windows Word smoke testing on real legal templates.

## Main files

- `backend/app/domain/expressions.py`
- `backend/app/domain/workflows.py`
- `backend/app/domain/template_automation.py`
- `backend/app/repositories/workflows.py`
- `backend/app/repositories/automation.py`
- `backend/app/services/automation_data.py`
- `backend/app/services/generation_service.py`
- `backend/app/api/workflows.py`
- `backend/app/api/automation.py`
- `backend/migrations/20261005000016_gavel_automation.sql`
- `word-extension/src/taskpane/components/AutomationPanel.tsx`
- `word-extension/src/services/word/automationRegionService.ts`

## Design boundary

The hierarchy after v1.3 is:

1. **Clio-style canonical legal data** — Matters, Contacts/Participants, Field Definitions/Values, Practice Areas/Stages, Document Sets.
2. **Gavel-style automation** — Workflows, calculations, branching, repeaters, template automation, headless generation.
3. **AutoDraft Word reliability** — immutable binding IDs, serialized Word mutation, verification/reconciliation, full DOCX snapshots.
4. **AutoDraft AI/extraction** — deterministic candidates, optional Jev System-1, Qwen System-2, lawyer review.

That separation is intentional: workflow logic operates on semantic legal data and never becomes a second field-identity system.
