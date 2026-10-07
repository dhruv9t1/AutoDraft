from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.expressions import ExpressionError, evaluate
from app.domain.workflows import (
    MAX_WORKFLOW_REPEATER_ITEMS,
    MAX_WORKFLOW_TOTAL_REPEATED_ITEMS,
    WorkflowAnswerValidationError,
    WorkflowDefinitionError,
    evaluate_workflow,
    validate_workflow_answers,
    validate_workflow_definition,
)

ROOT = Path(__file__).resolve().parents[1]


def test_calculations_are_isolated_from_answer_namespace_and_field_refs():
    definition = {
        "pages": [{"id": "p", "questions": [{"id": "q", "type": "number", "semanticKey": "amount"}]}],
        "calculations": [{"key": "total", "expression": {"literal": 10}}],
    }
    result = evaluate_workflow(definition, {"amount": 5, "total": 999})
    assert result.calculations == {"total": 10}
    # A calculation cannot be referenced through field/fact; that would put it
    # back into the legal semantic namespace. var is the explicit dependency API.
    with pytest.raises(WorkflowDefinitionError, match="use var references"):
        validate_workflow_definition({
            "pages": [],
            "calculations": [
                {"key": "a", "expression": {"literal": 1}},
                {"key": "b", "expression": {"field": "a"}},
            ],
        })
    with pytest.raises(WorkflowDefinitionError, match="reserved calculation namespace"):
        validate_workflow_definition({
            "pages": [{"id": "p", "questions": [{"id": "q", "semanticKey": "calculated.total", "type": "number"}]}],
            "calculations": [{"key": "total", "expression": {"literal": 1}}],
        })


def test_calculation_dependencies_are_topologically_sorted_and_cycles_fail():
    definition = {
        "pages": [{"id": "p", "condition": {"gte": [{"var": "b"}, {"literal": 3}]}, "questions": []}],
        "calculations": [
            {"key": "b", "expression": {"add": [{"var": "a"}, {"literal": 2}]}},
            {"key": "a", "expression": {"literal": 1}},
        ],
    }
    validated = validate_workflow_definition(definition)
    assert [x["key"] for x in validated["calculations"]] == ["a", "b"]
    result = evaluate_workflow(definition, {})
    assert result.calculations == {"a": 1, "b": 3}
    assert result.visible_pages

    with pytest.raises(WorkflowDefinitionError, match="cycle"):
        validate_workflow_definition({
            "pages": [],
            "calculations": [
                {"key": "a", "expression": {"var": "b"}},
                {"key": "b", "expression": {"var": "a"}},
            ],
        })
    with pytest.raises(WorkflowDefinitionError, match="unknown calculation"):
        validate_workflow_definition({
            "pages": [],
            "calculations": [{"key": "a", "expression": {"var": "missing"}}],
        })


def test_ordering_comparisons_are_numeric_or_date_only_and_fail_closed():
    assert evaluate({"gt": [{"literal": "9"}, {"literal": "10"}]}).value is False
    assert evaluate({"lt": [{"literal": "2026-01-01"}, {"literal": "2026-02-01"}]}).value is True
    with pytest.raises(ExpressionError, match="numeric or ISO date"):
        evaluate({"gt": [{"literal": "abc"}, {"literal": "def"}]})


def test_workflow_repeater_platform_limits_apply_even_without_definition_maximum():
    with pytest.raises(WorkflowDefinitionError, match="platform limit"):
        validate_workflow_definition({
            "pages": [{"id": "p", "questions": [{
                "id": "r", "semanticKey": "rows", "type": "repeater",
                "maxItems": MAX_WORKFLOW_REPEATER_ITEMS + 1,
                "children": [{"id": "v", "semanticKey": "value", "type": "text"}],
            }]}],
            "calculations": [],
        })

    definition = {
        "pages": [{"id": "p", "questions": [{
            "id": "r", "semanticKey": "rows", "type": "repeater",
            "children": [{
                "id": "nested", "semanticKey": "nested", "type": "repeater",
                "children": [{"id": "v", "semanticKey": "value", "type": "text"}],
            }],
        }]}],
        "calculations": [],
    }
    with pytest.raises(WorkflowAnswerValidationError) as too_many:
        validate_workflow_answers(definition, {"rows": [{"nested": [{"value": "x"} for _ in range(MAX_WORKFLOW_REPEATER_ITEMS)]} for _ in range(9)]})
    assert any(e["reason"] == "total_items" for e in too_many.value.errors)
    assert MAX_WORKFLOW_TOTAL_REPEATED_ITEMS < 9 * MAX_WORKFLOW_REPEATER_ITEMS


def test_generation_attempts_are_append_only_with_retry_lineage_and_render_outside_transaction():
    service = (ROOT / "app/services/generation_service.py").read_text()
    migration = (ROOT / "migrations/20261006000029_workflow_generation_correctness.sql").read_text()
    api = (ROOT / "app/api/automation.py").read_text()

    assert "retry_of_attempt_id" in migration
    assert "attempt_number" in migration
    assert "started_at" in migration and "finished_at" in migration
    assert "immutable after terminal state" in migration
    assert "uq_generation_attempt_one_processing" in migration
    assert "INSERT INTO generation_attempts" in service
    assert "retry_of_attempt_id" in service
    assert "finished_at=NOW()" in service
    assert "artifact_ids=COALESCE(artifact_ids,'[]'::jsonb) || $1::jsonb" in service
    assert "idempotencyKey is required for every persisted headless generation request" in service
    assert "idempotencyKey is required for every persisted headless generation request" in api

    # CPU/ZIP/XML rendering occurs before the short persistence transaction.
    render_at = service.index("rendered = render_docx_base64")
    persist_tx_at = service.index("async with self.db.p().transaction() as conn:", render_at)
    assert render_at < persist_tx_at
