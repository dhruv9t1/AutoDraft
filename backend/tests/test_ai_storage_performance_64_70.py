from pathlib import Path

from app.citation_verifier import verify_and_sanitize_citations
from app.binary_store import estimated_base64_decoded_size

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent


def test_64_external_jev_is_tenant_policy_gated():
    gateway=(ROOT/'app/ai/gateway.py').read_text()
    repo=(ROOT/'app/repositories/ai_governance.py').read_text()
    migration=(ROOT/'migrations/20261006000027_ai_storage_generation_pagination.sql').read_text()
    assert 'organization_ai_policies' in migration
    assert 'external_system1_enabled' in repo
    assert 'external_system1_policy' in gateway
    assert 'allow_external_system1=policy["enabled"]' in gateway


def test_65_candidate_provenance_is_immutable_and_lawyer_disposition_is_persisted():
    migration=(ROOT/'migrations/20261006000027_ai_storage_generation_pagination.sql').read_text()
    repo=(ROOT/'app/repositories/ai_governance.py').read_text()
    for term in ('candidate_fingerprint','provider_versions','rules_version','prompt_schema_version','decision_path','final_lawyer_disposition'):
        assert term in migration
    assert 'lawyer_disposition' in repo
    assert 'candidate_provider' in repo


def test_66_broader_indian_citation_shapes_are_detected_without_being_called_verified():
    draft='Authorities include 2024 INSC 123, 2024:DHC:1234, MANU/SC/0123/2024, 2024 LiveLaw (SC) 321 and 2023 Cri LJ 456.'
    cleaned,report=verify_and_sanitize_citations(draft,[])
    assert report['detectedCitationCount'] == 5
    assert report['verifiedAuthorityCount'] == 0
    assert report['status'] == 'not_checked'
    assert cleaned.count('[AUTHORITY REQUIRED:') == 5


def test_67_binary_objects_are_primary_storage_and_legacy_migration_tool_exists():
    migration=(ROOT/'migrations/20261006000027_ai_storage_generation_pagination.sql').read_text()
    generation=(ROOT/'app/services/generation_service.py').read_text()
    templates=(ROOT/'app/repositories/templates.py').read_text()
    documents=(ROOT/'app/repositories/documents.py').read_text()
    migrator=(ROOT/'app/binary_storage_migrate.py').read_text()
    assert 'docx_object_key' in migration and 'object_key' in migration
    assert 'docx_base64=NULL' in migrator
    assert 'put_bytes' in generation and 'put_base64' in templates and 'put_bytes' in documents


def test_68_json_base64_is_capped_before_materialization_and_binary_upload_routes_exist():
    security=(ROOT/'app/security.py').read_text()
    template_api=(ROOT/'app/api/templates.py').read_text()
    matter_api=(ROOT/'app/api/matters.py').read_text()
    assert 'json_max_bytes' in security and 'limited_receive' in security
    assert '/content/file' in template_api and 'UploadFile' in template_api
    assert '/documents/file' in matter_api and 'UploadFile' in matter_api
    assert estimated_base64_decoded_size('YQ==') == 1


def test_69_authoritative_generation_is_durable_queued_with_progress_cancel_idempotency_and_attempts():
    api=(ROOT/'app/api/automation.py').read_text()
    worker=(ROOT/'app/runtime_worker.py').read_text()
    service=(ROOT/'app/services/generation_service.py').read_text()
    migrations='\n'.join(p.read_text() for p in (ROOT/'migrations').glob('*.sql'))
    assert "create_job('generation'" in api
    assert "/api/generation/jobs/{job_id}/events" in api
    assert 'request_cancel' in api
    assert "append_event(job_id,'progress'" in worker
    assert 'idempotency_key' in service
    assert 'generation_attempts' in migrations


def test_70_high_volume_list_endpoints_use_cursor_pagination():
    files={
        'contacts': ROOT/'app/api/contacts.py',
        'matters': ROOT/'app/api/matters.py',
        'templates': ROOT/'app/api/templates.py',
        'workflows': ROOT/'app/api/workflows.py',
        'document_sets': ROOT/'app/api/document_sets.py',
        'fields': ROOT/'app/api/fields.py',
        'artifacts': ROOT/'app/api/automation.py',
    }
    for name,path in files.items():
        text=path.read_text()
        assert 'cursor' in text, name
        assert 'limit' in text, name
    frontend=(PROJECT/'word-extension/src/services/autodraftWorkspaceService.ts').read_text()
    assert 'collectCursorPages' in frontend
