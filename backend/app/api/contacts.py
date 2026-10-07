from __future__ import annotations
import re, uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from ..models import ContactCreateRequest,ContactUpdateRequest,MatterParticipantCreateRequest,MatterParticipantUpdateRequest
from ..repositories.contacts import ContactRepository
from ..runtime import api_auth,db,utc_iso
from ..pagination import decode_cursor,page_rows

router=APIRouter(tags=["contacts"]); repo=ContactRepository(db)

def uid(value:str,label:str)->uuid.UUID:
    try:return uuid.UUID(value)
    except ValueError as exc:raise HTTPException(400,f"Invalid {label} ID") from exc

def contact(row):
    return {"id":str(row['id']),"contactType":row['contact_type'],"displayName":row['display_name'],"firstName":row['first_name'],"middleName":row['middle_name'],"lastName":row['last_name'],"companyName":row['company_name'],"email":row['email'],"phone":row['phone'],"metadata":row['metadata'] or {},"createdAt":utc_iso(row['created_at']),"updatedAt":utc_iso(row['updated_at'])}

def participant(row):
    return {"id":str(row['id']),"matterId":str(row['matter_id']),"contactId":str(row['contact_id']),"roleKey":row['role_key'],"displayRole":row['display_role'],"isClient":row['is_client'],"isPrimary":row['is_primary'],"representedByFirm":row['represented_by_firm'],"position":row['position'],"metadata":row['metadata'] or {},"contact":{"id":str(row['contact_id']),"contactType":row['contact_type'],"displayName":row['display_name'],"firstName":row['first_name'],"middleName":row['middle_name'],"lastName":row['last_name'],"companyName":row['company_name'],"email":row['email'],"phone":row['phone']}}

@router.get('/api/contacts',dependencies=[Depends(api_auth)])
async def list_contacts(q:str=Query(default="",max_length=120),limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows=await repo.list(q,limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {"contacts":[contact(r) for r in items],"nextCursor":next_cursor}

@router.post('/api/contacts',dependencies=[Depends(api_auth)])
async def create_contact(req:ContactCreateRequest):
    name=req.display_name.strip()
    if not name:raise HTTPException(400,"Contact display name is required")
    data=req.model_dump();data['display_name']=name
    return contact(await repo.create(data))

@router.get('/api/contacts/{contact_id}',dependencies=[Depends(api_auth)])
async def get_contact(contact_id:str):
    row=await repo.get(uid(contact_id,'contact'))
    if not row:raise HTTPException(404,"Contact not found")
    return contact(row)

@router.patch('/api/contacts/{contact_id}',dependencies=[Depends(api_auth)])
async def update_contact(contact_id:str,req:ContactUpdateRequest):
    data=req.model_dump(exclude_unset=True)
    if data.get('display_name') is not None:
        data['display_name']=data['display_name'].strip()
        if not data['display_name']:raise HTTPException(400,"Contact display name cannot be empty")
    row=await repo.update(uid(contact_id,'contact'),data)
    if not row:raise HTTPException(404,"Contact not found")
    return contact(row)

@router.get('/api/matters/{matter_id}/participants',dependencies=[Depends(api_auth)])
async def list_participants(matter_id:str):
    return {"participants":[participant(r) for r in await repo.participants(uid(matter_id,'matter'))]}

@router.post('/api/matters/{matter_id}/participants',dependencies=[Depends(api_auth)])
async def add_participant(matter_id:str,req:MatterParticipantCreateRequest):
    role=re.sub(r'[^a-z0-9_.-]+','_',req.role_key.strip().lower()).strip('_')
    if not role or not req.display_role.strip():raise HTTPException(400,"roleKey and displayRole are required")
    data=req.model_dump();data['role_key']=role;data['display_role']=req.display_role.strip()
    row=await repo.add_participant(uid(matter_id,'matter'),uid(req.contact_id,'contact'),data)
    if not row:raise HTTPException(404,"Matter or contact not found")
    rows=await repo.participants(uid(matter_id,'matter'));found=next((x for x in rows if x['id']==row['id']),None)
    return participant(found) if found else {"id":str(row['id'])}

@router.patch('/api/matters/{matter_id}/participants/{participant_id}',dependencies=[Depends(api_auth)])
async def update_participant(matter_id:str,participant_id:str,req:MatterParticipantUpdateRequest):
    data=req.model_dump(exclude_unset=True)
    if data.get('role_key') is not None:data['role_key']=re.sub(r'[^a-z0-9_.-]+','_',data['role_key'].strip().lower()).strip('_')
    if data.get('display_role') is not None:data['display_role']=data['display_role'].strip()
    row=await repo.update_participant(uid(matter_id,'matter'),uid(participant_id,'participant'),data)
    if not row:raise HTTPException(404,"Participant not found")
    rows=await repo.participants(uid(matter_id,'matter'));found=next((x for x in rows if x['id']==row['id']),None)
    return participant(found) if found else {"id":str(row['id'])}

@router.delete('/api/matters/{matter_id}/participants/{participant_id}',status_code=204,dependencies=[Depends(api_auth)])
async def remove_participant(matter_id:str,participant_id:str):
    row=await repo.remove_participant(uid(matter_id,'matter'),uid(participant_id,'participant'))
    if not row:raise HTTPException(404,"Participant not found")
    return Response(status_code=204)
