> **ARCHIVED / HISTORICAL — NOT CURRENT IMPLEMENTATION.** Model/runtime assumptions in this planning track have been superseded. See `../CURRENT_ARCHITECTURE.md`.

# Determinism & Accuracy Track

> **Two goals:**
> 1. **Pure-function behavior** — the same document fed through the LLM pipeline must produce byte-identical variables across runs.
> 2. **Push variable identification toward 100% recall** — via deterministic extractors, multi-pass critic loop, human-in-loop correction capture, and (later) fine-tuning.
>
> **Companion doc:** [LLM_TRAINING_PLAN.md](./LLM_TRAINING_PLAN_legacy.md) — fine-tuning is Phase 4 of this track.

---

## Honest framing

| Claim | Reality |
|---|---|
| "Pure function" | Achievable. Requires `temperature=0`, fixed `seed`, `top_k=1`, JSON-schema constrained decoding, and a runtime that is deterministic (local Ollama, not shared cloud GPU). |
| "100% accuracy" | Not realistic for open-ended legal-doc variable identification. Practical target: **F1 ≥ 0.95 + human-in-loop confirmation in the Word UI**. The user is the final gate. |
| "Restart from scratch" | Not recommended. `backend/src/ollama.rs` already implements deterministic chunking, multi-tier validation, list-marker filtering, substring-overlap dedup, and JSON sanitization. Bolt onto it. |

---

## What's missing from LLM_TRAINING_PLAN.md

| Gap | Why it matters | Where it's addressed |
|---|---|---|
| No determinism strategy (no `temperature`, `seed`, no JSON schema) | Training a model doesn't help if inference samples non-deterministically | **Phase 0** |
| No per-document recall mechanism | Keyword tracking is a *retraining* loop — improves accuracy across releases, not within a single document | **Phase 2** (multi-pass critic) |
| GPU-first phasing | Cheap wins (regex extractors, sampling lockdown, multi-pass) come before any GPU spend | **Phases 0–2 first**, fine-tuning at Phase 4 |
| Correction capture is a separate CLI tool | Users won't run a CLI; corrections must be captured as a side-effect of normal add-in usage | **Phase 3** |

---

## Phased roadmap

### Phase 0 — Lock determinism (1–2 days, no ML)

**Goal:** Same input → byte-identical output across runs.

**Tasks:**
- [x] Add `temperature: 0`, `top_p: 1`, `top_k: 1`, `seed: <fixed const>` to `OllamaChatRequest` in `backend/src/ollama.rs`.
- [x] Replace `response_format: {"type": "json_object"}` with a full JSON **schema** via Ollama's `format` field. Schema must lock the variables array shape and field types. *(Note: `response_format` retained alongside `format` for OpenAI-compat transition; remove once Ollama-native is the only path.)*
- [ ] Switch `OLLAMA_MODEL` from `gpt-oss:120b` (shared cloud) to a self-hosted model (Qwen2.5-7B or 14B as an interim model before Phase 4 fine-tunes a 3B). *(Deferred — pending model selection decision; doc itself flags this as an open question on line 193. Operator-driven.)*
- [x] Add a snapshot test: feed a fixed document through `identify_variables` 10 times in CI; assert all 10 outputs are byte-identical. *(Implemented at `backend/tests/determinism_snapshot.rs`, gated with `#[ignore]` + `OLLAMA_DETERMINISM_TEST=1` so it runs locally against a live Ollama, not in default CI.)*
- [x] Verify chunking is deterministic (already is — paragraph splits at fixed offsets). *(Verified via `backend/tests/chunking_determinism.rs`, 2 tests passing in CI.)*

**Exit criterion:** snapshot test passes 10 consecutive runs with identical output.

**Files touched:** `backend/src/ollama.rs`, `backend/src/config.rs`, `backend/.env`, `backend/tests/`.

---

### Phase 1 — Hybrid deterministic extractors (3–5 days)

**Goal:** Stop relying on the LLM for categories with strict format. Regex-based extractors run alongside the LLM and merge into the result.

**Categories to extract deterministically:**

| Category | Pattern (sketch) | Notes |
|---|---|---|
| PIN code | `\b\d{6}\b` and spaced variant `\d{2}\s?\d{2}\s?\d{2}` | 6-digit Indian postal |
| GSTIN | `\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z\d]` | 15-char canonical (the previous sketch on this row had 16 chars — corrected during Phase 1 implementation); also handle spaced-letter variant |
| IFSC | `[A-Z]{4}0[A-Z0-9]{6}` | Bank IFSC |
| Mobile | `[6-9]\d{9}` and `+91 ?[6-9]\d{9}` | Indian mobile |
| Email | RFC-lite | |
| Date | `\d{1,2}[/-]\d{1,2}[/-]\d{2,4}` | DD/MM/YYYY first |
| Cheque/Account number | label-anchored: `(Cheque\s*No\.?|A/c\s*No\.?|Account\s*No\.?)\s*[:\-]?\s*[\d\s]+` | Includes digit-spaced variants |
| Section + Act | `Section\s+\d+(?:\([a-z]\))?\s+of\s+(?:The\s+)?[A-Z][\w\s,]+(?:Act|Code|Ordinance)(?:,?\s*\d{4})?` | Full phrase |

