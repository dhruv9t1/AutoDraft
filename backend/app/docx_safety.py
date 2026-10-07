from __future__ import annotations

import io
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import BinaryIO, Iterator
from xml.etree import ElementTree as ET

from .config import get_settings


class UnsafeDocxPackage(ValueError):
    """Raised when a DOCX/ZIP package violates resource-safety limits."""


@dataclass(frozen=True)
class DocxPackageStats:
    entries: int
    total_uncompressed_bytes: int
    total_compressed_bytes: int
    max_compression_ratio: float


def _normalized_name(name: str) -> str:
    # ZIP member names are POSIX paths regardless of host platform.
    candidate = name.replace("\\", "/")
    path = PurePosixPath(candidate)
    if path.is_absolute() or ".." in path.parts:
        raise UnsafeDocxPackage(f"Unsafe DOCX ZIP member path: {name!r}")
    return candidate


def validate_docx_archive(archive: zipfile.ZipFile) -> DocxPackageStats:
    """Validate central-directory metadata before any member is decompressed.

    This is deliberately conservative. It blocks ZIP bombs using independent
    entry-count, per-entry, total-uncompressed and compression-ratio ceilings.
    """
    settings = get_settings()
    infos = archive.infolist()
    if not infos:
        raise UnsafeDocxPackage("DOCX package is empty")
    if len(infos) > settings.docx_max_zip_entries:
        raise UnsafeDocxPackage(
            f"DOCX contains too many ZIP entries ({len(infos)} > {settings.docx_max_zip_entries})"
        )

    seen: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    max_ratio = 1.0
    for info in infos:
        name = _normalized_name(info.filename)
        if name in seen:
            raise UnsafeDocxPackage(f"DOCX contains duplicate ZIP member: {name}")
        seen.add(name)
        if info.flag_bits & 0x1:
            raise UnsafeDocxPackage(f"Encrypted DOCX ZIP member is not supported: {name}")
        if info.file_size < 0 or info.compress_size < 0:
            raise UnsafeDocxPackage(f"Invalid DOCX ZIP metadata for member: {name}")
        if info.file_size > settings.docx_max_zip_entry_uncompressed_bytes:
            raise UnsafeDocxPackage(
                f"DOCX ZIP member is too large after decompression: {name}"
            )
        total_uncompressed += info.file_size
        total_compressed += info.compress_size
        if total_uncompressed > settings.docx_max_zip_uncompressed_bytes:
            raise UnsafeDocxPackage("DOCX expands beyond the configured uncompressed-size limit")

        if info.file_size >= settings.docx_zip_ratio_min_uncompressed_bytes:
            if info.compress_size == 0:
                raise UnsafeDocxPackage(f"Suspicious zero-size compressed member: {name}")
            ratio = info.file_size / max(1, info.compress_size)
            max_ratio = max(max_ratio, ratio)
            if ratio > settings.docx_max_zip_compression_ratio:
                raise UnsafeDocxPackage(
                    f"DOCX ZIP member has a suspicious compression ratio: {name}"
                )

    required = {"[Content_Types].xml", "word/document.xml"}
    missing = sorted(required - seen)
    if missing:
        raise UnsafeDocxPackage(
            "DOCX package is missing required OOXML part(s): " + ", ".join(missing)
        )
    return DocxPackageStats(
        entries=len(infos),
        total_uncompressed_bytes=total_uncompressed,
        total_compressed_bytes=total_compressed,
        max_compression_ratio=max_ratio,
    )



_FORBIDDEN_PART_PREFIXES = (
    "word/embeddings/", "word/activeX/", "customUI/",
)
_FORBIDDEN_PART_NAMES = {
    "word/vbaProject.bin", "word/vbaData.xml", "word/attachedTemplate.xml",
}
_FORBIDDEN_CONTENT_MARKERS = (
    "macroenabled", "vbaproject", "oleobject", "activex",
)

def validate_docx_content_policy(archive: zipfile.ZipFile) -> None:
    """Reject active/external content outside AutoDraft's supported DOCX subset.

    AutoDraft authoritative templates are data-only OOXML. Macros, OLE/package
    embeddings, ActiveX/custom UI, attached templates and external relationship
    targets are rejected rather than copied through to generated documents.
    """
    names = {info.filename.replace("\\", "/") for info in archive.infolist()}
    for name in names:
        if name in _FORBIDDEN_PART_NAMES or any(name.startswith(prefix) for prefix in _FORBIDDEN_PART_PREFIXES):
            raise UnsafeDocxPackage(f"Unsupported active/embedded DOCX content: {name}")
        if name.lower().endswith(".bin"):
            raise UnsafeDocxPackage(f"Binary embedded DOCX part is not supported: {name}")

    try:
        content_types = archive.read("[Content_Types].xml").decode("utf-8", errors="ignore").lower()
    except Exception as exc:
        raise UnsafeDocxPackage("DOCX content-type manifest could not be read") from exc
    if any(marker in content_types for marker in _FORBIDDEN_CONTENT_MARKERS):
        raise UnsafeDocxPackage("DOCX contains macros, embedded packages, or other active content")

    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    for name in sorted(n for n in names if n.endswith(".rels")):
        try:
            root = ET.fromstring(archive.read(name))
        except ET.ParseError as exc:
            raise UnsafeDocxPackage(f"Malformed OOXML relationship part: {name}") from exc
        for rel in root.findall("r:Relationship", rel_ns):
            if str(rel.get("TargetMode") or "").lower() == "external":
                target = str(rel.get("Target") or "")
                raise UnsafeDocxPackage(f"External OOXML relationship is not supported: {name} -> {target}")


@contextmanager
def safe_docx_zip(source: bytes | bytearray | BinaryIO | str) -> Iterator[zipfile.ZipFile]:
    """Open a DOCX only after validating its ZIP central directory."""
    if isinstance(source, (bytes, bytearray)):
        raw = bytes(source)
        if len(raw) > get_settings().max_docx_snapshot_bytes:
            raise UnsafeDocxPackage("DOCX exceeds the configured compressed-size limit")
        target: bytes | BinaryIO | str = io.BytesIO(raw)
    else:
        target = source
    try:
        archive = zipfile.ZipFile(target, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise UnsafeDocxPackage("Template snapshot is not a valid DOCX package") from exc
    try:
        validate_docx_archive(archive)
        validate_docx_content_policy(archive)
        yield archive
    finally:
        archive.close()
