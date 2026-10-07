from __future__ import annotations

from pathlib import Path

import pytest

from app.auth import validate_security_configuration
from app.config import Settings
from app.domain.template_automation import TemplateAutomationError, validate_blueprint
from app.domain.workflows import WorkflowDefinitionError, validate_workflow_definition
from app.webhook_security import WebhookSecurityError, resolve_safe_webhook_target

ROOT = Path(__file__).resolve().parents[2]


def _workflow(children):
    return {
        "pages": [{"id": "p1", "questions": [{"id": "r1", "type": "repeater", "semanticKey": "people", "children": children}]}],
        "calculations": [],
    }


def test_repeater_sibling_semantic_keys_must_be_unique():
    with pytest.raises(WorkflowDefinitionError, match="same scope"):
        validate_workflow_definition(_workflow([
            {"id": "a", "type": "text", "semanticKey": "person.name"},
            {"id": "b", "type": "text", "semanticKey": "person.name"},
        ]))


def test_same_child_key_may_exist_in_distinct_repeater_scopes():
    definition = {
        "pages": [{"id": "p1", "questions": [
            {"id": "r1", "type": "repeater", "semanticKey": "people", "children": [{"id": "a", "type": "text", "semanticKey": "name"}]},
            {"id": "r2", "type": "repeater", "semanticKey": "assets", "children": [{"id": "b", "type": "text", "semanticKey": "name"}]},
        ]}], "calculations": [],
    }
    validate_workflow_definition(definition)


def test_blueprint_rejects_duplicate_and_cross_type_tags():
    with pytest.raises(TemplateAutomationError, match="collides"):
        validate_blueprint({
            "bindings": [{"controlTag": "same", "semanticKey": "matter.name"}],
            "conditions": [{"regionTag": "same", "expression": True}],
        })
    with pytest.raises(TemplateAutomationError, match="collides"):
        validate_blueprint({"bindings": [
            {"controlTag": "same", "semanticKey": "matter.name"},
            {"controlTag": "same", "semanticKey": "matter.other"},
        ]})


def test_token_mode_rejects_short_hmac_secret_but_accepts_32_random_bytes_encoding():
    with pytest.raises(RuntimeError, match="too weak"):
        validate_security_configuration(Settings(_env_file=None, security_mode="token", auth_hmac_secret="short", intake_require_malware_scan_in_production=True))
    validate_security_configuration(Settings(_env_file=None, security_mode="token", auth_hmac_secret="A" * 43, object_store_encryption_key="B" * 64, intake_require_malware_scan_in_production=True))


@pytest.mark.asyncio
async def test_webhook_resolution_pins_validated_ip(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    target = await resolve_safe_webhook_target("https://example.com/hook?x=1", allow_private=False)
    assert target.url == "https://93.184.216.34/hook?x=1"
    assert target.host_header == "example.com"
    assert target.sni_hostname == "example.com"


@pytest.mark.asyncio
async def test_webhook_resolution_rejects_any_private_resolution(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(WebhookSecurityError, match="private/reserved"):
        await resolve_safe_webhook_target("https://example.com/hook", allow_private=False)


def test_public_workflow_structured_options_are_normalized_in_browser_code():
    source = (ROOT / "backend/app/api/workflows.py").read_text()
    assert "function optionParts(o)" in source
    assert "['value','id','key','label']" in source
    assert "op.value=n.value" in source
    assert "get().includes(o)" not in source


def test_quarantine_is_separate_from_accepted_upload_quota_and_expires():
    service = (ROOT / "backend/app/services/intake_service.py").read_text()
    config = (ROOT / "backend/app/config.py").read_text()
    quota_body = service.split("async def _quota_check", 1)[1].split("async def _quarantine_quota_check", 1)[0]
    assert "intake_file_quarantine" not in quota_body.replace("_purge_expired_quarantine", "")
    assert "intake_quarantine_retention_seconds" in config
    assert "DELETE FROM intake_file_quarantine" in service
    assert "intake_quarantine_session_storage_quota_bytes" in service


def test_successful_mutations_use_atomic_request_transaction_for_audit():
    main = (ROOT / "backend/app/main.py").read_text()
    db = (ROOT / "backend/app/db.py").read_text()
    auth_api = (ROOT / "backend/app/api/authentication.py").read_text()
    assert "async with db.p().request_transaction() as request_tx" in main
    assert "await request_tx.connection.execute" in main
    assert "audit event could not be persisted" not in main
    assert "class RequestTransactionScope" in db
    assert "_request_connection" in db
    assert "await db.p().execute(" in auth_api
