from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query

from ..domain.template_automation import TemplateAutomationError, validate_blueprint
from ..auth import require_role
from ..permissions import require_permission
from ..models import HeadlessGenerationRequest, TemplateAutomationSaveRequest
from ..repositories.automation import AutomationRepository
from ..runtime import api_auth, db, utc_iso, binary_object_store, runtime_state, settings
from ..services.generation_service import GenerationService
from ..pagination import decode_cursor, page_rows

router=APIRouter(tags=['automation'])
repo=AutomationRepository(db,binary_object_store);generation=GenerationService(db,binary_object_store)

def uid(value:str|None,label:str)->uuid.UUID|None:
    if value is None:return None
    try:return uuid.UUID(value)
    except ValueError as exc:raise HTTPException(400,f'Invalid {label} ID') from exc

@router.get('/api/templates/{template_id}/automation',dependencies=[Depends(api_auth)])
async def get_automation(template_id:str):
    row=await repo.draft(uid(template_id,'template'))
    if not row:raise HTTPException(404,'Template not found')
    return {'blueprint':row['blueprint'],'updatedAt':utc_iso(row['updated_at']) if row['updated_at'] else None}

@router.post('/api/templates/{template_id}/automation/bootstrap',dependencies=[Depends(api_auth)])
async def bootstrap_automation(template_id:str):
    result=await repo.bootstrap(uid(template_id,'template'))
    if not result:raise HTTPException(404,'Template not found')
    return result

@router.put('/api/templates/{template_id}/automation',dependencies=[Depends(api_auth)])
async def save_automation(template_id:str,req:TemplateAutomationSaveRequest):
    try:row=await repo.save_draft(uid(template_id,'template'),req.blueprint)
    except TemplateAutomationError as exc:raise HTTPException(422,str(exc)) from exc
    if not row:raise HTTPException(404,'Template not found')
    return {'blueprint':row['blueprint'],'updatedAt':utc_iso(row['updated_at'])}

@router.post('/api/templates/{template_id}/automation/preflight',dependencies=[Depends(api_auth)])
async def preflight_automation(template_id:str,req:TemplateAutomationSaveRequest|None=None):
    try:result=await repo.preflight(uid(template_id,'template'),validate_blueprint(req.blueprint) if req else None)
    except TemplateAutomationError as exc:raise HTTPException(422,str(exc)) from exc
    if not result:raise HTTPException(404,'Template not found')
    return result

@router.post('/api/templates/{template_id}/automation/publish',dependencies=[Depends(api_auth)])
async def publish_automation(template_id:str):
    try:row=await repo.publish(uid(template_id,'template'))
    except (ValueError,TemplateAutomationError) as exc:raise HTTPException(409,str(exc)) from exc
    if not row:raise HTTPException(404,'Template not found')
    return {'id':str(row['id']),'templateId':str(row['template_id']),'templateVersionId':str(row['template_version_id']),'blueprint':row['blueprint'],'preflight':row['preflight'],'createdAt':utc_iso(row['created_at'])}

@router.get('/api/templates/{template_id}/versions/{version}/automation',dependencies=[Depends(api_auth)])
async def version_automation(template_id:str,version:int):
    row=await repo.version(uid(template_id,'template'),version)
    if not row:raise HTTPException(404,'Published automation for this template version was not found')
    return {'id':str(row['id']),'templateId':str(row['template_id']),'templateVersionId':str(row['template_version_id']),'templateVersion':row['version_number'],'blueprint':row['blueprint'],'preflight':row['preflight'],'createdAt':utc_iso(row['created_at'])}

@router.post('/api/generation/headless')
async def headless_generation(req:HeadlessGenerationRequest,request:Request,ctx=Depends(api_auth)):
    if req.data_overrides:
        require_role(ctx,'lawyer');require_permission(ctx,'generation.override')
        if not (req.override_reason or '').strip():raise HTTPException(422,'overrideReason is required when dataOverrides are supplied')
    if not (req.idempotency_key or '').strip():
        raise HTTPException(422,'idempotencyKey is required for every persisted headless generation request')
    if req.save_to_matter:
        job=await runtime_state.create_job('generation',owner_user_id=ctx.user_id,payload={
            'request':req.model_dump(by_alias=True),'actorUserId':ctx.user_id,'actorRole':ctx.role,
        },ttl_seconds=settings.generation_job_ttl_seconds)
        return {'jobId':str(job['id']),'status':'queued','queued':True}
    try:
        return await generation.generate(
            matter_id=uid(req.matter_id,'matter'),template_id=uid(req.template_id,'template'),template_version=req.template_version,
            document_set_version_id=uid(req.document_set_version_id,'document set version'),workflow_session_id=uid(req.workflow_session_id,'workflow session'),
            generation_run_id=uid(req.generation_run_id,'generation run'),overrides=req.data_overrides,save_to_matter=False,
            idempotency_key=req.idempotency_key,override_reason=(req.override_reason or '').strip() or None,override_actor_user_id=ctx.user_id,override_actor_role=ctx.role)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc

