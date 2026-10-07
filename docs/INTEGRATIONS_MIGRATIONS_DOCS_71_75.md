# Issues 71–75 completion ledger

## 71 — Transactional outbox delivery

Implemented organization-scoped webhook endpoints, encrypted per-endpoint signing secrets, deterministic idempotency keys, lease/reclaim semantics, canonical JSON signing, retryable-status classification, exponential backoff, immutable delivery-attempt rows, dead-letter state, admin inspection/retry APIs, SSRF-oriented target checks, and a dedicated `python -m app.webhook_worker_process` dispatcher.

## 72 — SQLx checksum equivalence

The Python migration runner now reads `version, checksum` from successful `_sqlx_migrations` rows and compares SQLx's SHA-384 checksum against the exact local SQL file bytes. A version match with a checksum mismatch is a hard failure. A SQLx history table without checksum evidence is also rejected.

## 73 — Real PostgreSQL adversarial coverage

`tests/test_postgres_contract_integration.py` now includes opt-in gates for forced RLS/policies across tenant-owned tables, tenant-aware FK metadata, cross-tenant CRUD attempts, cross-tenant parent spoofing, missing tenant context, and public intake/workflow token bootstrap. Use distinct migration/runtime URLs as documented in `MIGRATION_AND_RLS_RELEASE_GATES.md`.

## 74 — Current production authentication documentation

Root/backend security documentation now treats Office/Entra SSO plus short-lived HMAC AutoDraft tokens as the production model. `API_AUTH_TOKEN` is explicitly deprecated local compatibility only and was removed from example environment files for new deployments.

## 75 — Historical architecture separation

Rust/Axum parallel-processing/performance notes and superseded LLM/determinism plans were moved to `docs/archive/`. `docs/CURRENT_ARCHITECTURE.md` is the concise active source of truth, and the release audit prevents selected obsolete markers from returning to active documentation.
