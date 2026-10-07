from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import (
    create_hmac_token,
    resolve_security_context,
    validate_security_configuration,
)
from app.config import Settings
from app.db import clear_request_organization

ROOT = Path(__file__).resolve().parents[2]
ORG = "00000000-0000-0000-0000-000000000011"
USER = "00000000-0000-0000-0000-000000000022"


def _request(*, client_host: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/matters",
            "raw_path": b"/api/matters",
            "query_string": b"",
            "headers": raw_headers,
            "client": (client_host, 12345),
            "server": ("127.0.0.1", 3001),
        }
    )


def _settings(**overrides) -> Settings:
    values = {
        "security_mode": "local",
        "host": "127.0.0.1",
        "allow_external_local_auth": False,
        "auth_hmac_secret": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_local_security_mode_refuses_non_loopback_bind_by_default():
    with pytest.raises(RuntimeError, match="only bind to loopback"):
        validate_security_configuration(_settings(host="0.0.0.0"))


def test_local_security_mode_requires_explicit_override_for_external_bind():
    validate_security_configuration(
        _settings(host="0.0.0.0", allow_external_local_auth=True)
    )


def test_token_security_mode_requires_signed_user_token_configuration():
    with pytest.raises(RuntimeError, match="AUTH_HMAC_SECRET"):
        validate_security_configuration(_settings(security_mode="token"))


def test_external_request_cannot_claim_owner_role_through_local_headers():
    request = _request(
        client_host="203.0.113.10",
        headers={"X-Organization-ID": ORG, "X-User-ID": USER, "X-User-Role": "owner"},
    )
    with pytest.raises(HTTPException) as exc:
        resolve_security_context(request, _settings())
    assert exc.value.status_code == 403
    clear_request_organization()


def test_proxied_request_cannot_claim_owner_role_in_local_mode():
    request = _request(
        client_host="127.0.0.1",
        headers={
            "X-Forwarded-For": "203.0.113.10",
            "X-Organization-ID": ORG,
            "X-User-ID": USER,
            "X-User-Role": "owner",
        },
    )
    with pytest.raises(HTTPException) as exc:
        resolve_security_context(request, _settings())
    assert exc.value.status_code == 403
    clear_request_organization()


def test_token_mode_ignores_client_role_headers_and_uses_signed_claims():
    secret = "test-secret-for-signed-user-claims"
    token = create_hmac_token(
        secret=secret,
        organization_id=ORG,
        user_id=USER,
        role="staff",
        ttl_seconds=120,
    )
    request = _request(
        client_host="203.0.113.10",
        headers={"Authorization": f"Bearer {token}", "X-User-Role": "owner"},
    )
    ctx = resolve_security_context(
        request,
        _settings(security_mode="token", host="0.0.0.0", auth_hmac_secret=secret),
    )
    assert ctx.organization_id == ORG
    assert ctx.user_id == USER
    assert ctx.role == "staff"
    clear_request_organization()


def test_derived_fact_rules_migration_forces_rls_and_fail_closed_policy():
    migration = (
        ROOT / "backend/migrations/20261005000018_derived_fact_rules_tenant_isolation.sql"
    ).read_text()
    assert "ALTER TABLE derived_fact_rules ENABLE ROW LEVEL SECURITY" in migration
    assert "ALTER TABLE derived_fact_rules FORCE ROW LEVEL SECURITY" in migration
    assert "organization_id = autodraft_current_organization_id()" in migration
    assert "ON derived_fact_rules(organization_id, fact_key)" in migration


def test_derived_rule_access_is_centralized_and_explicitly_tenant_filtered():
    repository = (ROOT / "backend/app/repositories/derived_rules.py").read_text()
    matters_api = (ROOT / "backend/app/api/matters.py").read_text()
    matter_service = (ROOT / "backend/app/services/matter_service.py").read_text()
    assert "VALUES(autodraft_current_organization_id()" in repository
    assert repository.count("organization_id=autodraft_current_organization_id()") >= 3
    assert "derived_rule_repo.upsert" in matters_api
    assert "derived_rule_repo.list" in matters_api
    assert "self.derived_rules.enabled()" in matter_service
    assert "SELECT fact_key,label,value_type,expression FROM derived_fact_rules" not in matter_service
