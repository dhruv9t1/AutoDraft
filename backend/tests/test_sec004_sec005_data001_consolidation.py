from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
TENANT = (ROOT / 'migrations' / '20261005000019_tenant_relational_integrity.sql').read_text()
CANONICAL = (ROOT / 'migrations' / '20261005000020_canonical_legal_value_authority.sql').read_text()


def test_sec004_finishes_forced_rls_for_previously_missed_tenant_tables():
    for table in ('app_users','intake_forms','audit_events','variables','activity_logs','matter_facts','questionnaire_versions','intake_answers','intake_files'):
        assert f"'{table}'" in TENANT
    assert 'ALTER TABLE %I FORCE ROW LEVEL SECURITY' in TENANT
    assert 'organization_id = autodraft_current_organization_id()' in TENANT
    assert 'public_intake_tokens' not in TENANT[TENANT.index('FOREACH tbl IN ARRAY ARRAY['):TENANT.rindex('] LOOP')]


def test_sec005_has_database_tenant_consistent_parent_child_constraints():
    required = (
        'fk_matter_participants_matter_tenant',
        'fk_matter_participants_contact_tenant',
        'fk_matter_field_values_matter_tenant',
        'fk_matter_field_values_definition_tenant',
        'fk_document_set_items_version_tenant',
        'fk_generation_runs_matter_tenant',
        'fk_workflow_sessions_version_tenant',
        'fk_template_automation_versions_snapshot_tenant',
        'fk_generation_artifacts_template_version_tenant',
    )
    for name in required:
        assert name in TENANT
    assert 'FOREIGN KEY (organization_id,matter_id) REFERENCES matters(organization_id,id)' in TENANT
    assert 'FOREIGN KEY (organization_id,field_definition_id) REFERENCES field_definitions(organization_id,id)' in TENANT


def test_data001_declares_typed_values_authoritative_and_guards_legacy_canonical_writes():
    assert 'matter_field_values is the authoritative legal-value store' in CANONICAL
    assert 'uq_matter_facts_canonical_projection' in CANONICAL
    assert 'autodraft_guard_legacy_canonical_fact_write' in CANONICAL
    assert "Canonical matter_facts rows are projections; write matter_field_values instead" in CANONICAL


def test_data001_application_reads_authoritative_store_without_legacy_fallback():
    source = (ROOT / 'app' / 'services' / 'automation_data.py').read_text()
    assert 'FROM matter_field_values' in source
    assert 'FROM matter_facts' not in source


def test_data001_all_canonical_writes_flow_through_shared_legal_value_repository():
    legal = (ROOT / 'app' / 'repositories' / 'legal_values.py').read_text()
    fields = (ROOT / 'app' / 'repositories' / 'fields.py').read_text()
    matters = (ROOT / 'app' / 'repositories' / 'matters.py').read_text()
    service = (ROOT / 'app' / 'services' / 'matter_service.py').read_text()
    assert 'INSERT INTO matter_field_values' in legal
    assert "set_config('autodraft.legacy_projection_write','on',true)" in legal
    assert 'self.legal_values.upsert_matter_value' in fields
    assert 'self.legal_values.upsert_matter_value' in matters
    assert 'upsert_matter_value_by_key' in service
    assert "source='derived'" in service
    assert "is_canonical=TRUE" not in service


def test_startup_diagnostics_require_comprehensive_rls_fk_and_canonical_migrations():
    db = (ROOT / 'app' / 'db.py').read_text()
    assert 'fk_matter_participants_matter_tenant' in db
    assert 'autodraft_guard_legacy_canonical_fact_write()' in db
    assert 'Tenant isolation is incomplete for:' in db
