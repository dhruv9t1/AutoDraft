# AutoDraft cumulative changes

This package is cumulative. It is based on the previously delivered `AutoDraft-corpus-tuned.zip` and retains the earlier security, extraction-accuracy, corpus-tuning, UTF-8-safe chunking, deterministic legal extractors, and position-aware Word wrapping fixes.

## Added in this revision

- Persistent **My document / Saved template** source selector instead of forcing users through a hidden menu path.
- Saved-template catalog is loaded from the backend on startup and refreshed when the user switches to Saved template.
- **Complete Drafting** now opens a confirmation dialog: **Save Empty Template for future use?**
- Completing a draft waits for the reusable master OOXML upload before content controls are removed.
- Reusable OOXML is captured from a temporary clean/unfilled view of content controls and then the user's live draft is restored, preventing typed case values from leaking into the master template.
- Draft-specific `current_value` data is cleared when completing so future uses open as an empty template rather than a previously filled case.
- Pending/in-flight value saves are drained before that clear, preventing a race that could repopulate the template after completion.
- Manually-added variables are now persisted to the template database and the reusable master OOXML is refreshed, so user corrections survive future reuse.
- Variable renames now update the Word content-control tag, database row, in-memory variable list, and reusable OOXML master together; a failed database rename rolls the Word tag back.
- Added an implementation plan for TypeSafe AI's Jev as an optional decision/routing layer (`docs/JEV_TYPESAFE_AI_INTEGRATION.md`).

## Earlier retained work

- Exposed credential removal and secret hygiene.
- Backend bearer-token guard / CORS hardening guidance.
- Sensitive document logging reduction.
- Modern Word webview compatibility clarification.
- Structure-preserving Word text extraction.
- Smaller UTF-8-safe LLM chunks and second-pass coverage audit.
- Expanded deterministic legal/financial extractors.
- Corpus-specific NI Act notice/complaint and summary-suit tuning.
- Same-value/different-semantic-field preservation.
- Exact source-position preservation and position-aware wrapping.
- Table/header/footer story-boundary fix.

## 2026-09-27 — Python backend migration

- Replaced the active Rust/Axum backend with Python 3.11+ / FastAPI.
- Preserved existing REST/SSE contracts so the Word add-in remains compatible.
- Ported deterministic legal-field extraction, post-processing, wrapping-plan generation, Ollama two-pass extraction, PostgreSQL template persistence, chunked OOXML uploads, API authentication and analysis routes.
- Existing PostgreSQL schema remains compatible; no data reset is required.
- Added Python regression tests and Python setup/deployment documentation.

## 2026-10-04 — vNext cumulative completion

This section supersedes the earlier provisional-template lifecycle notes above where they conflict.

- Built on `AutoDraft-vNext-Foundation-2026-10-03.zip` rather than the older cumulative archive.
- A new **My document** AutoDraft is not persisted during detection/wrapping. The database template is created only when the user explicitly chooses **Save Empty Template & Complete**.
- Back/cancel before completion leaves no Saved Template row. Unsaved rename/manual add operations update Word + local React state only.
- The explicit save captures a clean reusable OOXML master, creates the template/variables, uploads the master, clears case-specific values, and rolls back the row if persistence fails.
- Extraction is one logical backend job with SSE event delivery, idle heartbeats, same-job polling fallback, and DELETE cancellation. A dropped SSE transport does not launch a second Ollama extraction.
- The legacy direct SSE endpoint also sends an immediate status frame, `: heartbeat` keep-alives, and cancels its producer on disconnect.
- Ollama chunk tasks are cancelled in `finally` blocks so aborted Word requests do not leave orphan model calls.
- Same-span/same-family field duplicates are conservatively collapsed after generic-name enrichment; repeated source values at different positions and semantically distinct fields are preserved.
- Added local OCR jobs for PDF/JPG/JPEG/PNG/TIF/TIFF using OCRmyPDF + Tesseract `guj+eng`, with dependency diagnostics, rotation/deskew, searchable-PDF output, full extracted text, cancellation, expiry cleanup, and Word import UI.
- Added `python-multipart`, `pypdf`, and Pillow backend dependencies required for OCR upload/conversion.
- `.env` loading is backend-relative, `qwen3:4b` is the documented default detector, and startup validates model availability through Ollama `/api/tags`.
- Python migrations now use a PostgreSQL advisory lock, SHA-256 checksums, and SQLx-history import; the legacy cascade-FK migration is idempotent.
- Added reproducible `scripts/make-release-zip.sh`, Python-first verification docs, and regression tests for duplicate collapse/OCR dependency errors.
