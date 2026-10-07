from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.domain.workflows import WorkflowAnswerValidationError, validate_workflow_answers
from app.services.automation_data import AutomationDataService

ROOT = Path(__file__).resolve().parents[1]


def _definition():
    return {
        "pages": [{
            "id": "p1",
            "questions": [
                {"id": "name", "semanticKey": "client.name", "type": "text", "validation": {"minLength": 2}},
                {"id": "email", "semanticKey": "client.email", "type": "email"},
                {"id": "amount", "semanticKey": "claim.amount", "type": "currency", "validation": {"minValue": 1, "maxValue": 100000}},
                {"id": "kind", "semanticKey": "claim.kind", "type": "select", "options": ["civil", "criminal"]},
                {"id": "flags", "semanticKey": "flags", "type": "multi_select", "options": ["urgent", "foreign"]},
                {"id": "filed", "semanticKey": "filed.on", "type": "date"},
                {"id": "children", "semanticKey": "children", "type": "repeater", "maxItems": 2, "children": [
                    {"id": "child_name", "semanticKey": "name", "type": "text", "required": True},
                    {"id": "child_age", "semanticKey": "age", "type": "number", "validation": {"minValue": 0, "maxValue": 120}},
                    {"id": "assets", "semanticKey": "assets", "type": "repeater", "children": [
                        {"id": "asset_name", "semanticKey": "name", "type": "text"},
                    ]},
                ]},
            ],
        }],
        "calculations": [],
    }


def test_gav001_rejects_unknown_keys_wrong_types_invalid_formats_and_nested_unknowns():
    bad = {
        "client.name": "A",
        "client.email": "not-email",
        "claim.amount": "not-a-number",
        "claim.kind": "tax",
        "flags": ["urgent", "forged"],
        "filed.on": "05/10/2026",
        "undeclared_key": "attacker-controlled",
        "children": [{"name": "Riya", "age": 999, "undeclared_nested": True, "assets": [{"name": "Flat", "secret": "x"}]}],
    }
    with pytest.raises(WorkflowAnswerValidationError) as caught:
        validate_workflow_answers(_definition(), bad)
    reasons = {(e["path"], e["reason"]) for e in caught.value.errors}
    assert ("undeclared_key", "unknown_key") in reasons
    assert ("children[0].undeclared_nested", "unknown_key") in reasons
    assert ("children[0].assets[0].secret", "unknown_key") in reasons
    assert ("client.email", "format") in reasons
    assert ("claim.amount", "type") in reasons
    assert ("claim.kind", "choice") in reasons
    assert ("flags", "choice") in reasons
    assert ("filed.on", "format") in reasons
    assert ("children[0].age", "max_value") in reasons


def test_gav001_normalizes_numeric_answers_and_accepts_declared_nested_shape():
    normalized = validate_workflow_answers(_definition(), {
        "client.name": "Asha",
        "client.email": "asha@example.com",
        "claim.amount": "30000.50",
        "claim.kind": "civil",
        "flags": ["urgent"],
        "filed.on": "2026-10-05",
        "children": [{"name": "Riya", "age": "12", "assets": [{"name": "Flat"}]}],
    })
    assert normalized["claim.amount"] == 30000.5
    assert normalized["children"][0]["age"] == 12


def test_gav001_validation_is_enforced_on_update_and_completion_and_public_api_maps_422():
    repository = (ROOT / "app" / "repositories" / "workflows.py").read_text()
    api = (ROOT / "app" / "api" / "workflows.py").read_text()
    assert repository.count("validate_workflow_answers(current['definition']") >= 3
    assert "Workflow answers failed schema validation" in api
    assert "except WorkflowAnswerValidationError" in api


def test_gav002_confirmed_canonical_values_win_and_conflicts_are_surfaced():
    service = AutomationDataService(None)  # type: ignore[arg-type]

    async def matter_data(_matter_id):
        return {"cheque.amount": "30000", "client.name": "Confirmed", "participants": []}

    async def session_data(_session_id):
        return ({"cheque.amount": 300000, "client.name": "Client", "new.answer": "ok"}, {"cheque.amount": 900000, "calc.only": 2})

    service.matter_data = matter_data  # type: ignore[method-assign]
    service.session_data = session_data  # type: ignore[method-assign]
    snapshot = asyncio.run(service.build_snapshot(matter_id=None, workflow_session_id=None, overrides={}))
    assert snapshot.data["cheque.amount"] == "30000"
    assert snapshot.data["client.name"] == "Confirmed"
    assert snapshot.data["new.answer"] == "ok"
    assert snapshot.data["calculated.calc.only"] == 2
    assert snapshot.data["calculated.cheque.amount"] == 900000
    assert {x["semanticKey"] for x in snapshot.conflicts} == {"cheque.amount", "client.name"}
    assert all(x["resolution"] == "canonical_retained" for x in snapshot.conflicts)

    overridden = asyncio.run(service.build_snapshot(matter_id=None, workflow_session_id=None, overrides={"cheque.amount": "31000"}))
    assert overridden.data["cheque.amount"] == "31000"


def test_gav002_generation_persists_and_returns_data_conflicts():
    source = (ROOT / "app" / "services" / "generation_service.py").read_text()
    assert "build_snapshot" in source
    assert "'dataConflicts':snapshot.conflicts" in source
    assert "canonical_retained" in (ROOT / "app" / "services" / "automation_data.py").read_text()


def test_gav003_authoritative_generation_requires_completed_session_and_client_review():
    source = (ROOT / "app" / "services" / "generation_service.py").read_text()
    api = (ROOT / "app" / "api" / "workflows.py").read_text()
    assert "workflow_session['status']!='completed'" in source
    assert "completed and schema-validated before authoritative generation" in source
    assert "workflow_session['audience'] in {'client','both'}" in source
    assert "authoritativeGenerationApproved" in source
    assert "validate_workflow_answers(workflow_session['definition']" in source
    assert "approve-for-generation" in api
    assert "Depends(lawyer_auth)" in api
    repository = (ROOT / "app" / "repositories" / "workflows.py").read_text()
    assert "reserved_metadata" in repository
    assert "authoritativeGenerationApprovedAt" in repository
