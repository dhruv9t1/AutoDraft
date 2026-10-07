from __future__ import annotations

import logging
import uuid
from ..db import Database
from ..models import Variable
from ..binary_store import BinaryObjectStore


log = logging.getLogger(__name__)


class TemplateRepository:
    def __init__(self, db: Database, objects: BinaryObjectStore | None = None, *, max_docx_bytes: int = 100 * 1024 * 1024):
        self.db=db; self.objects=objects; self.max_docx_bytes=max_docx_bytes

    async def create(self, *, name:str, type_:str, subtype:str, description:str, variables:list[Variable]):
        tid=uuid.uuid4()
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow(
                "INSERT INTO templates(organization_id,id,name,type,subtype,description) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5) RETURNING created_at,updated_at",
                tid,name,type_,subtype,description,
            )
            if variables:
                await conn.executemany(
                    "INSERT INTO variables(template_id,variable_name,original_text,position,confidence_score,current_value,binding_id) VALUES($1,$2,$3,$4,$5,$6,COALESCE($7::uuid,gen_random_uuid()))",
                    [(tid,v.name,v.original_text,int(v.position),v.confidence_score,v.current_value,v.binding_id) for v in variables],
                )
        return tid,row

    async def list(self, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        limit=max(1,min(int(limit),200))
        if cursor_updated_at is None:
            return await self.db.p().fetch("""SELECT id,name,type,subtype,description,created_at,updated_at,current_version,snapshot_kind,
                (docx_object_key IS NOT NULL OR docx_base64 IS NOT NULL) AS has_docx
                FROM templates WHERE deleted_at IS NULL ORDER BY updated_at DESC,id DESC LIMIT $1""",limit+1)
        return await self.db.p().fetch("""SELECT id,name,type,subtype,description,created_at,updated_at,current_version,snapshot_kind,
                (docx_object_key IS NOT NULL OR docx_base64 IS NOT NULL) AS has_docx
                FROM templates WHERE deleted_at IS NULL AND (updated_at,id)<($1,$2)
                ORDER BY updated_at DESC,id DESC LIMIT $3""",cursor_updated_at,cursor_id,limit+1)

    async def get_meta(self, tid: uuid.UUID):
        return await self.db.p().fetchrow("""SELECT id,name,type,subtype,description,created_at,updated_at,current_version,snapshot_kind,
            (docx_object_key IS NOT NULL OR docx_base64 IS NOT NULL) AS has_docx
            FROM templates WHERE id=$1 AND deleted_at IS NULL""",tid)

    async def variables(self, tid: uuid.UUID):
        return await self.db.p().fetch("SELECT id,variable_name,original_text,position,confidence_score,current_value,binding_id FROM variables WHERE template_id=$1 ORDER BY position",tid)

    async def update_meta(self, tid:uuid.UUID, *, name:str, type_:str, subtype:str, description:str):
        return await self.db.p().fetchrow("""UPDATE templates SET name=$1,type=$2,subtype=$3,description=$4,updated_at=NOW()
            WHERE id=$5 AND deleted_at IS NULL RETURNING id,name,type,subtype,description,created_at,updated_at,current_version,snapshot_kind,
            (docx_object_key IS NOT NULL OR docx_base64 IS NOT NULL) AS has_docx""",name,type_,subtype,description,tid)

    async def duplicate(self, source_id:uuid.UUID):
        async with self.db.p().transaction() as conn:
            source=await conn.fetchrow("""SELECT name,type,subtype,description,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,
                snapshot_kind,current_version FROM templates WHERE id=$1 AND deleted_at IS NULL""",source_id)
            if not source:return None
            new_id=uuid.uuid4();new_name=f"{source['name']} Copy"
            row=await conn.fetchrow("""INSERT INTO templates(organization_id,id,name,type,subtype,description,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind,current_version)
                VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING created_at,updated_at""",
                new_id,new_name,source['type'],source['subtype'],source['description'],source['body_ooxml'],source['docx_base64'],source['docx_object_key'],source['docx_sha256'],source['docx_size_bytes'],source['snapshot_kind'],source['current_version'])
            variables=await conn.fetch("SELECT variable_name,original_text,position,confidence_score,current_value FROM variables WHERE template_id=$1 ORDER BY position",source_id)
            if variables:
                await conn.executemany("INSERT INTO variables(template_id,variable_name,original_text,position,confidence_score,current_value,binding_id) VALUES($1,$2,$3,$4,$5,$6,gen_random_uuid())",[(new_id,v['variable_name'],v['original_text'],v['position'],v['confidence_score'],None) for v in variables])
            versions=await conn.fetch("""SELECT version_number,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind,metadata
                FROM template_versions WHERE template_id=$1 ORDER BY version_number""",source_id)
            for v in versions:
                await conn.execute("""INSERT INTO template_versions(organization_id,template_id,version_number,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind,metadata)
                    VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb)""",new_id,v['version_number'],v['body_ooxml'],v['docx_base64'],v['docx_object_key'],v['docx_sha256'],v['docx_size_bytes'],v['snapshot_kind'],v['metadata'])
        return new_id,new_name,source,row

    async def soft_delete(self, tid:uuid.UUID):
        return await self.db.p().execute("UPDATE templates SET deleted_at=NOW(),updated_at=NOW() WHERE id=$1 AND deleted_at IS NULL",tid)

    async def _hydrate(self,row):
        if not row:return row
        result=dict(row)
        if result.get('docx_object_key') and self.objects:
            result['docx_base64']=await self.objects.get_base64(str(result['docx_object_key']))
        return result

    async def get_content(self, tid:uuid.UUID):
        row=await self.db.p().fetchrow("SELECT body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind,current_version FROM templates WHERE id=$1 AND deleted_at IS NULL",tid)
        return await self._hydrate(row)

    async def save_snapshot(self, tid:uuid.UUID, *, body_ooxml:str|None, docx_base64:str|None, snapshot_kind:str):
        stored=None
        if docx_base64 is not None and self.objects:
            stored=await self.objects.put_base64(namespace=f"templates/{tid}",encoded=docx_base64,max_bytes=self.max_docx_bytes)
        try:
            async with self.db.p().transaction() as conn:
                current=await conn.fetchrow("SELECT current_version FROM templates WHERE id=$1 AND deleted_at IS NULL FOR UPDATE",tid)
                if not current:return None
                existing_count=await conn.fetchval("SELECT COUNT(*) FROM template_versions WHERE template_id=$1",tid)
                next_version=int(current['current_version'] or 1) if not existing_count else int(current['current_version'] or 1)+1
                db_b64=None if stored else docx_base64
                key=stored.key if stored else None;sha=stored.sha256 if stored else None;size=stored.byte_length if stored else 0
                await conn.execute("""UPDATE templates SET body_ooxml=$1,docx_base64=$2,docx_object_key=$3,docx_sha256=$4,docx_size_bytes=$5,
                    snapshot_kind=$6,current_version=$7,updated_at=NOW() WHERE id=$8""",body_ooxml,db_b64,key,sha,size,snapshot_kind,next_version,tid)
                await conn.execute("""INSERT INTO template_versions(organization_id,template_id,version_number,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind)
                    VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8)""",tid,next_version,body_ooxml,db_b64,key,sha,size,snapshot_kind)
            return next_version
        except Exception:
            if stored and self.objects:
                try:
                    await self.objects.delete(stored.key)
                except Exception:
                    log.exception("Failed to remove orphaned template snapshot object %s", stored.key)
            raise

    async def versions(self, tid:uuid.UUID):
        return await self.db.p().fetch("""SELECT id,version_number,snapshot_kind,(docx_object_key IS NOT NULL OR docx_base64 IS NOT NULL) AS has_docx,
            created_at,metadata FROM template_versions WHERE template_id=$1 ORDER BY version_number DESC""",tid)

    async def version_content(self, tid:uuid.UUID, version:int):
        row=await self.db.p().fetchrow("""SELECT version_number,body_ooxml,docx_base64,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind,created_at
            FROM template_versions WHERE template_id=$1 AND version_number=$2""",tid,version)
        return await self._hydrate(row)
