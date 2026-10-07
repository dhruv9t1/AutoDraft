from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.docx_safety import UnsafeDocxPackage, safe_docx_zip

ROOT = Path(__file__).resolve().parents[1]


def _docx(extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
        for name, content in (extra or {}).items():
            z.writestr(name, content)
    return buf.getvalue()


def test_docx001_accepts_small_valid_package_and_rejects_high_ratio_member_before_read():
    with safe_docx_zip(_docx()) as archive:
        assert "word/document.xml" in archive.namelist()

    bomb = _docx({"word/media/bomb.bin": b"A" * (2 * 1024 * 1024)})
    with pytest.raises(UnsafeDocxPackage, match="compression ratio"):
        with safe_docx_zip(bomb):
            pass


def test_docx001_is_centralized_across_rendering_extraction_and_storage():
    safety = (ROOT / "app/docx_safety.py").read_text()
    automation = (ROOT / "app/domain/template_automation.py").read_text()
    reader = (ROOT / "app/extraction/docx_reader.py").read_text()
    fonts = (ROOT / "app/extraction/legacy_fonts.py").read_text()
    storage = (ROOT / "app/storage.py").read_text()
    assert "infolist()" in safety
    for needle in (
        "docx_max_zip_entries",
        "docx_max_zip_uncompressed_bytes",
        "docx_max_zip_entry_uncompressed_bytes",
        "docx_max_zip_compression_ratio",
    ):
        assert needle in safety
    assert "safe_docx_zip(content)" in automation
    assert "safe_docx_zip(data)" in reader
    assert "safe_docx_zip(source)" in fonts
    assert "safe_docx_zip(raw)" in storage


def test_runtime001_uses_postgres_durable_queue_and_no_process_local_job_dictionaries():
    runtime = (ROOT / "app/runtime.py").read_text()
    migration = (ROOT / "migrations/20261005000021_durable_runtime_state.sql").read_text()
    worker = (ROOT / "app/runtime_worker.py").read_text()
    documents = (ROOT / "app/api/documents.py").read_text()
    ocr = (ROOT / "app/api/ocr.py").read_text()
    templates = (ROOT / "app/api/templates.py").read_text()

    assert "chunk_sessions: dict" not in runtime
    assert "extraction_jobs: dict" not in runtime
    assert "ocr_jobs: dict" not in runtime
    for table in ("runtime_jobs", "runtime_job_events", "runtime_chunk_sessions", "runtime_chunks"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "FOR UPDATE SKIP LOCKED" in migration
    assert "lease_expires_at" in migration
    assert "autodraft_claim_runtime_job" in migration
    assert "release_for_retry" in worker
    assert "runtime_state.create_job" in documents
    assert "runtime_state.create_job" in ocr
    assert "runtime_state.create_chunk_session" in documents
    assert "runtime_state.create_chunk_session" in templates
