from __future__ import annotations

import pytest

from app.models import Variable
from app.ocr_service import OcrDependencyError, ensure_ocr_dependencies
from app.post_processing import dedup, finalize


def _v(name: str, text: str, position: int, confidence: float = 0.9) -> Variable:
    return Variable(
        name=name,
        originalText=text,
        position=position,
        confidenceScore=confidence,
    )


def test_same_span_same_semantic_family_collapses_to_stronger_candidate():
    values = [
        _v("Cheque Date", "20-03-2026", 10, 0.71),
        _v("Cheque Date 2", "20-03-2026", 10, 0.96),
        _v("Check Date", "20-03-2026", 10, 0.80),
    ]
    result = dedup(values)
    assert len(result) == 1
    assert result[0].confidence_score == pytest.approx(0.96)


def test_same_value_at_different_positions_survives():
    values = [
        _v("Cheque Date", "20-03-2026", 5),
        _v("Cheque Date", "20-03-2026", 50),
    ]
    result = dedup(values)
    assert [item.position for item in result] == [5, 50]


def test_same_span_distinct_semantics_survive():
    values = [
        _v("Invoice Number", "192", 7),
        _v("Delivery Challan Number", "192", 7),
    ]
    assert len(dedup(values)) == 2


def test_generic_name_is_enriched_before_deduplication():
    document = "Cheque dated 20-03-2026 was dishonoured."
    pos = document.index("20-03-2026")
    result = finalize(
        [
            _v("Date", "20-03-2026", pos, 0.8),
            _v("Cheque Date", "20-03-2026", pos, 0.9),
        ],
        document,
    )
    assert len(result) == 1
    assert result[0].name == "Cheque Date"


@pytest.mark.asyncio
async def test_ocr_dependency_error_names_missing_ocrmypdf(monkeypatch):
    import app.ocr_service as module

    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(OcrDependencyError, match="OCRmyPDF is not installed"):
        await ensure_ocr_dependencies(("guj", "eng"))
