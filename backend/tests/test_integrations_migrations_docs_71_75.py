from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.db import _sqlx_checksum
from app.webhook_security import WebhookSecretBox, canonical_webhook_body, sign_webhook, validate_webhook_url, WebhookSecurityError

ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/"backend"


def test_sqlx_checksum_uses_exact_sha384_bytes(tmp_path:Path):
    path=tmp_path/"20260101000000_example.sql"
    raw=b"-- keep CRLF\r\nSELECT 1;\r\n"
    path.write_bytes(raw)
    assert _sqlx_checksum(path)==hashlib.sha384(raw).digest()


def test_migration_runner_requires_sqlx_checksum_equivalence():
    source=(BACKEND/"app"/"db.py").read_text()
    assert "SELECT version,checksum FROM _sqlx_migrations WHERE success = TRUE" in source
    assert "hmac.compare_digest(expected_sqlx, stored_sqlx)" in source
    assert "cannot prove migration equivalence safely" in source


def test_webhook_secrets_encrypt_and_sign_without_plaintext_storage():
    box=WebhookSecretBox("x"*48)
    encrypted=box.encrypt("00000000-0000-0000-0000-000000000123","super-secret-value")
    assert "super-secret-value" not in encrypted
    assert box.decrypt("00000000-0000-0000-0000-000000000123",encrypted)=="super-secret-value"
    body=canonical_webhook_body({"b":2,"a":1})
    sig=sign_webhook("secret","123","delivery",body)
    assert sig.value.startswith("v1=") and len(sig.value)==67


def test_webhook_url_policy_requires_https_in_production():
    assert validate_webhook_url("https://example.com/hook",production=True)=="https://example.com/hook"
    with pytest.raises(WebhookSecurityError): validate_webhook_url("http://example.com/hook",production=True)
    with pytest.raises(WebhookSecurityError): validate_webhook_url("https://u:p@example.com/hook",production=True)


def test_webhook_migration_contains_complete_delivery_contract():
    sql=(BACKEND/"migrations"/"20261006000028_webhook_delivery_system.sql").read_text()
    for token in (
        "webhook_endpoints","webhook_deliveries","webhook_delivery_attempts","idempotency_key",
        "lease_expires_at","attempt_count","autodraft_claim_webhook_delivery",
        "autodraft_finish_webhook_delivery","backoff_base_seconds","status='dead'",
        "FOR UPDATE OF d SKIP LOCKED","FORCE ROW LEVEL SECURITY",
    ):
        assert token in sql


def test_integration_worker_sends_signing_and_idempotency_headers():
    src=(BACKEND/"app"/"webhook_worker.py").read_text()
    assert '"Idempotency-Key"' in src
    assert '"X-AutoDraft-Signature"' in src
    assert '"X-AutoDraft-Timestamp"' in src
    assert "follow_redirects=False" in src


def test_security_docs_use_current_sso_model_and_legacy_docs_are_archived():
    for rel in ("README.md","SECURITY.md","backend/README.md"):
        text=(ROOT/rel).read_text()
        assert "AUTH_HMAC_SECRET" in text
        assert "Entra" in text or "SSO" in text
    assert not (ROOT/"test-parallel-processing.md").exists()
    assert not (ROOT/"docs"/"LLM_TRAINING_PLAN.md").exists()
    assert (ROOT/"docs"/"archive"/"test-parallel-processing-rust-legacy.md").exists()
    assert (ROOT/"docs"/"archive"/"LLM_TRAINING_PLAN_legacy.md").exists()
