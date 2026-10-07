# AutoDraft current architecture (v1.3 consolidated)

This document is the source of truth for the active implementation.

- **Backend:** Python 3.11+, FastAPI, asyncpg/PostgreSQL.
- **Word client:** React/TypeScript + Office.js.
- **Production identity:** Office/Microsoft Entra SSO -> `/api/auth/office-exchange` -> short-lived tenant-scoped HMAC AutoDraft token. Live `app_users.active`, role and `auth_version` are rechecked on protected requests.
- **Tenant isolation:** fail-closed tenant context, forced RLS for normal organization-owned tables, tenant-aware composite relationships, non-owner/NOBYPASSRLS runtime role.
- **Canonical legal data:** typed canonical field-value layer with conflict-aware writes and provenance.
- **Automation:** immutable workflows/templates/document sets, approved workflow trust boundary, queued authoritative generation.
- **Large binaries:** immutable application object store; PostgreSQL stores keys/hashes/metadata.
- **Long-running work:** durable PostgreSQL queue metadata + external object storage with dedicated runtime workers.
- **Integrations:** transactional outbox plus dedicated signed webhook dispatcher with leasing, retries, idempotency and dead-letter state.
- **AI:** deterministic/local Qwen/Ollama defaults (`qwen3:4b`); optional external Jev is organization-policy gated and default-deny.

Files under `docs/archive/` are historical design records. They may describe the former Rust/Axum backend, superseded model choices, or old performance assumptions and must not be used as current deployment guidance.
