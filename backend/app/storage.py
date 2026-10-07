from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass

from .docx_safety import UnsafeDocxPackage, safe_docx_zip


@dataclass(frozen=True)
class PrivateBlob:
    content: bytes
    sha256: str
    size_bytes: int


def safe_filename(value: str, fallback: str = "document") -> str:
    """Return a display filename only; never a filesystem path."""
    name=(value or "").replace("\\","/").split("/")[-1].strip()
    name=re.sub(r"[\x00-\x1f\x7f]", "", name)
    name=re.sub(r"\s+", " ", name)
    if name in {"",".",".."}: name=fallback
    return name[:240]


def decode_private_docx(value: str, *, max_bytes: int) -> PrivateBlob:
    try: raw=base64.b64decode(value,validate=True)
    except Exception as exc: raise ValueError("docxBase64 is not valid Base64") from exc
    if not raw.startswith(b"PK"):
        raise ValueError("The supplied package is not a DOCX/ZIP file")
    if len(raw)>max_bytes:
        raise OverflowError("DOCX exceeds the configured private-storage limit")
    try:
        with safe_docx_zip(raw):
            pass
    except UnsafeDocxPackage as exc:
        raise ValueError(str(exc)) from exc
    return PrivateBlob(raw,hashlib.sha256(raw).hexdigest(),len(raw))


def private_blob(content: bytes, *, max_bytes: int) -> PrivateBlob:
    if len(content)>max_bytes: raise OverflowError("File exceeds the configured private-storage limit")
    return PrivateBlob(content,hashlib.sha256(content).hexdigest(),len(content))
