from __future__ import annotations

import uuid
from fastapi import HTTPException

from ..config import Settings
from ..domain.facts import evaluate_expression
from ..models import MatterDocumentCreateRequest, MatterFactRequest
from ..repositories.documents import MatterDocumentRepository
from ..repositories.matters import MatterRepository
from ..repositories.contacts import ContactRepository
from ..repositories.fields import FieldRepository
from ..repositories.derived_rules import DerivedFactRuleRepository
from ..runtime import utc_iso
from ..storage import decode_private_docx, safe_filename


class MatterService:
    def __init__(self, repo: MatterRepository, documents: MatterDocumentRepository, settings: Settings, *, contacts: ContactRepository | None = None, fields: FieldRepository | None = None, derived_rules: DerivedFactRuleRepository | None = None):
        self.repo=repo; self.documents=documents; self.settings=settings
        self.contacts=contacts; self.fields=fields; self.derived_rules=derived_rules

    @staticmethod
    def parse_id(value: str, label: str = "matter") -> uuid.UUID:
        try: return uuid.UUID(value)
        except ValueError as exc: raise HTTPException(400, f"Invalid {label} ID") from exc

    @staticmethod
    def row(row):
        if not row: return None
        d=dict(row)
        for key in ("id","resolution_fact_id","field_definition_id","practice_area_id","stage_id"):
            if d.get(key) is not None: d[key]=str(d[key])
        for key in ("created_at","updated_at","confirmed_at","resolved_at"):
            if d.get(key) is not None: d[key]=utc_iso(d[key])
        return d

    @staticmethod
    def participant_row(r):
        return {"id":str(r['id']),"matterId":str(r['matter_id']),"contactId":str(r['contact_id']),"roleKey":r['role_key'],"displayRole":r['display_role'],"isClient":r['is_client'],"isPrimary":r['is_primary'],"representedByFirm":r['represented_by_firm'],"position":r['position'],"metadata":r['metadata'] or {},"contact":{"id":str(r['contact_id']),"contactType":r['contact_type'],"displayName":r['display_name'],"firstName":r['first_name'],"middleName":r['middle_name'],"lastName":r['last_name'],"companyName":r['company_name'],"email":r['email'],"phone":r['phone']}}

    @staticmethod
    def canonical_value_row(r):
        return {"id":str(r['id']),"fieldDefinitionId":str(r['field_definition_id']),"semanticKey":r['semantic_key'],"displayLabel":r['display_label'],"valueType":r['value_type'],"value":r.get('value'),"rawText":r['raw_text'],"source":r['source'],"status":r['status'],"provenance":r['provenance'] or {},"groupKey":r.get('group_key'),"groupLabel":r.get('group_label'),"groupRoleKey":r.get('group_role_key'),"updatedAt":utc_iso(r['updated_at'])}

    async def detail(self, matter_id: uuid.UUID):
        matter=await self.repo.get(matter_id)
        if not matter: raise HTTPException(404,"Matter not found")
        facts=[self.row(x) for x in await self.repo.facts(matter_id)]
        authorities=[self.row(x) for x in await self.repo.authorities(matter_id)]
        raw_conflicts=await self.repo.conflicts(matter_id)
        fact_by_id={str(item.get("id")):item for item in facts if item.get("id")}
        conflicts=[]
        for raw in raw_conflicts:
            item=self.row(raw);candidate_ids=[str(x) for x in (raw.get("candidate_fact_ids") or [])];item["candidates"]=[fact_by_id[x] for x in candidate_ids if x in fact_by_id];conflicts.append(item)
        documents=[self.row(x) for x in await self.documents.list(matter_id)]
        participants=[self.participant_row(x) for x in await self.contacts.participants(matter_id)] if self.contacts else []
        values=[self.canonical_value_row(x) for x in await self.fields.values('matter',matter_id)] if self.fields else []
        return {
            "id":str(matter["id"]),"title":matter["title"],"matterType":matter["matter_type"],"status":matter["status"],
            "referenceCode":matter.get('reference_code') or "","practiceAreaId":str(matter['practice_area_id']) if matter.get('practice_area_id') else None,
            "practiceAreaName":matter.get('practice_area_name'),"stageId":str(matter['stage_id']) if matter.get('stage_id') else None,"stageName":matter.get('stage_name'),
            "stageChangedAt":utc_iso(matter['stage_changed_at']) if matter.get('stage_changed_at') else None,
            "facts":facts,"canonicalValues":values,"participants":participants,"authorities":authorities,"conflicts":conflicts,"documents":documents,
        }

    async def add_fact(self, matter_id: uuid.UUID, req: MatterFactRequest):
        if not await self.repo.get(matter_id): raise HTTPException(404,"Matter not found")
        if not req.field.strip() or not req.fact.strip(): raise HTTPException(400,"Fact field and value are required")
        row=await self.repo.add_fact(matter_id,field=req.field.strip(),fact=req.fact.strip(),source=req.source,status=req.status)
        return self.row(row)

    async def create_document(self, matter_id: uuid.UUID, req: MatterDocumentCreateRequest):
        if not await self.repo.get(matter_id): raise HTTPException(404,"Matter not found")
        try: decode_private_docx(req.docx_base64,max_bytes=self.settings.matter_document_max_bytes)
        except OverflowError as exc: raise HTTPException(413,"Matter document is too large") from exc
        except ValueError as exc: raise HTTPException(400,str(exc)) from exc
        name=safe_filename(req.name,"Matter document.docx")
        return self.row(await self.documents.create(matter_id,name=name,docx_base64=req.docx_base64,mime_type=req.mime_type,source=req.source,metadata=req.metadata))

    async def derive(self, matter_id: uuid.UUID):
        if not self.fields:
            raise RuntimeError("Canonical field repository is not configured")
        values=await self.fields.values('matter',matter_id)
        canonical={
            str(item['semantic_key']):str(item.get('value') if item.get('value') is not None else '')
            for item in values
            if item.get('semantic_key') and item.get('status') in {'confirmed','accepted','derived'}
        }
        if not self.derived_rules:
            raise RuntimeError("Derived fact rule repository is not configured")
        rules=await self.derived_rules.enabled()
        results=[]
        for rule in rules:
            evaluated=evaluate_expression(rule["expression"],canonical)
            if not evaluated: continue
            written=await self.fields.upsert_matter_value_by_key(
                matter_id,rule['fact_key'],label=rule['label'],value=evaluated.value,
                value_type=rule['value_type'],source='derived',status='derived',
                provenance={'derivedFrom':list(evaluated.sources),'derivedRuleId':str(rule['id']) if rule.get('id') else None},
            )
            if not written: continue
            outcome,_definition,legacy=written
            if outcome.get('status') == 'conflict':
                # Derived values are proposals too; a conflicting confirmed legal
                # value remains authoritative until lawyer review resolves it.
                continue
            results.append(self.row(legacy));canonical[rule["fact_key"]]=evaluated.value
        return results

