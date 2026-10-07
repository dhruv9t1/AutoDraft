from __future__ import annotations

from pathlib import Path

import pytest

from app.db import MissingTenantContextError, ScopedPool, clear_request_organization, reset_request_organization

ROOT = Path(__file__).resolve().parents[2]


def test_production_scoped_pool_fails_without_tenant_context():
    token = clear_request_organization()
    try:
        pool = ScopedPool(object())  # type: ignore[arg-type]
        with pytest.raises(MissingTenantContextError):
            pool._organization()
    finally:
        reset_request_organization(token)


def test_local_default_tenant_requires_explicit_opt_in():
    token = clear_request_organization()
    try:
        pool = ScopedPool(
            object(),  # type: ignore[arg-type]
            allow_default_organization=True,
            default_organization_id="00000000-0000-0000-0000-000000000001",
        )
        assert pool._organization() == "00000000-0000-0000-0000-000000000001"
    finally:
        reset_request_organization(token)


def test_runtime_database_defaults_to_dedicated_role_and_separate_migrator_config():
    config = (ROOT / "backend/app/config.py").read_text()
    main = (ROOT / "backend/app/main.py").read_text()
    assert "postgresql://autodraft_app:" in config
    assert "migration_database_url" in config
    assert "assert_safe_runtime_role" in main
    assert "ALLOW_UNSAFE_DATABASE_ROLE" in (ROOT / "backend/.env.example").read_text()


def test_rls_hardening_migration_is_fail_closed_and_forced():
    migration = (ROOT / "backend/migrations/20261005000017_rls_runtime_hardening.sql").read_text()
    assert "CREATE OR REPLACE FUNCTION autodraft_current_organization_id()" in migration
    assert "AutoDraft tenant context is required" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "organization_id = autodraft_current_organization_id()" in migration
    assert "DROP DEFAULT" in migration
    assert "COALESCE(NULLIF(current_setting" not in migration


def test_application_inserts_no_longer_use_default_org_sql_fallback():
    application = "\n".join(
        path.read_text() for path in (ROOT / "backend/app").rglob("*.py")
    )
    assert "COALESCE(NULLIF(current_setting('autodraft.organization_id'" not in application
    assert "autodraft_current_organization_id()" in application
