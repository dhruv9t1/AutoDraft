from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File, Form, Query

from ..models import *
from ..repositories.documents import MatterDocumentRepository
from ..repositories.matters import MatterRepository
from ..repositories.contacts import ContactRepository
from ..repositories.fields import FieldRepository
from ..repositories.derived_rules import DerivedFactRuleRepository
from ..runtime import api_auth, db, settings, utc_iso, binary_object_store
from ..auth import require_role
from ..services.matter_service import MatterService
from ..pagination import decode_cursor,page_rows

router = APIRouter(tags=["matters"])
repo = MatterRepository(db)
doc_repo = MatterDocumentRepository(db,binary_object_store,max_bytes=settings.matter_document_max_bytes)
contact_repo = ContactRepository(db)
field_repo = FieldRepository(db)
derived_rule_repo = DerivedFactRuleRepository(db)
service = MatterService(repo, doc_repo, settings, contacts=contact_repo, fields=field_repo, derived_rules=derived_rule_repo)


def summary(row):
    return {
        "id":str(row["id"]),"title":row["title"],"matterType":row["matter_type"],"status":row["status"],
        "referenceCode":row.get("reference_code") or "","practiceAreaId":str(row["practice_area_id"]) if row.get("practice_area_id") else None,
        "practiceAreaName":row.get("practice_area_name"),"stageId":str(row["stage_id"]) if row.get("stage_id") else None,
        "stageName":row.get("stage_name"),"stageChangedAt":utc_iso(row["stage_changed_at"]) if row.get("stage_changed_at") else None,"primaryClientName":row.get("primary_client_name"),
        "createdAt":utc_iso(row["created_at"]),"updatedAt":utc_iso(row["updated_at"]),
    }


@router.post("/api/matters", dependencies=[Depends(api_auth)])
async def create_matter(req: MatterCreateRequest):
    title=req.title.strip()
    if not title: raise HTTPException(400,"Matter name is required")
    
    try:
        row=await repo.create(title, req.matter_type.strip(),practice_area_id=service.parse_id(req.practice_area_id,"practice area") if req.practice_area_id else None,stage_id=service.parse_id(req.stage_id,"stage") if req.stage_id else None,reference_code=req.reference_code.strip())
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    if not row: raise HTTPException(404,"Practice area or stage not found")
    return summary(row)