**Status (Phase 1 implemented in quick task `260505-247`):**
- [x] `backend/src/extractors/` module landed with one file per category and 56 unit tests covering positive + negative cases for each pattern listed above.
- [x] Extractors run on the full document **before** chunked LLM extraction in both `identify_variables` (batch) and `identify_variables_streaming` (SSE).
- [x] Per-chunk anchor list is filtered to anchors whose byte position falls inside the chunk window and embedded in the prompt via a new `<anchors>` section in `build_user_prompt_with_anchors`.
- [x] Union + extractor-wins-on-equal-`original_text` semantics implemented via prepending extractor variables before `dedup_by_original_text`. `dedup_substring_overlap` keeps the longer span when an LLM hit and an extractor hit overlap on a non-equal span.
- [x] Existing `validate_variables`, `dedup_by_original_text`, `dedup_substring_overlap` reused unchanged. Merge sequence extracted into a public `OllamaService::merge_extractor_and_llm` for reuse and testability.
- [x] `backend/tests/extractor_merge.rs` integration test covers all four merge invariants.
- [ ] Per-category recall ≥ 99% on a 20-doc smoke set. **Deferred — operational verification, not implementation.** No 20-doc Indian-legal smoke set exists yet; build the corpus alongside Phase 3 correction capture so the same documents serve both purposes.

**Merge strategy (as implemented):**
- Run extractors on the full document **before** chunked LLM extraction.
- Pass extractor hits as a "do-not-miss" `<anchors>` list in the LLM user prompt, scoped per chunk.
- After LLM returns, union both sets; on `original_text` overlap, deterministic extractor wins.
- Reuse existing `validate_variables`, `dedup_by_original_text`, `dedup_substring_overlap`.

**Exit criterion:** per-category recall ≥ 99% on a 20-doc smoke set for the listed categories. *(Deferred — see Status above.)*

**Files touched:** `backend/src/extractors/{mod,pin,gstin,ifsc,mobile,email,date,cheque_account,section_act}.rs`, `backend/src/lib.rs`, `backend/src/main.rs`, `backend/src/ollama.rs`, `backend/tests/extractor_merge.rs`.

---

### Phase 2 — Multi-pass critic loop (3–5 days)

**Goal:** Per-document iterative refinement — the "iterative feedback" piece. Pushes recall toward saturation without extra training data.

**Loop:**
1. **Pass 1:** existing extraction (LLM + Phase 1 extractors).
2. **Pass 2 (critic):** send `{document, variables_so_far}` to the LLM with a critic prompt:
   > *"Below is a document and a list of variables already extracted. List ONLY variables that are present in the document but missing from this list. Return the same JSON schema. If nothing is missing, return an empty array."*
3. Union results; re-validate with `validate_variables`; dedupe.
4. Repeat until a pass returns 0 new variables OR a hard cap of 3 iterations.
5. With `temperature=0` (Phase 0), the loop terminates in 1–2 extra passes typically.

**Cost:** 2–3× inference per document. Acceptable for accuracy goal; hidden behind streaming UX.

**Exit criterion:** on a held-out 20-doc set, recall increases ≥5pp vs single-pass without precision drop >2pp.

**Files touched:** `backend/src/ollama.rs` (new method `identify_variables_with_critic`), prompt constants, tests.

---

### Phase 3 — Correction capture in the Word add-in (~1 week)

**Goal:** Turn every user interaction into a labeled data point. Builds the gold corpus for Phase 4 fine-tuning **for free**.

**Backend:**
- [ ] New Postgres table:
  ```sql
  CREATE TABLE variable_corrections (
      id UUID PRIMARY KEY,
      document_id UUID NOT NULL,
      document_text_hash TEXT NOT NULL,
      variable_name TEXT NOT NULL,
      original_text TEXT NOT NULL,
      action TEXT NOT NULL,  -- 'accepted' | 'edited' | 'removed' | 'added' | 'renamed'
      previous_value JSONB,  -- for 'edited' / 'renamed'
      created_at TIMESTAMPTZ DEFAULT NOW(),
      user_id TEXT
  );
  ```
