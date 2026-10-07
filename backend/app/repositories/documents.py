from __future__ import annotations

import base64
import hashlib
import uuid
from ..db import Database
from ..binary_store import BinaryObjectStore, estimated_base64_decoded_size


class MatterDocumentRepository:
    def __init__(self, db: Database, objects: BinaryObjectStore | None = None, *, max_bytes: int = 100 * 1024 * 1024):
        self.db = db; self.objects=objects; self.max_bytes=max_bytes

    async def list(self, matter_id: uuid.UUID, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        limit=max(1,min(int(limit),200))
        if cursor_updated_at is None:
            return await self.db.p().fetch(
                """SELECT id,name,mime_type,size_bytes,source,metadata,created_at,updated_at
                   FROM matter_documents WHERE matter_id=$1 AND archived_at IS NULL
                   ORDER BY updated_at DESC,id DESC LIMIT $2""", matter_id,limit+1
            )
        return await self.db.p().fetch(
            """SELECT id,name,mime_type,size_bytes,source,metadata,created_at,updated_at
               FROM matter_documents WHERE matter_id=$1 AND archived_at IS NULL AND (updated_at,id)<($2,$3)
               ORDER BY updated_at DESC,id DESC LIMIT $4""",matter_id,cursor_updated_at,cursor_id,limit+1)

    async def create_bytes(self,matter_id:uuid.UUID,*,name:str,data:bytes,mime_type:str,source:str,metadata:dict):
        raw=bytes(data)
        if len(raw)>self.max_bytes: raise ValueError("Matter Document is too large")
        if self.objects:
            stored=await self.objects.put_bytes(namespace=f"matter-documents/{matter_id}",data=raw,suffix=".docx")
            key=stored.key;digest=stored.sha256;db_b64=None
        else:
            key=None;digest=hashlib.sha256(raw).hexdigest();db_b64=base64.b64encode(raw).decode("ascii")
        meta={**(metadata or {}),"sha256":digest}
        try:
            return await self.db.p().fetchrow(
                """INSERT INTO matter_documents(organization_id,matter_id,name,mime_type,docx_base64,object_key,sha256,size_bytes,source,metadata)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                   RETURNING id,name,mime_type,size_bytes,source,metadata,created_at,updated_at""",
                matter_id,name,mime_type,db_b64,key,digest,len(raw),source,meta)
        except Exception:
            if key and self.objects: await self.objects.delete(key)
            raise

    async def create(self, matter_id: uuid.UUID, *, name: str, docx_base64: str, mime_type: str, source: str, metadata: dict):
        if estimated_base64_decoded_size(docx_base64)>self.max_bytes: raise ValueError("Matter Document is too large")
        try: raw=base64.b64decode(docx_base64,validate=True)
        except Exception as exc: raise ValueError("docxBase64 is invalid") from exc
        return await self.create_bytes(matter_id,name=name,data=raw,mime_type=mime_type,source=source,metadata=metadata)

    async def get(self, matter_id: uuid.UUID, document_id: uuid.UUID, *, include_content: bool = False):
        cols="id,name,mime_type,size_bytes,source,metadata,created_at,updated_at,object_key,sha256"+(",docx_base64" if include_content else "")
        row=await self.db.p().fetchrow(f"SELECT {cols} FROM matter_documents WHERE id=$1 AND matter_id=$2 AND archived_at IS NULL",document_id,matter_id)
        if not row:return None
        result=dict(row)
        if include_content and result.get('object_key') and self.objects:
            result['docx_base64']=await self.objects.get_base64(str(result['object_key']))
        return result

    async def get_bytes(self,matter_id:uuid.UUID,document_id:uuid.UUID)->tuple[dict,bytes]|None:
        row=await self.db.p().fetchrow("SELECT id,name,mime_type,size_bytes,source,metadata,created_at,updated_at,object_key,docx_base64,sha256 FROM matter_documents WHERE id=$1 AND matter_id=$2 AND archived_at IS NULL",document_id,matter_id)
        if not row:return None
        result=dict(row)
        if result.get('object_key') and self.objects:raw=await self.objects.get_bytes(str(result['object_key']))
        else:raw=base64.b64decode(str(result.get('docx_base64') or ''),validate=True)
        return result,raw

    async def update(self, matter_id: uuid.UUID, document_id: uuid.UUID, *, name: str | None, archived: bool | None):
        current=await self.get(matter_id,document_id)
        if not current:return None
        return await self.db.p().fetchrow(
            """UPDATE matter_documents SET name=COALESCE($1,name),archived_at=CASE WHEN $2 THEN NOW() ELSE archived_at END,updated_at=NOW()
               WHERE id=$3 AND matter_id=$4 RETURNING id,name,mime_type,size_bytes,source,metadata,created_at,updated_at""",
            name,bool(archived),document_id,matter_id)
