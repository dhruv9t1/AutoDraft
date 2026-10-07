from __future__ import annotations

import re

from ...extraction.models import CandidateDecision, FieldCandidate

STATIC_HEADINGS = {
    "legal notice", "affidavit", "complaint", "verification", "prayer", "facts",
    "schedule", "annexure", "subject", "regards", "yours faithfully",
}


class RulesDecisionProvider:
    name = "rules"

    def __init__(self, boilerplate_values: set[str] | None = None):
        self.boilerplate_values = {x.strip().casefold() for x in (boilerplate_values or set()) if x.strip()}

    async def decide(self, candidate: FieldCandidate) -> CandidateDecision | None:
        value = candidate.original_text.strip()
        folded = value.casefold()
        if folded in self.boilerplate_values:
            return CandidateDecision("boilerplate", ("organization_boilerplate",), 1.0, "rule")
        if folded in STATIC_HEADINGS:
            return CandidateDecision("heading", ("known_heading",), 0.99, "rule")
        if candidate.repetition_count > 100:
            return CandidateDecision("ambiguous", ("very_high_repetition",), None, "rule")
        codes = {e.code for e in candidate.evidence}
        # Explicit label/value extraction is sufficiently grounded to bypass System-1,
        # but still goes through the existing Qwen System-2 verifier when enabled.
        if "label_value_pair" in codes:
            return CandidateDecision("replaceable_value", ("explicit_label_value",), 0.94, "rule", candidate.suggested_label)
        # Strong domain-specific extractor labels are evidence, not universal truth.
        if "autodraft_pattern" in codes and candidate.suggested_label.lower() not in {"date", "amount", "candidate text"}:
            return CandidateDecision("replaceable_value", ("domain_specific_pattern",), 0.88, "rule", candidate.suggested_label)
        # Bare short labels/punctuation are never useful values.
        if len(value) < 2 or re.fullmatch(r"[-_=.:/\s]+", value):
            return CandidateDecision("label", ("structural_token",), 1.0, "rule")
        return None
