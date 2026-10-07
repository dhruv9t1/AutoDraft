# Constraints (SPEC Intel)

> Synthesized from SPEC-classified sources:
> - Six implementation stories: `docs/stories/1-` through `6-`
> - `docs/DETERMINISM_AND_ACCURACY_TRACK.md`
> - `docs/LLM_TRAINING_PLAN.md`
> - `docs/indian-laws-vector-db-plan.md`
>
> Each entry includes type (api-contract | schema | nfr | protocol | implementation), source, and content block.

---

## CONSTRAINT-story-1.1-template-creation-form-ui
- source: docs/stories/1-template-creation-form-ui.md
- type: implementation
- status: completed
- scope: word-extension/src/taskpane/components/TemplateCreationForm.tsx (763 lines), App.tsx integration, services/types.ts (TemplateMetadata)
- content:
  - Component must be a React + TypeScript single-screen form using Fluent UI
  - Title "Create a new template", subtitle "Turn your current document into a standard template"
  - Fields: text input (name), searchable combobox (type), dynamic combobox (subtype dependent on type), multi-line description
  - Integrate via `viewMode="templateCreation"` in App.tsx navigation
  - Validation rules consistent across journeys
- refines: REQ-template-creation-form, REQ-template-metadata-input

## CONSTRAINT-story-1.2-auto-detect-variables
- source: docs/stories/2-auto-detect-variables-feature.md
- type: implementation + nfr
- status: drafted
- scope: TemplateCreationForm.tsx, services/documentExtraction.ts, services/aiVariableService.ts, backend/src/handlers.rs, backend/src/ollama.rs
- content:
  - Button enable/disable bound to form validation (name + type + subtype required)
  - Document content extracted via Office Add-in API; empty-document check before API call
  - Existing AI service in `backend/src/ollama.rs` invoked with extracted content
  - Loading indicator with non-blocking UI
  - 80% detection threshold validation in client/server
  - Fallback paths for: <80% detection, empty document, no variables, AI service failure
  - NFR: <10s for documents up to 5MB
- refines: REQ-auto-detect-variables-button, REQ-ai-variable-detection, REQ-variable-detection-display, REQ-nfr-performance

## CONSTRAINT-story-1.3-variable-processing-and-display
- source: docs/stories/3-variable-processing-and-display.md
- type: implementation + protocol
- status: in-progress
- scope: word-extension/src/services/documentExtraction.ts, services/aiVariableService.ts, TemplateCreationForm.tsx
- content:
  - Variable replacement in document via Office Add-in API; multiple-occurrence handling; preserve formatting
  - Manual variables typed in-document by user are extracted and merged with AI-identified variables before save
  - Implementation completion notes: `extractVariablesFromDocument()` uses regex `/\[\[([^\]]+)\]\]/g` (DOUBLE square brackets) — this CONTRADICTS the PRD/project-overview format `[variable name]` (single brackets) and the story's own narrative `{variable name}`. **See INGEST-CONFLICTS.md WARNING [variable-format-divergence].**
  - Deduplication is case-insensitive on variable name; sorted by position
  - Confidence scores preserved for AI-identified variables; manual additions saved without scores
- refines: REQ-variable-formatting

## CONSTRAINT-story-1.4-variable-confirmation-and-template-creation
- source: docs/stories/4-variable-confirmation-and-template-creation.md
- type: api-contract + schema + nfr
- status: drafted
- scope: TemplateCreationForm.tsx, backend/src/handlers.rs, backend/src/models.rs, backend/migrations/, backend/migrations/20250127000001_create_variables_table.sql
- content:
  - Backend MUST expose a template-creation endpoint accepting `{name, type, subtype, description, variables[]}`
  - Save MUST be transactional (all-or-nothing); template + variables in single transaction
  - Variables linked to template by template-name foreign key (verify schema supports this)
  - On successful response, frontend transitions to Journey 1.2
  - Performance NFR: complete operation <1 minute
- refines: REQ-variable-confirmation, REQ-create-template-button, REQ-nfr-reliability, REQ-nfr-performance

