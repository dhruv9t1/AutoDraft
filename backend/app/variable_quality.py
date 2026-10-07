from __future__ import annotations

import re
import uuid
from collections.abc import Iterable

from .models import Variable

_NAMESPACE = uuid.UUID("d1e7d736-58e2-4c40-8a06-1c6f9cb0b7aa")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _normalized_occurrences(document: str, needle: str) -> int:
    parts = [re.escape(part) for part in re.split(r"\s+", needle.strip()) if part]
    if not parts:
        return 0
    pattern = re.compile(r"[\s\u00a0]+".join(parts), re.IGNORECASE)
    return sum(1 for _ in pattern.finditer(document or ""))


def _binding_id(variable: Variable) -> str:
    seed = f"{int(variable.position)}|{_norm(variable.original_text)}"
    return str(uuid.uuid5(_NAMESPACE, seed))


def audit_variables(
    document: str,
    variables: Iterable[Variable],
) -> tuple[list[Variable], list[str]]:
    """Fail closed on ungrounded AI spans and attach stable Word binding metadata."""
    grounded: list[Variable] = []
    warnings: list[str] = []
    seen: set[tuple[int, str, str]] = set()

    for variable in variables:
        source_text = (variable.original_text or "").strip()
        if not source_text:
            warnings.append(f'Dropped "{variable.name}" because its source span is empty.')
            continue

        exact_count = (document or "").count(source_text)
        if exact_count:
            occurrence_count = exact_count
            anchor_quality = "exact"
        else:
            normalized_count = _normalized_occurrences(document, source_text)
            if not normalized_count:
                warnings.append(
                    f'Dropped ungrounded variable "{variable.name}": '
                    "the proposed source text does not occur in the document."
                )
                continue
            occurrence_count = normalized_count
            anchor_quality = "normalized"

        dedupe_key = (int(variable.position), _norm(source_text), _norm(variable.name))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        variable.binding_id = variable.binding_id or _binding_id(variable)
        variable.anchor_quality = anchor_quality
        variable.source_occurrences = occurrence_count
        variable.grounded = True
        if variable.id is None:
            variable.id = variable.binding_id
        grounded.append(variable)

    return grounded, warnings
