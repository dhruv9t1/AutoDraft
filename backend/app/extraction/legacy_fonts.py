from __future__ import annotations

import io
import re
from dataclasses import dataclass
from html import unescape

from ..docx_safety import safe_docx_zip

# Ported and tightened from the lawyer-firm experiment. These are legacy
# pre-Unicode Indian-script font families observed in real legal DOCX files.
LEGACY_FONT = re.compile(
    r"saral(?![a-z])|gopika|bimal|terafont|harikrishna|ghanshyam|nilkanth|lmg|"
    r"shree\W*guj|avantika|sulekh|akruti|eklg|gujlys|kruti\W*dev|devlys|chanakya",
    re.I,
)
DIGIT_SAFE_FONTS = ("gopika", "bimal")


@dataclass(frozen=True)
class LegacyFontDiagnostic:
    font_name: str
    run_count: int
    inherited_only: bool = False


def legacy_font_runs(source: bytes | bytearray | io.BytesIO | str) -> list[LegacyFontDiagnostic]:
    counts: dict[str, int] = {}
    with safe_docx_zip(source) as archive:
        for name in archive.namelist():
            if not re.fullmatch(r"word/(document|header\d*|footer\d*)\.xml", name):
                continue
            xml = re.sub(
                r"<mc:Fallback>.*?</mc:Fallback>",
                "",
                archive.read(name).decode("utf-8", errors="replace"),
                flags=re.S,
            )
            for run in re.split(r"<w:r[ >]", xml)[1:]:
                text_at = run.find("<w:t")
                if text_at < 0:
                    continue
                head = re.sub(r"<w:rPrChange\b.*?</w:rPrChange>", "", run[:text_at], flags=re.S)
                match = re.search(r'w:ascii="([^"]+)"', head) or re.search(r'w:hAnsi="([^"]+)"', head)
                if not match:
                    continue
                font = match.group(1)
                if not LEGACY_FONT.search(font):
                    continue
                text = unescape("".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", run[text_at:])))
                if any(token in font.lower() for token in DIGIT_SAFE_FONTS) and re.fullmatch(r"[0-9\s/.,:-]*", text):
                    continue
                if text.strip():
                    counts[font] = counts.get(font, 0) + 1

        for part in ("word/styles.xml", "word/theme/theme1.xml"):
            if part not in archive.namelist():
                continue
            xml = archive.read(part).decode("utf-8", errors="replace")
            for font in re.findall(r'(?:w:ascii|w:hAnsi|typeface)="([^"]+)"', xml):
                if LEGACY_FONT.search(font):
                    counts.setdefault(font, 0)

    return [
        LegacyFontDiagnostic(name, count, inherited_only=count == 0)
        for name, count in sorted(counts.items(), key=lambda item: item[0].lower())
    ]
