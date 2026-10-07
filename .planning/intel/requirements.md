# Requirements (PRD Intel)

> Synthesized from PRD-classified sources:
> - `docs/Journey_1.1_Create_New_Template_PRD.md` (Journey 1.1 PRD)
> - `docs/business-docs/Scope, behavior & goal.md` (cross-journey behavioral PRD)
>
> SPEC-classified user stories (`docs/stories/1-` through `6-`) refine these requirements with implementation-level acceptance criteria; their AC restatements are kept in `constraints.md`. Original PRD ACs win on conflict per ADR > SPEC > PRD precedence (PRD wins SPEC because no ADR exists for these scopes).

---

## Functional Requirements (Journey 1.1)

### REQ-template-creation-form
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR001)
- scope: Template Creation Form entry point
- description: User must access "Create a new template" feature with title "Create a new template" and subtitle "Turn your current document into a standard template".
- acceptance:
  - AC1.1: Option accessible from Office Add-in panel
  - AC1.2: Form displays specified title + subtitle
  - AC1.3: All form fields on the same screen (no multi-step wizard)

### REQ-template-metadata-input
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR002)
- scope: template metadata fields
- description: User must enter template name, select type, select subtype, and add description.
- acceptance:
  - AC2.1: Template name = text input
  - AC2.2: Template type = dropdown/select
  - AC2.3: Template subtype = dropdown/select
  - AC2.4: Description = multi-line text area
  - AC2.5: All fields visible on same screen

### REQ-auto-detect-variables-button
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR003)
- scope: Auto Detect Variables CTA
- description: CTA triggers AI-powered variable detection.
- acceptance:
  - AC3.1: Button displayed below metadata fields
  - AC3.2: Disabled until name + type + subtype entered
  - AC3.3: On click, calls AI LLM service
  - AC3.4: Document content passed to service
  - AC3.5: Loading indicator shown during processing

### REQ-ai-variable-detection
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR004, NFR004)
- scope: AI variable detection accuracy + edge cases
- description: AI must identify ≥80% of variables. Below threshold falls back to manual entry.
- acceptance:
  - AC4.1: AI processes document, identifies variables
  - AC4.2: System validates ≥80% detection
  - AC4.3: <80% (or 0%) → prompt "Ask user to define it manually"
  - AC4.4: Empty document → prompt "Ask user to upload a document"
  - AC4.5: Plain-text doc with no variables → prompt "Ask user to define it manually"

### REQ-variable-detection-display
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR005)
- scope: variable detection results UX
- description: Show variable count + list view.
- acceptance:
  - AC5.1: Display "We have identified X number of variables in the document"
  - AC5.2: Variables displayed as a list (NOT inline only — see WARNING in conflicts report regarding format)
  - AC5.3: User can view all detected variables

### REQ-variable-formatting
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR006), docs/business-docs/01-project-overview.mdc (Journey 1.1 step 6)
- scope: variable token format in document
- description: Detected variables are formatted in the document. **Format conflict — see WARNING in INGEST-CONFLICTS.md.**
- acceptance:
  - AC6.1: Variables formatted with bracket pattern in template body
  - AC6.2: Original text replaced in document
  - AC6.3: User can manually add/edit variables in document directly
- competing-variants:
  - PRD FR006 + project-overview: `[variable name]` (single square brackets)
  - Story 1.3 narrative: `{variable name}` (curly braces)
  - Story 1.3 implementation/tasks: `[[variable name]]` (double square brackets) — completion notes confirm regex `/\[\[([^\]]+)\]\]/g`

### REQ-variable-confirmation
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR007)
- scope: confirmation checkbox before save
- description: User must confirm detected + custom variables.
- acceptance:
  - AC7.1: Checkbox text "I confirm the detected and custom added variables"
  - AC7.2: Unchecked by default
  - AC7.3: Must be checked to enable Create Template

### REQ-create-template-button
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR008)
- scope: Create Template CTA + persistence
- description: Save template + variables to DB transactionally.
- acceptance:
  - AC8.1: Side-by-side with "Choose Existing Template"
  - AC8.2: Disabled until checkbox confirmed
  - AC8.3: On click, saves name + type + subtype + description + variables
  - AC8.4: Variables saved against template name
  - AC8.5: After save, transition to Journey 1.2

### REQ-choose-existing-template
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR009)
- scope: Choose Existing Template CTA
- description: Always-available navigation to Journey 1.3.
- acceptance:
  - AC9.1: Side-by-side with Create Template
  - AC9.2: Always available (not gated on variable detection)
  - AC9.3: On click, navigate to Journey 1.3

