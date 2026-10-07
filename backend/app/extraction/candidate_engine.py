from __future__ import annotations

import hashlib
import re
from typing import Iterable

from ..extractors import extract_all
from ..identification_mode import IdentificationMode, extract_general_deterministic, extract_label_value_candidates
from ..models import Variable
from .grouping import annotate_groups
from .models import CandidateEvidence, FieldCandidate
from .unicode_view import normalize_space, offset_view

MONTH = r"(?i:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?"

# Extra high-recall patterns adapted from lawyer-firm. These are candidates,
# never automatic fields. Order matters only within this supplement: earlier
# overlapping rules own the span so the candidate set stays stable.
EXTRA_PATTERNS: list[tuple[str, str, re.Pattern[str], int]] = [
    ("date", "Date", re.compile(rf"\b\d{{1,2}}[/.-]\d{{1,2}}[/.-](?:\d{{4}}|\d{{2}})\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH},?\s+\d{{4}}\b", re.A), 0),
    ("money", "Amount", re.compile(r"(?:\b(?:Rs|RS|INR)\.?|₹)\s*:?\s*(\d[\d,]*(?:=\d{2}|\.\d{2})?)|\b(\d{1,3}(?:,\d{2,3})*(?:=\d{2}\b|(?=/-)))", re.A), 1),
    ("rate", "Rate", re.compile(r"\b\d+(?:\.\d+)?\s*%", re.A), 0),
    ("reference", "Reference Number", re.compile(r"(?<![\w/])\d+/\d{4}\b", re.A), 0),
    ("quoted_name", "Quoted Name", re.compile(r"[“‘\"]+((?:[^”\"’‘]|’(?=\w)){2,80})[”’\"]", re.A), 1),
    ("caps_phrase", "Candidate Text", re.compile(r"\b[A-Z][A-Z.&'@-]+(?:(?:,? +|, *)(?:[A-Z][A-Z.&'@-]+|[A-Z]\.?(?= [A-Z]{2})|\d{1,2}))+\b", re.A), 0),
    ("title_phrase", "Candidate Text", re.compile(r"\b[A-Z][a-z]+(?: (?:[A-Z][a-z]+|[A-Z]\.)){0,4} [A-Z][a-z]+\b", re.A), 0),
    ("caps_word", "Candidate Text", re.compile(r"\b[A-Z]{4,}\b", re.A), 0),
]

LABEL_VALUE = re.compile(
    r"(?m)^[ \t]*([A-Za-z][A-Za-z0-9 /&().,_\-]{1,60}?)[ \t]*(?::|[-–—]|\t)[ \t]*([^\n\r]{1,180})$"
)


def _context(document: str, position: int, length: int, before: int = 120, after: int = 60) -> str:
    return document[max(0, position-before):min(len(document), position+length+after)]


def _candidate_id(position: int, text: str, kind: str) -> str:
    raw = f"{position}\0{kind}\0{text}".encode("utf-8")
    return "fc_" + hashlib.sha1(raw).hexdigest()[:18]


def _from_variable(variable: Variable, document: str, source: str) -> FieldCandidate:
    return FieldCandidate(
        candidate_id=_candidate_id(variable.position, variable.original_text, source),
        kind=source,
        suggested_label=variable.name,
        original_text=variable.original_text,
        position=variable.position,
        context=_context(document, variable.position, len(variable.original_text)),
        evidence=[CandidateEvidence(source, f"Detected by {source.replace('_', ' ')}", 0.35)],
        confidence=variable.confidence_score,
    )


def _extract_supplement(document: str) -> list[FieldCandidate]:
    view = offset_view(document)
    occupied: list[tuple[int, int]] = []
    out: list[FieldCandidate] = []

    def overlaps(start: int, end: int) -> bool:
        return any(start < b and end > a for a, b in occupied)

    # Explicit label/value pairs are strong evidence but remain semantic candidates.
    for match in LABEL_VALUE.finditer(view):
        raw_label = document[match.start(1):match.end(1)]
        start, end = match.start(2), match.end(2)
        source_text = document[start:end].strip()
        left_trim = len(document[start:end]) - len(document[start:end].lstrip())
        start += left_trim
        end = start + len(source_text)
        if not source_text or re.fullmatch(r"[-_=.:/\s]+", source_text):
            continue
        occupied.append((start, end))
        out.append(FieldCandidate(
            candidate_id=_candidate_id(start, source_text, "label_value"),
            kind="label_value",
            suggested_label=normalize_space(raw_label)[:80] or "Variable",
            original_text=source_text,
            position=start,
            context=_context(document, start, len(source_text)),
            evidence=[CandidateEvidence("label_value_pair", "Value follows an explicit document label", 0.6)],
            confidence=0.88,
        ))

    for kind, label, regex, group in EXTRA_PATTERNS:
        for match in regex.finditer(view):
            selected_group = group
            if kind == "money" and group == 1 and match.lastindex and match.group(1) is None and match.group(2) is not None:
                selected_group = 2
            start = match.start(selected_group) if selected_group else match.start()
            end = match.end(selected_group) if selected_group else match.end()
            if start < 0 or end <= start or overlaps(start, end):
                continue
            text = document[start:end]
            if not text.strip():
                continue
            occupied.append((start, end))
            out.append(FieldCandidate(
                candidate_id=_candidate_id(start, text, f"lawyer_{kind}"),
                kind=kind,
                suggested_label=label,
                original_text=text,
                position=start,
                context=_context(document, start, len(text)),
                evidence=[CandidateEvidence("lawyer_pattern", f"High-recall {kind} candidate", 0.15)],
                confidence=0.65,
            ))
    return out


def generate_candidates(document: str, mode: IdentificationMode) -> list[FieldCandidate]:
    """Generate source-grounded candidates without deciding that they are fields."""
    base: list[Variable]
    if mode == IdentificationMode.LEGAL:
        base = extract_all(document) + extract_label_value_candidates(document)
    else:
        base = extract_general_deterministic(document)

    candidates = [_from_variable(v, document, "autodraft_pattern") for v in base]
    candidates.extend(_extract_supplement(document))

    # Keep same textual values at different positions. Collapse only exact duplicate
    # candidate producers at one span/label family.
    unique: dict[tuple[int, str, str], FieldCandidate] = {}
    for candidate in candidates:
        key = (candidate.position, candidate.original_text, candidate.suggested_label.lower())
        current = unique.get(key)
        if current is None:
            unique[key] = candidate
        else:
            current.evidence.extend(candidate.evidence)
            if (candidate.confidence or 0) > (current.confidence or 0):
                current.confidence = candidate.confidence

    return annotate_groups(sorted(unique.values(), key=lambda c: (c.position, -len(c.original_text))))
