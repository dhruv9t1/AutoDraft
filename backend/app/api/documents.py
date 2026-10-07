from __future__ import annotations
import asyncio, json, uuid
from typing import Any
from collections import Counter
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from ..runtime import *
from ..models import *
from ..post_processing import group_into_blocks
from ..wrapping import build_wrapping_plan
from ..analysis_prompts import SUMMARY_SYSTEM, RISK_SYSTEM, DEADLINE_SYSTEM
from ..verifier import verify_document
from ..variable_quality import audit_variables
from ..services.field_service import identification_complete_payload
from ..services.organization_service import get_boilerplate_values
from ..extraction.docx_reader import inspect_docx_bytes
from ..db import clear_request_connection, reset_request_connection, reset_request_organization, set_request_organization
from ..repositories.ai_governance import AIGovernanceRepository
from ..auth import require_role

router=APIRouter(tags=["documents"])
ai_governance=AIGovernanceRepository(db)

async def _persist_candidate_provenance(document:str, variables:list[Variable], request:Request)->str:
    request_id=uuid.uuid4()
    policy=await ai.external_system1_policy()
    descriptor=ai.provenance_descriptor(external_system1_enabled=bool(policy.get("enabled")))
    mapping=await ai_governance.persist_candidates(document=document,variables=variables,actor_user_id=request.state.security.user_id,request_id=request_id,provider=descriptor["provider"],model_version=descriptor["model"],provider_chain=descriptor["providerChain"],provider_versions=descriptor.get("providerVersions"))
    for variable in variables:
        if variable.candidate_id and variable.candidate_id in mapping:
            variable.decision_record_id=mapping[variable.candidate_id]
    return str(request_id)

@router.post("/api/documents/docx-diagnostics", response_model=DocxDiagnosticsResponse, dependencies=[Depends(api_auth)])
async def docx_diagnostics(file: UploadFile = File(...)):
    data = await file.read(settings.max_docx_snapshot_bytes + 1)
    if len(data) > settings.max_docx_snapshot_bytes:
        raise HTTPException(413, "DOCX is too large for diagnostics")
    try:
        paragraphs, legacy = inspect_docx_bytes(data)
    except Exception as exc:
        raise HTTPException(400, f"Could not inspect DOCX: {exc}") from exc
    counts = Counter(p.story for p in paragraphs)
    warnings = []
    for finding in legacy:
        if finding.run_count:
            warnings.append(
                f"Legacy pre-Unicode Indian font '{finding.font_name}' appears in {finding.run_count} text run(s). "
                "Those characters may look Gujarati/Hindi in Word but are not Unicode text; review or convert them before field detection."
            )
        else:
            warnings.append(
                f"Legacy pre-Unicode Indian font '{finding.font_name}' is referenced by styles/theme. "
                "Review the document if Gujarati/Hindi text looks corrupted to AutoDraft."
            )
    return DocxDiagnosticsResponse(
        paragraphCount=len(paragraphs),
        storyCounts=dict(counts),
        legacyFonts=[
            DocxLegacyFontFinding(fontName=x.font_name, runCount=x.run_count, inheritedOnly=x.inherited_only)
            for x in legacy
        ],
        warnings=warnings,
    )
@router.post("/api/documents/identify-variables",dependencies=[Depends(api_auth)])
async def identify_variables(req:VariableIdentificationRequest, request:Request):
    doc=req.document_content
    if not doc.strip(): raise HTTPException(400,"Document content is required")
    if len(doc)>settings.max_document_length: raise HTTPException(413,"Document too large")
    boilerplate = await get_boilerplate_values(db)
    vars_, ai_failed, mode, coverage=await ai.identify_variables(doc,req.known_variables or [], boilerplate)
    provenance_request_id=await _persist_candidate_provenance(doc,vars_,request)
    payload = identification_complete_payload(doc, {
        "variables": vars_,
        "ai_failed": ai_failed,
        "identificationMode": mode.value,
        "coverageWarnings": coverage,
    })
    response=VariableIdentificationResponse.model_validate(payload)
    data=response.model_dump(by_alias=True)
    data["provenanceRequestId"]=provenance_request_id
    return data

