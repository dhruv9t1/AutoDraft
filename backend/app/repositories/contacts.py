from __future__ import annotations
import uuid
from ..db import Database
from ..services.domain_events import emit_domain_event

class ContactRepository:
    def __init__(self, db: Database): self.db=db

    async def list(self, query: str = "", *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        q=(query or "").strip();limit=max(1,min(int(limit),200))
        params=[];where=["archived_at IS NULL"]
        if q:
            params.append(q);where.append(f"(display_name ILIKE '%'||${len(params)}||'%' OR email ILIKE '%'||${len(params)}||'%' OR phone ILIKE '%'||${len(params)}||'%')")
        if cursor_updated_at is not None:
            params.extend([cursor_updated_at,cursor_id]);where.append(f"(updated_at,id)<(${len(params)-1},${len(params)})")
        params.append(limit+1)
        return await self.db.p().fetch(f"SELECT * FROM contacts WHERE {' AND '.join(where)} ORDER BY updated_at DESC,id DESC LIMIT ${len(params)}",*params)

    async def get(self, contact_id: uuid.UUID):
        return await self.db.p().fetchrow("SELECT * FROM contacts WHERE id=$1 AND archived_at IS NULL",contact_id)

    async def create(self, data: dict):
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow(
                """INSERT INTO contacts(organization_id,contact_type,display_name,first_name,middle_name,last_name,company_name,email,phone,metadata)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                   RETURNING *""",
                data['contact_type'],data['display_name'],data['first_name'],data['middle_name'],data['last_name'],data['company_name'],data['email'],data['phone'],data['metadata'])
            await emit_domain_event(conn,aggregate_type="contact",aggregate_id=row['id'],event_type="ContactCreated",payload={"displayName":row['display_name'],"contactType":row['contact_type']})
            return row

    async def update(self, contact_id: uuid.UUID, data: dict):
        async with self.db.p().transaction() as conn:
            current=await conn.fetchrow("SELECT * FROM contacts WHERE id=$1 AND archived_at IS NULL FOR UPDATE",contact_id)
            if not current:return None
            values={k:(data[k] if data.get(k) is not None else current[k]) for k in ('contact_type','display_name','first_name','middle_name','last_name','company_name','email','phone','metadata')}
            archived=data.get('archived')
            row=await conn.fetchrow(
                """UPDATE contacts SET contact_type=$1,display_name=$2,first_name=$3,middle_name=$4,last_name=$5,company_name=$6,email=$7,phone=$8,metadata=$9::jsonb,
                   archived_at=CASE WHEN $10::boolean IS TRUE THEN NOW() WHEN $10::boolean IS FALSE THEN NULL ELSE archived_at END,updated_at=NOW()
                   WHERE id=$11 RETURNING *""",
                values['contact_type'],values['display_name'],values['first_name'],values['middle_name'],values['last_name'],values['company_name'],values['email'],values['phone'],values['metadata'],archived,contact_id)
            await emit_domain_event(conn,aggregate_type="contact",aggregate_id=contact_id,event_type="ContactUpdated",payload={"displayName":row['display_name'],"archived":bool(row['archived_at'])})
            return row

    async def participants(self, matter_id: uuid.UUID):
        return await self.db.p().fetch(
            """SELECT mp.*,c.contact_type,c.display_name,c.first_name,c.middle_name,c.last_name,c.company_name,c.email,c.phone
               FROM matter_participants mp JOIN contacts c ON c.id=mp.contact_id
               WHERE mp.matter_id=$1 AND c.archived_at IS NULL ORDER BY mp.position,mp.created_at""",matter_id)

    async def add_participant(self, matter_id: uuid.UUID, contact_id: uuid.UUID, data: dict):
        async with self.db.p().transaction() as conn:
            if not await conn.fetchval("SELECT 1 FROM matters WHERE id=$1 AND archived_at IS NULL",matter_id): return None
            if not await conn.fetchval("SELECT 1 FROM contacts WHERE id=$1 AND archived_at IS NULL",contact_id): return None
            if data['is_primary']:
                await conn.execute("UPDATE matter_participants SET is_primary=FALSE,updated_at=NOW() WHERE matter_id=$1 AND role_key=$2",matter_id,data['role_key'])
            row=await conn.fetchrow(
                """INSERT INTO matter_participants(organization_id,matter_id,contact_id,role_key,display_role,is_client,is_primary,represented_by_firm,position,metadata)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                   ON CONFLICT(matter_id,contact_id,role_key) DO UPDATE SET display_role=EXCLUDED.display_role,is_client=EXCLUDED.is_client,is_primary=EXCLUDED.is_primary,represented_by_firm=EXCLUDED.represented_by_firm,position=EXCLUDED.position,metadata=EXCLUDED.metadata,updated_at=NOW()
                   RETURNING *""",matter_id,contact_id,data['role_key'],data['display_role'],data['is_client'],data['is_primary'],data['represented_by_firm'],data['position'],data['metadata'])
            await emit_domain_event(conn,aggregate_type="matter_participant",aggregate_id=row['id'],matter_id=matter_id,event_type="MatterParticipantUpserted",payload={"contactId":str(contact_id),"roleKey":row['role_key'],"isClient":row['is_client']})
            return row

    async def update_participant(self, matter_id: uuid.UUID, participant_id: uuid.UUID, data: dict):
        async with self.db.p().transaction() as conn:
            cur=await conn.fetchrow("SELECT * FROM matter_participants WHERE id=$1 AND matter_id=$2 FOR UPDATE",participant_id,matter_id)
            if not cur:return None
            vals={k:(data[k] if data.get(k) is not None else cur[k]) for k in ('role_key','display_role','is_client','is_primary','represented_by_firm','position','metadata')}
            if vals['is_primary']:
                await conn.execute("UPDATE matter_participants SET is_primary=FALSE,updated_at=NOW() WHERE matter_id=$1 AND role_key=$2 AND id<>$3",matter_id,vals['role_key'],participant_id)
            row=await conn.fetchrow("""UPDATE matter_participants SET role_key=$1,display_role=$2,is_client=$3,is_primary=$4,represented_by_firm=$5,position=$6,metadata=$7::jsonb,updated_at=NOW() WHERE id=$8 AND matter_id=$9 RETURNING *""",vals['role_key'],vals['display_role'],vals['is_client'],vals['is_primary'],vals['represented_by_firm'],vals['position'],vals['metadata'],participant_id,matter_id)
            await emit_domain_event(conn,aggregate_type="matter_participant",aggregate_id=participant_id,matter_id=matter_id,event_type="MatterParticipantUpdated",payload={"roleKey":row['role_key']})
            return row

    async def remove_participant(self, matter_id: uuid.UUID, participant_id: uuid.UUID):
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow("DELETE FROM matter_participants WHERE id=$1 AND matter_id=$2 RETURNING id,contact_id,role_key",participant_id,matter_id)
            if row: await emit_domain_event(conn,aggregate_type="matter_participant",aggregate_id=participant_id,matter_id=matter_id,event_type="MatterParticipantRemoved",payload={"contactId":str(row['contact_id']),"roleKey":row['role_key']})
            return row
