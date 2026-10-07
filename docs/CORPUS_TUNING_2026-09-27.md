# Corpus tuning — supplied legal notices, NI Act complaints, and summary suits

This pass was tuned against the user's supplied document family rather than generic legal text.

## What the corpus showed

1. **Font colour is presentation, not ground truth.** Red/blue runs include fixed headings, labels, advocate material, list/page markers and case data. Raw colour runs must never be merged as authoritative variables.
2. **Party terminology depends on document family.** NI Act complaints use Complainant/Accused; summary civil suits use Plaintiff/Defendant. Forcing every document into Complainant/Accused creates bad names and loses civil-party fields.
3. **The same current value can represent different fields.** A transaction can have the same number for Invoice No. and Delivery Challan No. Dedup by `originalText` alone is therefore incorrect.
4. **Exact positions matter.** Deterministic extractors know the byte offset. Replacing that offset with `document.find(value)` moves every repeated value to the first occurrence and breaks Word linking.
5. **Notice-service data is variable.** India Post/courier tracking identifiers, dispatch dates, service dates and compliance/cause-of-action dates change per matter and must not be filtered as boilerplate.
6. **The long pleadings contain recurring high-value labels** that should not depend on a 3B model: case/suit number, court number, suit value, court fee, cheque dates, bank account, IFSC, delivery challan, E-Way Bill, HSN, interest rate and limitation dates.

## Changes made

- Added `LegalFieldsExtractor` for the recurring labelled fields above.
- Extended `PartyExtractor` to Plaintiff/Defendant/Respondent and `Mr`/`Mrs`/`Ms`, quoted firm names, and `SHOP/OFFICE` variants.
- Kept postal tracking values and taught the LLM prompt that they are case variables.
- Added corpus-shaped few-shot examples for NI Act complaint headers and summary-suit transactions.
- Reduced default LLM chunk size to 8,000 characters for accuracy-first extraction on 6–37 page documents.
- Changed exact-value dedup to retain same-valued, differently named fields at different exact positions.
- Preserved deterministic source positions during validation.
- Made Word wrapping choose the occurrence nearest the backend position when multiple semantic fields share the same text.
- Stopped red/blue formatting candidates from being automatically unioned into the authoritative result.

## Important test-data warning

Do not use filenames as extraction ground truth. Several supplied filenames contain cheque numbers that differ from the values inside the document body. AutoDraft should learn from and validate against the Word document content, not the filename.

## Recommended runtime settings

```env
OLLAMA_CHUNK_SIZE=8000
OLLAMA_EXTRACTION_PASSES=2
OLLAMA_MAX_PARALLEL_CHUNKS=2
OLLAMA_TEMPERATURE=0
OLLAMA_TOP_K=1
OLLAMA_SEED=42
```

## What this is / is not

This is **domain calibration and prompt/extractor tuning**, not a weight-level model fine-tune. A real LoRA/SFT fine-tune should only be done after a reviewed gold dataset exists. The supplied documents are excellent evaluation material, but they do not by themselves specify which spans are intended variables; formatting colour is demonstrably not a reliable annotation source.
