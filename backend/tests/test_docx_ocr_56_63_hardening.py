from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.domain import template_automation as ta
from app.ocr_service import OcrProcessingError, _image_to_pdf, _validated_pdf_reader
import app.ocr_service as ocr

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(document_xml: str, extra: dict[str, bytes] | None = None) -> bytes:
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
      <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
      <Default Extension="xml" ContentType="application/xml"/>
      <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
    </Types>'''
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", document_xml.encode())
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return out.getvalue()


def _simple_doc(tag: str = "field-name") -> str:
    return f'''<w:document xmlns:w="{W}"><w:body><w:p><w:sdt>
      <w:sdtPr><w:tag w:val="{tag}"/></w:sdtPr>
      <w:sdtContent><w:r><w:t>PLACEHOLDER</w:t></w:r></w:sdtContent>
    </w:sdt></w:p></w:body></w:document>'''


def test_preflight_rejects_automation_in_footnotes_and_textboxes():
    blueprint = {"bindings": [{"controlTag": "field-name", "semanticKey": "name"}]}
    footnotes = f'''<w:footnotes xmlns:w="{W}"><w:footnote w:id="1"><w:p><w:sdt>
      <w:sdtPr><w:tag w:val="field-name"/></w:sdtPr><w:sdtContent><w:r><w:t>X</w:t></w:r></w:sdtContent>
    </w:sdt></w:p></w:footnote></w:footnotes>'''.encode()
    doc = f'''<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>main</w:t></w:r></w:p></w:body></w:document>'''
    result = ta.preflight_blueprint(blueprint, _docx(doc, {"word/footnotes.xml": footnotes}))
    assert result["ready"] is False
    assert any(i["code"] == "UNSUPPORTED_WORD_STORY" for i in result["issues"])

    textbox = f'''<w:document xmlns:w="{W}"><w:body><w:p><w:txbxContent><w:p><w:sdt>
      <w:sdtPr><w:tag w:val="field-name"/></w:sdtPr><w:sdtContent><w:r><w:t>X</w:t></w:r></w:sdtContent>
    </w:sdt></w:p></w:txbxContent></w:p></w:body></w:document>'''
    result = ta.preflight_blueprint(blueprint, _docx(textbox))
    assert result["ready"] is False
    assert any(i["code"] == "UNSUPPORTED_WORD_STORY" and "textbox" in i["part"] for i in result["issues"])


def test_preflight_rejects_complex_binding_and_malformed_other_word_story():
    blueprint = {"bindings": [{"controlTag": "field-name", "semanticKey": "name"}]}
    complex_doc = f'''<w:document xmlns:w="{W}"><w:body><w:p><w:sdt>
      <w:sdtPr><w:tag w:val="field-name"/></w:sdtPr><w:sdtContent>
      <w:r><w:rPr><w:b/></w:rPr><w:t>A</w:t></w:r><w:r><w:i/><w:t>B</w:t></w:r>
      </w:sdtContent></w:sdt></w:p></w:body></w:document>'''
    result = ta.preflight_blueprint(blueprint, _docx(complex_doc))
    assert result["ready"] is False
    assert any(i["code"] == "UNSUPPORTED_COMPLEX_BINDING" for i in result["issues"])

    result = ta.preflight_blueprint(
        {"bindings": []},
        _docx(_simple_doc("unrelated"), {"word/comments.xml": b"<w:comments>"}),
    )
    assert result["ready"] is False
    assert any(i["code"] == "INVALID_DOCX" for i in result["issues"])


def test_render_enforces_aggregate_post_expansion_limits(monkeypatch):
    base = ta.get_settings()
    values = base.model_dump()
    values["max_rendered_total_xml_bytes"] = 64
    constrained = type(base)(**values)
    monkeypatch.setattr(ta, "get_settings", lambda: constrained)
    blueprint = {"bindings": [{"controlTag": "field-name", "semanticKey": "name"}]}
    with pytest.raises(ta.TemplateAutomationError, match="aggregate limit"):
        ta.render_docx(_docx(_simple_doc()), blueprint, {"name": "A"})


def test_image_pixel_frame_guards_run_before_full_decode(tmp_path: Path, monkeypatch):
    settings = ocr.get_settings()
    values = settings.model_dump()
    values.update({
        "ocr_max_image_width": 100,
        "ocr_max_image_height": 100,
        "ocr_max_image_pixels_per_frame": 10_000,
        "ocr_max_image_frames": 2,
        "ocr_max_image_total_pixels": 10_000,
    })
    constrained = type(settings)(**values)
    monkeypatch.setattr(ocr, "get_settings", lambda: constrained)
    source = tmp_path / "wide.png"
    Image.new("RGB", (101, 10), "white").save(source)
    with pytest.raises(OcrProcessingError, match="dimensions exceed"):
        _image_to_pdf(source, tmp_path / "out.pdf")


def test_pdf_page_dimension_limits_are_checked_before_ocr(tmp_path: Path, monkeypatch):
    settings = ocr.get_settings()
    values = settings.model_dump()
    values.update({
        "ocr_max_pdf_pages": 10,
        "ocr_max_pdf_page_width_points": 500.0,
        "ocr_max_pdf_page_height_points": 500.0,
        "ocr_max_pdf_page_area_points": 250_000.0,
    })
    constrained = type(settings)(**values)
    monkeypatch.setattr(ocr, "get_settings", lambda: constrained)
    path = tmp_path / "oversized.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=100)
    with path.open("wb") as handle:
        writer.write(handle)
    with pytest.raises(OcrProcessingError, match="dimensions exceed"):
        _validated_pdf_reader(path)


def test_ocr_resource_limits_and_real_smoke_are_wired_into_readiness():
    source = Path(ocr.__file__).read_text()
    assert "RLIMIT_AS" in source and "RLIMIT_CPU" in source and "RLIMIT_FSIZE" in source
    assert "ocr_max_temp_bytes" in source
    assert "_SMOKE_FIXTURE" in source and "ગુજરાતી પરીક્ષણ 12345" in source
    fixture = Path(ocr.__file__).resolve().parent / "fixtures" / "ocr-smoke-guj-eng.png"
    assert fixture.is_file() and fixture.stat().st_size > 0
    api = (Path(ocr.__file__).resolve().parent / "api" / "ocr.py").read_text()
    assert "ocr_smoke_status" in api and "smokeTest" in api
