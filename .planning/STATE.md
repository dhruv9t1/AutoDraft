# AutoDraft — Current State

Updated 2026-10-07. This replaces the stale May 2026 phase/branch/model snapshot.

## Active state

- Backend is Python/FastAPI, not Rust/Axum.
- Default Ollama model family is `qwen3:4b`.
- Word bindings use immutable content-control IDs plus structural occurrence evidence.
- Production authentication and tenant isolation are implemented; runtime database roles must be non-owner, non-superuser, and NOBYPASSRLS.
- Historical roadmap/quick-task files may mention `gpt-oss:120b`, IE 11, Rust, or marker-token formats; treat those references as historical only unless an active source-of-truth document repeats them.

## Release gates

Run the checks in `RELEASE_CHECKS.md`. Full release validation additionally requires PostgreSQL with the production-style runtime role, a configured Ollama instance/model, OCRmyPDF/Tesseract for OCR paths, and a real supported Microsoft Word host for Office.js behavior.