## CONSTRAINT-story-1.5-choose-existing-template-navigation
- source: docs/stories/5-choose-existing-template-navigation.md
- type: implementation
- status: drafted
- scope: TemplateCreationForm.tsx, App.tsx
- content:
  - Always-enabled CTA, sibling to Create Template
  - Routing to Journey 1.3 view via App.tsx routing layer
  - Pass any required navigation context (template list, etc. — Journey 1.3 component may need creation)
- refines: REQ-choose-existing-template

## CONSTRAINT-story-1.6-template-auto-save
- source: docs/stories/6-template-auto-save.md
- type: implementation
- status: drafted
- scope: TemplateCreationForm.tsx, App.tsx, word-extension/src/services/
- content:
  - Auto-save triggered on navigation away (component unmount lifecycle)
  - Session state must track "template created in this session" flag
  - Attempting a second template in the same session → save prior template first
  - Auto-save logic must reuse the same save service from Story 1.4 (no parallel implementation)
  - Optional: surface auto-save status to user
- refines: REQ-template-auto-save

---

## CONSTRAINT-determinism-track
- source: docs/DETERMINISM_AND_ACCURACY_TRACK.md
- type: protocol + nfr
- scope: backend/src/ollama.rs, backend/src/config.rs, backend/.env, backend/src/extractors/ (new), backend/migrations/, backend/src/handlers.rs, word-extension/src/services/, scripts/export_training_data.py
- content:
  - **Phase 0 (determinism, 1–2 days, no ML):** Add `temperature: 0`, `top_p: 1`, `top_k: 1`, `seed: <fixed const>` to `OllamaChatRequest`. Replace `response_format: {"type": "json_object"}` with full JSON schema via Ollama `format` field. Switch `OLLAMA_MODEL` from `gpt-oss:120b` (shared cloud) to self-hosted (Qwen2.5-7B or 14B interim). Snapshot test: 10 identical outputs over 10 runs.
  - **Phase 1 (regex extractors, 3–5 days):** New `backend/src/extractors/` module covering PIN, GSTIN, IFSC, mobile, email, date, cheque/account number, Section+Act references. Run before chunked LLM extraction; pass extractor hits as anchor list to LLM; on overlap, deterministic extractor wins. Reuse existing dedup helpers. Exit: ≥99% per-category recall on 20-doc smoke set.
  - **Phase 2 (multi-pass critic, 3–5 days):** New method `identify_variables_with_critic`. Critic prompt sends `{document, variables_so_far}` and asks for missing variables; loop until 0 new or hard cap of 3 iterations. Cost: 2–3× inference per document. Exit: recall ≥+5pp without precision drop >2pp.
  - **Phase 3 (correction capture, ~1 week):** New table `variable_corrections` with columns (id UUID PK, document_id UUID, document_text_hash TEXT, variable_name TEXT, original_text TEXT, action TEXT in {accepted, edited, removed, added, renamed}, previous_value JSONB, created_at, user_id). Endpoint `POST /api/corrections` (batch insert). Frontend hooks accept/edit/remove/rename/add-new flows; batch flush every N seconds or on session end. Exit: 50+ corrections in first dogfood week.
  - **Phase 4 (fine-tune Qwen 2.5-3B):** Run LLM_TRAINING_PLAN.md Phases 1–4 with three amendments: (1) skip `review_tool.py` CLI, use `variable_corrections` table directly via `scripts/export_training_data.py`; (2) carry Phase 0 determinism into Modelfile (`temperature 0`, `top_p 1`, `top_k 1`, `seed 42`) and JSON-schema `format`; (3) wait for ~200 reviewed docs before first run.
  - **Phase 5 (continuous evaluation):** Freeze 10% of corrections corpus as eval set; CI job runs pipeline against eval on every backend PR; per-category recall dashboard; re-train when any category drifts >5pp below baseline.
  - **NFR:** Same input must yield byte-identical output across runs. Practical accuracy target F1 ≥ 0.95 (not 100%).

