from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.workflows import WorkflowDefinitionError, validate_workflow_answers, validate_workflow_definition
from app.security import PostgresRateLimiter


def _workflow(pattern: str) -> dict:
    return {
        "pages": [
            {
                "id": "page.one",
                "questions": [
                    {
                        "id": "q.reference",
                        "type": "text",
                        "semanticKey": "matter.reference",
                        "validation": {"pattern": pattern},
                    }
                ],
            }
        ],
        "calculations": [],
    }


def test_workflow_publication_rejects_catastrophic_regex() -> None:
    with pytest.raises(WorkflowDefinitionError, match="unsafe or invalid"):
        validate_workflow_definition(_workflow(r"^(a+)+$"))


def test_workflow_publication_accepts_safe_regex_and_runtime_matches() -> None:
    definition = validate_workflow_definition(_workflow(r"^[A-Z]{2}[0-9]{4}$"))
    answers = validate_workflow_answers(definition, {"matter.reference": "AB1234"})
    assert answers["matter.reference"] == "AB1234"


def test_workflow_regex_input_is_bounded() -> None:
    definition = validate_workflow_definition(_workflow(r"^a+$"))
    with pytest.raises(Exception) as exc_info:
        validate_workflow_answers(definition, {"matter.reference": "a" * 5000})
    assert "pattern" in str(getattr(exc_info.value, "errors", exc_info.value))


@pytest.mark.asyncio
async def test_rate_limiter_consumes_local_permit_leases_before_reserving_again() -> None:
    limiter = PostgresRateLimiter(None, limit=5, window_seconds=60, lease_size=3)
    calls = 0

    async def reserve(_digest, _window_start, _expires):
        nonlocal calls
        calls += 1
        already_reserved = (calls - 1) * 3
        return min(3, max(0, 5 - already_reserved))

    limiter._reserve = reserve  # type: ignore[method-assign]
    assert [await limiter.allow("same-client") for _ in range(5)] == [True] * 5
    assert calls == 2
    assert await limiter.allow("same-client") is False
    assert calls == 3


def test_health_endpoint_is_not_subject_to_database_rate_limiter() -> None:
    main_source = (Path(__file__).resolve().parents[1] / "app/main.py").read_text()
    assert 'rate_limited = path.startswith("/api/") and not path.startswith("/api/health")' in main_source
