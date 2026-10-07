# AI, binary storage, generation and pagination hardening (64-70)

## Tenant AI policy
External Jev/System-1 processing is default-deny per organization. An administrator must explicitly enable it through the organization AI-policy API. Deployment-level Jev credentials merely make the provider available; they do not grant tenant consent.

Candidate decisions are persisted in `candidate_decision_audit` with candidate/source fingerprint, provider chain and exact provider model versions, rule-set version, prompt/schema version, decision path/evidence and final lawyer disposition.

## Binary document storage
New full DOCX writes for templates, template versions, Matter Documents and generation artifacts store immutable object keys, SHA-256 and byte lengths in PostgreSQL. Legacy Base64 columns remain nullable only for backward-compatible reads.

Before production cutover, migrate legacy rows with:

```bash
cd backend
python -m app.binary_storage_migrate --dry-run
python -m app.binary_storage_migrate
```

`BINARY_OBJECT_STORE_PATH` must be durable and shared by all API and runtime-worker instances. The current filesystem implementation intentionally exposes a small contract that may be replaced by S3/Azure Blob/GCS.

Large template and Matter Document uploads use multipart/binary routes. JSON bodies are capped before FastAPI/Pydantic materialization, preventing very large Base64 JSON requests from consuming memory before validation.

## Authoritative generation
`saveToMatter=true` requests enqueue a durable `generation` runtime job and require an idempotency key. The queue supports ownership, cancellation, persisted progress events, cluster-wide concurrency and immutable `generation_attempts`. Generated DOCX bytes are stored in the binary object store; runtime job state contains only metadata and download URLs.

## Cursor pagination
Keyset cursor pagination is used for matters, contacts, templates, workflows, workflow sessions, document sets, Matter Documents, canonical field values and generation artifacts. The Word client automatically walks cursor pages for screens that still need an aggregate list.


### Encryption at rest

Filesystem-backed runtime and binary objects support mandatory production AES-256-GCM encryption through `OBJECT_STORE_ENCRYPTION_KEY`. New writes are encrypted and authenticated; run `python -m app.object_store_encrypt` to rewrite pre-existing plaintext objects after enabling the key.
