from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import Settings
from .docx_safety import UnsafeDocxPackage, safe_docx_zip


SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".txt"}
MIME_BY_KIND = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpeg": "image/jpeg",
    "text": "text/plain",
}
EXTENSIONS_BY_KIND = {
    "pdf": {".pdf"},
    "docx": {".docx"},
    "png": {".png"},
    "jpeg": {".jpg", ".jpeg"},
    "text": {".txt"},
}


class IntakeFileRejected(ValueError):
    def __init__(self, message: str, *, reason: str, status_code: int = 415):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class InspectedUpload:
    detected_kind: str
    detected_mime: str
    extension: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class MalwareScanResult:
    status: str  # clean | infected | unavailable | error
    engine: str
    detail: str = ""


def normalize_extensions(values: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in values:
        text = str(value or "").strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = "." + text
        result.add(text)
    return result


def _zip_has_exact_eof(content: bytes) -> bool:
    # Reject appended-data ZIP polyglots. Ordinary DOCX packages use the classic
    # EOCD record; comments are supported. ZIP64 files are conservatively rejected.
    sig = b"PK\x05\x06"
    pos = content.rfind(sig, max(0, len(content) - 65557))
    if pos < 0 or pos + 22 > len(content):
        return False
    comment_len = int.from_bytes(content[pos + 20:pos + 22], "little")
    return pos + 22 + comment_len == len(content)


def _inspect_kind(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        tail = content[-4096:].rstrip()
        eof = tail.rfind(b"%%EOF")
        if eof < 0 or tail[eof + 5:].strip():
            raise IntakeFileRejected("PDF has trailing or malformed content", reason="pdf_polyglot")
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        if not content.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
            raise IntakeFileRejected("PNG file is incomplete or contains trailing payload data", reason="png_polyglot")
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        if not content.endswith(b"\xff\xd9"):
            raise IntakeFileRejected("JPEG file is incomplete or contains trailing payload data", reason="jpeg_polyglot")
        return "jpeg"
    if content.startswith(b"PK\x03\x04"):
        if not _zip_has_exact_eof(content):
            raise IntakeFileRejected("DOCX ZIP contains appended or malformed payload data", reason="docx_polyglot")
        try:
            with safe_docx_zip(content):
                pass
        except UnsafeDocxPackage as exc:
            raise IntakeFileRejected(str(exc), reason="unsafe_docx") from exc
        return "docx"
    if b"\x00" not in content:
        try:
            content.decode("utf-8")
            return "text"
        except UnicodeDecodeError:
            pass
    raise IntakeFileRejected("Uploaded file type is not supported", reason="unknown_signature")


def inspect_upload(
    content: bytes,
    *,
    filename: str,
    declared_mime: str | None,
    allowed_extensions: Iterable[str],
) -> InspectedUpload:
    if not content:
        raise IntakeFileRejected("Uploaded file is empty", reason="empty_file")
    extension = Path(filename or "").suffix.lower()
    allowed = normalize_extensions(allowed_extensions)
    if extension not in SUPPORTED_EXTENSIONS:
        raise IntakeFileRejected("Filename extension is not a supported intake document type", reason="unsupported_extension")
    if allowed and extension not in allowed:
        raise IntakeFileRejected("File extension is not allowed for this question", reason="extension_not_allowed")

    kind = _inspect_kind(content)
    if extension not in EXTENSIONS_BY_KIND[kind]:
        raise IntakeFileRejected("File content does not match its filename extension", reason="extension_signature_mismatch")

    detected_mime = MIME_BY_KIND[kind]
    declared = str(declared_mime or "").split(";", 1)[0].strip().lower()
    compatible_declared = {
        "", "application/octet-stream", detected_mime,
    }
    if kind == "jpeg":
        compatible_declared.update({"image/jpg", "image/pjpeg"})
    if kind == "text":
        compatible_declared.update({"text/plain", "text/csv"})
    if declared not in compatible_declared:
        raise IntakeFileRejected("Declared MIME type does not match file content", reason="mime_mismatch")

    return InspectedUpload(
        detected_kind=kind,
        detected_mime=detected_mime,
        extension=extension,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
    )


async def scan_for_malware(content: bytes, *, filename: str, settings: Settings) -> MalwareScanResult:
    command = str(settings.intake_malware_scanner_command or "clamscan").strip()
    executable = shutil.which(command) if os.path.sep not in command else (command if os.path.exists(command) else None)
    if not executable:
        return MalwareScanResult(status="unavailable", engine=command or "clamscan", detail="scanner executable not found")

    suffix = Path(filename or "upload").suffix[:16]
    path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="autodraft-intake-", suffix=suffix, delete=False) as handle:
            handle.write(content)
            path = handle.name
        proc = await asyncio.create_subprocess_exec(
            executable,
            "--no-summary",
            "--stdout",
            path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=float(settings.intake_malware_scan_timeout_seconds))
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return MalwareScanResult(status="error", engine=command, detail="scanner timed out")
        detail = (stdout + b"\n" + stderr).decode("utf-8", errors="replace").strip()[:1000]
        if proc.returncode == 0:
            return MalwareScanResult(status="clean", engine=command, detail=detail)
        if proc.returncode == 1:
            return MalwareScanResult(status="infected", engine=command, detail=detail)
        return MalwareScanResult(status="error", engine=command, detail=detail or f"scanner exited {proc.returncode}")
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
