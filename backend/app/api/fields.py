from __future__ import annotations
import re,uuid
from fastapi import APIRouter,Depends,HTTPException,Query
from ..models import FieldGroupCreateRequest,FieldDefinitionCreateRequest,FieldDefinitionUpdateRequest,FieldValueUpsertRequest
from ..repositories.fields import FieldRepository
from ..runtime import api_auth,db,utc_iso
from ..auth import require_role
from ..pagination import decode_cursor,encode_cursor
router=APIRouter(tags=['fields']);repo=FieldRepository(db)

async def admin_auth(ctx=Depends(api_auth)):
    require_role(ctx, 'admin')
    return ctx

def uid(v:str,label='record'):
    try:return uuid.UUID(v)
    except ValueError as exc:raise HTTPException(400,f'Invalid {label} ID') from exc

def semkey(v:str)->str:return re.sub(r'[^a-z0-9_.\[\]-]+','_',v.strip().lower()).strip('_')
def group_row(r):return {'id':str(r['id']),'key':r['key'],'label':r['label'],'entityScope':r['entity_scope'],'roleKey':r['role_key'],'practiceAreaId':str(r['practice_area_id']) if r['practice_area_id'] else None,'practiceAreaName':r.get('practice_area_name') if hasattr(r,'get') else None,'position':r['position']}
def definition(r):
    return {'id':str(r['id']),'semanticKey':r['semantic_key'],'displayLabel':r['display_label'],'description':r['description'],'entityScope':r['entity_scope'],'valueType':r['value_type'],'repeatable':r['repeatable'],'required':r['required'],'validation':r['validation'] or {},'formatting':r['formatting'] or {},'options':r['options'] or [],'aliases':r['aliases'] or [],'groupId':str(r['group_id']) if r['group_id'] else None,'groupKey':r.get('group_key') if hasattr(r,'get') else None,'groupLabel':r.get('group_label') if hasattr(r,'get') else None,'groupRoleKey':r.get('group_role_key') if hasattr(r,'get') else None,'practiceAreaId':str(r['practice_area_id']) if r['practice_area_id'] else None,'matterType':r['matter_type'],'position':r['position'],'active':r['active']}
def value(r):
    payload={'id':str(r['id']),'fieldDefinitionId':str(r['field_definition_id']),'semanticKey':r['semantic_key'],'displayLabel':r['display_label'],'valueType':r['value_type'],'repeatable':bool(r.get('repeatable')),'value':r.get('value'),'rawText':r.get('raw_text'),'source':r['source'],'status':r['status'],'provenance':r['provenance'] or {},'groupKey':r.get('group_key'),'groupLabel':r.get('group_label'),'groupRoleKey':r.get('group_role_key'),'updatedAt':utc_iso(r['updated_at'])}
    if r.get('repeatable'):payload['items']=r.get('items') or []
    return payload

@router.get('/api/field-groups',dependencies=[Depends(api_auth)])
async def list_groups():return {'groups':[group_row(r) for r in await repo.groups()]}
@router.post('/api/field-groups',dependencies=[Depends(admin_auth)])
async def create_group(req:FieldGroupCreateRequest):
    k=semkey(req.key);label=req.label.strip();aid=uid(req.practice_area_id,'practice area') if req.practice_area_id else None
    if not k or not label:raise HTTPException(400,'key and label are required')
    row=await repo.create_group({'key':k,'label':label,'entity_scope':req.entity_scope,'role_key':semkey(req.role_key) if req.role_key else None,'practice_area_id':aid,'position':req.position})
    if not row:raise HTTPException(404,'Practice area not found')
    return group_row(row)

@router.get('/api/field-migration-errors',dependencies=[Depends(admin_auth)])
async def list_field_migration_errors(limit:int=Query(default=200,ge=1,le=1000)):
    rows=await repo.migration_errors(limit=limit)
    return {'errors':[{'id':str(r['id']),'parentType':r['parent_type'],'parentId':str(r['parent_id']),'fieldDefinitionId':str(r['field_definition_id']),'semanticKey':r.get('semantic_key'),'displayLabel':r.get('display_label'),'sourceValueId':str(r['source_value_id']) if r['source_value_id'] else None,'rawText':r['raw_text'],'targetValueType':r['target_value_type'],'reason':r['reason'],'createdAt':utc_iso(r['created_at'])} for r in rows]}

