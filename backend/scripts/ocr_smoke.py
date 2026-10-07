from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from app.config import get_settings
from app.ocr_service import OcrService, ocr_smoke_status


async def main() -> int:
    source_value = os.getenv("AUTODRAFT_OCR_SMOKE_INPUT", "").strip()
    expected = os.getenv("AUTODRAFT_OCR_SMOKE_EXPECT", "").strip()
    settings = get_settings()

    if not source_value:
        result = await ocr_smoke_status(tuple(settings.ocr_language_list), force=True)
        print(("PASS" if result.passed else "FAIL") + " - " + result.message)
        return 0 if result.passed else 1

    source = Path(source_value).expanduser().resolve()
    if not source.is_file():
        print(f"FAIL - OCR smoke input does not exist: {source}")
        return 1
    if not expected:
        print("FAIL - AUTODRAFT_OCR_SMOKE_EXPECT is required when using an external fixture")
        return 1

    service = OcrService(settings.ocr_language_list, min(settings.ocr_timeout_seconds, 300))
    session = service.new_session_dir()
    try:
        result = await service.process_path(source, session)
        if not result.ocr_performed:
            print("FAIL - fixture already had a complete text layer; use a genuinely scanned fixture")
            return 1
        if expected.casefold() not in result.text.casefold():
            print("FAIL - expected OCR text was not recognised")
            return 1
        if not result.searchable_pdf.exists() or result.searchable_pdf.stat().st_size <= 0:
            print("FAIL - searchable PDF was not produced")
            return 1
        print(f"PASS - OCR smoke: {result.pages} page(s), languages={'+'.join(result.languages)}")
        return 0
    finally:
        shutil.rmtree(session, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
