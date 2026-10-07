# Requirements: Legal Doc Template Builder

**Defined:** 2026-05-05
**Core Value:** A lawyer can turn an existing document into a reusable, variable-aware template in under one minute, with the AI doing ≥95% of the variable-identification work and the user serving as the final accuracy gate.

## v1 Requirements (Milestone 1: Journey 1.1 → 1.6 + Determinism Phases 0–2)

Requirements for Milestone 1. Each maps to exactly one roadmap phase.

### Template Form (Journey 1.1 entry)

- [x] **TPL-FORM-01**: User can open a single-screen "Create a new template" form with title "Create a new template", subtitle "Turn your current document into a standard template", and fields name + type + subtype + description (Story 1.1, shipped)
- [ ] **TPL-FORM-02**: All variable tokens in document text, persisted templates, and the extraction regex use the canonical format `{variable name}` (D-009)

### Variable Detection (Auto Detect Variables)

- [ ] **TPL-DETECT-01**: User can click "Auto Detect Variables" (enabled only after name + type + subtype entered), see a loading indicator, and the document content is sent to the backend AI service
- [ ] **TPL-DETECT-02**: Detected variables are returned, deduplicated case-insensitively, sorted by document position, displayed as a list with the count "We have identified X number of variables in the document", and replaced in the document body using the canonical `{variable name}` format
- [ ] **TPL-DETECT-03**: AI variable-detection accuracy threshold (≥80%) gates the UX path; sub-threshold, empty-document, no-variables, and AI-service-failure cases each fall back to a clear manual-entry prompt

### Template Persistence

- [ ] **TPL-SAVE-01**: User must check "I confirm the detected and custom added variables" (unchecked by default) before "Create Template" enables; on click, the backend saves template + variables in a single transaction and the frontend transitions to Journey 1.2

### Navigation

- [ ] **TPL-NAV-01**: "Choose Existing Template" CTA is always available (not gated on variable detection), sits side-by-side with "Create Template", and routes to the Journey 1.3 view

### Lifecycle

- [ ] **TPL-LIFECYCLE-01**: On navigation away the current in-flight template auto-saves; the user cannot create multiple templates from the same document in one session — attempting to do so saves the prior template first

### Non-Functional (Journey 1.1)

- [ ] **NFR-PERF-01**: Template creation completes <1 minute; AI variable detection completes <10s for documents up to 5MB; UI remains responsive during AI processing
- [ ] **NFR-USABILITY-01**: All form fields clearly labeled; error messages clear and actionable; loading indicators on async ops; UI follows provided mockup
- [ ] **NFR-RELIABILITY-01**: AI service failures fall back to manual entry; empty-document validation prevents invalid ops; database save operations are transactional and atomic
- [ ] **NFR-ACCURACY-01**: AI identifies ≥80% of variables (success threshold); detection accuracy validated before allowing template creation

### AI Determinism & Accuracy (Determinism Track Phases 0–2)

- [ ] **AI-DETERMINISM-01**: `OllamaChatRequest` carries `temperature: 0`, `top_p: 1`, `top_k: 1`, `seed: <fixed const>`; `response_format` replaced with full JSON schema via Ollama `format` field; `OLLAMA_MODEL` switched from shared `gpt-oss:120b` to self-hosted (Qwen2.5-7B or 14B interim); snapshot test confirms 10 identical outputs over 10 runs on a fixed input
- [ ] **AI-RECALL-01**: New `backend/src/extractors/` module covers PIN, GSTIN, IFSC, mobile, email, date, cheque/account number, Section+Act references; runs before chunked LLM extraction; passes hits as anchor list to LLM; on overlap, deterministic extractor wins; reuses existing dedup helpers; ≥99% per-category recall on a 20-doc smoke set
- [ ] **AI-RECALL-02**: New `identify_variables_with_critic` method sends `{document, variables_so_far}` to a critic prompt asking for missing variables; loops until 0 new or hard cap of 3 iterations; recall ≥+5pp without precision drop >2pp on the smoke set
- [ ] **AI-ACCURACY-01**: F1 ≥ 0.95 measured against a held-out variable-extraction smoke set covering Journey 1.1's representative document mix