@router.get('/api/field-definitions',dependencies=[Depends(api_auth)])
async def list_definitions(scope:str|None=Query(default=None),practiceAreaId:str|None=Query(default=None),matterType:str|None=Query(default=None),includeInactive:bool=False):
    aid=uid(practiceAreaId,'practice area') if practiceAreaId else None
    return {'fields':[definition(r) for r in await repo.definitions(scope=scope,practice_area_id=aid,matter_type=matterType,include_inactive=includeInactive)]}

@router.post('/api/field-definitions',dependencies=[Depends(admin_auth)])
async def create_definition(req:FieldDefinitionCreateRequest):
    key=semkey(req.semantic_key);label=req.display_label.strip()
    if not key or not label:raise HTTPException(400,'semanticKey and displayLabel are required')
    data=req.model_dump();data['semantic_key']=key;data['display_label']=label
    data['group_id']=uid(req.group_id,'field group') if req.group_id else None;data['practice_area_id']=uid(req.practice_area_id,'practice area') if req.practice_area_id else None
    try:row=await repo.create_definition(data)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not row:raise HTTPException(404,'Field group or practice area not found')
    return definition(row)

@router.patch('/api/field-definitions/{field_id}',dependencies=[Depends(admin_auth)])
async def update_definition(field_id:str,req:FieldDefinitionUpdateRequest):
    data=req.model_dump(exclude_unset=True)
    if 'group_id' in data and data['group_id'] is not None:data['group_id']=uid(data['group_id'],'field group')
    if 'practice_area_id' in data and data['practice_area_id'] is not None:data['practice_area_id']=uid(data['practice_area_id'],'practice area')
    try:row=await repo.update_definition(uid(field_id,'field'),data)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not row:raise HTTPException(404,'Field definition not found')
    return definition(row)

@router.get('/api/matters/{matter_id}/field-values',dependencies=[Depends(api_auth)])
async def matter_values(matter_id:str,limit:int=Query(default=100,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows,page=await repo.values_page('matter',uid(matter_id,'matter'),limit=limit,cursor_updated_at=t,cursor_id=i)
    next_cursor=encode_cursor(page[limit-1]['effective_updated_at'],page[limit-1]['field_definition_id']) if len(page)>limit else None
    return {'values':[value(r) for r in rows],'nextCursor':next_cursor}
@router.put('/api/matters/{matter_id}/field-values/{field_id}',dependencies=[Depends(api_auth)])
async def put_matter_value(matter_id:str,field_id:str,req:FieldValueUpsertRequest):
    try:result=await repo.upsert_matter_value(uid(matter_id,'matter'),uid(field_id,'field'),value=req.value,source=req.source,status=req.status,provenance=req.provenance)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not result:raise HTTPException(404,'Matter or field definition not found')
    row,_=result;rows=await repo.values('matter',uid(matter_id,'matter'));found=next((r for r in rows if r['id']==row['id']),None);return value(found)

@router.get('/api/contacts/{contact_id}/field-values',dependencies=[Depends(api_auth)])
async def contact_values(contact_id:str,limit:int=Query(default=100,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows,page=await repo.values_page('contact',uid(contact_id,'contact'),limit=limit,cursor_updated_at=t,cursor_id=i)
    next_cursor=encode_cursor(page[limit-1]['effective_updated_at'],page[limit-1]['field_definition_id']) if len(page)>limit else None
    return {'values':[value(r) for r in rows],'nextCursor':next_cursor}
@router.put('/api/contacts/{contact_id}/field-values/{field_id}',dependencies=[Depends(api_auth)])
async def put_contact_value(contact_id:str,field_id:str,req:FieldValueUpsertRequest):
    try:result=await repo.upsert_contact_value(uid(contact_id,'contact'),uid(field_id,'field'),value=req.value,source=req.source,status=req.status,provenance=req.provenance)
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    if not result:raise HTTPException(404,'Contact or field definition not found')
    row,_=result;rows=await repo.values('contact',uid(contact_id,'contact'));found=next((r for r in rows if r['id']==row['id']),None);return value(found)
