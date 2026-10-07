from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from ..models import *
from ..db import set_request_organization
from ..repositories.intake import IntakeRepository
from ..runtime import ai, api_auth, db, dump, utc_iso
from ..token_security import bearer_token_hash
from ..services.intake_service import IntakeService

router=APIRouter(tags=["intake"])
repo=IntakeRepository(db)
service=IntakeService(repo)


def _normalise_intake_questions(raw):
    allowed={"text","textarea","date","number","currency","email","phone","select","boolean","address","person","multi_select","file"};out=[];seen=set()
    for index,item in enumerate(raw if isinstance(raw,list) else []):
        if not isinstance(item,dict):continue
        label=str(item.get("label") or item.get("question") or "").strip()
        if not label:continue
        qid=re.sub(r"[^a-z0-9]+","_",str(item.get("id") or label).lower()).strip("_") or f"question_{index+1}";base=qid;suffix=2
        while qid in seen:qid=f"{base}_{suffix}";suffix+=1
        seen.add(qid);qtype=str(item.get("type") or "text").lower()
        if qtype not in allowed:qtype="textarea" if len(label)>80 else "text"
        options=item.get("options") if isinstance(item.get("options"),list) else []
        validation={"allowedExtensions":[".pdf",".docx",".png",".jpg",".jpeg",".txt"]} if qtype=="file" else {}
        out.append({"id":qid,"label":label,"type":qtype,"required":bool(item.get("required",True)),"options":[str(x) for x in options if str(x).strip()],"mapsTo":str(item.get("mapsTo") or item.get("maps_to") or label).strip(),"helpText":str(item.get("helpText") or item.get("help_text") or "").strip(),"approved":False,"sectionId":None,"position":index,"displayRule":None,"validation":validation})
    return out[:40]


@router.post("/api/intake/generate",response_model=IntakeGenerateResponse,dependencies=[Depends(api_auth)])
async def generate_intake(req:IntakeGenerateRequest):
    matter=(req.matter_type or "").strip() or "Legal matter"
    prompt=f"""Create a concise but case-specific client intake questionnaire for an Indian legal matter.
Matter type: {matter}
Known facts: {json.dumps(req.known_facts,ensure_ascii=False)}
Ask only information a lawyer reasonably needs to evaluate and draft this matter: identity/contact, chronology, transaction/document facts, relief, limitation/deadlines, evidence/documents, jurisdiction and matter-specific facts.
Return JSON with title, matterType and questions. Every question must contain id, label, type, required, options, mapsTo and helpText. Allowed type values only: text, textarea, date, number, currency, email, phone, select, boolean, address, person, multi_select, file."""
    candidate=await ai.structured_analysis("You design matter-specific legal client intake forms. Do not give legal conclusions. Return valid JSON only.",prompt,purpose="intake")
    data=candidate if isinstance(candidate,dict) else {}
    return {"title":str(data.get("title") or f"{matter} Client Intake"),"matterType":matter,"questions":_normalise_intake_questions(data.get("questions",[]))}


# ── Versioned lawyer-owned questionnaire API ────────────────────────────────
@router.get("/api/questionnaires",dependencies=[Depends(api_auth)])
async def list_questionnaires():
    rows=await repo.list_templates()
    return {"questionnaires":[{"id":str(r['id']),"title":r['title'],"matterType":r['matter_type'],"status":r['status'],"latestVersion":r['latest_version'],"publishedAt":utc_iso(r['published_at']) if r['published_at'] else None,"updatedAt":utc_iso(r['updated_at'])} for r in rows]}


@router.post("/api/questionnaires",dependencies=[Depends(api_auth)])
async def save_questionnaire(req:QuestionnaireSaveRequest):
    return await service.save(req)


@router.get("/api/questionnaires/{questionnaire_id}",dependencies=[Depends(api_auth)])
async def get_questionnaire(questionnaire_id:str):
    return await service.definition(service.qid(questionnaire_id))


@router.post("/api/questionnaires/{questionnaire_id}/publish",dependencies=[Depends(api_auth)])
async def publish_questionnaire(questionnaire_id:str):
    return await service.publish(service.qid(questionnaire_id))


@router.post("/api/questionnaires/{questionnaire_id}/sessions",dependencies=[Depends(api_auth)])
async def create_questionnaire_session(questionnaire_id:str,req:IntakePublishRequest,request:Request):
    # URL ID is authoritative; body ID is accepted only to keep typed clients explicit.
    qid=service.qid(questionnaire_id)
    if service.qid(req.questionnaire_id)!=qid:raise HTTPException(400,"Questionnaire ID mismatch")
    return await service.create_session(qid,matter_id=req.matter_id,expires_days=req.expires_in_days,base_url=str(request.base_url))


