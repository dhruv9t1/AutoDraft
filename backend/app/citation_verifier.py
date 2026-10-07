from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_SOURCE_MARKER_RE = re.compile(r"\s*\[Source:\s*[^\]]+\]", flags=re.IGNORECASE)

# Indian reporters + court neutral citations commonly encountered in pleadings,
# opinions and drafting material. Patterns are deliberately conservative: they
# identify citation-shaped text for verification; they do not assert authority.
_CITATION_PATTERNS = (
    re.compile(r"\bAIR\s+\d{4}\s+(?:SC|SCC|Bom|Cal|Del|Mad|All|Ker|Guj|Raj|MP|Pat|Ori|AP|Kant|P&H|J&K)\s+\d+\b", re.IGNORECASE),
    re.compile(r"\(\d{4}\)\s+\d+\s+SCC(?:\s*\((?:Cri|L&S|Tax)\))?\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{4}\s+SCC\s+OnLine\s+[A-Za-z&.() -]{1,24}\s+\d+\b", re.IGNORECASE),
    re.compile(r"\(\d{4}\)\s+\d+\s+SCR\s+\d+\b", re.IGNORECASE),
    re.compile(r"\b\d{4}\s+(?:Cri\s+LJ|CrLJ|DLT|KLT|GLR|MLJ|Mh\s+LJ|Bom\s+CR|All\s+LJ|Kar\s+LJ|CTC)\s+\d+\b", re.IGNORECASE),
    # Supreme Court neutral citation, e.g. 2024 INSC 123.
    re.compile(r"\b20\d{2}\s+INSC\s+\d+\b", re.IGNORECASE),
    # High Court neutral citations, e.g. 2024:DHC:1234 or 2024:BHC-AS:12345.
    re.compile(r"\b20\d{2}:[A-Z][A-Z0-9-]{1,15}:\d+\b", re.IGNORECASE),
    # MANU identifiers used extensively in Indian legal databases.
    re.compile(r"\bMANU/[A-Z]{2,8}/\d{3,8}/\d{4}\b", re.IGNORECASE),
    # LiveLaw style citations, e.g. 2024 LiveLaw (SC) 321.
    re.compile(r"\b20\d{2}\s+LiveLaw\s*\([A-Za-z&. -]{2,20}\)\s*\d+\b", re.IGNORECASE),
    # Indian Law Reports / state series with year in brackets.
    re.compile(r"\b(?:ILR|I\.L\.R\.)\s*\(?20\d{2}\)?\s*[A-Za-z.() &-]{1,24}\s+\d+\b", re.IGNORECASE),
)


def _authority_value(authority: Any, *names: str) -> str:
    for name in names:
        if isinstance(authority, dict) and name in authority:
            return str(authority[name] or "")
        if hasattr(authority, name):
            return str(getattr(authority, name) or "")
    return ""


def _canonical_citation(value: str) -> str:
    # Matching is punctuation/spacing tolerant while preserving letters/digits.
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _authority_citations(authority: Any) -> set[str]:
    values={_authority_value(authority,"citation")}
    # Some research adapters place the citation in title/excerpt. Keep those as
    # search sources without conflating them with a verified authority state.
    values.add(_authority_value(authority,"title"))
    values.add(_authority_value(authority,"excerpt"))
    return {_canonical_citation(v) for v in values if v}


def _authority_search_text(authority: Any) -> str:
    return " ".join(
        (
            _authority_value(authority, "title"),
            _authority_value(authority, "citation"),
            _authority_value(authority, "court"),
            _authority_value(authority, "date"),
            _authority_value(authority, "source_url", "sourceUrl"),
            _authority_value(authority, "excerpt"),
        )
    ).lower()


def _extract_citations(text: str) -> list[str]:
    matches: list[tuple[int,str]]=[]
    seen: set[str]=set()
    for pattern in _CITATION_PATTERNS:
        for match in pattern.finditer(text or ""):
            citation = re.sub(r"\s+", " ", match.group(0).strip())
            key=_canonical_citation(citation)
            if key and key not in seen:
                seen.add(key); matches.append((match.start(),citation))
    matches.sort(key=lambda x:x[0])
    return [citation for _,citation in matches]


def verify_and_sanitize_citations(
    draft: str,
    retrieved_authorities: Iterable[Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Return truthful citation state and mark unsupported citations for review.

    Detection intentionally covers a broad set of Indian reporter and neutral
    citation formats. A textual/source match is still *not* called verified;
    authoritative verification remains a server/lawyer-controlled state.
    """
    text = str(draft or "")
    authorities = list(retrieved_authorities or [])
    removed_markers = [marker.strip() for marker in _SOURCE_MARKER_RE.findall(text)]
    text = _SOURCE_MARKER_RE.sub("", text)

    citations = _extract_citations(text)
    authority_texts = [_authority_search_text(authority) for authority in authorities]
    authority_keys=[_authority_citations(authority) for authority in authorities]
    unsupported: list[str] = []
    supported: list[str] = []

    for citation in citations:
        canonical=_canonical_citation(citation)
        matched=False
        if authorities:
            matched=any(canonical in keys for keys in authority_keys)
            if not matched:
                compact_text=re.sub(r"[^a-z0-9]+","",citation.lower())
                matched=any(compact_text and compact_text in re.sub(r"[^a-z0-9]+","",authority_text) for authority_text in authority_texts)
        if matched:
            supported.append(citation)
        else:
            unsupported.append(citation)
            text=text.replace(citation,f"[AUTHORITY REQUIRED: verify citation {citation}]")

    if not citations and not removed_markers:
        status = "not_applicable"
    elif not authorities:
        status = "not_checked"
    elif unsupported or removed_markers:
        status = "partially_matched" if supported else "needs_verification"
    else:
        status = "source_matched"

    return text, {
        "status": status,
        "authorityCount": len(authorities),
        "sourceMatchedCitationCount": len(supported),
        "verifiedAuthorityCount": 0,
        "detectedCitationCount": len(citations),
        "supportedCitations": supported,
        "unsupportedCitations": unsupported,
        "removedSyntheticSourceMarkers": removed_markers,
    }
