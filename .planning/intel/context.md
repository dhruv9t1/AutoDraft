# Context (DOC Intel)

> Synthesized from DOC-classified sources:
> - `docs/business-docs/01-project-overview.mdc`
> - `docs/clarifying_questions_answers.md`
> - `docs/business-docs/journey-1-q&a.md`
>
> Verbatim-style notes attributed to source. Used by the roadmapper as background context, not requirements.

---

## Topic: Product Vision

- source: docs/business-docs/01-project-overview.mdc
- The product is a Word add-in for lawyers that manages legal-document templates with variable-based filling.
- Master data holds templates by type (e.g., Legal Notice). Variables come from templates and from in-memory state.
- The whole UI resembles MS Word; reference image: `docs/business-docs/MSWord-screenshot.png`. The Office add-in (React app) is loaded on the LEFT side of the user document.
- Expectations: focus on drafting only, nothing else. User-friendly editing screens and variable injection in template after form/table is filled.

---

## Topic: User Journeys (canonical narrative)

- source: docs/business-docs/01-project-overview.mdc

### Journey 1.1 — New Template Drafting
1. User creates a new template with label "Create a new template", description "Turn your current document into a standard template".
2. Enter template name (text), select Template Type, select template subtype, add note/description.
3. CTA "Auto Detect Variables" identifies variables via AI LLM.
4. AI must process document and identify ≥80% of variables.
5. UI shows information: "These many variables are identified."
6. Process the template having variables with name format `[variable name]`.
7. Below the CTA, ask user to confirm via checkbox "I confirm the detected and custom added variables".
8. Below that, two CTAs side-by-side: "Create Template" + "Choose Existing Template".
9. "Create Template" → save variables against template name in DB. See Journey 1.2 for follow-up.
10. "Choose Existing Template" → Journey 1.3.

### Journey 1.2 — Update Master Template (downstream from 1.1)
1. User selects "Template type" from a searchable select bar.
2. CTA identifies variables; AI processes for new variables.
3. ≥80% threshold check; UI shows new variables identified.
4. Process template with `[variable name]` formatting.
5. Checkbox: "Update the Master Template".
6. If checked → append new variables with old ones, against the template name in DB.

### Journey 1.3 — Fill Form with Variables (downstream from 1.1 or 1.2)
1. After "Create Template" (Journey 1.1) or "Fill the form" (Journey 1.2) → new screen opens.
2. Screen shows all dynamic variables as form text inputs with validation.
3. User clicks "Apply Data" to inject values.
4. Open preview in document; user can edit.
5. Save each variable in DB.

---

## Topic: Stakeholder Clarifications — Journey 1.1

- source: docs/clarifying_questions_answers.md, docs/business-docs/journey-1-q&a.md (these two files are near-duplicates; same Q&A content)

### Scope, behavior & goal
- "Create Template" without confirming checkbox → Disable the button.
- "Choose Existing Template" availability → Any time.
- AI detects 0% or <80% → ask user to define manually.

### User Interface
- "Create a new template" placement → per provided screenshot.
- Template name + type + subtype on the same screen (not separate steps).
- Detected variables displayed as a list (NOT inline in document only).

### Default state
- Default view → per provided screenshot.
- "Auto Detect Variables" enabled only after entering template details.

### Integration / business logic
- One template per session per document (no multi-template per session).
- Auto-save previous template if user goes back to create another.

### User roles & permissions
- No roles required — first release has only one user type.

### Edge cases
- Empty document on "Auto Detect Variables" → ask user to upload a document.
- No variables in plain-text doc → ask user to define manually.
- Manual add/edit of variables → done in document directly (no separate UI).

### Scope boundaries
- Journey 1.1 is for creating NEW templates only (no editing here).
- Out of scope: template deletion, template sharing.

### Business context
- Why now: decrease the time to draft a template.
- Primary users: lawyers, paralegals, legal assistants.
- Success: user can draft a template in less than 1 minute.

---

## Topic: Cross-journey behavioral clarifications

- source: docs/business-docs/Scope, behavior & goal.md (also classified as PRD; behavioral clarifications captured here for context)
- Drafting is the time-consuming bottleneck the system attacks. Goals: faster + accurate + consistent + easier + quicker drafting.
- Post-AI-identification UX: show list of variables; ask user to fill values in form. Re-selecting same template loads a TABLE view of variables and allows entering new values.
- Multi-template selection: ONE at a time.
- Main goal: faster template creation, accuracy, user adoption.
- Template selection UI: searchable creatable dropdown. Template-name only when displayed (no description/preview/count). Top 5 recently used templates surfaced.
- Existing-template handling: "always create new template if user adds or edits new variables" (V1) — but also "merge with existing ones" (V2) for AI-identified variables. **This contradiction is captured as a competing-variants WARNING in INGEST-CONFLICTS.md.**
- Automatic save vs explicit confirm: explicit confirmation required.
- Edge case: API failure → fallback to manual entry.
- Edge case: wrong template type for document → error + ask user to select different template.
- Out of scope: template management, variable management, document preview. Exception: in-document `[variable]` edits should sync against the template.
- Adoption goal: all lawyers (no segmentation).

---

## Topic: Technical Stack (existing)

- source: docs/Journey_1.1_Create_New_Template_PRD.md §6.2, docs/business-docs/01-project-overview.mdc, all story files
- AI service: existing `backend/src/ollama.rs` (Rust + Ollama-compatible API; current model `gpt-oss:120b`)
- Document extraction: existing `word-extension/src/services/documentExtraction.ts` (Office.js)
- Backend API: existing handlers in `backend/src/handlers.rs`; models in `backend/src/models.rs`
- Database: PostgreSQL with sqlx migrations under `backend/migrations/`; existing migration `20250127000001_create_variables_table.sql` for variables
- Frontend: React 18 + TypeScript + Fluent UI v9 + Webpack + Office.js; tsconfig targets ES5 with IE11 support
- Existing frontend services: `aiVariableService.ts`, `documentExtraction.ts`, types in `services/types.ts`
- Existing components: `App.tsx` (with `viewMode="templateCreation"` routing), `TemplateCreationForm.tsx` (763 lines, completed for Story 1.1)

---

## Topic: Risk register (consolidated)

- source: docs/Journey_1.1_Create_New_Template_PRD.md §7.4, individual stories
- High: AI variable-detection accuracy (80% threshold not always achievable); user-confirmation workflow dependency
- Medium: template naming/type validation; DB save reliability; AI service availability + response time; document-formatting impact from text replacement; manual variable-edit format inconsistencies
- Low: UI rendering performance; form-field validation edge cases

---

## Topic: Dependencies between journeys

- source: docs/Journey_1.1_Create_New_Template_PRD.md §6.1
- Journey 1.1 → Journey 1.2: post-create transition; DB schema must support template updates; variables can be appended.
- Journey 1.1 → Journey 1.3: "Choose Existing Template" navigates to fill-form view; variable format must be consistent (see WARNING in conflicts report regarding `[variable name]` vs `[[variable name]]` vs `{variable name}`).

---

## Topic: Out-of-band workstream — Indian Laws Vector DB

- source: docs/indian-laws-vector-db-plan.md
- Separate 20-week workstream for a vector-DB-backed legal-corpus retrieval system, integrating with the Word add-in as a sidebar legal-search panel + citation generator + compliance checker.
- Not part of Journey 1.1 critical path. Roadmapper should sequence after the variable-extraction track or in parallel as a distinct epic.
