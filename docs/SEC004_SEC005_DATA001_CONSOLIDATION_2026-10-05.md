# SEC-004 / SEC-005 / DATA-001 Consolidation — 2026-10-05

This pass builds on the SEC-001 through SEC-004 baseline and implements the requested consolidation items.

## SEC-004 completion — comprehensive tenant isolation

- Added tenant ownership to legacy/indirect child tables that previously inherited tenancy only through a parent.
- Applied fail-closed `autodraft_current_organization_id()` defaults for new tenant-owned rows.
- Enabled and forced RLS with the fail-closed `autodraft_tenant_isolation` policy across all normal organization-owned domain tables.
- `app_users`, legacy `intake_forms`, and `audit_events` are now included.
- Public token-routing tables remain outside RLS intentionally because they are used only to resolve a bearer token to an organization before tenant context exists.
- Startup diagnostics now reject any normal `organization_id` table lacking enabled+forced RLS and the tenant policy.

## SEC-005 — same-tenant relational integrity

- Added `(organization_id,id)` unique keys to tenant parents.
- Added composite tenant-aware foreign keys for matter/contact/field, intake/questionnaire, document-set/template, workflow/session, generation/artifact, and public token-routing relationships.
- Cross-tenant parent/child UUID references are therefore rejected by PostgreSQL even if application code omits a tenant predicate.

## DATA-001 — one authoritative legal-value store

- `matter_field_values` is now the authoritative typed matter legal-value store.
- Added `CanonicalLegalValueRepository` as the shared write/projection boundary.
- Direct canonical field writes, legacy matter-fact writes, derived values, workflow promotion, and field-value APIs converge on the typed store.
- Canonical rows in `matter_facts` are retained as a compatibility projection and are updated transactionally from `matter_field_values`.
- A database trigger rejects independent writes to canonical `matter_facts` rows unless the controlled projection gate is active.
- Generation/automation matter data no longer falls back to `matter_facts`; it reads the authoritative typed values only.
- Conflict candidates remain non-canonical history rows in `matter_facts`; conflict resolution commits the approved value to `matter_field_values` and then projects it back for compatibility.

## Validation performed in this environment

- Python compileall: PASS.
- Focused SEC-004/SEC-005/DATA-001 tests: PASS.
- Backend test suite with a test-only `asyncpg` import shim: 115 passed, 2 skipped.
- The two skipped tests require `AUTODRAFT_TEST_DATABASE_URL` and a real PostgreSQL server.
- Real PostgreSQL migration/RLS/foreign-key execution remains a release gate and is not claimed as proven by this environment.