# Compatibility endpoint now persists through the versioned model instead of
# the legacy monolithic JSONB intake_forms table.
@router.post("/api/intake/share",dependencies=[Depends(api_auth)])
async def share_intake(req:IntakeShareRequest,request:Request):
    if not req.questions:raise HTTPException(400,"Add at least one intake question before publishing.")
    unapproved=[q.id for q in req.questions if not q.approved]
    if unapproved:raise HTTPException(409,detail={"message":"Every AI-suggested question must be approved or removed before publishing.","fields":unapproved})
    section=IntakeSection(id="section-main",title="Questions",position=0)
    definition=await service.save(QuestionnaireSaveRequest(title=req.title,matterType=req.matter_type,sections=[section],questions=[q.model_copy(update={"section_id":"section-main","position":i}) for i,q in enumerate(req.questions)]))
    qid=service.qid(definition['id']);await service.publish(qid)
    return await service.create_session(qid,matter_id=None,expires_days=7,base_url=str(request.base_url))


@router.get("/api/intake/{token}",dependencies=[Depends(api_auth)])
async def get_intake_answers(token:str):
    payload=await service.review_payload(token)
    if payload:return payload
    # Legacy token compatibility.
    row=await db.p().fetchrow("SELECT title,matter_type,questions,answers,submitted_at,template_id,expires_at,revoked_at FROM intake_forms WHERE token_hash=$1",bearer_token_hash(token))
    if not row:raise HTTPException(404,"Intake form not found")
    if row['revoked_at'] or (row['expires_at'] and row['expires_at']<datetime.now(timezone.utc)):raise HTTPException(410,"Intake link expired or revoked")
    return {"title":row['title'],"matterType":row['matter_type'],"questions":row['questions'],"answers":row['answers'] or {},"submittedAt":utc_iso(row['submitted_at']) if row['submitted_at'] else None,"templateId":row['template_id']}


@router.get("/api/intake/public/{token}")
async def public_intake_data(token:str):
    payload=await service.public_data(token)
    if payload:
        if payload['status'] in {'revoked','expired'}:raise HTTPException(410,"Intake link expired or revoked")
        return payload
    legacy=await service.legacy_public_data(token)
    if not legacy:raise HTTPException(404,"Intake form not found")
    if legacy.get('status') in {'revoked','expired'}:raise HTTPException(410,"Intake link expired or revoked")
    return legacy


@router.post("/api/intake/public/{token}/files/{question_id}")
async def upload_intake_file(token:str,question_id:str,file:UploadFile=File(...)):
    return await service.store_file(token,question_id,file)


@router.post("/api/intake/public/{token}/submit")
async def submit_public_intake(token:str,req:IntakeSubmission):
    if await repo.public_session_by_token(token):return await service.submit(token,req.answers)
    return await service.submit_legacy(token,req.answers)


