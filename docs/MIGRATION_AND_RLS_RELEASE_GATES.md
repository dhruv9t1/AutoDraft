# Migration and tenant-isolation release gates

## SQLx history compatibility

AutoDraft's Python migration runner does not import SQLx history by version alone. For every successful `_sqlx_migrations` row whose version exists locally, the runner computes SQLx's SHA-384 checksum over the exact migration file bytes and requires it to equal the stored `checksum BYTEA`. A mismatch is a hard release/startup failure; operators must never edit an applied migration.

## Real PostgreSQL adversarial suite

Use a disposable PostgreSQL database with two distinct roles:

```bash
export AUTODRAFT_TEST_MIGRATION_DATABASE_URL='postgresql://...schema-owner.../autodraft_test'
export AUTODRAFT_TEST_DATABASE_URL='postgresql://...autodraft_app.../autodraft_test'
cd backend
pytest -q tests/test_postgres_contract_integration.py
```

The suite verifies:

- every normal organization-owned table has RLS enabled, forced and the AutoDraft tenant policy;
- runtime cross-tenant SELECT/UPDATE/DELETE visibility is blocked;
- cross-tenant INSERT is rejected;
- tenant-aware composite FKs reject parent spoofing for participants, canonical fields, workflows and generation;
- missing `autodraft.organization_id` fails closed;
- public intake and workflow bearer-token bootstrap resolves only the token's own tenant.

These tests are intentionally skipped unless both URLs are supplied. They are a production release gate, not unit-test evidence.