### REQ-template-auto-save
- source: docs/Journey_1.1_Create_New_Template_PRD.md (FR010)
- scope: lifecycle / single-template-per-session
- description: Auto-save template on navigation; one template per document per session.
- acceptance:
  - AC10.1: On navigation away, template auto-saves
  - AC10.2: Cannot create multiple templates from same doc in one session
  - AC10.3: Attempting another → previous saved first

---

## Non-Functional Requirements

### REQ-nfr-performance
- source: docs/Journey_1.1_Create_New_Template_PRD.md (NFR001)
- scope: end-to-end template creation, AI inference
- acceptance:
  - Template creation completes <1 minute
  - AI variable detection completes <10s for documents up to 5MB
  - UI remains responsive during AI processing

### REQ-nfr-usability
- source: docs/Journey_1.1_Create_New_Template_PRD.md (NFR002)
- scope: form accessibility + UX
- acceptance:
  - All form fields clearly labeled
  - Error messages clear and actionable
  - Loading indicators on async ops
  - UI follows provided screenshot/mockup

### REQ-nfr-reliability
- source: docs/Journey_1.1_Create_New_Template_PRD.md (NFR003)
- scope: AI fallback + DB integrity
- acceptance:
  - AI service failures fall back to manual entry
  - Empty document validation prevents invalid ops
  - Database save operations are transactional and atomic

### REQ-nfr-accuracy
- source: docs/Journey_1.1_Create_New_Template_PRD.md (NFR004)
- scope: AI threshold
- acceptance:
  - AI identifies ≥80% of variables (success threshold)
  - Detection accuracy validated before allowing template creation

---

## Cross-Journey Behavioral Requirements (from `Scope, behavior & goal.md`)

### REQ-cross-template-merge-behavior
- source: docs/business-docs/Scope, behavior & goal.md (§4 Q11, Q13)
- scope: existing template + variable-update behavior across Journeys 1.1/1.2
- description: Cross-journey behavior for handling variable updates against existing templates. **Competing-variants conflict — see WARNING in INGEST-CONFLICTS.md.**
- competing-variants:
  - V1 (Scope, behavior & goal Q11): "Always create a new template if user adds or edits new variables in template" — implies forking behavior
  - V2 (Scope, behavior & goal Q13): "Merge with existing ones" if a template already has variables
  - V3 (project-overview Journey 1.2 step 7): "Append new variables with old ones, against the template name in Database" — explicit append into the same record
  - Resolver notes: V2 and V3 are roughly compatible; V1 contradicts both. User must pick.

### REQ-cross-template-selection
- source: docs/business-docs/Scope, behavior & goal.md (§1 Q3, §3 Q9, §3 Q10)
- scope: template-selection dropdown behavior (relevant to Journeys 1.2/1.3)
- description: Single template at a time; empty searchable dropdown by default; "Identify Variables" + "Fill the form" disabled when no template selected.
- acceptance:
  - One template at a time (no multi-select)
  - Default state: empty searchable creatable dropdown
  - Top 5 recently used templates surfaced
  - Both action buttons disabled when no template selected

### REQ-cross-fallback-on-failure
- source: docs/business-docs/Scope, behavior & goal.md (§6 Q16, Q17), docs/clarifying_questions_answers.md (§6)
- scope: AI failure / API failure
- acceptance:
  - AI cannot identify variables → ask user to manually identify
  - API failure / timeout → fallback to manual entry
  - Wrong template type / empty document → error message + ask user to select different template

---

## Success Metrics (PRD §9)

- source: docs/Journey_1.1_Create_New_Template_PRD.md (§9)
- Primary: time-to-create-template < 1 minute
- Secondary:
  - AI ≥80% recall in ≥90% of cases
  - ≥80% of users create first template without errors
  - <5% template creation error rate
  - Users report template creation faster than manual

---

## Out of Scope (Journey 1.1)

- source: docs/Journey_1.1_Create_New_Template_PRD.md (§8), docs/clarifying_questions_answers.md (§7), docs/business-docs/Scope, behavior & goal.md (§7)
- Template deletion
- Template sharing
- Template editing (existing templates) — except: in-document `[variable]` edits sync back to template
- Template management UI (list/search/filter)
- Separate variable management UI (variables edited in-document)
- Document preview with variables filled
- Template versioning
- Template import/export

---

## Open Questions (PRD §11) — flagged for roadmapper

1. Available template types and subtypes (list TBD)
2. Maximum variables per template
3. Duplicate template-name policy
4. Character limits for name/description
5. Maximum document size for AI processing
6. Limit on templates per user
