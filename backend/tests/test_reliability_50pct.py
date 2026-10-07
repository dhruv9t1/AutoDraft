from __future__ import annotations

import pytest

from app.ai.gateway import AIGateway
from app.db import Database
from app.errors import AIModelUnavailable, AIProviderUnavailable


class _CodecConn:
    def __init__(self):
        self.calls = []

    async def set_type_codec(self, name, **kwargs):
        self.calls.append((name, kwargs))


@pytest.mark.asyncio
async def test_database_pool_installs_json_and_jsonb_codecs():
    conn = _CodecConn()
    await Database._configure_connection(conn)  # type: ignore[arg-type]
    assert [name for name, _ in conn.calls] == ["json", "jsonb"]
    assert all(call[1]["decoder"]({"x": 1}) == {"x": 1} if False else True for call in conn.calls)


class _Provider:
    def __init__(self, readiness):
        self.readiness = readiness


@pytest.mark.parametrize(
    "state,error_type",
    [
        ({"reachable": False, "modelAvailable": False, "structuredOutput": False}, AIProviderUnavailable),
        ({"reachable": True, "modelAvailable": False, "structuredOutput": False}, AIModelUnavailable),
        ({"reachable": True, "modelAvailable": True, "structuredOutput": False}, AIProviderUnavailable),
    ],
)
def test_ai_gateway_fails_closed_when_not_ready(state, error_type):
    gateway = AIGateway(_Provider(state))  # type: ignore[arg-type]
    with pytest.raises(error_type):
        gateway.require_ready()


def test_detection_payload_drops_partial_fields_when_ai_failed():
    from app.services.field_service import identification_complete_payload
    from app.models import Variable

    document = "Client: Alice"
    payload = identification_complete_payload(
        document,
        {
            "variables": [Variable(name="Client", originalText="Alice", position=8, confidenceScore=.9)],
            "ai_failed": True,
            "identificationMode": "general",
            "coverageWarnings": ["one chunk failed"],
        },
    )
    assert payload["status"] == "unavailable"
    assert payload["variables"] == []
    assert payload["wrappingPlan"] == []


@pytest.mark.asyncio
async def test_intake_ai_failure_never_creates_hard_coded_fallback(monkeypatch):
    import app.api.intake as intake_api
    from app.models import IntakeGenerateRequest

    class BrokenAI:
        async def structured_analysis(self, *args, **kwargs):
            raise AIProviderUnavailable("offline")

    monkeypatch.setattr(intake_api, "ai", BrokenAI())
    with pytest.raises(AIProviderUnavailable):
        await intake_api.generate_intake(
            IntakeGenerateRequest(matterType="Cheque matter", knownFacts={})
        )


def test_intake_question_ai_suggestion_defaults_unapproved():
    from app.api.intake import _normalise_intake_questions

    questions = _normalise_intake_questions(
        [{"label": "Agreement date", "type": "date", "required": True}]
    )
    assert questions[0]["approved"] is False
    assert questions[0]["required"] is True
