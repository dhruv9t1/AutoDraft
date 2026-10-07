# Variable extraction accuracy — September 2026 hardening

This revision addresses low recall in the AutoDraft variable-identification pipeline.

## Root causes fixed

1. **Word structure was destroyed before inference.** `cleanText()` collapsed tabs/repeated spaces and turned bare carriage-return paragraph separators into spaces. Legal pleadings use tabs and paragraph layout to associate labels and values. The extractor now preserves tabs/repeated spaces and converts CR to newline.
2. **Chunks were too large for exhaustive extraction by the local 3B model.** The default was 60,000 bytes. It is now 12,000 bytes with overlap, which gives the model a much smaller coverage task per call.
3. **Overlap offsets were wrong.** Chunks included pre-context but reported the non-overlap offset, so deterministic anchors were scoped incorrectly after chunk 1. Chunks now report their actual byte start.
4. **UTF-8 chunk slicing was unsafe.** Smart quotes/Indic scripts could put a raw byte boundary inside a character. Chunk boundaries are now adjusted to valid UTF-8 boundaries.
5. **Known variables polluted every chunk.** The entire known-variable inventory was injected into every prompt. Known variables are now scoped to chunks where their value actually occurs.
6. **Single-pass extraction systematically missed fields.** `OLLAMA_EXTRACTION_PASSES=2` now runs a second, differently-worded coverage audit that asks only for missing fields.
7. **One failed batch chunk discarded good work.** Batch extraction now keeps successful chunks and deterministic anchors when only some LLM chunks fail.
8. **Deterministic coverage was too narrow.** Added/expanded extraction for rupee amounts, spaced Indian mobiles, `Cheque Number`, reference/file/complaint IDs, invoice IDs, LR IDs, and label-anchored party/person/address fields.
9. **Cheque/account extractor wrapped labels.** It now returns the value only, matching the product's short-span invariant.
10. **Bare leading-zero six-digit IDs were misclassified as PIN codes.** PIN extraction now respects the fact that Indian PIN codes do not start with zero.
11. **Advocate mobile numbers could be emitted with 100% deterministic confidence.** Mobile extraction now rejects advocate/enrollment-line context.

## Recommended production settings

```env
OLLAMA_CHUNK_SIZE=8000
OLLAMA_EXTRACTION_PASSES=2
OLLAMA_MAX_PARALLEL_CHUNKS=2
OLLAMA_TEMPERATURE=0
OLLAMA_TOP_K=1
OLLAMA_SEED=42
```

If latency becomes more important than recall, set `OLLAMA_EXTRACTION_PASSES=1`. Do not increase chunk size first; large chunks are a major recall regression for exhaustive extraction on the current local model.

## Remaining limitation

`identificationPercentage` is still an average of model confidence scores, not a measured recall/accuracy score against ground truth. Use the regression/evaluation dataset for true precision/recall/F1. A model can report high confidence and still miss a field.


## 2026-09-27 corpus calibration

The supplied legal-notice / NI Act complaint / summary-suit corpus showed that red/blue font colour is not a reliable variable annotation: it is also used for fixed headings, labels, advocate material and emphasis. The frontend therefore treats colour as diagnostic/fallback only.

The corpus also contains same-valued semantic fields (for example an invoice number and a delivery-challan number with the same current value). Exact extractor positions are now preserved and Word wrapping is position-aware for these cases. See `CORPUS_TUNING_2026-09-27.md`.
