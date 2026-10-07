from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database
from ..domain.workflows import WorkflowAnswerValidationError, evaluate_workflow, validate_workflow_answers, validate_workflow_definition
from ..services.domain_events import emit_domain_event
from ..services.automation_data import AutomationDataService


class WorkflowRepository:
    def __init__(self, db: Database):
        self.db=db;self.data=AutomationDataService(db)

    async def list(self, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None):
        limit=max(1,min(int(limit),200));cursor_sql="" if cursor_updated_at is None else " AND (w.updated_at,w.id)<($1,$2)"
        args=[limit+1] if cursor_updated_at is None else [cursor_updated_at,cursor_id,limit+1];limit_ref="$1" if cursor_updated_at is None else "$3"
        return await self.db.p().fetch(f"""SELECT w.*,pa.name AS practice_area_name,
          (SELECT COUNT(*) FROM workflow_versions v WHERE v.workflow_id=w.id) AS version_count
          FROM workflows w LEFT JOIN practice_areas pa ON pa.id=w.practice_area_id
          WHERE w.status<>'retired' {cursor_sql} ORDER BY w.updated_at DESC,w.id DESC LIMIT {limit_ref}""",*args)

    async def get(self, workflow_id:uuid.UUID):
        row=await self.db.p().fetchrow("SELECT * FROM workflows WHERE id=$1",workflow_id)
        if not row:return None
        versions=await self.db.p().fetch("SELECT id,version_number,status,published_at,created_at FROM workflow_versions WHERE workflow_id=$1 ORDER BY version_number DESC",workflow_id)
        latest=await self.db.p().fetchrow("SELECT * FROM workflow_versions WHERE workflow_id=$1 ORDER BY version_number DESC LIMIT 1",workflow_id)
        return row,versions,latest

    async def create(self, data:dict[str,Any]):
        definition=validate_workflow_definition(data['definition'])
        async with self.db.p().transaction() as conn:
            if data.get('practice_area_id') and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1",data['practice_area_id']):return None
            row=await conn.fetchrow("""INSERT INTO workflows(organization_id,name,description,audience,practice_area_id,matter_type,current_version)
              VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,1) RETURNING *""",
              data['name'],data['description'],data['audience'],data.get('practice_area_id'),data['matter_type'])
            version=await conn.fetchrow("INSERT INTO workflow_versions(organization_id,workflow_id,version_number,status,definition) VALUES($1,$2,1,'draft',$3::jsonb) RETURNING *",row['organization_id'],row['id'],definition)
            await emit_domain_event(conn,aggregate_type='workflow',aggregate_id=row['id'],event_type='WorkflowCreated',payload={'name':row['name'],'version':1})
            return row,version

    async def update(self, workflow_id:uuid.UUID, data:dict[str,Any], fields_set:set[str]):
        async with self.db.p().transaction() as conn:
            current=await conn.fetchrow("SELECT * FROM workflows WHERE id=$1 FOR UPDATE",workflow_id)
            if not current:return None
            practice=data.get('practice_area_id') if 'practice_area_id' in fields_set else current['practice_area_id']
            if practice and not await conn.fetchval("SELECT 1 FROM practice_areas WHERE id=$1",practice):return None
            row=await conn.fetchrow("""UPDATE workflows SET name=$1,description=$2,audience=$3,practice_area_id=$4,matter_type=$5,status='draft',updated_at=NOW() WHERE id=$6 RETURNING *""",
              data.get('name',current['name']),data.get('description',current['description']),data.get('audience',current['audience']),practice,data.get('matter_type',current['matter_type']),workflow_id)
            latest=await conn.fetchrow("SELECT * FROM workflow_versions WHERE workflow_id=$1 ORDER BY version_number DESC LIMIT 1 FOR UPDATE",workflow_id)
            definition=data.get('definition') if 'definition' in fields_set else (latest['definition'] if latest else {'pages':[],'calculations':[]})
            definition=validate_workflow_definition(definition)
            if latest and latest['status']=='draft':
                version=await conn.fetchrow("UPDATE workflow_versions SET definition=$1::jsonb WHERE id=$2 RETURNING *",definition,latest['id'])
            else:
                number=int(latest['version_number'] if latest else 0)+1
                version=await conn.fetchrow("INSERT INTO workflow_versions(organization_id,workflow_id,version_number,status,definition) VALUES($1,$2,$3,'draft',$4::jsonb) RETURNING *",current['organization_id'],workflow_id,number,definition)
                await conn.execute("UPDATE workflows SET current_version=$1 WHERE id=$2",number,workflow_id)
            await emit_domain_event(conn,aggregate_type='workflow',aggregate_id=workflow_id,event_type='WorkflowDraftUpdated',payload={'version':version['version_number']})
            return row,version

    async def publish(self, workflow_id:uuid.UUID):
        async with self.db.p().transaction() as conn:
            latest=await conn.fetchrow("SELECT * FROM workflow_versions WHERE workflow_id=$1 ORDER BY version_number DESC LIMIT 1 FOR UPDATE",workflow_id)
            if not latest:return None
            validate_workflow_definition(latest['definition'])
            if latest['status']=='published':return latest
            await conn.execute("UPDATE workflow_versions SET status='retired' WHERE workflow_id=$1 AND status='published'",workflow_id)
            row=await conn.fetchrow("UPDATE workflow_versions SET status='published',published_at=NOW() WHERE id=$1 RETURNING *",latest['id'])
            await conn.execute("UPDATE workflows SET status='published',current_version=$1,updated_at=NOW() WHERE id=$2",row['version_number'],workflow_id)
            await emit_domain_event(conn,aggregate_type='workflow',aggregate_id=workflow_id,event_type='WorkflowPublished',payload={'version':row['version_number']})
            return row

    async def create_session(self, workflow_id:uuid.UUID, *, matter_id:uuid.UUID|None, expires_days:int, metadata:dict[str,Any]):
        token=secrets.token_urlsafe(32);token_hash=hashlib.sha256(token.encode()).hexdigest();expires=datetime.now(timezone.utc)+timedelta(days=expires_days)
        async with self.db.p().transaction() as conn:
            workflow=await conn.fetchrow("SELECT * FROM workflows WHERE id=$1 AND status='published'",workflow_id)
            if not workflow:return None
            version=await conn.fetchrow("SELECT * FROM workflow_versions WHERE workflow_id=$1 AND status='published' ORDER BY version_number DESC LIMIT 1",workflow_id)
            if not version:return None
            if matter_id and not await conn.fetchval("SELECT 1 FROM matters WHERE id=$1",matter_id):return None
            row=await conn.fetchrow("""INSERT INTO workflow_sessions(organization_id,workflow_version_id,matter_id,metadata,expires_at)
              VALUES($1,$2,$3,$4::jsonb,$5) RETURNING *""",workflow['organization_id'],version['id'],matter_id,metadata,expires)
            if workflow['audience'] in {'client','both'}:
                await conn.execute("INSERT INTO public_workflow_tokens(token_hash,organization_id,session_id,expires_at) VALUES($1,$2,$3,$4)",token_hash,workflow['organization_id'],row['id'],expires)
            await emit_domain_event(conn,aggregate_type='workflow_session',aggregate_id=row['id'],matter_id=matter_id,event_type='WorkflowSessionStarted',payload={'workflowId':str(workflow_id),'version':version['version_number']})
            return row,workflow,version,(token if workflow['audience'] in {'client','both'} else None)


    async def list_sessions(self, *, limit:int=50, cursor_updated_at=None, cursor_id:uuid.UUID|None=None, workflow_id:uuid.UUID|None=None, matter_id:uuid.UUID|None=None, status:str|None=None):
        limit=max(1,min(int(limit),200));args=[];clauses=[]
        if workflow_id is not None:
            args.append(workflow_id);clauses.append(f"w.id=${len(args)}")
        if matter_id is not None:
            args.append(matter_id);clauses.append(f"s.matter_id=${len(args)}")
        if status:
            args.append(status);clauses.append(f"s.status=${len(args)}")
        if cursor_updated_at is not None:
            args.extend([cursor_updated_at,cursor_id]);clauses.append(f"(s.updated_at,s.id)<(${len(args)-1},${len(args)})")
        args.append(limit+1);where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
        return await self.db.p().fetch(f"""SELECT s.id,s.workflow_version_id,s.matter_id,s.status,s.current_page,s.expires_at,s.completed_at,s.created_at,s.updated_at,
                   v.version_number,w.id AS workflow_id,w.name AS workflow_name,w.audience
              FROM workflow_sessions s JOIN workflow_versions v ON v.id=s.workflow_version_id JOIN workflows w ON w.id=v.workflow_id
              {where} ORDER BY s.updated_at DESC,s.id DESC LIMIT ${len(args)}""",*args)

    async def session(self, session_id:uuid.UUID):
        return await self.db.p().fetchrow("""SELECT s.*,v.definition,v.version_number,w.id AS workflow_id,w.name,w.audience
          FROM workflow_sessions s JOIN workflow_versions v ON v.id=s.workflow_version_id JOIN workflows w ON w.id=v.workflow_id WHERE s.id=$1""",session_id)

    async def public_session(self, raw_token:str):
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest()
        async with self.db.raw_pool().acquire() as conn:
            lookup=await conn.fetchrow("SELECT organization_id,session_id,expires_at FROM public_workflow_tokens WHERE token_hash=$1",token_hash)
            if not lookup:return None
            if lookup['expires_at'] and lookup['expires_at']<datetime.now(timezone.utc):return {'expired':True}
            async with conn.transaction():
                await conn.execute("SELECT set_config('autodraft.organization_id',$1,true)",str(lookup['organization_id']))
                row=await conn.fetchrow("""SELECT s.*,v.definition,v.version_number,w.id AS workflow_id,w.name,w.audience
                  FROM workflow_sessions s JOIN workflow_versions v ON v.id=s.workflow_version_id JOIN workflows w ON w.id=v.workflow_id WHERE s.id=$1""",lookup['session_id'])
                return dict(row) if row else None

    async def update_session(self, session_id:uuid.UUID, *, answers:dict[str,Any], current_page:str|None, metadata:dict[str,Any]):
        current=await self.session(session_id)
        if not current or current['status']!='in_progress':return None
        reserved={'authoritativeGenerationApproved','authoritativeGenerationApprovedBy','authoritativeGenerationApprovedAt'}
        blocked=sorted(reserved.intersection(metadata.keys()))
        if blocked:
            raise WorkflowAnswerValidationError([{'path':f'metadata.{key}','semanticKey':key,'reason':'reserved_metadata','message':'This review field may only be set by the lawyer approval endpoint'} for key in blocked])
        patch=validate_workflow_answers(current['definition'],answers)
        merged=dict(current['answers'] or {});merged.update(patch)
        merged=validate_workflow_answers(current['definition'],merged)
        base=await self.data.matter_data(current['matter_id']);base.update(merged)
        evaluation=evaluate_workflow(current['definition'],base)
        row=await self.db.p().fetchrow("""UPDATE workflow_sessions SET answers=$1::jsonb,calculations=$2::jsonb,current_page=COALESCE($3,current_page),metadata=metadata||$4::jsonb,updated_at=NOW() WHERE id=$5 AND status='in_progress' RETURNING *""",merged,evaluation.calculations,current_page,metadata,session_id)
        return row,current,evaluation

    async def approve_for_generation(self, session_id: uuid.UUID, *, user_id: str):
        current=await self.session(session_id)
        if not current or current['status']!='completed':return None
        metadata={
            'authoritativeGenerationApproved':True,
            'authoritativeGenerationApprovedBy':str(user_id),
            'authoritativeGenerationApprovedAt':datetime.now(timezone.utc).isoformat(),
        }
        return await self.db.p().fetchrow(
            "UPDATE workflow_sessions SET metadata=metadata||$1::jsonb,updated_at=NOW() WHERE id=$2 AND status='completed' RETURNING *",
            metadata,session_id,
        )

    async def complete_session(self, session_id:uuid.UUID):
        current=await self.session(session_id)
        if not current or current['status']!='in_progress':return None
        answers=validate_workflow_answers(current['definition'],dict(current['answers'] or {}))
        base=await self.data.matter_data(current['matter_id']);base.update(answers)
        evaluation=evaluate_workflow(current['definition'],base)
        if not evaluation.complete:return {'missing':evaluation.missing_required,'evaluation':evaluation}
        async with self.db.p().transaction() as conn:
            row=await conn.fetchrow("UPDATE workflow_sessions SET calculations=$1::jsonb,status='completed',completed_at=NOW(),updated_at=NOW() WHERE id=$2 RETURNING *",evaluation.calculations,session_id)
            await emit_domain_event(conn,aggregate_type='workflow_session',aggregate_id=session_id,matter_id=current['matter_id'],event_type='WorkflowSessionCompleted',payload={'workflowId':str(current['workflow_id'])})
            return {'row':row,'evaluation':evaluation}
