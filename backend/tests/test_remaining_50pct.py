from __future__ import annotations

import base64
import io
import uuid
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.auth import create_hmac_token, verify_hmac_token
from app.domain.facts import evaluate_expression
from app.storage import decode_private_docx, safe_filename

ROOT = Path(__file__).resolve().parents[2]


def test_signed_security_context_round_trip_and_tamper_rejected():
    org=str(uuid.uuid4()); user=str(uuid.uuid4()); secret="this-is-a-long-test-secret"
    token=create_hmac_token(secret=secret,organization_id=org,user_id=user,role="lawyer")
    ctx=verify_hmac_token(token,secret)
    assert ctx.organization_id==org and ctx.user_id==user and ctx.role=="lawyer"
    with pytest.raises(HTTPException): verify_hmac_token(token+"x",secret)


def test_derived_fact_dsl_is_deterministic_and_does_not_eval_code():
    result=evaluate_expression({"op":"concat","separator":" ","args":[{"fact":"client.first"},{"fact":"client.last"}]},{"client.first":"Asha","client.last":"Patel"})
    assert result and result.value=="Asha Patel"
    assert evaluate_expression({"op":"__import__","args":[]},{}) is None


def test_private_docx_validation_and_filename_sanitization():
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w") as z:
        z.writestr("[Content_Types].xml","<Types/>")
        z.writestr("word/document.xml","<w:document/>")
    encoded=base64.b64encode(buf.getvalue()).decode()
    blob=decode_private_docx(encoded,max_bytes=1024*1024)
    assert blob.content.startswith(b"PK") and blob.sha256
    assert safe_filename("../../client.docx","fallback.docx")=="client.docx"
    with pytest.raises(ValueError): decode_private_docx(base64.b64encode(b"not a docx").decode(),max_bytes=1024)


def test_main_is_thin_and_backend_is_decomposed():
    main=(ROOT/"backend/app/main.py").read_text()
    assert len(main.splitlines()) < 180
    for relative in [
        "backend/app/api/matters.py","backend/app/api/intake.py","backend/app/api/templates.py",
        "backend/app/services/matter_service.py","backend/app/repositories/intake.py","backend/app/domain/facts.py",
    ]: assert (ROOT/relative).exists()


def test_word_mutations_are_centralized_behind_operation_queue():
    src=ROOT/"word-extension/src"
    offenders=[]
    for path in src.rglob("*.ts*"):
        if path.name=="operationQueue.ts": continue
        text=path.read_text(errors="ignore")
        if "Word.run(" in text: offenders.append(str(path.relative_to(ROOT)))
    assert offenders==[]


def test_tenant_creates_use_request_scoped_postgres_organization():
    combined="\n".join((ROOT/p).read_text() for p in [
        "backend/app/repositories/matters.py","backend/app/repositories/templates.py",
        "backend/app/repositories/documents.py","backend/app/repositories/intake.py",
    ])
    assert "autodraft_current_organization_id()" in combined
    migration=(ROOT/"backend/migrations/20261005000017_rls_runtime_hardening.sql").read_text()
    assert "FORCE ROW LEVEL SECURITY" in migration and "autodraft_tenant_isolation" in migration
    assert "COALESCE(NULLIF(current_setting" not in migration
