from __future__ import annotations
import uuid
from ..db import Database
from ..services.domain_events import emit_domain_event

class PracticeRepository:
    def __init__(self, db: Database): self.db=db

    async def areas(self):
        return await self.db.p().fetch("SELECT * FROM practice_areas ORDER BY position,lower(name)")

    async def create_area(self, *, key:str,name:str,description:str,position:int,active:bool):
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow("""INSERT INTO practice_areas(organization_id,key,name,description,position,active)
            VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5)
            ON CONFLICT(organization_id,key) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description,position=EXCLUDED.position,active=EXCLUDED.active,updated_at=NOW() RETURNING *""",key,name,description,position,active)
            await emit_domain_event(conn,aggregate_type="practice_area",aggregate_id=row['id'],event_type="PracticeAreaUpserted",payload={"key":row['key'],"name":row['name']})
            return row

    async def update_area(self, area_id:uuid.UUID, data:dict):
        async with self.db.p().transaction() as conn:
            cur=await conn.fetchrow("SELECT * FROM practice_areas WHERE id=$1 FOR UPDATE",area_id)
            if not cur:return None
            vals={k:(data[k] if data.get(k) is not None else cur[k]) for k in ('name','description','position','active')}
            row=await conn.fetchrow("UPDATE practice_areas SET name=$1,description=$2,position=$3,active=$4,updated_at=NOW() WHERE id=$5 RETURNING *",vals['name'],vals['description'],vals['position'],vals['active'],area_id)
            await emit_domain_event(conn,aggregate_type="practice_area",aggregate_id=area_id,event_type="PracticeAreaUpdated",payload={"name":row['name'],"active":row['active']})
            return row

    async def stages(self, practice_area_id:uuid.UUID|None=None):
        if practice_area_id:
            return await self.db.p().fetch("SELECT * FROM matter_stages WHERE practice_area_id=$1 ORDER BY position,lower(name)",practice_area_id)
        return await self.db.p().fetch("SELECT * FROM matter_stages ORDER BY practice_area_id NULLS FIRST,position,lower(name)")

    async def create_stage(self, *, key:str,name:str,practice_area_id:uuid.UUID,description:str,position:int,active:bool):
        async with self.db.p().transaction() as conn:
            if not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1",practice_area_id):return None
            row=await conn.fetchrow("""INSERT INTO matter_stages(organization_id,practice_area_id,key,name,description,position,active)
            VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6)
            ON CONFLICT(organization_id,practice_area_id,key) DO UPDATE SET name=EXCLUDED.name,description=EXCLUDED.description,position=EXCLUDED.position,active=EXCLUDED.active,updated_at=NOW() RETURNING *""",practice_area_id,key,name,description,position,active)
            await emit_domain_event(conn,aggregate_type="matter_stage",aggregate_id=row['id'],event_type="MatterStageUpserted",payload={"key":row['key'],"name":row['name'],"practiceAreaId":str(practice_area_id) if practice_area_id else None})
            return row

    async def update_stage(self, stage_id:uuid.UUID, data:dict):
        async with self.db.p().transaction() as conn:
            cur=await conn.fetchrow("SELECT * FROM matter_stages WHERE id=$1 FOR UPDATE",stage_id)
            if not cur:return None
            vals={k:(data[k] if data.get(k) is not None else cur[k]) for k in ('name','description','position','active')}
            row=await conn.fetchrow("UPDATE matter_stages SET name=$1,description=$2,position=$3,active=$4,updated_at=NOW() WHERE id=$5 RETURNING *",vals['name'],vals['description'],vals['position'],vals['active'],stage_id)
            await emit_domain_event(conn,aggregate_type="matter_stage",aggregate_id=stage_id,event_type="MatterStageUpdated",payload={"name":row['name'],"active":row['active']})
            return row
