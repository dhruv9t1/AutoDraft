from __future__ import annotations

import base64
import uuid
from fastapi import HTTPException

from ..config import Settings
from ..repositories.templates import TemplateRepository
from ..runtime import compress_ooxml, decompress_ooxml, utc_iso


class TemplateService:
    def __init__(self, repo:TemplateRepository, settings:Settings): self.repo=repo; self.settings=settings

    @staticmethod
    def tid(value:str)->uuid.UUID:
        try:return uuid.UUID(value)
        except ValueError as exc: raise HTTPException(400,"Invalid template ID") from exc

    @staticmethod
    def meta(row):
        return {"id":str(row['id']),"name":row['name'],"type":row['type'] or "","subtype":row['subtype'] or "","description":row['description'] or "","createdAt":utc_iso(row['created_at']),"updatedAt":utc_iso(row['updated_at'] or row['created_at']),"currentVersion":row.get('current_version',1) if hasattr(row,'get') else row['current_version'],"snapshotKind":row['snapshot_kind'] if 'snapshot_kind' in row else 'body_ooxml',"hasFullDocx":bool(row['has_docx']) if 'has_docx' in row else False}

    def validate_docx(self, encoded:str|None)->None:
        if encoded is None:return
        try:raw=base64.b64decode(encoded,validate=True)
        except Exception as exc:raise HTTPException(400,"docxBase64 is not valid Base64") from exc
        if not raw.startswith(b'PK'):raise HTTPException(400,"The full-document snapshot is not a DOCX package")
        if len(raw)>self.settings.max_docx_snapshot_bytes:raise HTTPException(413,"Full DOCX snapshot is too large")

    def validate_body(self, body:str)->None:
        if body and len(body.encode())>self.settings.max_ooxml_body_bytes:raise HTTPException(413,"Template body OOXML is too large")

    async def content(self,tid:uuid.UUID):
        row=await self.repo.get_content(tid)
        if not row:raise HTTPException(404,"Template not found")
        return {"bodyOoxml":decompress_ooxml(row['body_ooxml']) if row['body_ooxml'] else None,"docxBase64":row['docx_base64'],"snapshotKind":row['snapshot_kind'],"currentVersion":row['current_version']}
