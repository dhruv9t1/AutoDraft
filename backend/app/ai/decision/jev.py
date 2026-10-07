from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ...extraction.models import CandidateDecision, FieldCandidate

QUESTION = {
    "variable": {
        "type": "noul",
        "instructions": "Is the highlighted text a matter-specific reusable VALUE in this legal or business document?",
        "criteria": {
            "true": "a case/client/party/transaction/contact/place/bank/date/amount/identifier detail that belongs to this instance",
            "false": "standard wording, heading, caption, label, boilerplate, instructions, or generic narrative",
        },
    }
}


class JevDecisionProvider:
    """Optional narrow System-1 provider.

    Jev is never required for correctness. Network/model failures make this provider
    abstain so Qwen or lawyer review can take over. A probability is retained as
    diagnostic evidence; only conservative bands become decisions.
    """

    name = "jev"

    def __init__(self, *, endpoint: str, api_key: str, model: str, timeout_seconds: float = 20.0):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=timeout_seconds)

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint and self.api_key)

    async def close(self) -> None:
        await self.client.aclose()

    async def decide(self, candidate: FieldCandidate) -> CandidateDecision | None:
        if not self.enabled:
            return None
        state = (
            f"Context: {candidate.context}\n"
            f"Highlighted text: {candidate.original_text}\n"
            f"Candidate kind: {candidate.kind}\n"
            f"Repetition count: {candidate.repetition_count}"
        )
        payload: dict[str, Any] = {"state": state, "questions": QUESTION, "model": self.model}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        last: Exception | None = None
        for attempt in range(4):
            try:
                response = await self.client.post(self.endpoint, json=payload, headers=headers)
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 3:
                    await asyncio.sleep(2**attempt)
                    continue
                response.raise_for_status()
                answer = response.json().get("answers", {}).get("variable", {})
                score = float(answer.get("noul"))
                if score >= 0.82:
                    return CandidateDecision("replaceable_value", ("jev_high_yes",), score, "system1")
                if score <= 0.18:
                    return CandidateDecision("static_text", ("jev_high_no",), score, "system1")
                return CandidateDecision("ambiguous", ("jev_uncertain",), score, "system1")
            except (httpx.TransportError, httpx.HTTPStatusError, ValueError, TypeError) as exc:
                last = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and status not in {429, 500, 502, 503, 504}:
                    return None
                if attempt < 3:
                    await asyncio.sleep(2**attempt)
                    continue
        return None
