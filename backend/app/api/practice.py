from __future__ import annotations
import re,uuid
from fastapi import APIRouter,Depends,HTTPException,Query
from ..models import PracticeAreaCreateRequest,PracticeAreaUpdateRequest,MatterStageCreateRequest,MatterStageUpdateRequest
from ..repositories.practice import PracticeRepository
from ..runtime import api_auth,db,utc_iso
from ..auth import require_role
router=APIRouter(tags=['practice']);repo=PracticeRepository(db)

async def admin_auth(ctx=Depends(api_auth)):
    require_role(ctx, 'admin')
    return ctx

def uid(v:str,label='record'):
    try:return uuid.UUID(v)
    except ValueError as exc:raise HTTPException(400,f'Invalid {label} ID') from exc

def key(v:str):return re.sub(r'[^a-z0-9_.-]+','_',v.strip().lower()).strip('_')
def area(r):return {'id':str(r['id']),'key':r['key'],'name':r['name'],'description':r['description'],'position':r['position'],'active':r['active'],'createdAt':utc_iso(r['created_at']),'updatedAt':utc_iso(r['updated_at'])}
def stage(r):return {'id':str(r['id']),'practiceAreaId':str(r['practice_area_id']) if r['practice_area_id'] else None,'key':r['key'],'name':r['name'],'description':r['description'],'position':r['position'],'active':r['active'],'createdAt':utc_iso(r['created_at']),'updatedAt':utc_iso(r['updated_at'])}

@router.get('/api/practice-areas',dependencies=[Depends(api_auth)])
async def list_areas():return {'practiceAreas':[area(r) for r in await repo.areas()]}
@router.post('/api/practice-areas',dependencies=[Depends(admin_auth)])
async def create_area(req:PracticeAreaCreateRequest):
    k=key(req.key);name=req.name.strip()
    if not k or not name:raise HTTPException(400,'key and name are required')
    return area(await repo.create_area(key=k,name=name,description=req.description.strip(),position=req.position,active=req.active))
@router.patch('/api/practice-areas/{area_id}',dependencies=[Depends(admin_auth)])
async def update_area(area_id:str,req:PracticeAreaUpdateRequest):
    row=await repo.update_area(uid(area_id,'practice area'),req.model_dump(exclude_unset=True))
    if not row:raise HTTPException(404,'Practice area not found')
    return area(row)
@router.get('/api/matter-stages',dependencies=[Depends(api_auth)])
async def list_stages(practiceAreaId:str|None=Query(default=None)):
    aid=uid(practiceAreaId,'practice area') if practiceAreaId else None
    return {'stages':[stage(r) for r in await repo.stages(aid)]}
@router.post('/api/matter-stages',dependencies=[Depends(admin_auth)])
async def create_stage(req:MatterStageCreateRequest):
    k=key(req.key);name=req.name.strip();aid=uid(req.practice_area_id,'practice area')
    if not k or not name:raise HTTPException(400,'key and name are required')
    row=await repo.create_stage(key=k,name=name,practice_area_id=aid,description=req.description.strip(),position=req.position,active=req.active)
    if not row:raise HTTPException(404,'Practice area not found')
    return stage(row)
@router.patch('/api/matter-stages/{stage_id}',dependencies=[Depends(admin_auth)])
async def update_stage(stage_id:str,req:MatterStageUpdateRequest):
    row=await repo.update_stage(uid(stage_id,'stage'),req.model_dump(exclude_unset=True))
    if not row:raise HTTPException(404,'Matter stage not found')
    return stage(row)
