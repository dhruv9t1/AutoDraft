from __future__ import annotations

import hashlib
from collections import defaultdict

from .models import CandidateEvidence, FieldCandidate
from .unicode_view import candidate_key


def annotate_groups(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    """Add textual-variant/repetition evidence without merging source occurrences."""
    buckets: dict[str, list[FieldCandidate]] = defaultdict(list)
    for candidate in candidates:
        key = candidate_key(candidate.original_text)
        if key:
            buckets[key].append(candidate)

    for key, group in buckets.items():
        group_id = "cg_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:14]
        spellings: list[str] = []
        seen: set[str] = set()
        for candidate in group:
            if candidate.original_text not in seen:
                seen.add(candidate.original_text)
                spellings.append(candidate.original_text)
        count = len(group)
        for candidate in group:
            candidate.group_id = group_id
            candidate.repetition_count = count
            candidate.variants = [x for x in spellings if x != candidate.original_text]
            if count > 1:
                candidate.evidence.append(
                    CandidateEvidence("repeated_value", f"Equivalent value occurs {count} times", 0.15)
                )
            if len(spellings) > 1:
                candidate.evidence.append(
                    CandidateEvidence("spelling_variants", f"{len(spellings)} source spellings share one comparison key", 0.08)
                )
            if count > 100:
                candidate.evidence.append(
                    CandidateEvidence("very_high_repetition", "Value occurs unusually often; review before binding", -0.35)
                )
    return candidates
