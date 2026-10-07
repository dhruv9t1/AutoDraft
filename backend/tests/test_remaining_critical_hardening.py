from pathlib import Path

import pytest

from app.domain.workflows import WorkflowDefinitionError, validate_workflow_definition
from app.repositories.legal_values import CanonicalLegalValueRepository


def test_gav004_rejects_calculation_collision_with_question_semantic_key():
    definition = {
        "pages": [{"id": "p1", "questions": [{"id": "q1", "type": "number", "semanticKey": "claim.total"}]}],
        "calculations": [{"key": "claim.total", "expression": {"literal": 10}}],
    }
    with pytest.raises(WorkflowDefinitionError, match="collides"):
        validate_workflow_definition(definition)


def test_workflow_rejects_duplicate_semantic_keys():
    definition = {
        "pages": [{"id": "p1", "questions": [
            {"id": "q1", "type": "text", "semanticKey": "client.name"},
            {"id": "q2", "type": "text", "semanticKey": "client.name"},
        ]}],
        "calculations": [],
    }
    with pytest.raises(WorkflowDefinitionError, match="Duplicate question semanticKey"):
        validate_workflow_definition(definition)


def test_typed_canonical_comparison_normalizes_equivalent_values():
    definition={"value_type":"currency","required":False,"options":[],"validation":{}}
    current={"value_text":None,"value_number":30000,"value_boolean":None,"value_date":None,"value_datetime":None,"value_json":None}
    assert CanonicalLegalValueRepository._matches_existing(definition,current,"30,000")


def test_workflow_promotion_uses_conflict_aware_canonical_write_path():
    root=Path(__file__).resolve().parents[1]
    source=(root/'app/api/workflows.py').read_text()
    assert 'field_repo.propose_matter_value' in source
    assert "conflicts.append" in source
    legal=(root/'app/repositories/legal_values.py').read_text()
    assert 'async def propose_matter_value' in legal
    assert "'conflicted'" in legal
    assert 'INSERT INTO fact_conflicts' in legal


def test_word_capabilities_use_common_api_requirement_sets():
    root=Path(__file__).resolve().parents[2]
    source=(root/'word-extension/src/services/word/capabilityService.ts').read_text()
    assert 'supports("CustomXmlParts")' in source
    assert 'supports("CompressedFile")' in source
    assert 'customXml: wordApi14' not in source
