from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.auth import validate_security_configuration
from app.config import Settings
from app.intake_file_security import IntakeFileRejected, inspect_upload
from app.intake_validation import UnsafeIntakeRegex, validate_intake_answers, validate_safe_regex

ROOT = Path(__file__).resolve().parents[2]


def test_public_workflow_does_not_embed_bearer_token_in_executable_js():
    source = (ROOT / "backend/app/api/workflows.py").read_text()
    assert "decodeURIComponent(location.pathname" in source
    assert "safe_token" not in source
    assert ".replace(\"__TOKEN__\"" not in source


def test_public_intake_bootstrap_is_non_executable_json_and_token_comes_from_url():
    source = (ROOT / "backend/app/api/intake.py").read_text()
    assert 'type="application/json"' in source
    assert "JSON.parse(document.getElementById('intake-bootstrap').textContent" in source
    assert "decodeURIComponent(location.pathname" in source
    assert "const D=__PAYLOAD__" not in source


def test_strict_intake_validation_rejects_unknown_and_wrong_typed_fields():
    questions = [
        {"id": "email", "type": "email", "required": True, "validation": {}},
        {"id": "services", "type": "multi_select", "options": ["Drafting", "Review"], "validation": {}},
        {"id": "date", "type": "date", "validation": {}},
        {"id": "agree", "type": "boolean", "validation": {}},
    ]
    result = validate_intake_answers(
        questions,
        {"email": "not-an-email", "services": "Drafting", "date": "tomorrow", "agree": "maybe", "undeclared": "x"},
    )
    assert set(result.invalid) == {"email", "services", "date", "agree"}
    assert result.unknown == ["undeclared"]


def test_strict_intake_validation_normalizes_valid_browser_types():
    questions = [
        {"id": "amount", "type": "currency", "required": True, "validation": {"minValue": 1}},
        {"id": "services", "type": "multi_select", "options": ["Drafting", "Review"], "validation": {}},
        {"id": "agree", "type": "boolean", "validation": {}},
        {"id": "proof", "type": "file", "required": True, "validation": {"allowedExtensions": [".pdf"]}},
    ]
    result = validate_intake_answers(
        questions,
        {"amount": "30.00", "services": ["Drafting"], "agree": True, "proof": "proof.pdf"},
        uploaded_file_question_ids={"proof"},
    )
    assert result.ok
    assert result.normalized["amount"] == "30.00"
    assert result.normalized["agree"] == "Yes"
    assert result.normalized["services"] == ["Drafting"]


def test_unsafe_regex_constructs_are_rejected_before_public_matching():
    with pytest.raises(UnsafeIntakeRegex):
        validate_safe_regex(r"^(a+)+$")
    with pytest.raises(UnsafeIntakeRegex):
        validate_safe_regex(r"^(a|aa)+$")
    with pytest.raises(UnsafeIntakeRegex):
        validate_safe_regex(r"^(?=a)a$")
    assert validate_safe_regex(r"^[A-Z]{2}[0-9]{4}$").fullmatch("AB1234")


def _minimal_docx() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_intake_uploads_are_identified_from_content_not_declared_mime():
    pdf = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    inspected = inspect_upload(pdf, filename="evidence.pdf", declared_mime="application/pdf", allowed_extensions=[".pdf"])
    assert inspected.detected_mime == "application/pdf"
    with pytest.raises(IntakeFileRejected):
        inspect_upload(pdf, filename="evidence.jpg", declared_mime="image/jpeg", allowed_extensions=[".jpg"])
    with pytest.raises(IntakeFileRejected):
        inspect_upload(pdf + b"PK\x03\x04evil", filename="evidence.pdf", declared_mime="application/pdf", allowed_extensions=[".pdf"])


def test_docx_upload_requires_safe_real_docx_package():
    inspected = inspect_upload(
        _minimal_docx(),
        filename="evidence.docx",
        declared_mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        allowed_extensions=[".docx"],
    )
    assert inspected.detected_mime.endswith("wordprocessingml.document")
    with pytest.raises(IntakeFileRejected):
        inspect_upload(b"PK\x03\x04not-a-docx", filename="evidence.docx", declared_mime="application/octet-stream", allowed_extensions=[".docx"])


def test_production_requires_malware_scan_policy_to_remain_enabled():
    settings = Settings(
        _env_file=None,
        security_mode="token",
        auth_hmac_secret="secret",
        intake_require_malware_scan_in_production=False,
    )
    with pytest.raises(RuntimeError, match="MALWARE_SCAN"):
        validate_security_configuration(settings)


def test_legacy_intake_routes_through_versioned_engine_and_shared_validator():
    service = (ROOT / "backend/app/services/intake_service.py").read_text()
    api = (ROOT / "backend/app/api/intake.py").read_text()
    assert "legacy-intake-migrate:" in service
    assert "return await self.submit(token, answers)" in service
    assert "validate_intake_answers" in service
    assert "return await service.submit_legacy(token,req.answers)" in api


def test_upload_quarantine_and_multi_level_quotas_are_database_backed():
    migration = (ROOT / "backend/migrations/20261006000025_public_intake_hardening.sql").read_text()
    service = (ROOT / "backend/app/services/intake_service.py").read_text()
    config = (ROOT / "backend/app/config.py").read_text()
    assert "CREATE TABLE IF NOT EXISTS intake_file_quarantine" in migration
    assert "FORCE ROW LEVEL SECURITY" in migration
    assert "intake_session_storage_quota_bytes" in config
    assert "intake_org_daily_upload_quota_bytes" in config
    assert "intake_session_file_count_limit" in config
    assert "pg_advisory_xact_lock" in service
    assert "Organization daily intake upload quota exceeded" in service
    assert "Intake session storage quota exceeded" in service
