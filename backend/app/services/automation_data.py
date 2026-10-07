from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ..db import Database
from ..domain.canonical_fields import display_value


@dataclass(frozen=True)
class AutomationDataSnapshot:
    data: dict[str, Any]
    conflicts: list[dict[str, Any]]
    canonical_keys: tuple[str, ...]


class AutomationDataService:
    def __init__(self, db: Database): self.db = db

    async def matter_data(self, matter_id: uuid.UUID | None) -> dict[str, Any]:
        if matter_id is None: return {}
        data: dict[str, Any] = {}
        values = await self.db.p().fetch(
            """SELECT fd.semantic_key,fd.value_type,fv.raw_text,fv.value_text,fv.value_number,fv.value_boolean,fv.value_date,fv.value_datetime,fv.value_json,
                      fv.value_contact_id,fv.value_matter_id,fv.value_document_id
               FROM matter_field_values fv JOIN field_definitions fd ON fd.id=fv.field_definition_id
               WHERE fv.matter_id=$1 AND fd.repeatable=FALSE AND fv.status IN ('confirmed','accepted','derived')""", matter_id,
        )
        for row in values:
            item=dict(row); data[row['semantic_key']] = display_value(item,row['value_type'])
        repeated = await self.db.p().fetch(
            """SELECT fd.semantic_key,fd.value_type,i.* FROM matter_field_value_items i
               JOIN field_definitions fd ON fd.id=i.field_definition_id
               WHERE i.matter_id=$1 AND i.status IN ('confirmed','accepted','derived')
               ORDER BY fd.semantic_key,i.position,i.id""", matter_id,
        )
        for row in repeated:
            item=dict(row); data.setdefault(row['semantic_key'],[]).append(display_value(item,row['value_type']))
        participants = await self.db.p().fetch(
            """SELECT mp.role_key,mp.display_role,mp.is_client,mp.is_primary,mp.position,
                      c.id AS contact_id,c.contact_type,c.display_name,c.first_name,c.middle_name,c.last_name,c.company_name,c.email,c.phone
               FROM matter_participants mp JOIN contacts c ON c.id=mp.contact_id
               WHERE mp.matter_id=$1 ORDER BY mp.position,mp.created_at""", matter_id,
        )
        by_role: dict[str,list[dict[str,Any]]] = {}
        people=[]
        for row in participants:
            contact={k:row[k] for k in ('contact_type','display_name','first_name','middle_name','last_name','company_name','email','phone')}
            contact.update({'id':str(row['contact_id']),'roleKey':row['role_key'],'displayRole':row['display_role'],'isClient':row['is_client'],'isPrimary':row['is_primary']})
            people.append(contact); by_role.setdefault(row['role_key'],[]).append(contact)
        data['participants']=people; data['participantsByRole']=by_role
        return data

    async def session_data(self, session_id: uuid.UUID | None) -> tuple[dict[str, Any], dict[str, Any]]:
        if session_id is None:return {},{}
        row=await self.db.p().fetchrow("SELECT answers,calculations FROM workflow_sessions WHERE id=$1",session_id)
        return (dict(row['answers'] or {}),dict(row['calculations'] or {})) if row else ({},{})

    async def build_snapshot(self, *, matter_id:uuid.UUID|None=None, workflow_session_id:uuid.UUID|None=None, overrides:dict[str,Any]|None=None) -> AutomationDataSnapshot:
        canonical=await self.matter_data(matter_id)
        answers,calculations=await self.session_data(workflow_session_id)
        data=dict(canonical)
        conflicts:list[dict[str,Any]]=[]

        def merge_proposed(values:dict[str,Any], source:str) -> None:
            for key,value in values.items():
                # Confirmed canonical matter data is the higher-trust tier. Proposed
                # workflow/calculation data may fill gaps but can never shadow it.
                if key in canonical:
                    if canonical[key] != value:
                        conflicts.append({
                            'semanticKey':str(key),'source':source,
                            'canonicalValue':canonical[key],'proposedValue':value,
                            'resolution':'canonical_retained',
                        })
                    continue
                data[key]=value

        merge_proposed(answers,'workflow_answer')
        # Workflow calculations live in a dedicated output namespace so they can
        # never silently shadow a confirmed canonical/answer semantic key.
        for key,value in calculations.items():
            namespaced=f'calculated.{key}'
            if namespaced in data:
                raise ValueError(f'Reserved calculation output key collides with legal data: {namespaced}')
            data[namespaced]=value
        # Explicit overrides are an authenticated staff/lawyer action and remain
        # the only generation-time tier allowed to supersede canonical data.
        if overrides:data.update(overrides)
        return AutomationDataSnapshot(data=data,conflicts=conflicts,canonical_keys=tuple(sorted(str(k) for k in canonical.keys())))

    async def build(self, *, matter_id:uuid.UUID|None=None, workflow_session_id:uuid.UUID|None=None, overrides:dict[str,Any]|None=None) -> dict[str,Any]:
        return (await self.build_snapshot(matter_id=matter_id,workflow_session_id=workflow_session_id,overrides=overrides)).data
