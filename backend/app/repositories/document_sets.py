from __future__ import annotations
import uuid
from ..db import Database
from ..services.domain_events import emit_domain_event

class DocumentSetRepository:
    def __init__(self, db: Database): self.db=db

    async def list(self, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        limit=max(1,min(int(limit),200));cursor_sql="" if cursor_updated_at is None else " AND (ds.updated_at,ds.id)<($1,$2)"
        args=[limit+1] if cursor_updated_at is None else [cursor_updated_at,cursor_id,limit+1];limit_ref="$1" if cursor_updated_at is None else "$3"
        return await self.db.p().fetch(f"""SELECT ds.*,pa.name AS practice_area_name,
          (SELECT COUNT(*) FROM document_set_drafts d WHERE d.document_set_id=ds.id) AS draft_item_count
          FROM document_sets ds LEFT JOIN practice_areas pa ON pa.id=ds.practice_area_id
          WHERE ds.status<>'retired' {cursor_sql} ORDER BY ds.updated_at DESC,ds.id DESC LIMIT {limit_ref}""",*args)

    async def get(self,set_id:uuid.UUID):
        row=await self.db.p().fetchrow("SELECT ds.*,pa.name AS practice_area_name FROM document_sets ds LEFT JOIN practice_areas pa ON pa.id=ds.practice_area_id WHERE ds.id=$1",set_id)
        if not row:return None
        drafts=await self.db.p().fetch("""SELECT d.*,t.name AS template_name,t.current_version,t.snapshot_kind,(t.docx_object_key IS NOT NULL OR t.docx_base64 IS NOT NULL) AS has_docx
          FROM document_set_drafts d JOIN templates t ON t.id=d.template_id WHERE d.document_set_id=$1 AND t.deleted_at IS NULL ORDER BY d.position,d.created_at""",set_id)
        versions=await self.db.p().fetch("SELECT * FROM document_set_versions WHERE document_set_id=$1 ORDER BY version_number DESC",set_id)
        return row,drafts,versions

    async def version(self,set_id:uuid.UUID,version_number:int):
        version=await self.db.p().fetchrow("SELECT * FROM document_set_versions WHERE document_set_id=$1 AND version_number=$2",set_id,version_number)
        if not version:return None
        items=await self.db.p().fetch("""SELECT i.*,t.name AS template_name,tv.version_number AS template_version
          FROM document_set_items i JOIN templates t ON t.id=i.template_id LEFT JOIN template_versions tv ON tv.id=i.template_version_id
          WHERE i.version_id=$1 ORDER BY i.position,i.id""",version['id'])
        return version,items

    async def create(self, *, name:str,description:str,practice_area_id,matter_type:str,items:list[dict]):
        async with self.db.p().transaction() as conn:
            if practice_area_id and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1",practice_area_id):return None
            row=await conn.fetchrow("""INSERT INTO document_sets(organization_id,name,description,practice_area_id,matter_type)
              VALUES(autodraft_current_organization_id(),$1,$2,$3,$4) RETURNING *""",name,description,practice_area_id,matter_type)
            await self._replace_drafts(conn,row['id'],items)
            await emit_domain_event(conn,aggregate_type="document_set",aggregate_id=row['id'],event_type="DocumentSetCreated",payload={"name":row['name'],"itemCount":len(items)})
            return row

    async def update(self,set_id:uuid.UUID, *, name,description,practice_area_id,practice_area_set:bool,matter_type,items):
        async with self.db.p().transaction() as conn:
            cur=await conn.fetchrow("SELECT * FROM document_sets WHERE id=$1 AND status<>'retired' FOR UPDATE",set_id)
            if not cur:return None
            vals={
              'name':name if name is not None else cur['name'],
              'description':description if description is not None else cur['description'],
              'practice_area_id':practice_area_id if practice_area_set else cur['practice_area_id'],
              'matter_type':matter_type if matter_type is not None else cur['matter_type'],
            }
            if vals['practice_area_id'] and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1",vals['practice_area_id']):return None
            row=await conn.fetchrow("UPDATE document_sets SET name=$1,description=$2,practice_area_id=$3,matter_type=$4,updated_at=NOW() WHERE id=$5 RETURNING *",vals['name'],vals['description'],vals['practice_area_id'],vals['matter_type'],set_id)
            if items is not None: await self._replace_drafts(conn,set_id,items)
            await emit_domain_event(conn,aggregate_type="document_set",aggregate_id=set_id,event_type="DocumentSetDraftUpdated",payload={"name":row['name'],"itemCount":len(items) if items is not None else None})
            return row

    async def _replace_drafts(self,conn,set_id,items):
        await conn.execute("DELETE FROM document_set_drafts WHERE document_set_id=$1",set_id)
        for i,item in enumerate(items):
            tid=item['template_id']
            template=await conn.fetchrow("SELECT id FROM templates WHERE id=$1 AND deleted_at IS NULL",tid)
            if not template: raise ValueError(f"Template not found: {tid}")
            await conn.execute("INSERT INTO document_set_drafts(organization_id,document_set_id,template_id,label,position,required,metadata) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6::jsonb)",set_id,tid,item.get('label') or '',item.get('position',i),item.get('required',True),item.get('metadata') or {})

    async def publish(self,set_id:uuid.UUID):
        async with self.db.p().transaction() as conn:
            ds=await conn.fetchrow("SELECT * FROM document_sets WHERE id=$1 AND status<>'retired' FOR UPDATE",set_id)
            if not ds:return None
            drafts=await conn.fetch("""SELECT d.*,t.current_version FROM document_set_drafts d JOIN templates t ON t.id=d.template_id
              WHERE d.document_set_id=$1 AND t.deleted_at IS NULL ORDER BY d.position,d.created_at""",set_id)
            if not drafts: raise ValueError("A document set must contain at least one template")
            resolved=[]
            for item in drafts:
                tv=await conn.fetchrow("SELECT id,version_number FROM template_versions WHERE template_id=$1 AND version_number=$2",item['template_id'],item['current_version'])
                if not tv:
                    raise ValueError("Every template in a published set needs an immutable template snapshot. Save the template document first.")
                resolved.append((item,tv))
            version_number=int(ds['current_version'] or 0)+1
            version=await conn.fetchrow("INSERT INTO document_set_versions(organization_id,document_set_id,version_number) VALUES(autodraft_current_organization_id(),$1,$2) RETURNING *",set_id,version_number)
            for item,tv in resolved:
                await conn.execute("INSERT INTO document_set_items(organization_id,version_id,template_id,template_version_id,label,position,required,metadata) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7::jsonb)",version['id'],item['template_id'],tv['id'],item['label'],item['position'],item['required'],item['metadata'])
            await conn.execute("UPDATE document_sets SET current_version=$1,status='published',updated_at=NOW() WHERE id=$2",version_number,set_id)
            await emit_domain_event(conn,aggregate_type="document_set",aggregate_id=set_id,event_type="DocumentSetPublished",payload={"version":version_number,"itemCount":len(resolved)})
            return version

    async def retire(self,set_id:uuid.UUID):
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow("UPDATE document_sets SET status='retired',updated_at=NOW() WHERE id=$1 RETURNING *",set_id)
            if row: await emit_domain_event(conn,aggregate_type="document_set",aggregate_id=set_id,event_type="DocumentSetRetired",payload={"name":row['name']})
            return row

    async def start_generation(self,matter_id:uuid.UUID,version_id:uuid.UUID,selected_items:list[str]):
        async with self.db.p().transaction() as conn:
            if not await conn.fetchval("SELECT 1 FROM matters WHERE id=$1 AND archived_at IS NULL",matter_id):return None
            version=await conn.fetchrow("""SELECT v.id,v.document_set_id FROM document_set_versions v JOIN document_sets ds ON ds.id=v.document_set_id
              WHERE v.id=$1 AND ds.status<>'retired'""",version_id)
            if not version:return None
            all_items=await conn.fetch("SELECT id,required FROM document_set_items WHERE version_id=$1 ORDER BY position",version_id)
            ordered=[str(r['id']) for r in all_items]; allowed=set(ordered)
            chosen=[x for x in selected_items if x in allowed] if selected_items else ordered
            required={str(r['id']) for r in all_items if r['required']}
            missing_required=sorted(required-set(chosen))
            if missing_required:
                raise ValueError("Required document-set items cannot be deselected: " + ", ".join(missing_required))
            row=await conn.fetchrow("""INSERT INTO generation_runs(organization_id,matter_id,document_set_version_id,status,selected_items)
              VALUES(autodraft_current_organization_id(),$1,$2,'selection',$3::jsonb) RETURNING *""",matter_id,version_id,chosen)
            await emit_domain_event(conn,aggregate_type="generation_run",aggregate_id=row['id'],matter_id=matter_id,event_type="GenerationRunStarted",payload={"documentSetVersionId":str(version_id),"selectedItems":chosen})
            return row

    async def advance_generation(self,run_id:uuid.UUID,status:str,metadata:dict):
        async with self.db.p().transaction() as conn:
            current=await conn.fetchrow("SELECT * FROM generation_runs WHERE id=$1 FOR UPDATE",run_id)
            if not current:return None
            allowed={
              "selection":{"population","failed"},
              "population":{"review","failed"},
              "review":{"completed","failed"},
              "completed":set(),
              "failed":set(),
            }
            if status != current['status'] and status not in allowed.get(current['status'],set()):
                raise ValueError(f"Generation run cannot move from {current['status']} to {status}")
            row=await conn.fetchrow("UPDATE generation_runs SET status=$1,metadata=metadata||$2::jsonb,updated_at=NOW() WHERE id=$3 RETURNING *",status,metadata,run_id)
            await emit_domain_event(conn,aggregate_type="generation_run",aggregate_id=run_id,matter_id=row['matter_id'],event_type="GenerationRunStatusChanged",payload={"from":current['status'],"status":status})
            return row
