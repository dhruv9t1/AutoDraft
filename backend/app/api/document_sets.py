from __future__ import annotations
import uuid
from fastapi import APIRouter,Depends,HTTPException,Response,Query
from ..models import DocumentSetCreateRequest,DocumentSetUpdateRequest,GenerationRunCreateRequest,GenerationRunUpdateRequest
from ..repositories.document_sets import DocumentSetRepository
from ..runtime import api_auth,db,utc_iso
from ..pagination import decode_cursor,page_rows
router=APIRouter(tags=['document-sets']);repo=DocumentSetRepository(db)

def uid(v:str,label='record'):
    try:return uuid.UUID(v)
    except ValueError as exc:raise HTTPException(400,f'Invalid {label} ID') from exc

def item_data(i):return {'template_id':uid(i.template_id,'template'),'label':i.label.strip(),'position':i.position,'required':i.required,'metadata':i.metadata}
def summary(r):return {'id':str(r['id']),'name':r['name'],'description':r['description'],'practiceAreaId':str(r['practice_area_id']) if r['practice_area_id'] else None,'practiceAreaName':r.get('practice_area_name'),'matterType':r['matter_type'],'status':r['status'],'currentVersion':r['current_version'],'draftItemCount':int(r.get('draft_item_count') or 0),'createdAt':utc_iso(r['created_at']),'updatedAt':utc_iso(r['updated_at'])}
def draft_item(r):return {'id':str(r['id']),'templateId':str(r['template_id']),'templateName':r['template_name'],'label':r['label'],'position':r['position'],'required':r['required'],'metadata':r['metadata'] or {},'currentTemplateVersion':r['current_version'],'hasFullDocx':r['has_docx'],'snapshotKind':r['snapshot_kind']}
def version_row(r):return {'id':str(r['id']),'versionNumber':r['version_number'],'status':r['status'],'publishedAt':utc_iso(r['published_at'])}
def published_item(r):return {'id':str(r['id']),'templateId':str(r['template_id']),'templateName':r['template_name'],'templateVersionId':str(r['template_version_id']) if r['template_version_id'] else None,'templateVersion':r['template_version'],'label':r['label'],'position':r['position'],'required':r['required'],'metadata':r['metadata'] or {}}

@router.get('/api/document-sets',dependencies=[Depends(api_auth)])
async def list_sets(limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows=await repo.list(limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {'documentSets':[summary(r) for r in items],'nextCursor':next_cursor}
@router.post('/api/document-sets',dependencies=[Depends(api_auth)])
async def create_set(req:DocumentSetCreateRequest):
    if not req.name.strip():raise HTTPException(400,'Document set name is required')
    try:row=await repo.create(name=req.name.strip(),description=req.description.strip(),practice_area_id=uid(req.practice_area_id,'practice area') if req.practice_area_id else None,matter_type=req.matter_type.strip(),items=[item_data(i) for i in req.items])
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not row:raise HTTPException(404,'Practice area not found')
    detail=await repo.get(row['id']);return {'documentSet':summary(detail[0]),'draftItems':[draft_item(x) for x in detail[1]],'versions':[]}
@router.get('/api/document-sets/{set_id}',dependencies=[Depends(api_auth)])
async def get_set(set_id:str):
    detail=await repo.get(uid(set_id,'document set'))
    if not detail:raise HTTPException(404,'Document set not found')
    row,drafts,versions=detail;return {'documentSet':summary(row),'draftItems':[draft_item(x) for x in drafts],'versions':[version_row(x) for x in versions]}
@router.patch('/api/document-sets/{set_id}',dependencies=[Depends(api_auth)])
async def update_set(set_id:str,req:DocumentSetUpdateRequest):
    items=[item_data(i) for i in req.items] if req.items is not None else None
    practice_area_set='practice_area_id' in req.model_fields_set
    try:row=await repo.update(uid(set_id,'document set'),name=req.name.strip() if req.name is not None else None,description=req.description.strip() if req.description is not None else None,practice_area_id=uid(req.practice_area_id,'practice area') if req.practice_area_id else None,practice_area_set=practice_area_set,matter_type=req.matter_type.strip() if req.matter_type is not None else None,items=items)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not row:raise HTTPException(404,'Document set or practice area not found')
    return await get_set(set_id)
@router.post('/api/document-sets/{set_id}/publish',dependencies=[Depends(api_auth)])
async def publish_set(set_id:str):
    try:row=await repo.publish(uid(set_id,'document set'))
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    if not row:raise HTTPException(404,'Document set not found')
    return version_row(row)
@router.get('/api/document-sets/{set_id}/versions/{version}',dependencies=[Depends(api_auth)])
async def get_version(set_id:str,version:int):
    detail=await repo.version(uid(set_id,'document set'),version)
    if not detail:raise HTTPException(404,'Document set version not found')
    row,items=detail;return {'version':version_row(row),'items':[published_item(x) for x in items]}
@router.delete('/api/document-sets/{set_id}',status_code=204,dependencies=[Depends(api_auth)])
async def retire_set(set_id:str):
    if not await repo.retire(uid(set_id,'document set')):raise HTTPException(404,'Document set not found')
    return Response(status_code=204)
@router.post('/api/generation-runs',dependencies=[Depends(api_auth)])
async def start_run(req:GenerationRunCreateRequest):
    row=await repo.start_generation(uid(req.matter_id,'matter'),uid(req.document_set_version_id,'document set version'),req.selected_items)
    if not row:raise HTTPException(404,'Matter or document set version not found')
    return {'id':str(row['id']),'matterId':str(row['matter_id']),'documentSetVersionId':str(row['document_set_version_id']),'status':row['status'],'selectedItems':row['selected_items'],'createdAt':utc_iso(row['created_at'])}
@router.patch('/api/generation-runs/{run_id}',dependencies=[Depends(api_auth)])
async def advance_run(run_id:str,req:GenerationRunUpdateRequest):
    try:row=await repo.advance_generation(uid(run_id,'generation run'),req.status,req.metadata)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    if not row:raise HTTPException(404,'Generation run not found')
    return {'id':str(row['id']),'matterId':str(row['matter_id']),'documentSetVersionId':str(row['document_set_version_id']) if row['document_set_version_id'] else None,'status':row['status'],'selectedItems':row['selected_items'],'metadata':row['metadata'],'updatedAt':utc_iso(row['updated_at'])}
