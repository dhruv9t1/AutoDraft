from pathlib import Path
import re
import uuid
import pytest

from app.domain.canonical_fields import display_value, storage_columns, validate_field_value


def _compact(text: str) -> str:
    """Collapse all whitespace so assertions check code intent, not formatting."""
    return re.sub(r'\s+', '', text)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parent
MIGRATION = (ROOT / 'migrations' / '20261006000023_canonical_data_completion.sql').read_text()
FIELDS = (ROOT / 'app' / 'repositories' / 'fields.py').read_text()
SERVICE = (ROOT / 'app' / 'services' / 'legal_value_service.py').read_text()


def test_arch001_has_one_universal_legal_value_write_service():
    assert 'class LegalValueWriteService' in SERVICE
    assert 'async def propose_matter_value' in SERVICE
    assert 'async def upsert_contact_value' in SERVICE
    assert 'async def _replace_repeatable' in SERVICE
    assert 'self.legal_values = LegalValueWriteService()' in FIELDS
    assert 'self.legal_values.propose_matter_value' in FIELDS
    assert 'self.legal_values.upsert_contact_value' in FIELDS


def test_schema_changes_fail_closed_when_persisted_values_would_be_invalidated():
    assert 'Cannot change valueType while persisted values exist' in FIELDS
    assert 'Cannot change repeatable while persisted values exist' in FIELDS
    assert 'Field schema change would invalidate existing value' in FIELDS
    assert '_assert_definition_compatible' in FIELDS


def test_repeatable_fields_have_stable_ordered_instance_tables_and_api_envelopes():
    assert 'CREATE TABLE IF NOT EXISTS matter_field_value_items' in MIGRATION
    assert 'CREATE TABLE IF NOT EXISTS contact_field_value_items' in MIGRATION
    assert 'position INTEGER NOT NULL DEFAULT 0' in MIGRATION
    assert 'matter_field_value_items' in SERVICE and 'contact_field_value_items' in SERVICE
    assert 'Repeatable item id does not belong to this field collection' in SERVICE
    types = (PROJECT / 'word-extension' / 'src' / 'services' / 'types.ts').read_text()
    assert 'CanonicalFieldValueItem' in types
    # The declared optional repeatable-items property; whitespace-insensitive so
    # formatter changes to types.ts do not fail a semantic contract check.
    assert 'items?:CanonicalFieldValueItem[]' in _compact(types)


def test_corrective_typed_backfill_populates_typed_columns_and_records_failures():
    assert 'CREATE TABLE IF NOT EXISTS field_value_migration_errors' in MIGRATION
    for token in ('autodraft_try_numeric','autodraft_try_boolean','autodraft_try_date','autodraft_try_timestamptz'):
        assert token in MIGRATION
    for column in ('value_number','value_boolean','value_date','value_datetime'):
        assert f'SET {column}=' in MIGRATION
    assert 'legacy value cannot be converted to declared canonical type' in MIGRATION


def test_practice_area_stage_compatibility_is_database_enforced():
    assert 'uq_matter_stages_org_practice_id' in MIGRATION
    assert 'ck_matters_stage_requires_practice' in MIGRATION
    assert 'fk_matters_practice_stage_compatible' in MIGRATION
    assert 'FOREIGN KEY(organization_id,practice_area_id,stage_id)' in MIGRATION


def test_reference_fields_are_uuid_typed_and_tenant_fk_backed():
    contact_id = uuid.uuid4()
    cols = storage_columns('contact_reference', str(contact_id))
    assert cols['value_contact_id'] == contact_id
    assert cols['value_text'] is None
    assert display_value(cols, 'contact_reference') == str(contact_id)
    with pytest.raises(ValueError):
        validate_field_value({'required':False,'value_type':'matter_reference','options':[],'validation':{}}, 'not-a-uuid')
    for constraint in (
        'fk_matter_value_contact_ref_tenant','fk_matter_value_matter_ref_tenant','fk_matter_value_document_ref_tenant',
        'fk_contact_value_contact_ref_tenant','fk_contact_value_matter_ref_tenant','fk_contact_value_document_ref_tenant',
    ):
        assert constraint in MIGRATION
