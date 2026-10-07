from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CandidateClassification = Literal[
    "replaceable_value",
    "static_text",
    "heading",
    "label",
    "boilerplate",
    "ambiguous",
]
DecisionSource = Literal["rule", "system1", "qwen", "lawyer", "unreviewed"]
ReviewState = Literal["accepted", "rejected", "needs_review"]


@dataclass
class CandidateEvidence:
    code: str
    detail: str = ""
    weight: float | None = None


@dataclass
class FieldCandidate:
    candidate_id: str
    kind: str
    suggested_label: str
    original_text: str
    position: int
    context: str
    evidence: list[CandidateEvidence] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    repetition_count: int = 1
    group_id: str | None = None
    classification: CandidateClassification = "ambiguous"
    decision_source: DecisionSource = "unreviewed"
    review_state: ReviewState = "needs_review"
    confidence: float | None = None
    semantic_key: str | None = None

    @property
    def end(self) -> int:
        return self.position + len(self.original_text)


@dataclass(frozen=True)
class CandidateDecision:
    classification: CandidateClassification
    reason_codes: tuple[str, ...] = ()
    score: float | None = None
    source: DecisionSource = "unreviewed"
    suggested_label: str | None = None
