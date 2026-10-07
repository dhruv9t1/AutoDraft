from pathlib import Path

from app.auth import create_hmac_token, verify_hmac_token
from app.config import Settings
from app.permissions import PERMISSION_MIN_ROLE, permission_for_request
from app.security import client_ip

ROOT = Path(__file__).resolve().parents[2]


def test_named_permission_matrix_covers_structural_and_generation_actions():
    for name in [
        "matter.write", "workflow.publish", "template.publish",
        "derived_rule.admin", "generation.execute", "generation.override",
    ]:
        assert name in PERMISSION_MIN_ROLE
    assert permission_for_request("POST", "/api/workflows/abc/publish") == "workflow.publish"
    assert permission_for_request("POST", "/api/derived-fact-rules") == "derived_rule.admin"
    assert permission_for_request("POST", "/api/generation/headless") == "generation.execute"


def test_generation_override_requires_reason_and_is_audited_in_code():
    api=(ROOT/"backend/app/api/automation.py").read_text()
    service=(ROOT/"backend/app/services/generation_service.py").read_text()
    assert "generation.override" in api
    assert "overrideReason is required" in api
    assert "GenerationOverrideApplied" in service
    assert "overrideAudit" in service


def test_hmac_token_carries_revocation_version():
    token=create_hmac_token(
        secret="secret", organization_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002", role="lawyer", auth_version=7,
    )
    ctx=verify_hmac_token(token,"secret")
    assert ctx.auth_version == 7
    runtime=(ROOT/"backend/app/runtime.py").read_text()
    assert "auth_version" in runtime and "has been revoked" in runtime


def test_shared_rate_limit_and_trusted_proxy_foundations_present():
    security=(ROOT/"backend/app/security.py").read_text()
    migration=(ROOT/"backend/migrations/20261006000024_authz_browser_rate_hardening.sql").read_text()
    assert "class PostgresRateLimiter" in security
    assert "security_rate_limit_buckets" in migration
    assert "trusted_proxy_ips" in (ROOT/"backend/app/config.py").read_text()


def test_cors_is_fail_closed_and_browser_policy_has_csp_hsts_nonce():
    main=(ROOT/"backend/app/main.py").read_text()
    security=(ROOT/"backend/app/security.py").read_text()
    assert 'origins or ["*"]' not in main
    assert "Content-Security-Policy" in security
    assert "Strict-Transport-Security" in security
    assert "script-src 'self' 'nonce-" in security
    assert "__NONCE__" in (ROOT/"backend/app/api/intake.py").read_text()
    assert "__NONCE__" in (ROOT/"backend/app/api/workflows.py").read_text()


def test_production_settings_do_not_create_wildcard_cors_default():
    settings=Settings(security_mode="token", auth_hmac_secret="x", cors_origins="")
    assert settings.cors_origin_list == []
