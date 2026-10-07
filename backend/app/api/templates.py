from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Form, Query

from ..models import *
from ..repositories.templates import TemplateRepository
from ..runtime import api_auth, db, decompress_ooxml, runtime_state, settings, utc_iso, binary_object_store
from ..services.template_service import TemplateService
from ..pagination import decode_cursor,page_rows

router=APIRouter(tags=["templates"])
repo=TemplateRepository(db,binary_object_store,max_docx_bytes=settings.max_docx_snapshot_bytes)
service=TemplateService(repo,settings)
log=logging.getLogger(__name__)


def _affected_rows(command_tag: str) -> int:
    parts=str(command_tag or "").split()
    if len(parts) < 2 or not parts[-1].isdigit():
        raise RuntimeError(f"Unexpected PostgreSQL command status: {command_tag!r}")
    return int(parts[-1])


def variable_dict(r):
    return {"id":str(r['id']),"name":r['variable_name'],"originalText":r['original_text'],"position":r['position'],"confidenceScore":r['confidence_score'],"currentValue":r['current_value'],"bindingId":str(r['binding_id']) if r['binding_id'] else None}


@router.post("/api/templates",dependencies=[Depends(api_auth)])
async def create_template(req:CreateTemplateRequest):
    if not req.name.strip():raise HTTPException(400,"Template name is required")
    tid,row=await repo.create(name=req.name.strip(),type_=req.type or "",subtype=req.subtype or "",description=req.description or "",variables=req.variables)
    return {"id":str(tid),"name":req.name.strip(),"type":req.type,"subtype":req.subtype,"description":req.description,"variablesCount":len(req.variables),"createdAt":utc_iso(row['created_at']),"currentVersion":1,"hasFullDocx":False}


