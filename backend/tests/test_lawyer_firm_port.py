from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.ai.decision import CandidateDecisionRouter, RulesDecisionProvider
from app.extraction.candidate_engine import generate_candidates
from app.extraction.grouping import annotate_groups
from app.extraction.legacy_fonts import legacy_font_runs
from app.extraction.models import FieldCandidate
from app.extraction.unicode_view import candidate_key, offset_view
from app.identification_mode import IdentificationMode
from scripts.evaluate_candidates import evaluate


def test_unicode_view_preserves_offsets_and_folds_indian_digits():
    source = "ચેક ૦૦૨૪૬૮\u00a0Dt. २४/०८/२०२५"
    view = offset_view(source)
    assert len(view) == len(source)
    assert "002468" in view
    assert "24/08/2025" in view
    start = view.index("002468")
    assert source[start:start + 6] == "૦૦૨૪૬૮"


def test_candidate_key_groups_script_and_spacing_without_merging_punctuation():
    assert candidate_key("૦ ૦ ૨ ૪ ૬ ૮") == candidate_key("002468")
    assert candidate_key("1/11/2023") != candidate_key("11/1/2023")


def test_grouping_keeps_distinct_occurrences_but_adds_variant_evidence():
    items = [
        FieldCandidate("a", "number", "Cheque", "૦૦૨૪૬૮", 10, "ctx"),
        FieldCandidate("b", "number", "Cheque", "002468", 40, "ctx"),
    ]
    out = annotate_groups(items)
    assert len(out) == 2
    assert out[0].group_id == out[1].group_id
    assert out[0].repetition_count == 2
    assert out[0].position != out[1].position
    assert "002468" in out[0].variants


def test_legacy_font_diagnostic_counts_preunicode_runs():
    xml = (
        '<w:document xmlns:w="x"><w:body><w:p><w:r><w:rPr>'
        '<w:rFonts w:ascii="Gujrati Saral-1" w:hAnsi="Gujrati Saral-1"/>'
        '</w:rPr><w:t>firyadI</w:t></w:r></w:p></w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", xml)
    findings = legacy_font_runs(buf.getvalue())
    assert [(x.font_name, x.run_count) for x in findings] == [("Gujrati Saral-1", 1)]


@pytest.mark.asyncio
async def test_rules_reject_organization_boilerplate_and_keep_uncertain_visible():
    text = "LEGAL NOTICE\nPUROHIT LAW ASSOCIATES\nCheque No.: 000134\n"
    candidates = generate_candidates(text, IdentificationMode.LEGAL)
    await CandidateDecisionRouter([RulesDecisionProvider({"PUROHIT LAW ASSOCIATES"})]).decide_all(candidates)
    firm = next(x for x in candidates if x.original_text == "PUROHIT LAW ASSOCIATES")
    assert firm.classification == "boilerplate"
    assert firm.review_state == "rejected"
    ambiguous = [x for x in candidates if x.classification == "ambiguous"]
    assert ambiguous  # uncertain candidates are retained, not silently deleted


@pytest.mark.asyncio
async def test_candidate_eval_fixture_has_full_positive_recall():
    root = Path(__file__).parent / "candidate_eval"
    result = await evaluate(root / "variables.jsonl", root, {"PUROHIT LAW ASSOCIATES"})
    assert result["candidateRecall"] == 1.0, result


def test_lawyer_firm_safety_seams_are_permanent_regressions():
    root = Path(__file__).resolve().parents[2]
    wrapping_ts = (root / "word-extension/src/services/wrappingPipeline.ts").read_text(encoding="utf-8")
    app_tsx = (root / "word-extension/src/taskpane/components/App.tsx").read_text(encoding="utf-8")
    backend_wrapping = (root / "backend/app/wrapping.py").read_text(encoding="utf-8")
    field_service = (root / "backend/app/services/field_service.py").read_text(encoding="utf-8")

    # Review-only discoveries must never mutate Word by a secondary code path.
    assert 'v.reviewState !== "needs_review"' in wrapping_ts
    assert 'v.reviewState !== "rejected"' in wrapping_ts
    assert 'v.review_state not in {"needs_review", "rejected"}' in backend_wrapping

    # Active pre-Unicode font runs are still diagnosed before binding. The Word
    # taskpane deliberately allows a guarded legacy-font mode because lawyers
    # may need to preserve the original combined document/fonts rather than run
    # an external conversion step first.
    assert app_tsx.count("await assertDocumentTextIsUnicodeSafe({ allowLegacyFonts: true });") >= 2
    diagnostics_ts = (root / "word-extension/src/services/documentDiagnosticsService.ts").read_text(encoding="utf-8")
    assert "AutoDraft is continuing in legacy-font mode" in diagnostics_ts

    # System-2 failure may expose only the explicitly marked review preview;
    # arbitrary partial AI output remains fail-closed.
    assert "system2_unavailable_preview" in field_service
    assert '"status": "unavailable"' in field_service


def test_direct_docx_reader_preserves_body_header_footer_text():
    from app.extraction.docx_reader import inspect_docx_bytes

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="x"><w:body><w:p><w:r><w:t>Cheque No.</w:t></w:r><w:r><w:t> 000134</w:t></w:r></w:p></w:body></w:document>',
        )
        archive.writestr(
            "word/header1.xml",
            '<w:hdr xmlns:w="x"><w:p><w:r><w:t>PUROHIT LAW ASSOCIATES</w:t></w:r></w:p></w:hdr>',
        )
        archive.writestr(
            "word/footer1.xml",
            '<w:ftr xmlns:w="x"><w:p><w:r><w:t>Page footer</w:t></w:r></w:p></w:ftr>',
        )
    paragraphs, findings = inspect_docx_bytes(buf.getvalue())
    assert findings == []
    assert any(p.text == "Cheque No. 000134" and p.story == "body" for p in paragraphs)
    assert any(p.text == "PUROHIT LAW ASSOCIATES" and p.story == "header" for p in paragraphs)
    assert any(p.text == "Page footer" and p.story == "footer" for p in paragraphs)
