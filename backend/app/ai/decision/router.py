from __future__ import annotations

import asyncio
from collections.abc import Iterable

from ...extraction.models import CandidateDecision, CandidateEvidence, FieldCandidate
from .base import CandidateDecisionProvider


class CandidateDecisionRouter:
    """System-1 routing layer; System-2 Qwen remains downstream in OllamaService."""

    def __init__(self, providers: Iterable[CandidateDecisionProvider], *, max_concurrency: int = 8):
        self.providers = list(providers)
        self.max_concurrency = max(1, max_concurrency)

    async def decide(self, candidate: FieldCandidate) -> CandidateDecision:
        for provider in self.providers:
            decision = await provider.decide(candidate)
            if decision is not None:
                return decision
        return CandidateDecision("ambiguous", ("no_system1_decision",), None, "unreviewed")

    async def decide_all(self, candidates: list[FieldCandidate]) -> list[FieldCandidate]:
        # A hosted System-1 provider is optional and may be called for many
        # ambiguous candidates. Bound concurrency prevents a large document from
        # becoming N sequential network round-trips while avoiding an unbounded
        # request burst against the provider. asyncio.gather preserves candidate
        # order, so source-order behavior stays deterministic.
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def decide_one(candidate: FieldCandidate) -> CandidateDecision:
            async with semaphore:
                return await self.decide(candidate)

        decisions = await asyncio.gather(*(decide_one(candidate) for candidate in candidates))
        for candidate, decision in zip(candidates, decisions):
            candidate.classification = decision.classification
            candidate.decision_source = decision.source
            candidate.confidence = decision.score if decision.score is not None else candidate.confidence
            if decision.suggested_label:
                candidate.suggested_label = decision.suggested_label
            for reason in decision.reason_codes:
                candidate.evidence.append(CandidateEvidence(reason))
            if decision.classification in {"static_text", "heading", "label", "boilerplate"}:
                candidate.review_state = "rejected"
            elif decision.classification == "replaceable_value":
                candidate.review_state = "accepted"
            else:
                candidate.review_state = "needs_review"
        return candidates
