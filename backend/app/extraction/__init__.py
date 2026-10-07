from .docx_reader import DocxParagraph, inspect_docx_bytes
from .grouping import annotate_groups
from .legacy_fonts import LegacyFontDiagnostic, legacy_font_runs
from .models import CandidateDecision, CandidateEvidence, FieldCandidate
from .unicode_view import candidate_key, normalize_space, offset_view

__all__ = [
    "CandidateDecision",
    "CandidateEvidence",
    "DocxParagraph",
    "FieldCandidate",
    "LegacyFontDiagnostic",
    "annotate_groups",
    "candidate_key",
    "inspect_docx_bytes",
    "legacy_font_runs",
    "normalize_space",
    "offset_view",
]