@router.get("/api/matters", dependencies=[Depends(api_auth)])
async def list_matters(limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows=await repo.list(limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {"matters":[summary(r) for r in items],"nextCursor":next_cursor}


@router.patch("/api/matters/{matter_id}", dependencies=[Depends(api_auth)])
async def patch_matter(matter_id: str, req: MatterUpdateRequest):
    mid=service.parse_id(matter_id)
    current=await repo.get(mid)
    if not current: raise HTTPException(404,"Matter not found")
    title=(req.title if req.title is not None else current["title"]).strip()
    if not title: raise HTTPException(400,"Matter name cannot be empty")
    
    practice_was_set = "practice_area_id" in req.model_fields_set
    stage_was_set = "stage_id" in req.model_fields_set
    practice_area_id = (
        service.parse_id(req.practice_area_id,"practice area") if req.practice_area_id
        else None if practice_was_set
        else current.get("practice_area_id")
    )
    stage_id = (
        service.parse_id(req.stage_id,"stage") if req.stage_id
        else None if stage_was_set
        else current.get("stage_id")
    )
    # A stage is practice-area-specific. Clearing the practice area also clears
    # the stage unless the caller supplied another valid practice area.
    if practice_was_set and practice_area_id is None:
        stage_id = None
    elif practice_was_set and not stage_was_set and practice_area_id != current.get("practice_area_id"):
        stage_id = None

    try:
        row=await repo.update(
            mid,title=title,
            matter_type=req.matter_type if req.matter_type is not None else current["matter_type"],
            status=req.status if req.status is not None else current["status"],
            practice_area_id=practice_area_id,
            stage_id=stage_id,
            reference_code=req.reference_code if req.reference_code is not None else (current.get("reference_code") or ""),
        )
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    if not row: raise HTTPException(404,"Matter, practice area, or stage not found")
    return summary(await repo.get(mid))


@router.get("/api/matters/{matter_id}", dependencies=[Depends(api_auth)])
async def get_matter(matter_id: str):
    return await service.detail(service.parse_id(matter_id))


@router.post("/api/matters/{matter_id}/facts", dependencies=[Depends(api_auth)])
async def add_matter_fact(matter_id: str, req: MatterFactRequest):
    return await service.add_fact(service.parse_id(matter_id), req)


@router.get("/api/matters/{matter_id}/conflicts", dependencies=[Depends(api_auth)])
async def list_fact_conflicts(matter_id: str):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    return {"conflicts":[service.row(r) for r in await repo.conflicts(mid)]}


@router.post("/api/matters/{matter_id}/conflicts/{conflict_id}/resolve", dependencies=[Depends(api_auth)])
async def resolve_fact_conflict(matter_id: str, conflict_id: str, req: FactConflictResolutionRequest):
    mid=service.parse_id(matter_id); cid=service.parse_id(conflict_id,"conflict")
    fid=service.parse_id(req.fact_id,"fact") if req.fact_id else None
    try: result=await repo.resolve_conflict(mid,cid,fact_id=fid,value=req.value,dismiss=req.dismiss)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
    if not result: raise HTTPException(404,"Open fact conflict not found")
    return result


@router.post("/api/matters/{matter_id}/derive", dependencies=[Depends(api_auth)])
async def derive_matter_facts(matter_id: str):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    return {"facts":await service.derive(mid)}


@router.post("/api/derived-fact-rules", dependencies=[Depends(api_auth)])
async def upsert_derived_fact_rule(req: DerivedFactRuleRequest):
    key=req.fact_key.strip()
    if not key or not req.label.strip(): raise HTTPException(400,"factKey and label are required")
    row=await derived_rule_repo.upsert(
        fact_key=key,
        label=req.label.strip(),
        value_type=req.value_type,
        expression=req.expression,
        enabled=req.enabled,
    )
    return service.row(row)


@router.get("/api/derived-fact-rules", dependencies=[Depends(api_auth)])
async def list_derived_fact_rules():
    rows=await derived_rule_repo.list()
    return {"rules":[service.row(r) for r in rows]}


@router.get("/api/matters/{matter_id}/activity", dependencies=[Depends(api_auth)])
async def matter_activity(matter_id: str):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    rows=await db.p().fetch("SELECT id,event_type,aggregate_type,aggregate_id,payload,status,created_at FROM outbox_events WHERE matter_id=$1 ORDER BY created_at DESC LIMIT 200",mid)
    return {"events":[{"id":str(r["id"]),"eventType":r["event_type"],"aggregateType":r["aggregate_type"],"aggregateId":str(r["aggregate_id"]) if r["aggregate_id"] else None,"payload":r["payload"] or {},"status":r["status"],"createdAt":utc_iso(r["created_at"])} for r in rows]}


@router.post("/api/matters/{matter_id}/authorities", dependencies=[Depends(api_auth)])
async def add_matter_authority(matter_id: str, req: MatterAuthorityRequest):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    return service.row(await repo.add_authority(mid,title=req.title,citation=req.citation,source_url=req.source_url))


@router.post("/api/matters/{matter_id}/authorities/{authority_id}/verification")
async def verify_matter_authority(matter_id: str, authority_id: str, req: MatterAuthorityVerificationRequest, ctx=Depends(api_auth)):
    require_role(ctx, "lawyer")
    mid=service.parse_id(matter_id)
    aid=service.parse_id(authority_id,"authority")
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    row=await repo.verify_authority(mid,aid,status=req.status,user_id=service.parse_id(ctx.user_id,"user"),evidence={"note":req.note,**req.evidence})
    if not row: raise HTTPException(404,"Authority not found")
    return service.row(row)


@router.get("/api/matters/{matter_id}/documents", dependencies=[Depends(api_auth)])
async def list_matter_documents(matter_id: str,limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid): raise HTTPException(404,"Matter not found")
    t,i=decode_cursor(cursor);rows=await doc_repo.list(mid,limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {"documents":[service.row(r) for r in items],"nextCursor":next_cursor}


@router.post("/api/matters/{matter_id}/documents", dependencies=[Depends(api_auth)])
async def create_matter_document(matter_id: str, req: MatterDocumentCreateRequest):
    return await service.create_document(service.parse_id(matter_id), req)


@router.post("/api/matters/{matter_id}/documents/file",dependencies=[Depends(api_auth)])
async def create_matter_document_file(matter_id:str,file:UploadFile=File(...),name:str=Form(default="Matter document.docx"),source:str=Form(default="captured")):
    mid=service.parse_id(matter_id)
    if not await repo.get(mid):raise HTTPException(404,"Matter not found")
    chunks=[];total=0
    while True:
        chunk=await file.read(1024*1024)
        if not chunk:break
        total+=len(chunk)
        if total>settings.matter_document_max_bytes:raise HTTPException(413,"Matter document is too large")
        chunks.append(chunk)
    raw=b''.join(chunks)
    if not raw.startswith(b'PK'):raise HTTPException(400,"Uploaded file is not a DOCX package")
    from ..storage import safe_filename
    try:row=await doc_repo.create_bytes(mid,name=safe_filename(name,"Matter document.docx"),data=raw,mime_type=file.content_type or "application/vnd.openxmlformats-officedocument.wordprocessingml.document",source=source,metadata={})
    except ValueError as exc:raise HTTPException(400,str(exc)) from exc
    return service.row(row)

@router.get("/api/matters/{matter_id}/documents/{document_id}/content",dependencies=[Depends(api_auth)])
async def download_matter_document(matter_id:str,document_id:str):
    result=await doc_repo.get_bytes(service.parse_id(matter_id),service.parse_id(document_id,"document"))
    if not result:raise HTTPException(404,"Matter document not found")
    row,raw=result
    return Response(content=raw,media_type=row['mime_type'],headers={"Content-Disposition":f'attachment; filename="{row["name"]}"'})

@router.get("/api/matters/{matter_id}/documents/{document_id}", dependencies=[Depends(api_auth)])
async def get_matter_document(matter_id: str, document_id: str):
    mid=service.parse_id(matter_id); did=service.parse_id(document_id,"document")
    row=await doc_repo.get(mid,did,include_content=True)
    if not row: raise HTTPException(404,"Matter document not found")
    data=service.row(row); data["docxBase64"]=data.pop("docx_base64")
    data["mimeType"]=data.pop("mime_type"); data["sizeBytes"]=data.pop("size_bytes")
    return data


@router.patch("/api/matters/{matter_id}/documents/{document_id}", dependencies=[Depends(api_auth)])
async def update_matter_document(matter_id: str, document_id: str, req: MatterDocumentUpdateRequest):
    mid=service.parse_id(matter_id); did=service.parse_id(document_id,"document")
    row=await doc_repo.update(mid,did,name=req.name,archived=req.archived)
    if not row: raise HTTPException(404,"Matter document not found")
    return service.row(row)


@router.delete("/api/matters/{matter_id}/documents/{document_id}", status_code=204, dependencies=[Depends(api_auth)])
async def archive_matter_document(matter_id: str, document_id: str):
    mid=service.parse_id(matter_id); did=service.parse_id(document_id,"document")
    row=await doc_repo.update(mid,did,name=None,archived=True)
    if not row: raise HTTPException(404,"Matter document not found")
    return Response(status_code=204)
