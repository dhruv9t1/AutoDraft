from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from .legacy_fonts import LegacyFontDiagnostic, legacy_font_runs
from ..docx_safety import safe_docx_zip


@dataclass(frozen=True)
class DocxParagraph:
    text: str
    story: str
    part_name: str
    index: int


def _sym(match: re.Match[str]) -> str:
    code = int(match.group(1), 16)
    return f"<w:t>{' ' if code >= 0xF000 else chr(code)}</w:t>"


def paragraphs_from_xml(xml: str) -> list[str]:
    xml = re.sub(r"<mc:Fallback>.*?</mc:Fallback>", "", xml, flags=re.S)
    xml = re.sub(r"<w:(?:br|cr)\b[^>]*/>|<w:tab/>", "<w:t> </w:t>", xml)
    xml = xml.replace("<w:noBreakHyphen/>", "<w:t>-</w:t>")
    xml = re.sub(r'<w:sym\b[^>]*?w:char="([0-9A-Fa-f]+)"[^>]*/>', _sym, xml)
    parts = re.split(r"<w:p[ >]|</w:p>", xml)
    text_parts = (
        "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", part))
        for part in parts
    )
    return [unescape(text) for text in text_parts if text.strip()]


def inspect_docx_bytes(data: bytes) -> tuple[list[DocxParagraph], list[LegacyFontDiagnostic]]:
    paragraphs: list[DocxParagraph] = []
    with safe_docx_zip(data) as archive:
        extras = sorted(
            (name for name in archive.namelist() if re.fullmatch(r"word/(header|footer)\d*\.xml", name)),
            key=lambda name: ("footer" in name, name),
        )
        for part_name in ["word/document.xml", *extras]:
            story = "body"
            if "/header" in part_name:
                story = "header"
            elif "/footer" in part_name:
                story = "footer"
            xml = archive.read(part_name).decode("utf-8", errors="replace")
            for text in paragraphs_from_xml(xml):
                paragraphs.append(DocxParagraph(text, story, part_name, len(paragraphs)))
    return paragraphs, legacy_font_runs(data)