@router.post("/api/documents/identify-variables-stream",dependencies=[Depends(api_auth)])
async def identify_variables_stream(req:VariableIdentificationRequest, request: Request):
    doc=req.document_content
    if not doc.strip(): raise HTTPException(400,"Document content is required")
    if len(doc)>settings.max_document_length: raise HTTPException(413,"Document too large")
    queue: asyncio.Queue[dict[str,Any] | None] = asyncio.Queue()
    boilerplate = await get_boilerplate_values(db)

    async def producer():
        try:
            async for item in ai.stream_variables(doc, req.known_variables or [], boilerplate):
                await queue.put(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            payload={"message":str(exc)}
            if isinstance(exc, AutoDraftError):
                payload.update({"code":exc.code,"recoverable":exc.recoverable})
            await queue.put({"event":"fatal_error","data":payload})
        finally:
            await queue.put(None)

    async def gen():
        # Stream bodies run after the middleware releases the bound request
        # transaction and resets the tenant context; detach from the released
        # connection and re-establish the tenant scope for stream-time queries.
        conn_token=clear_request_connection()
        tenant_token=set_request_organization(request.state.security.organization_id)
        worker=asyncio.create_task(producer())
        yield sse("status", {"state":"started","message":"Variable identification started"})
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item=await asyncio.wait_for(queue.get(), timeout=max(0.1, settings.sse_heartbeat_seconds))
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is None:
                    break
                if item["event"]=="_final":
                    final_vars=[Variable.model_validate(v) if isinstance(v,dict) else v for v in item["data"].get("variables",[])]
                    provenance_request_id=await _persist_candidate_provenance(doc,final_vars,request)
                    final_data={**item["data"],"variables":[dump(v) for v in final_vars]}
                    complete=identification_complete_payload(doc,final_data)
                    complete["provenanceRequestId"]=provenance_request_id
                    yield sse("complete", complete)
                    break
                data=item["data"]
                if item["event"]=="chunk_done" and isinstance(data,dict):
                    chunk_vars=[Variable.model_validate(v) if isinstance(v,dict) else v for v in data.get("variables",[])]
                    chunk_vars,_=audit_variables(doc,chunk_vars)
                    data={**data,"variables":[dump(v) for v in chunk_vars]}
                yield sse(item["event"], data)
        finally:
            if not worker.done():
                worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            reset_request_organization(tenant_token)
            reset_request_connection(conn_token)

    return StreamingResponse(gen(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})

def _public_extraction_job(job_id: str, job: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "jobId": job_id,
        "status": job.get("status", "queued"),
        "error": job.get("error"),
        "createdAt": utc_iso(job.get("created_at") or job.get("created")),
        "attemptCount": int(job.get("attempt_count") or 0),
    }
    if job.get("status") == "completed" and job.get("result") is not None:
        payload["result"] = job["result"]
    return payload


@router.post("/api/documents/identify-jobs",dependencies=[Depends(api_auth)])
async def create_identify_job(req: VariableIdentificationRequest, request: Request):
    doc=req.document_content
    if not doc.strip(): raise HTTPException(400,"Document content is required")
    if len(doc)>settings.max_document_length: raise HTTPException(413,"Document too large")
    job = await runtime_state.create_job(
        "extraction",
        owner_user_id=request.state.security.user_id,
        payload=req.model_dump(by_alias=True),
        ttl_seconds=settings.extraction_job_ttl_seconds,
    )
    return _public_extraction_job(str(job["id"]), job)


@router.get("/api/documents/identify-jobs/{job_id}",dependencies=[Depends(api_auth)])
async def get_identify_job(job_id: str, request: Request):
    job=await runtime_state.get_job(job_id,owner_user_id=request.state.security.user_id)
    if not job: raise HTTPException(404,"Extraction job not found")
    if job.get("job_type") != "extraction": raise HTTPException(404,"Extraction job not found")
    return _public_extraction_job(job_id, job)


@router.get("/api/documents/identify-jobs/{job_id}/events",dependencies=[Depends(api_auth)])
async def identify_job_events(job_id: str, request: Request):
    initial=await runtime_state.get_job(job_id,owner_user_id=request.state.security.user_id)
    if not initial or initial.get("job_type") != "extraction": raise HTTPException(404,"Extraction job not found")
    organization_id = request.state.security.organization_id
    async def event_stream():
        tenant_token=set_request_organization(organization_id)
        after_id=0
        try:
            yield sse("status", {"state":initial["status"],"jobId":job_id})
            while True:
                if await request.is_disconnected():
                    return
                events=await runtime_state.events_after(job_id, after_id, owner_user_id=request.state.security.user_id)
                for item in events:
                    after_id=max(after_id,int(item["id"]))
                    yield sse(str(item["event_type"]), item.get("data") or {})
                    if item["event_type"] in {"complete","fatal_error"}:
                        return
                job=await runtime_state.get_job(job_id,owner_user_id=request.state.security.user_id)
                if not job or job["status"] in {"completed","failed","cancelled"}:
                    return
                try:
                    await asyncio.sleep(max(0.1,min(1.0,settings.sse_heartbeat_seconds)))
                except asyncio.CancelledError:
                    return
                yield ": heartbeat\n\n"
        finally:
            reset_request_organization(tenant_token)
    return StreamingResponse(event_stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache, no-transform","X-Accel-Buffering":"no"})


@router.delete("/api/documents/identify-jobs/{job_id}",status_code=204,dependencies=[Depends(api_auth)])
async def cancel_identify_job(job_id: str, request: Request):
    await runtime_state.request_cancel(job_id,owner_user_id=request.state.security.user_id)
    return Response(status_code=204)


@router.post("/api/documents/start-chunked-upload",dependencies=[Depends(api_auth)])
async def start_document_chunked(req:StartDocumentChunkedRequest, request: Request):
    if req.total_chunks < 1 or req.total_chunks > 10000:
        raise HTTPException(400,"Invalid totalChunks")
    session=await runtime_state.create_chunk_session(
        owner_user_id=request.state.security.user_id,
        kind="document",
        total_chunks=req.total_chunks,
        expected_total_size=settings.max_document_length * 4,
        metadata={"templateId":req.template_id,"templateName":req.template_name},
    )
    return {"sessionId":str(session["id"]),"totalChunks":req.total_chunks}


@router.post("/api/documents/upload-chunk",dependencies=[Depends(api_auth)])
async def upload_document_chunk(req:UploadDocumentChunkRequest, request: Request):
    try:
        session=await runtime_state.put_chunk(req.session_id,req.chunk_index,req.chunk_content,owner_user_id=request.state.security.user_id,kind="document")
    except IndexError as exc:
        raise HTTPException(400,str(exc)) from exc
    if not session or session.get("session_kind") != "document":
        raise HTTPException(404,"Upload session not found")
    if int(session.get("received_bytes") or 0) > settings.max_document_length * 4:
        # UTF-8 bytes can exceed Python character count; stop obviously abusive
        # sessions before final concatenation. The final character limit remains authoritative.
        raise HTTPException(413,"Chunked document is too large")
    received=int(session["received"])
    total=int(session["total_chunks"])
    return {"sessionId":req.session_id,"chunkIndex":req.chunk_index,"chunksReceived":received,"totalChunks":total,"isComplete":received==total}


@router.post("/api/documents/finalize-chunked-upload",dependencies=[Depends(api_auth)])
async def finalize_document_chunked(req:FinalizeDocumentChunkedRequest, request: Request):
    try:
        finalized=await runtime_state.finalize_chunk_session(req.session_id,owner_user_id=request.state.security.user_id,kind="document")
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    if not finalized:
        raise HTTPException(404,"Upload session not found")
    session,chunks=finalized
    if session.get("session_kind") != "document":
        raise HTTPException(404,"Upload session not found")
    document="".join(chunks)
    if len(document)>settings.max_document_length: raise HTTPException(413,"Document too large")
    boilerplate = await get_boilerplate_values(db)
    vars_, ai_failed, mode, coverage=await ai.identify_variables(document,[], boilerplate)
    payload=identification_complete_payload(document,{
        "variables":vars_,
        "ai_failed":ai_failed,
        "identificationMode":mode.value,
        "coverageWarnings":coverage,
    })
    return VariableIdentificationResponse.model_validate(payload)


@router.post("/api/documents/candidate-decisions/{record_id}/lawyer-review")
async def review_candidate_decision(record_id:str, req:CandidateLawyerReviewRequest, ctx=Depends(api_auth)):
    require_role(ctx,"lawyer")
    try: rid=uuid.UUID(record_id)
    except ValueError as exc: raise HTTPException(400,"Invalid candidate decision record ID") from exc
    try: row=await ai_governance.lawyer_disposition(rid,lawyer_user_id=ctx.user_id,disposition=req.disposition,reason=req.reason)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    if not row: raise HTTPException(404,"Candidate decision record not found")
    return {"id":str(row["id"]),"candidateId":row["candidate_id"],"finalLawyerDisposition":row["final_lawyer_disposition"],"lawyerUserId":str(row["lawyer_user_id"]),"lawyerReason":row["lawyer_reason"],"lawyerReviewedAt":utc_iso(row["lawyer_reviewed_at"])}

@router.post("/api/documents/summarize",dependencies=[Depends(api_auth)])
async def summarize(req:SummaryRequest):
    x=await ai.structured_analysis(SUMMARY_SYSTEM,f"<document>\n{req.document_content[:30000]}\n</document>")
    return {"summary":x.get("summary",""),"documentType":x.get("document_type",x.get("documentType","Other")),"keyParties":x.get("key_parties",x.get("keyParties",[])),"keyDates":x.get("key_dates",x.get("keyDates",[])),"keyAmounts":x.get("key_amounts",x.get("keyAmounts",[])),"legalReferences":x.get("legal_references",x.get("legalReferences",[])),"urgency":x.get("urgency","low")}

@router.post("/api/documents/risk-assessment",dependencies=[Depends(api_auth)])
async def risk(req:RiskAssessmentRequest):
    x=await ai.structured_analysis(RISK_SYSTEM,f"Document type hint: {req.document_type or 'unknown'}\n<document>\n{req.document_content[:30000]}\n</document>")
    return {"overallRisk":x.get("overall_risk",x.get("overallRisk","medium")),"riskScore":x.get("risk_score",x.get("riskScore",5)),"riskFactors":x.get("risk_factors",x.get("riskFactors",[])),"complianceIssues":x.get("compliance_issues",x.get("complianceIssues",[])),"recommendations":x.get("recommendations",[])}

@router.post("/api/documents/deadlines",dependencies=[Depends(api_auth)])
async def deadlines(req:DeadlineRequest):
    x=await ai.structured_analysis(DEADLINE_SYSTEM,f"<document>\n{req.document_content[:30000]}\n</document>")
    deadlines=[]
    for d in x.get("deadlines",[]): deadlines.append({"date":d.get("date",""),"description":d.get("description",""),"daysRemaining":d.get("days_remaining",d.get("daysRemaining")),"urgency":d.get("urgency","normal")})
    notices=[]
    for n in x.get("notices",[]): notices.append({"noticeType":n.get("notice_type",n.get("noticeType","")),"noticeDate":n.get("notice_date",n.get("noticeDate","")),"responseDeadline":n.get("response_deadline",n.get("responseDeadline")),"legalSection":n.get("legal_section",n.get("legalSection"))})
    return {"deadlines":deadlines,"notices":notices}

@router.post("/api/documents/verify", response_model=VerificationResponse, dependencies=[Depends(api_auth)])
async def verify_final_document(req:VerificationRequest):
 base=verify_document(req.document_content,req.variables,req.current_values)
 if req.legal_mode and req.document_content.strip():
  try:
   prompt=f"""Audit this final legal draft for material review issues only. Do not rewrite it. Find inconsistent party names, contradictory dates/amounts/case identifiers, missing obvious matter-specific facts, or stale template values. Verification is advisory, so use only warning or info severity. Return JSON with an issues array.
<document>
{req.document_content[:30000]}
</document>"""
   analysis=await ai.structured_analysis("You are a conservative final legal-draft verifier. Never invent facts. All findings are advisory warnings or information, never blockers.",prompt)
   for issue in analysis.get("issues",[]) if isinstance(analysis,dict) else []:
    if not isinstance(issue,dict):
     continue
    sev=str(issue.get("severity","warning")).lower()
    if sev not in {"warning","info"}: sev="warning"
    message=str(issue.get("message") or issue.get("detail") or issue.get("title") or "").strip()
    # Never surface an empty/generic semantic warning. A review finding must tell
    # the user what concrete inconsistency or missing fact was observed.
    if not message or message.lower() in {"semantic review issue","review issue","potential issue"}:
     continue
    code=str(issue.get("code") or "SEMANTIC_REVIEW").strip() or "SEMANTIC_REVIEW"
    variable_name=issue.get("variableName") or issue.get("variable_name")
    evidence=issue.get("evidence") or issue.get("excerpt")
    base["issues"].append({"severity":sev,"code":code,"message":message,"variableName":variable_name,"evidence":str(evidence)[:500] if evidence is not None else None})
  except Exception as exc:
   base["issues"].append({"severity":"warning","code":"SEMANTIC_AUDIT_UNAVAILABLE","message":"The secondary semantic verifier was unavailable. Deterministic verification completed.","variableName":None,"evidence":str(exc)[:160]})
 base["blockers"]=0;base["warnings"]=sum(x["severity"]=="warning" for x in base["issues"]);base["status"]="review" if base["warnings"] else "pass"
 return base
