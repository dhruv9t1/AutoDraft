# Roadmap: Legal Doc Template Builder

## Overview

Milestone 1 ships Journey 1.1 → 1.6 (the full new-template creation flow inside
the Word add-in) plus Determinism-track Phases 0–2 (cheap deterministic wins on
the LLM pipeline that need no GPU and no fine-tune). Phase 1 closes out the
already-shipped Story 1.1 form work, Phases 2–6 deliver the remaining Story
1.2–1.6 functionality (auto-detect, processing/display, transactional save,
existing-template navigation, auto-save lifecycle), and Phases 7–9 lock down
LLM determinism, layer regex extractors as anchors, and add a multi-pass critic
loop. Milestone 2 picks up Determinism Phases 3 (correction capture) and 4
(Qwen 2.5-3B fine-tune); Phase 5 (continuous eval) is cross-cutting and
activates after Milestone 2. The Indian-laws vector DB is a separate Milestone
3 epic.

## Milestones

- 🚧 **Milestone 1: Journey 1.1 → 1.6 ship + F1 ≥ 0.95** — Phases 1–9
- 📋 **Milestone 2: Correction capture + fine-tune** — Determinism Phases 3 & 4 (planned)
- 📋 **Milestone 3: Indian-laws vector DB** — orthogonal 20-week epic (planned)

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [x] **Phase 1: Story 1.1 closeout** - Template Creation Form UI is shipped; capture validated state
- [ ] **Phase 2: Auto Detect Variables CTA** - Story 1.2: button, extraction, ≥80% threshold gating, fallbacks
- [ ] **Phase 3: Variable processing & display** - Story 1.3: dedup, list display, in-document `{variable name}` rendering, format migration (D-009)
- [ ] **Phase 4: Confirmation & transactional save** - Story 1.4: checkbox-gated CTA, atomic save, Journey 1.2 transition
- [ ] **Phase 5: Choose Existing Template navigation** - Story 1.5: always-on CTA, route to Journey 1.3 view
- [ ] **Phase 6: Auto-save lifecycle** - Story 1.6: navigation auto-save + one-template-per-session enforcement
- [ ] **Phase 7: LLM determinism lockdown** - Determinism Phase 0: sampling + JSON schema + self-hosted model (NEXT)
- [ ] **Phase 8: Deterministic regex extractors** - Determinism Phase 1: extractors module + anchor-list strategy
- [ ] **Phase 9: Multi-pass critic loop** - Determinism Phase 2: critic method + recall lift + F1 ≥ 0.95 verification

## Phase Details

### Phase 1: Story 1.1 closeout
**Goal**: Confirm shipped Template Creation Form UI satisfies its requirements and is ready to host Phase 2's CTA additions
**Depends on**: Nothing (already shipped)
**Requirements**: TPL-FORM-01
**Success Criteria** (what must be TRUE):
  1. User can open the add-in panel in Word and see the "Create a new template" view with title "Create a new template" and subtitle "Turn your current document into a standard template"
  2. User can fill template name (text), select template type (searchable combobox), select template subtype (dependent combobox), and enter description (multi-line textarea) on a single screen
  3. `viewMode="templateCreation"` routing in `App.tsx` reaches `TemplateCreationForm.tsx` without console errors on Word desktop and Word Online
**Plans**: TBD
**UI hint**: yes

### Phase 2: Auto Detect Variables CTA
**Goal**: User can trigger backend AI variable extraction from the open document and receive a usable result or a clear fallback prompt
**Depends on**: Phase 1
**Requirements**: TPL-DETECT-01, TPL-DETECT-03, NFR-USABILITY-01, NFR-ACCURACY-01
**Success Criteria** (what must be TRUE):
  1. User sees the "Auto Detect Variables" CTA below the metadata fields, disabled until name + type + subtype are all entered
  2. On click, document content is extracted via Office.js, sent to the existing `backend/src/ollama.rs` service, and a loading indicator is shown while the UI remains responsive
  3. When AI recall is ≥80% the result enters the Phase 3 display path; when <80%, empty-document, no-variables, or AI-service-failure occurs, the user sees a specific manual-entry prompt
  4. Detection completes in <10s for documents up to 5MB
**Plans**: TBD
**UI hint**: yes

### Phase 3: Variable processing & display
**Goal**: Detected variables are deduplicated, displayed as a list, rendered in-document using the canonical `{variable name}` format, and remain editable in-document
**Depends on**: Phase 2
**Requirements**: TPL-DETECT-02, TPL-FORM-02
**Success Criteria** (what must be TRUE):
  1. User sees "We have identified X number of variables in the document" plus a list view of all detected variables (case-insensitively deduplicated, sorted by document position, AI-confidence scores preserved on AI-identified items)
  2. Original variable text in the document is replaced with `{variable name}` (curly-brace single token), formatting preserved on multiple-occurrence replacement
  3. `extractVariablesFromDocument()` regex is migrated from `/\[\[([^\]]+)\]\]/g` to `/\{([^}]+)\}/g`, and any persisted templates carrying the legacy `[[…]]` form are migrated by a one-shot script
  4. User can manually type a `{new variable}` directly into the document and have it picked up at save time alongside AI-identified variables
**Plans**: TBD
**UI hint**: yes