@router.get("/intake/{token}",response_class=HTMLResponse)
async def public_intake_page(token:str, request:Request):
    try:data=await public_intake_data(token)
    except HTTPException as exc:
        return HTMLResponse("<h1>Form not found or unavailable</h1>",status_code=exc.status_code)
    if data.get('status')=='submitted' or data.get('submitted'):
        return HTMLResponse("<main style='font-family:sans-serif;max-width:680px;margin:60px auto'><h1>Already submitted</h1><p>Your lawyer has received this intake.</p></main>")
    payload=(json.dumps({"title":data['title'],"questions":data['questions']},ensure_ascii=False,separators=(",",":"))
             .replace("&","\\u0026").replace("<","\\u003c").replace(">","\\u003e"))
    html="""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>AutoDraft Client Intake</title><style>
body{font-family:system-ui;background:#f6f7f9;color:#1f2937}main{max-width:760px;margin:32px auto;background:white;padding:28px;border-radius:12px;box-shadow:0 2px 14px #0001}.q{margin-top:18px}.hidden{display:none}label{display:block;font-weight:650}input,textarea,select{width:100%;box-sizing:border-box;padding:11px;margin-top:6px;border:1px solid #cbd5e1;border-radius:7px}textarea{min-height:110px}button{margin-top:24px;background:#d95f02;color:white;border:0;border-radius:8px;padding:12px 18px;font-weight:700}small{display:block;color:#64748b}.req{font-size:12px;color:#7c2d12;margin-left:6px}.errors{display:none;background:#fef2f2;border:1px solid #fecaca;padding:12px;border-radius:8px;margin:12px 0}.errors:focus{outline:3px solid #93c5fd}.checks label{font-weight:400}.checks input{width:auto;margin-right:6px}.section{margin-top:28px;padding-top:12px;border-top:1px solid #e5e7eb}.section h2{margin:0 0 4px}.section p{margin:0;color:#64748b}
</style></head><body><main id="app"></main><script id="intake-bootstrap" type="application/json">__PAYLOAD__</script><script nonce="__NONCE__">
const D=JSON.parse(document.getElementById('intake-bootstrap').textContent||'{}');const TOKEN=decodeURIComponent(location.pathname.split('/').filter(Boolean).pop()||'');const app=document.getElementById('app');const h=document.createElement('h1');h.textContent=D.title;app.appendChild(h);const intro=document.createElement('p');intro.textContent='Complete the information below. Your lawyer will review every response before it is used.';app.appendChild(intro);const err=document.createElement('div');err.className='errors';err.setAttribute('role','alert');err.setAttribute('tabindex','-1');app.appendChild(err);const f=document.createElement('form');const nodes={};
function visible(q,a){const r=q.displayRule;if(!r||!r.questionId)return true;const actual=a[r.questionId]||'';const expected=r.value||'';if(r.operator==='not_equals')return String(actual)!==String(expected);if(r.operator==='exists')return !!String(actual).trim();if(r.operator==='not_exists')return !String(actual).trim();if(r.operator==='contains')return String(actual).toLowerCase().includes(String(expected).toLowerCase());return String(actual)===String(expected)}
function answers(){const a={};new FormData(f).forEach((v,k)=>{if(a[k]!==undefined)a[k]=[].concat(a[k],String(v));else a[k]=String(v)});for(const q of D.questions.filter(x=>x.type==='multi_select')){if(a[q.id]===undefined)a[q.id]=[];else if(!Array.isArray(a[q.id]))a[q.id]=[a[q.id]]}return a}
function applyRules(){const a=answers();for(const q of D.questions){const wrap=nodes[q.id];if(!wrap)continue;const show=visible(q,a);wrap.classList.toggle('hidden',!show);const el=wrap.querySelector('[name="'+q.id+'"]');if(el)el.required=!!q.required&&show}}
let lastSection=null;for(const q of D.questions){const sectionKey=q.sectionId||q.sectionTitle||'Questions';if(sectionKey!==lastSection){lastSection=sectionKey;const section=document.createElement('div');section.className='section';const sh=document.createElement('h2');sh.textContent=q.sectionTitle||'Questions';section.appendChild(sh);if(q.sectionDescription){const sd=document.createElement('p');sd.textContent=q.sectionDescription;section.appendChild(sd)}f.appendChild(section)}const wrap=document.createElement('div');wrap.className='q';wrap.dataset.qid=q.id;nodes[q.id]=wrap;const l=document.createElement('label');l.htmlFor='q_'+q.id;l.append(document.createTextNode(q.label));const r=document.createElement('span');r.className='req';r.textContent=q.required?'Required':'Optional';l.appendChild(r);wrap.appendChild(l);let e;if(q.type==='textarea'||q.type==='address'){e=document.createElement('textarea')}else if(q.type==='select'||q.type==='boolean'){e=document.createElement('select')}else if(q.type==='multi_select'){e=document.createElement('div');e.className='checks';for(const o of q.options||[]){const x=document.createElement('input');x.type='checkbox';x.name=q.id;x.value=o;const ll=document.createElement('label');ll.appendChild(x);ll.append(document.createTextNode(o));e.appendChild(ll)}}else{e=document.createElement('input');e.type=q.type==='file'?'file':({email:'email',phone:'tel',date:'date',number:'number',currency:'number'}[q.type]||'text');if(q.type==='currency')e.step='0.01'}if(e.tagName!=='DIV'){e.id='q_'+q.id;e.name=q.id;e.required=!!q.required;e.setAttribute('aria-required',q.required?'true':'false');const v=q.validation||{};if(v.minLength!==undefined)e.minLength=Number(v.minLength);if(v.maxLength!==undefined)e.maxLength=Number(v.maxLength);if(v.pattern)e.pattern=String(v.pattern);if((q.type==='number'||q.type==='currency')&&v.minValue!==undefined)e.min=String(v.minValue);if((q.type==='number'||q.type==='currency')&&v.maxValue!==undefined)e.max=String(v.maxValue);if(q.type==='file'&&Array.isArray(v.allowedExtensions))e.accept=v.allowedExtensions.join(',')}if(q.type==='select'){const blank=document.createElement('option');blank.value='';blank.textContent='Select…';e.appendChild(blank);for(const o of q.options||[]){const op=document.createElement('option');op.value=o;op.textContent=o;e.appendChild(op)}}if(q.type==='boolean'){for(const o of ['', 'Yes','No']){const op=document.createElement('option');op.value=o;op.textContent=o||'Select…';e.appendChild(op)}}wrap.appendChild(e);if(q.helpText){const hs=document.createElement('small');hs.textContent=q.helpText;wrap.appendChild(hs)}f.appendChild(wrap)}
f.addEventListener('change',applyRules);f.addEventListener('input',applyRules);const b=document.createElement('button');b.type='submit';b.textContent='Send to lawyer';f.appendChild(b);function showErrors(ids,message){const labels=ids.map(id=>{const q=D.questions.find(x=>x.id===id);return q?q.label:id});err.replaceChildren();const strong=document.createElement('b');strong.textContent=String(message||'Please review these answers.');err.appendChild(strong);if(labels.length){const ul=document.createElement('ul');for(const label of labels){const li=document.createElement('li');li.textContent=String(label);ul.appendChild(li)}err.appendChild(ul)}err.style.display='block';err.focus();const first=ids[0]&&document.getElementById('q_'+ids[0]);if(first)first.setAttribute('aria-invalid','true')}
f.onsubmit=async ev=>{ev.preventDefault();err.style.display='none';applyRules();for(const el of f.elements)if(el.removeAttribute)el.removeAttribute('aria-invalid');const a=answers();const missing=D.questions.filter(q=>visible(q,a)&&q.required&&!String(a[q.id]||'').trim()&&q.type!=='file').map(q=>q.id);if(missing.length){showErrors(missing,missing.length+' required answer'+(missing.length===1?' needs':'s need')+' attention');return}b.disabled=true;try{for(const q of D.questions.filter(x=>x.type==='file')){const input=document.getElementById('q_'+q.id);if(input&&input.files&&input.files[0]){const fd=new FormData();fd.append('file',input.files[0]);const up=await fetch('/api/intake/public/'+TOKEN+'/files/'+q.id,{method:'POST',body:fd});if(!up.ok)throw new Error('File upload failed for '+q.label);const meta=await up.json();a[q.id]=meta.filename}}const response=await fetch('/api/intake/public/'+TOKEN+'/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answers:a})});if(response.ok){app.innerHTML='<h1>Submitted</h1><p>Your lawyer has received your information for review.</p>';return}let body={};try{body=await response.json()}catch{};const detail=body.detail||{};showErrors(detail.fields||[],detail.message||'Please review the highlighted answers.')}catch(e){showErrors([],e.message||'Submission failed. Please try again.')}finally{b.disabled=false}};app.appendChild(f);applyRules();
</script></body></html>""".replace("__PAYLOAD__",payload).replace("__NONCE__",getattr(request.state,"csp_nonce",""))
    return HTMLResponse(html)


@router.get("/api/intake/{token}/files/{question_id}",dependencies=[Depends(api_auth)])
async def download_intake_file(token:str,question_id:str):
    from urllib.parse import quote
    row=await service.download_file(token,question_id)
    filename=quote(str(row['filename']),safe='')
    return Response(
        content=bytes(row['content']),
        media_type=row['mime_type'] or 'application/octet-stream',
        headers={
            "Content-Disposition":f"attachment; filename*=UTF-8''{filename}",
            "Content-Length":str(row['size_bytes']),
        },
    )

@router.post("/api/intake/{token}/revoke",dependencies=[Depends(api_auth)])
async def revoke_intake(token:str):
    tag=await db.p().execute("UPDATE intake_sessions SET status='revoked',revoked_at=NOW() WHERE token_hash=$1",bearer_token_hash(token))
    if not tag.endswith('0'):return {"revoked":True}
    tag=await db.p().execute("UPDATE intake_forms SET revoked_at=NOW() WHERE token_hash=$1",bearer_token_hash(token))
    if tag.endswith('0'):raise HTTPException(404,"Intake form not found")
    return {"revoked":True}