@router.get("/api/templates",dependencies=[Depends(api_auth)])
async def list_templates(limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows=await repo.list(limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {"templates":[service.meta(r) for r in items],"nextCursor":next_cursor}


@router.patch("/api/templates/{template_id}",dependencies=[Depends(api_auth)])
async def patch_template(template_id:str,req:TemplateUpdateRequest):
    tid=service.tid(template_id);current=await repo.get_meta(tid)
    if not current:raise HTTPException(404,"Template not found")
    name=(req.name if req.name is not None else current['name']).strip()
    if not name:raise HTTPException(400,"Template name cannot be empty")
    row=await repo.update_meta(tid,name=name,type_=req.type if req.type is not None else current['type'],subtype=req.subtype if req.subtype is not None else current['subtype'],description=req.description if req.description is not None else current['description'])
    return service.meta(row)


@router.post("/api/templates/{template_id}/duplicate",dependencies=[Depends(api_auth)])
async def duplicate_template(template_id:str):
    result=await repo.duplicate(service.tid(template_id))
    if not result:raise HTTPException(404,"Template not found")
    new_id,new_name,source,row=result
    return {"id":str(new_id),"name":new_name,"type":source['type'] or "","subtype":source['subtype'] or "","description":source['description'] or "","createdAt":utc_iso(row['created_at']),"currentVersion":source['current_version'],"hasFullDocx":bool(source.get('docx_object_key') or source.get('docx_base64'))}


@router.delete("/api/templates/{template_id}",status_code=204,dependencies=[Depends(api_auth)])
async def delete_template(template_id:str):
    result=await repo.soft_delete(service.tid(template_id))
    if result.endswith("0"):raise HTTPException(404,"Template not found")
    return Response(status_code=204)


@router.get("/api/templates/{template_id}",dependencies=[Depends(api_auth)])
async def get_template(template_id:str):
    tid=service.tid(template_id);row=await repo.get_meta(tid)
    if not row:raise HTTPException(404,"Template not found")
    data=service.meta(row);data['variables']=[variable_dict(v) for v in await repo.variables(tid)]
    return data


@router.get("/api/templates/{template_id}/content",dependencies=[Depends(api_auth)])
async def get_template_content(template_id:str):
    return await service.content(service.tid(template_id))


@router.put("/api/templates/{template_id}/content",status_code=204,dependencies=[Depends(api_auth)])
async def put_template_content(template_id:str,req:UpdateTemplateContentRequest):
    tid=service.tid(template_id);service.validate_body(req.body_ooxml);service.validate_docx(req.docx_base64)
    kind=req.snapshot_kind or ("full_docx" if req.docx_base64 else "body_ooxml")
    from ..runtime import compress_ooxml
    stored=compress_ooxml(req.body_ooxml) if req.body_ooxml else None
    version=await repo.save_snapshot(tid,body_ooxml=stored,docx_base64=req.docx_base64,snapshot_kind=kind)
    if version is None:raise HTTPException(404,"Template not found")
    return Response(status_code=204,headers={"X-AutoDraft-Template-Version":str(version)})


@router.put("/api/templates/{template_id}/content/file",status_code=204,dependencies=[Depends(api_auth)])
async def put_template_content_file(template_id:str,file:UploadFile=File(...),bodyOoxml:str=Form(default="")):
    tid=service.tid(template_id)
    chunks=[];total=0
    while True:
        chunk=await file.read(1024*1024)
        if not chunk:break
        total+=len(chunk)
        if total>settings.max_docx_snapshot_bytes:raise HTTPException(413,"Full DOCX snapshot is too large")
        chunks.append(chunk)
    raw=b''.join(chunks)
    if not raw.startswith(b'PK'):raise HTTPException(400,"Uploaded snapshot is not a DOCX package")
    service.validate_body(bodyOoxml)
    from ..runtime import compress_ooxml
    compressed_body=compress_ooxml(bodyOoxml) if bodyOoxml else None
    stored=await binary_object_store.put_bytes(namespace=f"templates/{tid}",data=raw,suffix=".docx")
    try:
        async with db.p().transaction() as conn:
            current=await conn.fetchrow("SELECT current_version FROM templates WHERE id=$1 AND deleted_at IS NULL FOR UPDATE",tid)
            if not current:raise HTTPException(404,"Template not found")
            count=await conn.fetchval("SELECT COUNT(*) FROM template_versions WHERE template_id=$1",tid)
            version=int(current['current_version'] or 1) if not count else int(current['current_version'] or 1)+1
            await conn.execute("UPDATE templates SET body_ooxml=$6,docx_base64=NULL,docx_object_key=$1,docx_sha256=$2,docx_size_bytes=$3,snapshot_kind='full_docx',current_version=$4,updated_at=NOW() WHERE id=$5",stored.key,stored.sha256,stored.byte_length,version,tid,compressed_body)
            await conn.execute("INSERT INTO template_versions(organization_id,template_id,version_number,body_ooxml,docx_object_key,docx_sha256,docx_size_bytes,snapshot_kind) VALUES(autodraft_current_organization_id(),$1,$2,$3,$4,$5,$6,'full_docx')",tid,version,compressed_body,stored.key,stored.sha256,stored.byte_length)
    except Exception:
        try:
            await binary_object_store.delete(stored.key)
        except Exception:
            log.exception("Failed to remove orphaned uploaded template object %s", stored.key)
        raise
    return Response(status_code=204,headers={"X-AutoDraft-Template-Version":str(version)})

@router.get("/api/templates/{template_id}/versions",dependencies=[Depends(api_auth)])
async def list_template_versions(template_id:str):
    tid=service.tid(template_id)
    if not await repo.get_meta(tid):raise HTTPException(404,"Template not found")
    rows=await repo.versions(tid)
    return {"versions":[{"id":str(r['id']),"version":r['version_number'],"snapshotKind":r['snapshot_kind'],"hasFullDocx":bool(r['has_docx']),"createdAt":utc_iso(r['created_at']),"metadata":r['metadata']} for r in rows]}


@router.get("/api/templates/{template_id}/versions/{version}/content",dependencies=[Depends(api_auth)])
async def get_template_version_content(template_id:str,version:int):
    row=await repo.version_content(service.tid(template_id),version)
    if not row:raise HTTPException(404,"Template version not found")
    return {"version":row['version_number'],"bodyOoxml":decompress_ooxml(row['body_ooxml']) if row['body_ooxml'] else None,"docxBase64":row['docx_base64'],"snapshotKind":row['snapshot_kind'],"createdAt":utc_iso(row['created_at'])}


@router.put("/api/variables/{variable_id}",dependencies=[Depends(api_auth)])
async def update_variable(variable_id:str,req:UpdateVariableRequest):
    try:vid=uuid.UUID(variable_id)
    except ValueError:raise HTTPException(400,"Invalid variable ID")
    if not req.name.strip():raise HTTPException(400,"Variable name cannot be empty")
    row=await db.p().fetchrow("UPDATE variables SET variable_name=$1,current_value=COALESCE($3,current_value),updated_at=NOW() WHERE id=$2 RETURNING id,variable_name,original_text,position,confidence_score,current_value,binding_id",req.name.strip(),vid,req.current_value)
    if not row:raise HTTPException(404,"Variable not found")
    return variable_dict(row)


@router.post("/api/templates/{template_id}/variables",dependencies=[Depends(api_auth)])
async def add_variable(template_id:str,req:AddTemplateVariableRequest):
    tid=service.tid(template_id)
    if not req.name.strip() or not req.original_text.strip():raise HTTPException(400,"Name and originalText are required")
    row=await db.p().fetchrow("INSERT INTO variables(template_id,variable_name,original_text,position,confidence_score,binding_id) SELECT $1,$2,$3,$4,$5,COALESCE($6::uuid,gen_random_uuid()) WHERE EXISTS(SELECT 1 FROM templates WHERE id=$1 AND deleted_at IS NULL) RETURNING id,variable_name,original_text,position,confidence_score,current_value,binding_id",tid,req.name.strip(),req.original_text.strip(),req.position,req.confidence_score,req.binding_id)
    if not row:raise HTTPException(404,"Template not found")
    return variable_dict(row)


@router.put("/api/templates/{template_id}/variable-values",dependencies=[Depends(api_auth)])
async def save_values(template_id:str,req:SaveVariableValuesRequest):
    tid=service.tid(template_id)
    if not await repo.get_meta(tid):raise HTTPException(404,"Template not found")
    updated=0
    async with db.p().transaction() as conn:
        for item in req.values:
            tag=await conn.execute("UPDATE variables SET current_value=$1,updated_at=NOW() WHERE template_id=$2 AND variable_name=$3",item.current_value,tid,item.variable_name)
            updated += _affected_rows(tag)
    return {"updated":updated}


# Chunked OOXML remains for body-only fallback. Full DOCX capture is sent through
# the normal content endpoint because Office.getFileAsync already slices it locally.
@router.post("/api/templates/{template_id}/content/chunked/start",dependencies=[Depends(api_auth)])
async def start_chunked(template_id:str,req:StartOoxmlChunkedUploadRequest, request: Request):
    tid=service.tid(template_id)
    if req.total_chunks < 1 or req.total_chunks > 10000:
        raise HTTPException(400,"Invalid totalChunks")
    if req.total_size < 0 or req.total_size > settings.max_ooxml_body_bytes:
        raise HTTPException(413,"OOXML body is too large")
    session=await runtime_state.create_chunk_session(
        owner_user_id=request.state.security.user_id,
        kind="template_ooxml",
        total_chunks=req.total_chunks,
        resource_id=str(tid),
        expected_total_size=req.total_size,
    )
    return {"sessionId":str(session["id"])}


@router.post("/api/templates/{template_id}/content/chunked/upload",dependencies=[Depends(api_auth)])
async def upload_chunk(template_id:str,req:UploadOoxmlChunkRequest, request: Request):
    tid=service.tid(template_id)
    try:
        session=await runtime_state.put_chunk(
            req.session_id,req.chunk_index,req.chunk_data,
            owner_user_id=request.state.security.user_id,kind="template_ooxml",resource_id=str(tid),
        )
    except IndexError as exc:
        raise HTTPException(400,str(exc)) from exc
    if not session: raise HTTPException(404,"Upload session not found")
    if req.total_chunks != int(session["total_chunks"]):
        raise HTTPException(400,"totalChunks does not match the upload session")
    received_bytes=int(session.get("received_bytes") or 0)
    expected=session.get("expected_total_size")
    if received_bytes > settings.max_ooxml_body_bytes or (expected is not None and received_bytes > int(expected) * 4 + 4096):
        raise HTTPException(413,"OOXML chunk upload exceeds its declared size")
    return {"received":int(session["received"]),"total":int(session["total_chunks"])}


@router.post("/api/templates/{template_id}/content/chunked/finalize",dependencies=[Depends(api_auth)])
async def finalize_chunked(template_id:str,req:FinalizeOoxmlChunkedUploadRequest, request: Request):
    tid=service.tid(template_id)
    try:
        finalized=await runtime_state.finalize_chunk_session(
            req.session_id,owner_user_id=request.state.security.user_id,kind="template_ooxml",resource_id=str(tid),
        )
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    if not finalized:raise HTTPException(404,"Upload session not found")
    session,chunks=finalized
    body=''.join(chunks)
    if len(body.encode("utf-8")) > settings.max_ooxml_body_bytes:
        raise HTTPException(413,"OOXML body is too large")
    service.validate_body(body)
    from ..runtime import compress_ooxml
    version=await repo.save_snapshot(tid,body_ooxml=compress_ooxml(body),docx_base64=None,snapshot_kind='body_ooxml')
    if version is None:raise HTTPException(404,"Template not found")
    return {"ok":True,"version":version}

