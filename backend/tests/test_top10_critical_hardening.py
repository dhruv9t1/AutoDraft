from __future__ import annotations

import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.docx_safety import UnsafeDocxPackage, safe_docx_zip
from app.models import MatterAuthorityRequest
from app.security import SensitivePathLogFilter, redact_sensitive_path
from app.token_security import bearer_token_hash

ROOT = Path(__file__).resolve().parents[2]


def _docx(*, extra: dict[str, bytes] | None = None, relationship_xml: bytes | None = None) -> bytes:
    buf = io.BytesIO()
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="xml" ContentType="application/xml"/>
 <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>'''
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        if relationship_xml is not None:
            zf.writestr("word/_rels/document.xml.rels", relationship_xml)
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_intake_tokens_are_hashed_and_paths_are_redacted():
    assert bearer_token_hash("secret-token") != "secret-token"
    assert redact_sensitive_path("/api/intake/public/very-secret-token/submit") == "/api/intake/public/[REDACTED]/submit"
    assert redact_sensitive_path("/workflow/very-secret-token") == "/workflow/[REDACTED]"
    import logging
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1", "GET", "/workflow/very-secret-token", "1.1", 200), None)
    assert SensitivePathLogFilter().filter(record)
    assert record.args[2] == "/workflow/[REDACTED]"
    migration = (ROOT / "backend/migrations/20261005000022_top10_critical_hardening.sql").read_text()
    assert "DROP COLUMN IF EXISTS token" in migration
    assert "public_intake_token_hashes" in migration
    repo = (ROOT / "backend/app/repositories/intake.py").read_text()
    assert "bearer_token_hash" in repo
    assert "public_intake_tokens" not in repo


def test_authority_verification_cannot_be_client_asserted():
    assert "verified" not in MatterAuthorityRequest.model_fields
    repo = (ROOT / "backend/app/repositories/matters.py").read_text()
    assert "VALUES($1,$2,$3,$4,FALSE,'unverified')" in repo
    verifier = (ROOT / "backend/app/citation_verifier.py").read_text()
    assert '"source_matched"' in verifier
    assert '"verified"' not in verifier.split("def verify_citations", 1)[-1]


def test_word_manifest_replacement_is_add_verify_then_delete_and_binding_rolls_back_on_manifest_failure():
    manifest = (ROOT / "word-extension/src/services/documentManifest.ts").read_text()
    add_at = manifest.index("const replacement = await addPart")
    verify_at = manifest.index("const verified = parseXml", add_at)
    delete_at = manifest.index("await Promise.all(matches.map(deletePart))", verify_at)
    assert add_at < verify_at < delete_at
    binding = (ROOT / "word-extension/src/services/word/bindingService.ts").read_text()
    assert "rollbackCreatedControlIds(payload.createdControlIds)" in binding
    assert "manifest evidence could not be persisted" in binding


def test_workflow_and_template_evaluation_fail_closed():
    workflow = (ROOT / "backend/app/domain/workflows.py").read_text()
    assert "raise WorkflowEvaluationError" in workflow
    renderer = (ROOT / "backend/app/domain/template_automation.py").read_text()
    assert "Binding {tag} evaluation failed" in renderer
    assert "Condition {tag} evaluation failed" in renderer
    assert "Repeater {tag} collection evaluation failed" in renderer
    assert "UNSUPPORTED_WORD_STORY" in renderer


def test_generation_requires_state_required_items_and_idempotency():
    service = (ROOT / "backend/app/services/generation_service.py").read_text()
    assert "allowed only while the run is in Population" in service
    assert "Generation run omits required document-set items" in service
    assert "idempotencyKey is required" in service
    assert "generation_attempts" in service
    api = (ROOT / "backend/app/api/automation.py").read_text()
    assert "if req.data_overrides" in api and "require_role(ctx,'lawyer')" in api


def test_request_and_render_limits_are_enforced_before_or_during_materialization():
    main = (ROOT / "backend/app/main.py").read_text()
    security = (ROOT / "backend/app/security.py").read_text()
    renderer = (ROOT / "backend/app/domain/template_automation.py").read_text()
    assert "RequestBodyLimitMiddleware" in main
    assert "content-length" in security
    assert "max_repeater_items" in renderer
    assert "max_total_repeated_items" in renderer
    assert "max_rendered_docx_bytes" in renderer


def test_docx_policy_accepts_normal_package_and_rejects_active_external_content():
    with safe_docx_zip(_docx()) as zf:
        assert "word/document.xml" in zf.namelist()
    with pytest.raises(UnsafeDocxPackage):
        with safe_docx_zip(_docx(extra={"word/vbaProject.bin": b"macro"})):
            pass
    external = b'''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Type="x" Target="https://example.com/payload" TargetMode="External"/>
    </Relationships>'''
    with pytest.raises(UnsafeDocxPackage):
        with safe_docx_zip(_docx(relationship_xml=external)):
            pass


def test_frontend_production_auth_has_no_compiled_shared_secret_and_logger_is_off_by_default():
    config = (ROOT / "word-extension/src/services/config.ts").read_text()
    auth = (ROOT / "word-extension/src/services/authService.ts").read_text()
    logger = (ROOT / "word-extension/src/services/logger.ts").read_text()
    assert "REACT_APP_API_AUTH_TOKEN" not in config
    assert "/api/auth/office-exchange" in auth
    assert 'isSetSupported("IdentityAPI", "1.3")' in auth
    assert "scheduleRefresh" in auth
    assert 'REACT_APP_ENABLE_DIAGNOSTIC_LOGGING === "true"' in logger
    assert "private enabled = diagnosticEnabled" in logger


def test_production_manifest_renderer_adds_webapplicationinfo(tmp_path: Path):
    output = tmp_path / "manifest.production.xml"
    env = os.environ.copy()
    env.update({
        "AUTODRAFT_ENTRA_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
        "AUTODRAFT_ENTRA_RESOURCE_URI": "api://addin.example.com/11111111-1111-1111-1111-111111111111",
        "AUTODRAFT_ADDIN_ORIGIN": "https://addin.example.com",
    })
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/render-production-manifest.py"), str(output)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )
    xml = output.read_text()
    assert "<WebApplicationInfo>" in xml
    assert "api://addin.example.com/11111111-1111-1111-1111-111111111111" in xml
    assert "https://localhost:3000" not in xml
    assert xml.index("<WebApplicationInfo>") < xml.index("</VersionOverrides>")


def test_release_gate_requires_real_external_evidence():
    gate = (ROOT / "scripts/run-real-environment-gates.sh").read_text()
    for name in (
        "AUTODRAFT_TEST_DATABASE_URL",
        "AUTODRAFT_ENTRA_CLIENT_ID",
        "AUTODRAFT_OCR_SMOKE_INPUT",
        "AUTODRAFT_WORD_E2E_EVIDENCE",
    ):
        assert name in gate
    assert "python -m scripts.fault_injection_live" in gate
    assert "python -m scripts.ocr_smoke" in gate
    assert "npm ci" in gate
    assert "verify-word-e2e-evidence.py" in gate
