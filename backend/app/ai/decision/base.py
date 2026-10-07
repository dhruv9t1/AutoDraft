from __future__ import annotations

from typing import Protocol

from ...extraction.models import CandidateDecision, FieldCandidate


class CandidateDecisionProvider(Protocol):
    name: str

    async def decide(self, candidate: FieldCandidate) -> CandidateDecision | None:
        """Return a decision, or None when this provider intentionally abstains."""
        ...