### Phase 4: Confirmation & transactional save
**Goal**: User explicitly confirms the variable set and the backend persists template + variables atomically, then transitions to Journey 1.2
**Depends on**: Phase 3
**Requirements**: TPL-SAVE-01, NFR-PERF-01, NFR-RELIABILITY-01
**Success Criteria** (what must be TRUE):
  1. The confirmation checkbox "I confirm the detected and custom added variables" is unchecked by default and "Create Template" is disabled until it is checked
  2. On click, the backend handler accepts `{name, type, subtype, description, variables[]}` and persists template + variables in a single PostgreSQL transaction (all-or-nothing)
  3. On a successful 2xx response, the frontend transitions to the Journey 1.2 view; on failure the form remains intact with a clear error
  4. End-to-end "open form → save" path completes in under 1 minute on a 5MB document
**Plans**: TBD
**UI hint**: yes

### Phase 5: Choose Existing Template navigation
**Goal**: User can leave the new-template flow at any time to pick an existing template, regardless of variable-detection state
**Depends on**: Phase 1 (does not depend on Phases 2–4 — CTA is always-available)
**Requirements**: TPL-NAV-01
**Success Criteria** (what must be TRUE):
  1. The "Choose Existing Template" CTA is rendered side-by-side with "Create Template" and is always enabled (not gated on variable detection or checkbox state)
  2. On click, App.tsx routes to the Journey 1.3 view (creating the placeholder Journey 1.3 component if it does not yet exist) and any required navigation context is passed through
**Plans**: TBD
**UI hint**: yes

### Phase 6: Auto-save lifecycle
**Goal**: The user cannot lose an in-flight template by navigating away, and cannot create a second template in the same session without saving the first
**Depends on**: Phase 4 (reuses Phase 4's save service — no parallel implementation)
**Requirements**: TPL-LIFECYCLE-01
**Success Criteria** (what must be TRUE):
  1. When the user navigates away from `TemplateCreationForm` (component unmount), the current draft auto-saves via the same Phase 4 save service
  2. Session state tracks a "template created in this session" flag for the current document; attempting a second template triggers an auto-save of the prior template first
  3. Auto-save status is surfaced to the user (success / failure) without blocking the navigation
**Plans**: TBD
**UI hint**: yes

### Phase 7: LLM determinism lockdown
**Goal**: Same document text yields byte-identical LLM output across runs, on a self-hosted model whose sampling we control
**Depends on**: Phase 2 (Phase 2 wires the AI call path; Phase 7 hardens the inputs to it)
**Requirements**: AI-DETERMINISM-01
**Success Criteria** (what must be TRUE):
  1. `OllamaChatRequest` in `backend/src/ollama.rs` sends `temperature: 0`, `top_p: 1`, `top_k: 1`, and a fixed `seed` constant on every call
  2. `response_format: {"type": "json_object"}` is replaced with a full JSON schema sent via Ollama's `format` field; the schema covers the variables-array shape used downstream
  3. `OLLAMA_MODEL` is switched from `gpt-oss:120b` (shared cloud) to a self-hosted Qwen2.5-7B or 14B interim model; `OLLAMA_API_URL` points to the self-hosted endpoint
  4. A snapshot test runs the pipeline 10 times on a fixed input document and asserts all 10 outputs are byte-identical
**Plans**: TBD

### Phase 8: Deterministic regex extractors
**Goal**: High-precision categories (PINs, GSTINs, IFSCs, dates, statutory references, etc.) are caught by deterministic regex before the LLM ever runs, and passed as anchors to the LLM call
**Depends on**: Phase 7
**Requirements**: AI-RECALL-01
**Success Criteria** (what must be TRUE):
  1. New `backend/src/extractors/` module exposes per-category extractors for at minimum: PIN, GSTIN, IFSC, mobile, email, date, cheque/account number, Section+Act references
  2. The extraction pipeline runs deterministic extractors first, passes their hits as an anchor list to the LLM call, and on overlap deterministic extractor output wins
  3. Existing dedup helpers in `ollama.rs` are reused (no parallel dedup logic)
  4. Per-category recall on the 20-document smoke set is ≥99% for every regex-covered category
**Plans**: TBD

### Phase 9: Multi-pass critic loop
**Goal**: A second LLM pass catches variables the first pass missed, lifting recall meaningfully without sacrificing precision, and Milestone 1's F1 ≥ 0.95 target is met
**Depends on**: Phase 8
**Requirements**: AI-RECALL-02, AI-ACCURACY-01
**Success Criteria** (what must be TRUE):
  1. New method `identify_variables_with_critic` exists on the AI service and sends `{document, variables_so_far}` to a critic prompt asking for missing variables
  2. The critic loop runs until either 0 new variables are returned or a hard cap of 3 iterations is hit; cost is bounded at 2–3× single-pass inference per document
  3. On the smoke set, recall lifts ≥+5 percentage points versus Phase 8 alone with precision drop ≤2 percentage points
  4. End-to-end F1 on the held-out smoke set is ≥0.95, satisfying Milestone 1's success metric

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 (done) → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.
Phase 7 is the user-suggested next phase to plan; the orchestrator may also
elect to plan Phase 2 first depending on which Story 1.x in-progress work
should be unblocked. Phases 5 and 6 may be executed in parallel with Phase 7
once Phase 4 lands.

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Story 1.1 closeout | 0/0 | Complete | pre-roadmap (Story 1.1) |
| 2. Auto Detect Variables CTA | 0/TBD | Not started | - |
| 3. Variable processing & display | 0/TBD | In progress (Story 1.3) | - |
| 4. Confirmation & transactional save | 0/TBD | Not started | - |
| 5. Choose Existing Template navigation | 0/TBD | Not started | - |
| 6. Auto-save lifecycle | 0/TBD | Not started | - |
| 7. LLM determinism lockdown | 0/TBD | Not started | - |
| 8. Deterministic regex extractors | 0/TBD | Not started | - |
| 9. Multi-pass critic loop | 0/TBD | Not started | - |
