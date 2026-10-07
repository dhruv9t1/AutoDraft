# AutoDraft 1.1 — lawyer-firm architecture port

Date: 2026-10-04

This release starts from the deep-audited AutoDraft 1.0.1 tree and ports the lawyer-firm ideas that improve AutoDraft without replacing its stronger matter, persistence, Word-binding, security, and review architecture.

## Ported and adapted

1. **Offset-preserving Unicode candidate view**
   - One source character maps to one comparison character, so candidate offsets remain valid.
   - Gujarati/Devanagari and other Unicode decimal digits are folded to ASCII digits for matching.
   - Unicode spaces are normalized for matching without rewriting the stored source text.
   - Accented Latin letters can be neutralized in the comparison view for stable ASCII-boundary regexes.

2. **Direct DOCX ZIP/XML diagnostics**
   - Reads Word body, headers, and footers directly from the DOCX package.
   - Joins Word runs at paragraph level for diagnostics.
   - This is a secondary inspection path; Office.js remains authoritative for live Word mutation.

3. **Legacy Indian-font diagnostics**
   - Detects common pre-Unicode Gujarati/Hindi font families such as Saral, Gopika, Terafont, LMG, Kruti Dev, DevLys, Chanakya, and related families.
   - Active legacy-font text blocks raw Auto Detect because the displayed glyphs may not match the stored characters.
   - Style/theme-only references are warnings rather than automatic blockers.

4. **High-recall deterministic candidate engine**
   - Existing AutoDraft extractors remain in place.
   - Additional ordered candidate patterns cover label/value pairs, dates, money, percentages, references, quoted names, uppercase phrases, and title-case phrases.
   - Earlier overlapping supplemental patterns own the candidate span so the result is stable.
   - Candidates are evidence, not automatically accepted fields.

5. **Candidate grouping without identity collapse**
   - Equivalent spelling/digit-script/spacing variants are grouped for evidence and repetition counts.
   - Every source occurrence remains separate and keeps its own position.
   - Same-looking values in different legal roles are never merged into one semantic field merely because their text matches.

6. **Organization boilerplate registry**
   - Tenant-scoped PostgreSQL table and authenticated API for firm names, lawyers, enrollment numbers, addresses, phones, emails, letterhead/signature text, and other fixed values.
   - Exact boilerplate matches are strong negative evidence for field discovery.
   - Values are reviewable/configurable instead of being hard-coded into Python.

7. **System-1 / Jev candidate-decision layer**
   - Provider-neutral `CandidateDecisionProvider` protocol.
   - Execution order: deterministic rules → optional Jev → existing Qwen/System-2 → lawyer review.
   - Jev asks only a narrow classification question and returns replaceable/static/ambiguous evidence.
   - Jev does not name fields, write documents, or become product truth.
   - The hosted provider is disabled by default; failures abstain and fall through safely.

8. **Explicit uncertainty / “check these” behavior**
   - Ambiguous candidates survive as `needs_review` rather than being silently deleted.
   - Backend wrapping plans exclude `needs_review`/`rejected` candidates.
   - Word independently filters them before mutation as a second safety barrier.
   - The task pane displays a **Check candidate** state.

9. **Graceful System-2 outage preview**
   - If Ollama/Qwen is unavailable, AutoDraft may surface deterministic/System-1 candidates as review-only hints.
   - Response status remains `unavailable` and the wrapping plan is empty.
   - Arbitrary partial AI results remain fail-closed.

10. **Candidate-level evaluation harness**
    - Checked-in labelled fixture measures candidate recall and deterministic rule decisions.
    - This complements the existing 16-document golden corpus and makes extraction changes measurable at the candidate boundary.

11. **Frontend service boundary for firm boilerplate**
    - The Word add-in has typed API helpers for listing, adding, and removing organization boilerplate through the central authenticated API client.

## Deliberately not copied

- A typed/date/amount-looking token is **not** automatically considered a real variable.
- A probability/confidence score is **not** product truth.
- Textually identical values are **not** globally merged into one field.
- Jev is **not** a replacement for grounding, semantic mapping, Qwen, or lawyer review.
- The lawyer-firm experimental persistence/server structure is **not** used; AutoDraft keeps PostgreSQL, tenant isolation, versioning, Matter Documents, and the Word reliability layer.

## Optional Jev configuration

Default behavior sends no legal text to Jev:

```env
SYSTEM1_PROVIDER=off
```

To intentionally enable the hosted provider, configure the deployment-owned endpoint/key:

```env
SYSTEM1_PROVIDER=jev
JEV_API_URL=https://api.typesafe.ai/v1/systemone
JEV_API_KEY=...
JEV_MODEL=jev-latest
JEV_TIMEOUT_SECONDS=20
```

Jev failure is non-fatal. The decision router continues to the next decision stage or lawyer review.

## Validation in this release

Run from `backend/`:

```bash
pytest -q
python scripts/evaluate_candidates.py
python scripts/evaluate_golden_corpus.py
```

Run repository release audit:

```bash
python scripts/audit-release.py .
```

The final release ZIP must also be re-extracted into a clean directory and the same checks rerun before distribution.

## Real-environment gates still required

A source/static test cannot certify a real Word host, live PostgreSQL, live Ollama, OCR binaries, or a hosted Jev account. Use `scripts/run-real-environment-gates.sh` and the Word-host smoke procedure before production deployment. Jev must remain disabled until external legal-data processing has been approved for the deployment.
