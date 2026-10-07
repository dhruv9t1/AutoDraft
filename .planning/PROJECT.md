# AutoDraft — Current Project Snapshot

This file supersedes the May 2026 Rust/IE11/token-planning snapshot. Historical planning records remain under `.planning/quick/` and `docs/archive/`; they are not current implementation guidance.

## Current architecture

- Frontend: React 18 + TypeScript + Fluent UI v9 + Office.js, running on modern supported Word webviews. IE 11 is not supported.
- Backend: Python 3.11+ + FastAPI + asyncpg/PostgreSQL. The former Rust/Axum backend is historical.
- AI: Ollama-compatible local models with `qwen3:4b` as the default field/drafting/review/verifier model unless deployment configuration explicitly overrides it.
- Variable binding: Word content controls with immutable binding IDs and manifest evidence. The current workflow does not depend on `[[...]]` or `{...}` marker-token replacement.
- Security: tenant-scoped Office/Entra SSO exchange, HMAC-signed short-lived AutoDraft tokens, PostgreSQL RLS/runtime-role separation, strict production CORS, and durable worker/object-store controls.

## Current sources of truth

Use `README.md`, `backend/README.md`, `backend/.env.example`, `docs/CURRENT_ARCHITECTURE.md`, `SECURITY.md`, and `RELEASE_CHECKS.md` for active build, deployment, and architecture guidance.

## Compatibility

`tsconfig.json` may transpile JavaScript syntax to ES5, but that is a compilation target rather than an IE 11 support promise. React 18 requires a modern supported Office host.
