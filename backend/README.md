# AutoDraft Backend — Python / FastAPI

The AutoDraft backend has been migrated from Rust/Axum to **Python 3.11-3.13 and FastAPI**. The Microsoft Word React/TypeScript add-in keeps the same HTTP API contract, so the frontend does not need a framework rewrite.

## Stack

- Python 3.11-3.13
- FastAPI + Uvicorn
- PostgreSQL via `asyncpg`
- `httpx` for Ollama/OpenAI-compatible AI calls
- Pydantic v2 request/response models
- Existing SQL migrations retained

## Quick start

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -e .
cp .env.example .env
python scripts/migrate.py
python run.py
```

The API listens on `http://127.0.0.1:3001` by default.

Development with reload:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 3001 --reload
```

Tests (development dependencies):

```bash
pip install -e ".[dev]"
pytest -q
```

`requirements.txt` remains available for deployment tooling that expects a pinned runtime requirements file; `requirements-dev.txt` adds the test dependencies.

## Preserved AutoDraft behavior

The Python port retains the cumulative functionality from the previous build: tenant-scoped SSO/HMAC authentication, CORS configuration, sensitive-log hardening, deterministic Indian legal-field extraction, 8K accuracy-first chunks, two-pass extraction/coverage audit, UTF-safe Python string chunking, exact-position preservation, same-value/different-semantic-field preservation, SSE variable streaming, PostgreSQL templates/variables, reusable empty-template OOXML, chunked OOXML upload, manual variable persistence, variable rename/value persistence, document analysis endpoints, and Word wrapping-plan generation.

## Important environment variables

See `.env.example`. Recommended extraction settings remain:

```env
OLLAMA_CHUNK_SIZE=8000
OLLAMA_EXTRACTION_PASSES=2
OLLAMA_MAX_PARALLEL_CHUNKS=2
OLLAMA_TEMPERATURE=0.0
OLLAMA_TOP_K=1
OLLAMA_SEED=42
```

For any shared/remote deployment, use `SECURITY_MODE=token`, an `AUTH_HMAC_SECRET` generated from at least 32 random bytes (for example `secrets.token_urlsafe(32)`), Microsoft Entra settings (`ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID`, `ENTRA_RESOURCE_URI`), and a strict `CORS_ORIGINS` list. `API_AUTH_TOKEN` is deprecated local compatibility only; production uses Office/Entra SSO plus `AUTH_HMAC_SECRET`.

The shared fixed-window rate limiter reserves small permit leases in PostgreSQL (`RATE_LIMIT_LEASE_SIZE`, default 10) and consumes those permits in-process. If the rate-limit table is temporarily unavailable, requests use the explicitly bounded per-process `RATE_LIMIT_FALLBACK_REQUESTS` ceiling and retry PostgreSQL after `RATE_LIMIT_DB_RETRY_SECONDS`; this avoids coupling all API availability to the limiter database while remaining bounded. `/api/health` is deliberately exempt so database failures can still be reported by health infrastructure.

## Layout

```text
backend/
  app/
    main.py              FastAPI composition, middleware, lifecycle
    api/                  HTTP route modules
    services/             application/use-case services
    repositories/         persistence adapters
    domain/               workflow/expression/domain logic
    ai/                   model/provider orchestration
    extraction/           extraction pipeline components
    config.py             environment settings
    db.py                 async PostgreSQL pool / tenant context
    models.py             shared Pydantic API models
    security.py           request limits, headers, IP/rate limiting
    intake_validation.py  public intake answer validation
    safe_regex.py         shared safe-regex validation
  migrations/             PostgreSQL migrations
  scripts/migrate.py      migration runner
  tests/                  Python regression tests
  pyproject.toml          package + runtime/dev dependency metadata
  requirements.txt        pinned runtime compatibility file
  requirements-dev.txt    runtime + test dependencies
  run.py
```


## Durable runtime workers and object storage

OCR/extraction jobs and chunk sessions are tenant- and user-owned. PostgreSQL stores queue metadata only; large job payloads, OCR input/output and chunk bodies are written through `RuntimeObjectStore` under `RUNTIME_OBJECT_STORE_PATH`. In token/production mode `OBJECT_STORE_ENCRYPTION_KEY` is mandatory and both runtime objects and immutable binaries are encrypted with AES-256-GCM before filesystem persistence. Production deployments should mount the paths on durable shared storage visible to every API and runtime-worker instance. Existing plaintext object stores can be converted once with `python -m app.object_store_encrypt` after the key is configured.

In `SECURITY_MODE=token`, `RUNTIME_WORKER_MODE=auto` keeps background work out of API processes. Run one or more dedicated worker services with:

```bash
python -m app.runtime_worker_process
```

`RUNTIME_CLUSTER_CONCURRENCY` is enforced transactionally in PostgreSQL, so adding worker processes cannot exceed the configured global OCR/extraction concurrency. Per-organization/user job quotas, per-user chunk-session quotas, incremental declared-size checks and an organization temporary-byte quota protect the shared runtime resources.


## Webhook/outbox worker

Domain events are persisted transactionally to `outbox_events`. Configure `WEBHOOK_SECRET_ENCRYPTION_KEY`, create organization-scoped endpoints through `/api/integrations/webhooks`, and run the dispatcher separately:

```bash
python -m app.webhook_worker_process
```

The dispatcher leases deliveries, sends canonical JSON with HMAC-SHA256 signatures and stable idempotency keys, retries retryable failures with exponential backoff, records every attempt, and moves exhausted/non-retryable deliveries to a dead-letter state that an administrator may explicitly retry.


Rejected intake uploads use separate quarantine quotas and a background quarantine janitor. `INTAKE_QUARANTINE_RETENTION_SECONDS` controls retention and `INTAKE_QUARANTINE_CLEANUP_INTERVAL_SECONDS` controls periodic cleanup; cleanup is tenant-scoped and does not depend on another upload arriving.