## v2 Requirements (Milestone 2 and beyond)

Deferred. Tracked but not in current roadmap.

### Journey 1.2 (Update Master Template — uses D-010 in-place append)

- **J12-CROSS-01**: User can re-open a document tied to an existing template, run Auto Detect Variables, and have new variables append in-place to that template's variable set (template_id retained, no fork, no union semantics)

### Journey 1.3 (Fill Form with Variables)

- **J13-FORM-01**: After "Create Template" or "Choose Existing Template", user sees a form with one text input per variable (with validation), can click "Apply Data", and values are injected into the document
- **J13-CROSS-01**: Template-selection dropdown is searchable + creatable, surfaces top 5 recently used templates, allows only one template at a time, and disables "Identify Variables" + "Fill the form" when no template is selected
- **J13-CROSS-02**: API failure / wrong template type / empty document each fall back to a clear error + manual-entry path

### AI Determinism & Accuracy (Phases 3–5)

- **AI-CORRECTIONS-01** (Determinism Phase 3): `variable_corrections` table + `POST /api/corrections` endpoint + frontend hooks for accept/edit/remove/rename/add-new + batch flush; exit when 50+ corrections captured in dogfood week
- **AI-FINETUNE-01** (Determinism Phase 4): Fine-tune Qwen 2.5-3B with QLoRA per LLM_TRAINING_PLAN with three amendments (skip review_tool.py, use corrections table; carry Phase 0 determinism into Modelfile; wait for ~200 reviewed docs)
- **AI-EVAL-01** (Determinism Phase 5, ongoing): Freeze 10% of corrections corpus as eval set; CI runs pipeline on every backend PR; per-category recall dashboard; re-train trigger when any category drifts >5pp below baseline

### Indian-Laws Vector DB (Milestone 3 / orthogonal track)

- **LEGAL-DB-01** through **LEGAL-DB-NN**: 20-week orthogonal workstream — Postgres+pgvector schema, hierarchical chunking, hybrid retrieval, sidebar search panel, citation generator, compliance checker. Out of scope for Milestones 1 and 2.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Template deletion / sharing / versioning / import/export | PRD §8 exclusions; not core to "draft fast" value prop |
| Standalone variable-management UI | D-004: variables are edited in-document only |
| Document preview with variables filled | Journey 1.3 deliverable, not Journey 1.1 |
| Multi-template-per-session | D-005: one template per document per session |
| Multi-user roles / permissions | Single user type for first release |
| LLM Modelfile sampling values from LLM_TRAINING_PLAN (`temperature 0.1`, `top_p 0.9`, `top_k 40`) | Superseded by Determinism Phase 0 lockdown (auto-resolved INFO in conflicts report) |
| Interactive `review_tool.py` CLI for training data | Superseded by `variable_corrections` table approach |

## Traceability

Phase mapping for Milestone 1 v1 requirements. Each requirement maps to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| TPL-FORM-01 | Phase 1 | Complete (Story 1.1 shipped) |
| TPL-FORM-02 | Phase 3 | Pending |
| TPL-DETECT-01 | Phase 2 | Pending |
| TPL-DETECT-02 | Phase 3 | In Progress (Story 1.3) |
| TPL-DETECT-03 | Phase 2 | Pending |
| TPL-SAVE-01 | Phase 4 | Pending |
| TPL-NAV-01 | Phase 5 | Pending |
| TPL-LIFECYCLE-01 | Phase 6 | Pending |
| NFR-PERF-01 | Phase 4 | Pending |
| NFR-USABILITY-01 | Phase 2 | Pending |
| NFR-RELIABILITY-01 | Phase 4 | Pending |
| NFR-ACCURACY-01 | Phase 2 | Pending |
| AI-DETERMINISM-01 | Phase 7 | Pending (NEXT) |
| AI-RECALL-01 | Phase 8 | Pending |
| AI-RECALL-02 | Phase 9 | Pending |
| AI-ACCURACY-01 | Phase 9 | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-05*
*Last updated: 2026-05-05 after `/gsd-new-project` ingest synthesis*