## CONSTRAINT-llm-training-plan
- source: docs/LLM_TRAINING_PLAN.md
- type: protocol + nfr + api-contract
- scope: training/ directory (new), backend/.env, deployment/Modelfile
- content:
  - Base model: Qwen 2.5-3B-Instruct (32K context, Apache 2.0)
  - QLoRA hyperparameters: rank=32, lora_alpha=64, target_modules=all linear, dropout=0.05, lr=2e-4, epochs=3–5, batch=4 with gradient_accum=4 (effective 16), max_seq_length=4096, warmup=0.1, scheduler=cosine, quantization=4-bit NF4
  - Training data format: chat-format JSONL with `{system, user, assistant}` messages mirroring inference; minimum 100 samples for QLoRA, recommended 500–1000
  - Validation: every `originalText` must exist in document text; no duplicates across splits; valid JSON; PascalCase-with-spaces variable names; confidence in [0.0, 1.0]
  - Splits: 80% train / 10% eval / 10% test
  - Deployment: GGUF Q8_0 quantization (production target — accuracy focus); convert via llama.cpp or Unsloth
  - Modelfile parameters: `temperature 0.1`, `top_p 0.9`, `top_k 40`, `repeat_penalty 1.1`, `num_ctx 4096`, `num_predict 4096`, stop `<|im_end|>` and `<|endoftext|>`. **CONFLICTS with DETERMINISM_AND_ACCURACY_TRACK Phase 0/4 lockdown — see INGEST-CONFLICTS.md WARNING [llm-sampling-divergence].**
  - Inference-time system prompt: short ("legal document variable extractor; return JSON with variables array"); detailed 440-line prompt is training-time only
  - Backend `.env` switch: `OLLAMA_MODEL=legal-var-extractor`, `OLLAMA_API_URL=http://localhost:11434`, `OLLAMA_API_PATH=/api/chat`, `OLLAMA_THINK_LEVEL=off`, `OLLAMA_CHUNK_SIZE=3000`, `OLLAMA_TIMEOUT_SECONDS=30`
  - Eval metrics: precision >0.90, recall >0.95, F1 >0.93, JSON valid rate >0.99, name accuracy >0.85, latency <5s/chunk
  - Cloud: RunPod RTX A5000 24GB ~$0.30/hr; total project compute ~$3.50

## CONSTRAINT-indian-laws-vector-db
- source: docs/indian-laws-vector-db-plan.md
- type: schema + api-contract + protocol
- scope: separate workstream — vector DB for legal corpus retrieval; integrates with Word add-in via search panel
- content:
  - Postgres + pgvector schema: `legal_documents` (id, title, document_type, citation, dates, jurisdiction, classification, status, source_url, raw_content, processed_content), `legal_embeddings` (document_id, chunk_id, chunk_text, embedding VECTOR(1536), chunk_type, metadata), `search_cache` (query_hash, results, ttl)
  - Hierarchical chunking: doc → section → paragraph → clause; max 500 tokens/chunk
  - Hybrid retrieval: semantic (cosine on vectors) + BM25 keyword + citation + temporal + jurisdiction filter
  - Embedding model candidates: OpenAI Ada-002, Sentence-BERT Legal, IndicBERT, custom-trained
  - API endpoints (Rust): POST `/api/legal/search`, POST `/api/legal/similar`, POST `/api/legal/citation`; GET `/api/legal/documents/:id`, `/api/legal/documents/:id/related`, `/api/legal/documents/:id/amendments`; POST `/api/legal/classify`; GET `/api/legal/categories`
  - Search request shape: `{query, filters{jurisdiction[], document_type[], date_range, subject[]}, search_type: semantic|keyword|hybrid, limit, offset}`
  - Search response: `{results[{document_id, title, relevance_score, excerpt, citation, metadata, related_provisions[]}], total, facets, suggestions}`
  - NFR: <500ms p90 search latency; >95% relevance; >90% major-laws coverage; daily updates
  - Tech stack: PostgreSQL+pgvector, Redis cache, optional Elasticsearch keyword index, Rust backend, Python ML services (FastAPI), Sentence Transformers
  - Timeline: 20 weeks across 5 milestones (Foundation → Data Collection → Advanced Features → Word Add-in Integration → Enhancement)
  - **Note:** Scope is orthogonal to Journey 1.1 template-creation flow; integrates downstream as a separate Word-addin feature (sidebar legal search, citation generation, compliance checking, suggestions). Roadmapper should treat as a separate workstream.
