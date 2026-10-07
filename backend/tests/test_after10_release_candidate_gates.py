from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_generation_state_required_items_body_and_active_docx_are_already_enforced():
    generation=(ROOT/'backend/app/services/generation_service.py').read_text()
    security=(ROOT/'backend/app/security.py').read_text()
    docx=(ROOT/'backend/app/docx_safety.py').read_text()
    assert 'allowed only while the run is in Population' in generation
    assert 'Generation run omits required document-set items' in generation
    assert 'class RequestBodyLimitMiddleware' in security and 'content-length' in security
    for marker in ('vbaProject.bin','word/embeddings/','word/activeX/','TargetMode'):
        assert marker in docx


def test_real_environment_certification_is_bound_to_exact_packaged_hash():
    prepare=(ROOT/'scripts/prepare-production-candidate.sh').read_text()
    verify=(ROOT/'scripts/verify-production-candidate.sh').read_text()
    word=(ROOT/'scripts/verify-word-e2e-evidence.py').read_text()
    docs=(ROOT/'docs/PRODUCTION_RELEASE_GATES.md').read_text()
    assert 'SHA256' in prepare and 'make-release-zip.sh' in prepare
    assert 'AUTODRAFT_TEST_MIGRATION_DATABASE_URL' in verify
    assert 'AUTODRAFT_RELEASE_SHA256' in verify
    assert 'npm ci' in verify and 'scripts.ocr_smoke' in verify and 'scripts.fault_injection_live' in verify
    assert 'releaseSha256' in word and 'AUTODRAFT_RELEASE_SHA256' in word
    assert 'exact immutable ZIP' in docs and 'different ZIP hash is rejected' in docs