- [ ] New endpoint `POST /api/corrections` (batch insert).
- [ ] SQLx migration in `backend/migrations/`.

**Frontend (`word-extension/`):**
- [ ] Hook accept / edit / remove / rename / add-new flows in the variable panel to enqueue a correction event.
- [ ] Batch-flush every N seconds or on session end.

**Exit criterion:** 50+ corrections captured within first week of dogfooding; data parses into the JSONL training format from `archive/LLM_TRAINING_PLAN_legacy.md` §2.2 with no transformation loss.

**Files touched:** `backend/migrations/`, `backend/src/handlers.rs`, `backend/src/models.rs`, `word-extension/src/services/`, frontend variable panel components.

---

### Phase 4 — Fine-tune Qwen 2.5-3B (per existing LLM_TRAINING_PLAN.md)

**Goal:** Replace `gpt-oss:120b` cloud with a small, fast, locally-hosted, domain-specialized model.

Run [LLM_TRAINING_PLAN.md](./LLM_TRAINING_PLAN_legacy.md) Phases 1–4 as written, **with three amendments:**

1. **Skip the `review_tool.py` CLI.** Use the `variable_corrections` table from Phase 3 as the gold dataset. Write `scripts/export_training_data.py` to read from that table directly.
2. **Carry Phase 0 determinism into the Modelfile:**
   ```
   PARAMETER temperature 0
   PARAMETER top_p 1
   PARAMETER top_k 1
   PARAMETER seed 42
   ```
   And keep using JSON-schema `format` from the Rust client.
3. **Wait for ~200 reviewed docs** before the first fine-tune run. QLoRA below that sample count overfits.

**Exit criterion:** fine-tuned 3B model matches or beats `gpt-oss:120b` on the held-out test set, with ≤3s/chunk latency.

---

### Phase 5 — Continuous evaluation (ongoing)

**Goal:** Catch regressions and track per-category recall over time.

- [ ] Freeze 10% of `variable_corrections` corpus as eval set; never include in training.
- [ ] CI job: run pipeline against eval set on every backend PR; report precision / recall / F1 / per-category recall.
- [ ] Per-category recall dashboard (this is the "keyword tracker" from `archive/LLM_TRAINING_PLAN_legacy.md` §6, but read from the corrections table).
- [ ] Re-train when any category recall drifts >5pp below baseline.

**Exit criterion:** dashboard live, CI gating PRs, monthly re-train cadence established.

---

## Sequencing & cost summary

| Phase | Effort | Dependency | Determinism | Accuracy gain | GPU $ |
|---|---|---|---|---|---|
| 0 — Sampling + JSON schema lockdown | 1–2 days | none | **adds** | small | $0 |
| 1 — Hybrid regex extractors | 3–5 days | 0 | preserved | **large** | $0 |
| 2 — Multi-pass critic loop | 3–5 days | 0 | preserved | **large** | $0 (more inference) |
| 3 — Correction capture in UI | ~1 week | none | n/a | enables Phase 4 | $0 |
| 4 — Fine-tune Qwen 2.5-3B | ~3 weeks | 3 (200+ docs) | preserved | medium-large | ~$3.50 (per LLM_TRAINING_PLAN §11) |
| 5 — Eval loop | ongoing | 4 | n/a | sustains gains | $0 |

**Phases 0 → 2 ship in ~2 weeks and deliver most of the practical gain before touching a GPU.**

---

## Decision log

| Date | Decision | Rationale |
|---|---|---|
| 2026-05-05 | Do **not** rebuild the pipeline from scratch | Existing `ollama.rs` already implements deterministic chunking, multi-tier validation, list-marker filtering, substring-overlap dedup, JSON sanitization, streaming. Months of work; gains live in bolt-ons. |
| 2026-05-05 | Sequence cheap deterministic wins (Phases 0–2) before fine-tuning (Phase 4) | LLM_TRAINING_PLAN.md is GPU-first; flipping the order delivers value in weeks instead of months and produces the gold corpus needed for fine-tuning anyway. |
| 2026-05-05 | Target F1 ≥ 0.95 + human-in-loop, not 100% | Open-ended variable identification cannot be 100%. Practical 100% comes from user confirmation in the Word UI. |

---

## Open questions

- [ ] Which interim model for Phase 0 self-hosting? Qwen2.5-14B-Instruct vs 7B vs Llama-3.3-70B-Instruct — pick based on available VRAM on the prod server.
- [ ] Where does Ollama run in prod? Same Ubuntu VM as the Rust backend, or a separate GPU box?
- [ ] How do we want to surface "low-confidence" variables in the Word UI so users review them first? (Affects Phase 3 UX design.)
- [ ] Privacy: does the corrections table need PII redaction before being used as training data?
