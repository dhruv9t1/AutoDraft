from __future__ import annotations

import uuid

from ..db import Database
from ..domain.facts import fact_key as make_fact_key, normalize_fact_value
from ..domain.canonical_fields import display_value
from ..services.domain_events import emit_domain_event
from ..services.legal_value_service import LegalValueWriteService


class MatterRepository:
    def __init__(self, db: Database):
        self.db = db
        self.legal_values = LegalValueWriteService()

    async def create(self, title: str, matter_type: str, *, practice_area_id=None, stage_id=None, reference_code: str = ""):
        async with self.db.p().transaction() as conn:
            if practice_area_id and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1", practice_area_id):
                return None
            if stage_id:
                if not practice_area_id: raise ValueError("A practice area is required before assigning a matter stage")
                stage = await conn.fetchrow("SELECT practice_area_id FROM matter_stages WHERE id=$1 AND active=TRUE", stage_id)
                if not stage: return None
                if practice_area_id and stage["practice_area_id"] and stage["practice_area_id"] != practice_area_id:
                    raise ValueError("Matter stage does not belong to the selected practice area")
            row = await conn.fetchrow(
                """INSERT INTO matters(organization_id,title,matter_type,practice_area_id,stage_id,reference_code)
                   VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5)
                   RETURNING *""",
                title, matter_type, practice_area_id, stage_id, reference_code,
            )
            await emit_domain_event(conn, aggregate_type="matter", aggregate_id=row["id"], matter_id=row["id"], event_type="MatterCreated", payload={"title": title, "matterType": matter_type})
            return row

    async def list(self, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        limit=max(1,min(int(limit),200))
        cursor_sql="" if cursor_updated_at is None else " AND (m.updated_at,m.id)<($1,$2)"
        args=[limit+1] if cursor_updated_at is None else [cursor_updated_at,cursor_id,limit+1]
        limit_ref="$1" if cursor_updated_at is None else "$3"
        return await self.db.p().fetch(f"""SELECT m.*,pa.name AS practice_area_name,ms.name AS stage_name,
                      (SELECT c.display_name FROM matter_participants mp JOIN contacts c ON c.id=mp.contact_id
                       WHERE mp.matter_id=m.id AND mp.is_client=TRUE ORDER BY mp.is_primary DESC,mp.position,mp.created_at LIMIT 1) AS primary_client_name
               FROM matters m LEFT JOIN practice_areas pa ON pa.id=m.practice_area_id LEFT JOIN matter_stages ms ON ms.id=m.stage_id
               WHERE m.archived_at IS NULL {cursor_sql} ORDER BY m.updated_at DESC,m.id DESC LIMIT {limit_ref}""",*args)

    async def get(self, matter_id: uuid.UUID):
        return await self.db.p().fetchrow(
            """SELECT m.*,pa.name AS practice_area_name,ms.name AS stage_name
               FROM matters m LEFT JOIN practice_areas pa ON pa.id=m.practice_area_id LEFT JOIN matter_stages ms ON ms.id=m.stage_id
               WHERE m.id=$1 AND m.archived_at IS NULL""", matter_id
        )

    async def update(self, matter_id: uuid.UUID, *, title: str, matter_type: str, status: str, practice_area_id=None, stage_id=None, reference_code: str = ""):
        archived = status == "archived"
        async with self.db.p().transaction() as conn:
            if practice_area_id and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1", practice_area_id): return None
            if stage_id:
                if not practice_area_id: raise ValueError("A practice area is required before assigning a matter stage")
                stage=await conn.fetchrow("SELECT practice_area_id FROM matter_stages WHERE id=$1 AND active=TRUE",stage_id)
                if not stage:return None
                if practice_area_id and stage["practice_area_id"] and stage["practice_area_id"] != practice_area_id:
                    raise ValueError("Matter stage does not belong to the selected practice area")
            row=await conn.fetchrow(
                """UPDATE matters SET title=$1,matter_type=$2,status=$3,practice_area_id=$4,stage_id=$5,reference_code=$6,
                   stage_changed_at=CASE WHEN stage_id IS DISTINCT FROM $5 THEN NOW() ELSE stage_changed_at END,
                   archived_at=CASE WHEN $7 THEN NOW() ELSE NULL END,updated_at=NOW()
                   WHERE id=$8 AND archived_at IS NULL RETURNING *""",
                title,matter_type,status,practice_area_id,stage_id,reference_code,archived,matter_id,
            )
            if row:
                await emit_domain_event(conn,aggregate_type="matter",aggregate_id=matter_id,matter_id=matter_id,event_type="MatterUpdated",payload={"title":title,"status":status,"stageId":str(stage_id) if stage_id else None})
            return row

    async def authorities(self, matter_id: uuid.UUID):
        return await self.db.p().fetch(
            "SELECT id,title,citation,source_url,verified,verification_status,verified_by_user_id,verified_at,verification_evidence,created_at FROM matter_authorities WHERE matter_id=$1 ORDER BY created_at", matter_id
        )

    async def add_authority(self, matter_id: uuid.UUID, *, title: str, citation: str, source_url: str):
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow(
                """INSERT INTO matter_authorities(matter_id,title,citation,source_url,verified,verification_status)
                   VALUES($1,$2,$3,$4,FALSE,'unverified')
                   RETURNING id,title,citation,source_url,verified,verification_status,verified_by_user_id,verified_at,verification_evidence,created_at""",
                matter_id,title,citation,source_url,
            )
            await emit_domain_event(conn,aggregate_type="matter_authority",aggregate_id=row['id'],matter_id=matter_id,event_type="MatterAuthorityAdded",payload={"title":title,"citation":citation,"verificationStatus":"unverified"})
            return row

    async def verify_authority(self, matter_id: uuid.UUID, authority_id: uuid.UUID, *, status: str, user_id: uuid.UUID, evidence: dict):
        verified = status == "lawyer_verified"
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow(
                """UPDATE matter_authorities
                   SET verification_status=$1,verified=$2,verified_by_user_id=$3,verified_at=NOW(),verification_evidence=$4::jsonb
                   WHERE id=$5 AND matter_id=$6
                   RETURNING id,title,citation,source_url,verified,verification_status,verified_by_user_id,verified_at,verification_evidence,created_at""",
                status,verified,user_id,evidence,authority_id,matter_id,
            )
            if row:
                await emit_domain_event(conn,aggregate_type="matter_authority",aggregate_id=authority_id,matter_id=matter_id,event_type="MatterAuthorityVerificationChanged",payload={"verificationStatus":status,"verified":verified})
            return row

    async def facts(self, matter_id: uuid.UUID):
        return await self.db.p().fetch(
            """SELECT id,field,fact,source,status,fact_key,label,value_type,value_json,is_canonical,derived_from,confirmed_at,field_definition_id,created_at,updated_at
               FROM matter_facts WHERE matter_id=$1 ORDER BY is_canonical DESC,COALESCE(updated_at,created_at),created_at""", matter_id
        )

    async def fact(self,matter_id:uuid.UUID,fact_id:uuid.UUID):
        return await self.db.p().fetchrow("""SELECT id,field,fact,source,status,fact_key,label,value_type,value_json,is_canonical,derived_from,confirmed_at,field_definition_id,created_at,updated_at FROM matter_facts WHERE matter_id=$1 AND id=$2""",matter_id,fact_id)

    async def conflicts(self, matter_id: uuid.UUID):
        return await self.db.p().fetch(
            "SELECT id,fact_key,status,candidate_fact_ids,resolution_fact_id,created_at,resolved_at FROM fact_conflicts WHERE matter_id=$1 ORDER BY status='open' DESC,created_at DESC",
            matter_id,
        )

    async def canonical_fact_by_key(self, matter_id:uuid.UUID, fact_key:str):
        return await self.db.p().fetchrow(
            """SELECT id,organization_id,matter_id,field,fact,source,status,fact_key,label,
                      value_type,value_json,is_canonical,derived_from,confirmed_at,
                      field_definition_id,created_at,updated_at
               FROM matter_facts
               WHERE matter_id=$1 AND fact_key=$2 AND is_canonical=TRUE
               ORDER BY COALESCE(updated_at,created_at) DESC LIMIT 1""",
            matter_id,fact_key,
        )

    async def add_fact(self, matter_id: uuid.UUID, *, field: str, fact: str, source: str, status: str):
        """Propose a legal value through the single conflict-aware canonical write path."""
        key = make_fact_key(field)
        async with self.db.p().transaction() as conn:
            definition = await self.legal_values.ensure_matter_definition(
                conn,matter_id=matter_id,semantic_key=key,display_label=field,value_type='text',aliases=[field],
            )
            outcome = await self.legal_values.propose_matter_value(
                conn,matter_id=matter_id,definition=definition,value=fact,source=source,
                provenance={'origin':'matter_fact_api'},desired_status=status,
            )
            legacy = outcome['legacy']
            if outcome['status'] == 'conflict':
                await emit_domain_event(
                    conn,aggregate_type="fact_conflict",aggregate_id=outcome['conflict_id'],matter_id=matter_id,
                    event_type="MatterFactConflictOpened",
                    payload={"factKey":key,"candidateFactId":str(legacy['id']),"source":source},
                )
            else:
                await emit_domain_event(
                    conn,aggregate_type="matter_fact",aggregate_id=legacy['id'],matter_id=matter_id,
                    event_type="MatterFactAccepted",
                    payload={"factKey":key,"source":source,"canonicalStore":"matter_field_values"},
                )
            return legacy

    async def resolve_conflict(self, matter_id: uuid.UUID, conflict_id: uuid.UUID, *, fact_id: uuid.UUID | None, value: str | None, dismiss: bool):
        async with self.db.p().transaction() as conn:
            conflict=await conn.fetchrow("SELECT * FROM fact_conflicts WHERE id=$1 AND matter_id=$2 AND status='open' FOR UPDATE",conflict_id,matter_id)
            if not conflict:return None
            if dismiss:
                await conn.execute("UPDATE fact_conflicts SET status='dismissed',resolved_at=NOW() WHERE id=$1",conflict_id)
                await emit_domain_event(conn,aggregate_type="fact_conflict",aggregate_id=conflict_id,matter_id=matter_id,event_type="MatterFactConflictDismissed",payload={"factKey":conflict['fact_key']})
                return {"status":"dismissed"}

            definition=await conn.fetchrow(
                """SELECT fd.* FROM field_definitions fd
                   JOIN matters m ON m.organization_id=fd.organization_id
                   WHERE m.id=$1 AND fd.semantic_key=$2""",
                matter_id,conflict['fact_key'],
            )
            if not definition:
                raise ValueError("Canonical field definition is missing for this conflict")

            selected=None
            selected_value=None
            if fact_id:
                selected=await conn.fetchrow(
                    "SELECT id,field,fact,fact_key,field_definition_id,is_canonical,value_json FROM matter_facts WHERE id=$1 AND matter_id=$2",
                    fact_id,matter_id,
                )
                if selected: selected_value=(selected.get('value_json') if definition.get('repeatable') and selected.get('value_json') is not None else selected['fact'])
            elif value is not None:
                selected_value=value
                if definition.get('repeatable'):
                    import json
                    try: selected_value=json.loads(value) if isinstance(value,str) else value
                    except json.JSONDecodeError as exc: raise ValueError('Replacement value for a repeatable field must be a JSON array') from exc
                selected=await conn.fetchrow(
                    """INSERT INTO matter_facts(
                           organization_id,matter_id,field,fact,source,status,fact_key,label,
                           value_type,is_canonical,field_definition_id
                       ) VALUES(
                           autodraft_current_organization_id(),$1,$2,$3,'lawyer','accepted',$4,$2,$5,FALSE,$6
                       ) RETURNING id,field,fact,fact_key,field_definition_id,is_canonical""",
                    matter_id,definition['display_label'],value,conflict['fact_key'],definition['value_type'],definition['id'],
                )
            if not selected or selected_value is None:
                raise ValueError("A valid fact or replacement value is required")

            _value_row,projection=await self.legal_values.upsert_matter_value(
                conn,matter_id=matter_id,definition=definition,value=selected_value,
                source='lawyer',status='confirmed',
                provenance={'conflictId':str(conflict_id),'selectedLegacyFactId':str(selected['id'])},
            )
            await conn.execute(
                """UPDATE matter_facts
                   SET status=CASE WHEN id=$3 THEN 'accepted' ELSE 'superseded' END,updated_at=NOW()
                   WHERE matter_id=$1 AND fact_key=$2 AND is_canonical=FALSE""",
                matter_id,conflict['fact_key'],selected['id'],
            )
            await conn.execute(
                "UPDATE fact_conflicts SET status='resolved',resolution_fact_id=$1,resolved_at=NOW() WHERE id=$2",
                projection['id'],conflict_id,
            )
            await emit_domain_event(conn,aggregate_type="fact_conflict",aggregate_id=conflict_id,matter_id=matter_id,event_type="MatterFactConflictResolved",payload={"factKey":conflict['fact_key'],"factId":str(projection['id']),"canonicalStore":"matter_field_values"})
            return {"status":"resolved","factId":str(projection['id']),"fact":projection['fact']}

