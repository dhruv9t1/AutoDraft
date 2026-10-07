import pytest

from app.config import Settings
from app.ollama_service import OllamaService


def test_anchor_llm_vars_uses_returned_position_for_duplicate_text():
    chunk = "Invoice No.: 192\nDelivery Challan No.: 192\n"
    second = chunk.rfind("192")
    raw = {
        "variables": [
            {
                "variableName": "Delivery Challan Number",
                "originalText": "192",
                "position": second,
                "confidenceScore": 0.9,
            }
        ]
    }

    variables = OllamaService._anchor_llm_vars(raw, chunk, 1000)
    assert len(variables) == 1
    assert variables[0].position == 1000 + second
    assert variables[0].original_text == "192"


def test_anchor_llm_vars_accepts_absolute_position_for_duplicate_text():
    chunk = "Alpha: SAME\nBeta: SAME\n"
    offset = 500
    second = chunk.rfind("SAME")
    raw = {
        "variables": [
            {
                "variableName": "Beta",
                "originalText": "SAME",
                "position": offset + second,
                "confidenceScore": 90,
            }
        ]
    }

    variables = OllamaService._anchor_llm_vars(raw, chunk, offset)
    assert variables[0].position == offset + second
    assert variables[0].confidence_score == 0.9


def test_anchor_llm_vars_preserves_actual_whitespace_from_document():
    chunk = "Client:\u00a0Alice   Example"
    raw = {
        "variables": [
            {
                "variableName": "Client",
                "originalText": "Alice Example",
                "position": 8,
                "confidenceScore": 0.9,
            }
        ]
    }

    variables = OllamaService._anchor_llm_vars(raw, chunk, 0)
    assert variables[0].original_text == "Alice   Example"
    assert chunk[variables[0].position : variables[0].position + len(variables[0].original_text)] == variables[0].original_text


@pytest.mark.asyncio
async def test_large_document_stream_uses_deterministic_candidates_without_qwen(monkeypatch):
    settings = Settings(ollama_semantic_document_char_limit=20)
    service = OllamaService(settings)

    async def fail_call(*args, **kwargs):
        raise AssertionError("large document stream should not call Ollama")

    monkeypatch.setattr(service, "_call", fail_call)
    document = ("Cheque No.: 000134\nDate: 20-03-2026\n" * 20)

    try:
        events = [
            item
            async for item in service.stream_variables(
                document,
                boilerplate_values=set(),
                allow_external_system1=False,
            )
        ]
    finally:
        await service.close()

    assert [item["event"] for item in events] == ["start", "chunk_done", "progress", "_final"]
    final = events[-1]["data"]
    assert final["ai_failed"] is False
    assert final["variables"]
    assert {variable.review_state for variable in final["variables"]} == {"needs_review"}
    assert all("large_document_review_only" in variable.reason_codes for variable in final["variables"])
    assert events[1]["data"]["variables"]
    assert {variable["reviewState"] for variable in events[1]["data"]["variables"]} == {"needs_review"}
    assert "large" in final["coverageWarnings"][0].lower()