@router.get('/api/generation/jobs/{job_id}')
async def generation_job(job_id:str,request:Request,ctx=Depends(api_auth)):
    job=await runtime_state.get_job(job_id,owner_user_id=ctx.user_id)
    if not job or job.get('job_type')!='generation':raise HTTPException(404,'Generation job not found')
    payload={'jobId':job_id,'status':job['status'],'error':job.get('error'),'createdAt':utc_iso(job['created_at']),'updatedAt':utc_iso(job['updated_at'])}
    if job['status']=='completed':payload['result']=job.get('result') or {}
    return payload

@router.delete('/api/generation/jobs/{job_id}',status_code=204)
async def cancel_generation_job(job_id:str,ctx=Depends(api_auth)):
    job=await runtime_state.get_job(job_id,owner_user_id=ctx.user_id,hydrate=False)
    if not job or job.get('job_type')!='generation':raise HTTPException(404,'Generation job not found')
    await runtime_state.request_cancel(job_id,owner_user_id=ctx.user_id)
    return Response(status_code=204)


@router.get('/api/generation/jobs/{job_id}/events')
async def generation_job_events(job_id:str,after:int=Query(default=0,ge=0),ctx=Depends(api_auth)):
    job=await runtime_state.get_job(job_id,owner_user_id=ctx.user_id,hydrate=False)
    if not job or job.get('job_type')!='generation':raise HTTPException(404,'Generation job not found')
    rows=await runtime_state.events_after(job_id,after,owner_user_id=ctx.user_id)
    return {'events':[{'id':int(r['id']),'type':r['event_type'],'data':r.get('data') or {},'createdAt':utc_iso(r['created_at'])} for r in rows]}

@router.get('/api/generation/artifacts')
async def list_generation_artifacts(matterId:str|None=Query(default=None),limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None),ctx=Depends(api_auth)):
    t,i=decode_cursor(cursor);args=[];clauses=[]
    if matterId:
        args.append(uid(matterId,'matter'));clauses.append(f'matter_id=${len(args)}')
    if t is not None:
        args.extend([t,i]);clauses.append(f'(created_at,id)<(${len(args)-1},${len(args)})')
    args.append(limit+1);where=(' WHERE '+' AND '.join(clauses)) if clauses else ''
    sql=("SELECT id,matter_id,generation_run_id,workflow_session_id,template_id,template_version_id,"
         "filename,mime_type,sha256,size_bytes,metadata,created_at FROM generation_artifacts"+where+
         f" ORDER BY created_at DESC,id DESC LIMIT ${len(args)}")
    rows=await db.p().fetch(sql,*args)
    items,next_cursor=page_rows(rows,limit,timestamp_field='created_at')
    return {'artifacts':[{'id':str(r['id']),'matterId':str(r['matter_id']) if r['matter_id'] else None,'generationRunId':str(r['generation_run_id']) if r['generation_run_id'] else None,
        'workflowSessionId':str(r['workflow_session_id']) if r['workflow_session_id'] else None,'templateId':str(r['template_id']),'templateVersionId':str(r['template_version_id']),
        'filename':r['filename'],'mimeType':r['mime_type'],'sha256':r['sha256'],'sizeBytes':r.get('size_bytes') if hasattr(r,'get') else r['size_bytes'],'metadata':r['metadata'] or {},
        'createdAt':utc_iso(r['created_at']),'downloadUrl':f"/api/generation/artifacts/{r['id']}/content"} for r in items],'nextCursor':next_cursor}

@router.get('/api/generation/artifacts/{artifact_id}/content')
async def generation_artifact_content(artifact_id:str,ctx=Depends(api_auth)):
    aid=uid(artifact_id,'artifact')
    row=await db.p().fetchrow('SELECT filename,mime_type,object_key,docx_base64 FROM generation_artifacts WHERE id=$1',aid)
    if not row:raise HTTPException(404,'Generation artifact not found')
    if row['object_key']:
        raw=await binary_object_store.get_bytes(str(row['object_key']))
    elif row['docx_base64']:
        import base64
        raw=base64.b64decode(row['docx_base64'],validate=True)
    else:raise HTTPException(410,'Generation artifact content is unavailable')
    return Response(content=raw,media_type=row['mime_type'],headers={'Content-Disposition':f'attachment; filename="{row["filename"]}"'})

