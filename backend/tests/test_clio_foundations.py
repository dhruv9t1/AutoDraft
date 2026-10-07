from pathlib import Path
from decimal import Decimal
import pytest

from app.domain.canonical_fields import storage_columns
from app.models import MatterCreateRequest, FieldDefinitionCreateRequest, ContactCreateRequest

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
MIGRATION=(ROOT/'migrations'/'20261005000015_clio_foundations.sql').read_text()


def test_typed_field_storage_keeps_types_separate():
    assert storage_columns('currency','1,250.50')['value_number'] == Decimal('1250.50')
    assert storage_columns('boolean','yes')['value_boolean'] is True
    assert storage_columns('date','2026-10-05')['value_date'].isoformat() == '2026-10-05'
    assert storage_columns('multi_choice',['A','B'])['value_json'] == ['A','B']
    with pytest.raises(ValueError): storage_columns('integer','12.5')


def test_clio_style_definition_is_distinct_from_value_contract():
    field=FieldDefinitionCreateRequest(semanticKey='transaction.cheque.amount',displayLabel='Cheque amount',valueType='currency')
    assert field.semantic_key == 'transaction.cheque.amount'
    assert field.value_type == 'currency'
    assert not hasattr(field,'value')


def test_contacts_are_durable_entities_not_matter_strings():
    c=ContactCreateRequest(contactType='company',displayName='Real Corporation',companyName='Real Corporation')
    assert c.contact_type == 'company'
    assert c.display_name == 'Real Corporation'


def test_matter_status_and_stage_are_separate_contracts():
    req=MatterCreateRequest(title='A v B',matterType='Cheque bounce',stageId='11111111-1111-1111-1111-111111111111')
    assert req.stage_id
    assert not hasattr(req,'status')  # creation status remains server-owned/open


def test_migration_contains_core_clio_foundations_and_rls():
    for table in ('contacts','matter_participants','field_definitions','matter_field_values','contact_field_values','practice_areas','matter_stages','field_groups','document_sets','document_set_versions','document_set_items','generation_runs','outbox_events'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in MIGRATION
    for tenant_table in ('contacts','matter_participants','field_definitions','document_sets','document_set_versions','document_set_items','document_set_drafts','outbox_events'):
        assert f"'{tenant_table}'" in MIGRATION
    assert 'ENABLE ROW LEVEL SECURITY' in MIGRATION


def test_existing_facts_are_backfilled_not_destroyed():
    assert 'ALTER TABLE matter_facts ADD COLUMN IF NOT EXISTS field_definition_id' in MIGRATION
    assert 'INSERT INTO field_definitions' in MIGRATION
    assert 'INSERT INTO matter_field_values' in MIGRATION
    assert 'DROP TABLE matter_facts' not in MIGRATION


def test_document_sets_pin_template_versions_before_publish():
    source=(ROOT/'app'/'repositories'/'document_sets.py').read_text()
    assert 'template_versions WHERE template_id=$1 AND version_number=$2' in source
    assert 'immutable template snapshot' in source
    assert 'template_version_id' in source


def test_domain_writes_have_transactional_outbox_foundation():
    helper=(ROOT/'app'/'services'/'domain_events.py').read_text()
    matters=(ROOT/'app'/'repositories'/'matters.py').read_text()
    contacts=(ROOT/'app'/'repositories'/'contacts.py').read_text()
    assert 'INSERT INTO outbox_events' in helper
    assert 'MatterCreated' in matters and 'MatterFactConflictResolved' in matters
    assert 'ContactCreated' in contacts and 'MatterParticipantUpserted' in contacts


def test_word_workspace_exposes_canonical_legal_data_panel():
    panel=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'LegalDataPanel.tsx').read_text()
    workspace=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'DraftingWorkspace.tsx').read_text()
    assert 'People & organizations' in panel
    assert 'Field cards' in panel
    assert 'Document sets' in panel
    assert 'Practice area & matter stage' in panel
    assert '<LegalDataPanel' in workspace


def test_definition_validation_is_deterministic_and_metadata_driven():
    from app.domain.canonical_fields import validate_field_value
    definition={"required":True,"value_type":"choice","options":["A","B"],"validation":{}}
    validate_field_value(definition,"A")
    with pytest.raises(ValueError): validate_field_value(definition,"")
    with pytest.raises(ValueError): validate_field_value(definition,"C")
    numeric={"required":False,"value_type":"currency","options":[],"validation":{"min":10,"max":20}}
    validate_field_value(numeric,"15")
    with pytest.raises(ValueError): validate_field_value(numeric,"9")


def test_stage_creation_requires_a_practice_area_and_field_scopes_are_real_storage_scopes():
    from pydantic import ValidationError
    from app.models import MatterStageCreateRequest
    with pytest.raises(ValidationError): MatterStageCreateRequest(key="drafting",name="Drafting")
    assert "'participant'" not in MIGRATION[MIGRATION.index('CREATE TABLE IF NOT EXISTS field_groups'):MIGRATION.index('CREATE TABLE IF NOT EXISTS matter_field_values')]


def test_matter_patch_distinguishes_omitted_from_explicit_null():
    source=(ROOT/'app'/'api'/'matters.py').read_text()
    assert '"practice_area_id" in req.model_fields_set' in source
    assert '"stage_id" in req.model_fields_set' in source
    assert 'if practice_was_set and practice_area_id is None' in source


def test_document_set_run_enforces_selection_population_review_order():
    source=(ROOT/'app'/'repositories'/'document_sets.py').read_text()
    assert '"selection":{"population","failed"}' in source
    assert '"population":{"review","failed"}' in source
    assert '"review":{"completed","failed"}' in source
    assert 'Generation run cannot move from' in source


def test_configuration_writes_are_admin_gated():
    practice=(ROOT/'app'/'api'/'practice.py').read_text()
    fields=(ROOT/'app'/'api'/'fields.py').read_text()
    assert "require_role(ctx, 'admin')" in practice
    assert "require_role(ctx, 'admin')" in fields
    assert "Depends(admin_auth)" in practice
    assert "Depends(admin_auth)" in fields


def test_taskpane_can_configure_and_prepare_clio_style_legal_data():
    panel=(PROJECT/'word-extension'/'src'/'taskpane'/'components'/'LegalDataPanel.tsx').read_text()
    for token in ('Configure practice area/stage','Configure field cards','Prepare for matter','Selection → Population → Review'):
        assert token in panel
