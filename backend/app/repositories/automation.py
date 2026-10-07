from __future__ import annotations

import base64
import binascii
import logging
import uuid
from typing import Any

from ..db import Database
from ..domain.template_automation import preflight_blueprint, validate_blueprint
from ..services.domain_events import emit_domain_event
from ..binary_store import BinaryObjectStore
from ..runtime_object_store import RuntimeObjectStoreError


log = logging.getLogger(__name__)


class AutomationRepository:
    def __init__(self, db: Database, objects: BinaryObjectStore | None = None): self.db=db; self.objects=objects

    async def draft(self, template_id:uuid.UUID):
        row=await self.db.p().fetchrow("SELECT blueprint,updated_at FROM template_automation_drafts WHERE template_id=$1",template_id)
        if row:return row
        if not await self.db.p().fetchval("SELECT 1 FROM templates WHERE id=$1 AND deleted_at IS NULL",template_id):return None
        return {'blueprint':{'bindings':[],'conditions':[],'repeaters':[]},'updated_at':None}

    async def bootstrap(self, template_id:uuid.UUID):
        if not await self.db.p().fetchval("SELECT 1 FROM templates WHERE id=$1 AND deleted_at IS NULL",template_id):return None
        variables=await self.db.p().fetch("SELECT variable_name,binding_id FROM variables WHERE template_id=$1 ORDER BY position",template_id)
        fields=await self.db.p().fetch("SELECT semantic_key,display_label,aliases FROM field_definitions WHERE active=TRUE")
        lookup:dict[str,str]={}
        for f in fields:
            for candidate in [f['semantic_key'],f['display_label'],*(f['aliases'] or [])]:
                key=str(candidate or '').strip().casefold()
                if key:lookup.setdefault(key,f['semantic_key'])
        bindings=[];unmapped=[]
        for var in variables:
            if not var['binding_id']:continue
            semantic=lookup.get(str(var['variable_name']).strip().casefold())
            if semantic:bindings.append({'controlTag':str(var['binding_id']),'semanticKey':semantic})
            else:unmapped.append({'controlTag':str(var['binding_id']),'variableName':var['variable_name']})
        blueprint={'bindings':bindings,'conditions':[],'repeaters':[],'retainControls':False}
        return {'blueprint':blueprint,'unmapped':unmapped}

    async def save_draft(self, template_id:uuid.UUID, blueprint:dict[str,Any]):
        bp=validate_blueprint(blueprint)
        async with self.db.p().transaction() as conn:
            template=await conn.fetchrow("SELECT organization_id FROM templates WHERE id=$1 AND deleted_at IS NULL",template_id)
            if not template:return None
            row=await conn.fetchrow("""INSERT INTO template_automation_drafts(template_id,organization_id,blueprint)
              VALUES($1,$2,$3::jsonb) ON CONFLICT(template_id) DO UPDATE SET blueprint=EXCLUDED.blueprint,updated_at=NOW() RETURNING *""",template_id,template['organization_id'],bp)
            await emit_domain_event(conn,aggregate_type='template',aggregate_id=template_id,event_type='TemplateAutomationDraftSaved',payload={'bindings':len(bp['bindings']),'conditions':len(bp['conditions']),'repeaters':len(bp['repeaters'])})
            return row

    async def current_snapshot(self, template_id:uuid.UUID):
        return await self.db.p().fetchrow("""SELECT t.id,t.organization_id,t.name,t.current_version,tv.id AS template_version_id,tv.version_number,tv.docx_base64,tv.docx_object_key,tv.snapshot_kind
          FROM templates t LEFT JOIN template_versions tv ON tv.template_id=t.id AND tv.version_number=t.current_version
          WHERE t.id=$1 AND t.deleted_at IS NULL""",template_id)

    async def preflight(self, template_id:uuid.UUID, blueprint:dict[str,Any]|None=None):
        snapshot=await self.current_snapshot(template_id)
        if not snapshot:return None
        if blueprint is None:
            draft=await self.draft(template_id);blueprint=draft['blueprint'] if draft else {'bindings':[],'conditions':[],'repeaters':[]}
        docx=None
        snapshot_error: str | None = None
        if snapshot.get('docx_object_key') and self.objects:
            try:
                docx=await self.objects.get_bytes(str(snapshot['docx_object_key']))
            except (RuntimeObjectStoreError, OSError) as exc:
                snapshot_error="The immutable DOCX snapshot could not be read from object storage."
                log.warning("Template automation preflight could not read snapshot for template %s", template_id, exc_info=exc)
        elif snapshot['docx_base64']:
            try:
                docx=base64.b64decode(snapshot['docx_base64'],validate=True)
            except (binascii.Error, ValueError) as exc:
                snapshot_error="The immutable DOCX snapshot contains invalid Base64 data."
                log.warning("Template automation preflight found invalid Base64 for template %s", template_id, exc_info=exc)
        if snapshot_error:
            result={"ready":False,"issues":[{"severity":"error","code":"TEMPLATE_SNAPSHOT_UNREADABLE","message":snapshot_error}],"tagCounts":{}}
        else:
            result=preflight_blueprint(blueprint,docx)
        result['templateVersion']=snapshot['version_number'];result['templateVersionId']=str(snapshot['template_version_id']) if snapshot['template_version_id'] else None
        return result

    async def publish(self, template_id:uuid.UUID):
        draft=await self.draft(template_id);snapshot=await self.current_snapshot(template_id)
        if not draft or not snapshot:return None
        if not snapshot['template_version_id']:raise ValueError('Template must have an immutable saved version before automation can be published')
        bp=validate_blueprint(draft['blueprint']);preflight=await self.preflight(template_id,bp)
        if not preflight or not preflight['ready']:
            raise ValueError('Template automation preflight failed')
        async with self.db.p().transaction() as conn:
            existing=await conn.fetchrow("SELECT * FROM template_automation_versions WHERE template_version_id=$1",snapshot['template_version_id'])
            if existing:
                if existing['blueprint'] != bp:raise ValueError('This immutable template version already has a different published automation blueprint; save a new template version first')
                return existing
            row=await conn.fetchrow("""INSERT INTO template_automation_versions(organization_id,template_id,template_version_id,blueprint,preflight)
              VALUES($1,$2,$3,$4::jsonb,$5::jsonb) RETURNING *""",snapshot['organization_id'],template_id,snapshot['template_version_id'],bp,preflight)
            await emit_domain_event(conn,aggregate_type='template',aggregate_id=template_id,event_type='TemplateAutomationPublished',payload={'templateVersion':snapshot['version_number'],'templateVersionId':str(snapshot['template_version_id'])})
            return row

    async def version(self, template_id:uuid.UUID, version_number:int):
        return await self.db.p().fetchrow("""SELECT tav.*,tv.version_number,tv.docx_base64,tv.docx_object_key,t.name AS template_name
          FROM template_automation_versions tav JOIN template_versions tv ON tv.id=tav.template_version_id JOIN templates t ON t.id=tav.template_id
          WHERE tav.template_id=$1 AND tv.version_number=$2""",template_id,version_number)

    async def by_template_version_id(self, version_id:uuid.UUID):
        return await self.db.p().fetchrow("""SELECT tav.*,tv.version_number,tv.docx_base64,tv.docx_object_key,t.name AS template_name
          FROM template_automation_versions tav JOIN template_versions tv ON tv.id=tav.template_version_id JOIN templates t ON t.id=tav.template_id
          WHERE tav.template_version_id=$1""",version_id)
