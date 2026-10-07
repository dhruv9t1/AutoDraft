from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse

from ..auth import require_role
from ..db import set_request_organization
from ..domain.workflows import WorkflowAnswerValidationError, WorkflowDefinitionError, WorkflowEvaluationError, evaluate_workflow
from ..models import WorkflowCreateRequest, WorkflowSessionCreateRequest, WorkflowSessionUpdateRequest, WorkflowUpdateRequest
from ..repositories.workflows import WorkflowRepository
from ..repositories.fields import FieldRepository
from ..runtime import api_auth, db, utc_iso
from ..pagination import decode_cursor,page_rows

router=APIRouter(tags=["workflows"])
repo=WorkflowRepository(db)
field_repo=FieldRepository(db)

async def admin_auth(ctx=Depends(api_auth)):
    require_role(ctx,"admin");return ctx

async def lawyer_auth(ctx=Depends(api_auth)):
    require_role(ctx,"lawyer");return ctx

def answer_validation_http(exc:WorkflowAnswerValidationError):
    return HTTPException(422,detail={"message":"Workflow answers failed schema validation","fields":exc.errors})

def evaluation_http(exc:WorkflowEvaluationError):
    return HTTPException(422,detail={"message":"Published workflow logic could not be evaluated safely","error":str(exc)})

def uid(value:str|None,label:str)->uuid.UUID|None:
    if value is None:return None
    try:return uuid.UUID(value)
    except ValueError as exc:raise HTTPException(400,f"Invalid {label} ID") from exc

def workflow_row(row):
    return {"id":str(row['id']),"name":row['name'],"description":row['description'],"audience":row['audience'],"practiceAreaId":str(row['practice_area_id']) if row['practice_area_id'] else None,"matterType":row['matter_type'],"status":row['status'],"currentVersion":row['current_version'],"createdAt":utc_iso(row['created_at']),"updatedAt":utc_iso(row['updated_at'])}

def version_row(row,include_definition=False):
    data={"id":str(row['id']),"workflowId":str(row['workflow_id']),"version":row['version_number'],"status":row['status'],"publishedAt":utc_iso(row['published_at']) if row['published_at'] else None,"createdAt":utc_iso(row['created_at'])}
    if include_definition:data['definition']=row['definition']
    return data

def evaluation_payload(evaluation):
    return {"calculations":evaluation.calculations,"visiblePages":evaluation.visible_pages,"missingRequired":evaluation.missing_required,"complete":evaluation.complete}

def session_row(row):
    return {"id":str(row['id']),"workflowVersionId":str(row['workflow_version_id']),"matterId":str(row['matter_id']) if row['matter_id'] else None,"status":row['status'],"answers":row['answers'] or {},"calculations":row['calculations'] or {},"currentPage":row['current_page'],"metadata":row['metadata'] or {},"expiresAt":utc_iso(row['expires_at']) if row['expires_at'] else None,"completedAt":utc_iso(row['completed_at']) if row['completed_at'] else None,"createdAt":utc_iso(row['created_at']),"updatedAt":utc_iso(row['updated_at'])}

@router.get('/api/workflows',dependencies=[Depends(api_auth)])
async def list_workflows(limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None)):
    t,i=decode_cursor(cursor);rows=await repo.list(limit=limit,cursor_updated_at=t,cursor_id=i);items,next_cursor=page_rows(rows,limit)
    return {'workflows':[workflow_row(r) for r in items],'nextCursor':next_cursor}

@router.post('/api/workflows',dependencies=[Depends(admin_auth)])
async def create_workflow(req:WorkflowCreateRequest):
    if not req.name.strip():raise HTTPException(400,'Workflow name is required')
    try:result=await repo.create({'name':req.name.strip(),'description':req.description.strip(),'audience':req.audience,'practice_area_id':uid(req.practice_area_id,'practice area'),'matter_type':req.matter_type.strip(),'definition':req.definition})
    except WorkflowDefinitionError as exc:raise HTTPException(422,str(exc)) from exc
    if not result:raise HTTPException(404,'Practice area not found')
    row,version=result;return {'workflow':workflow_row(row),'draftVersion':version_row(version,True)}

@router.get('/api/workflows/{workflow_id}',dependencies=[Depends(api_auth)])
async def get_workflow(workflow_id:str):
    result=await repo.get(uid(workflow_id,'workflow'))
    if not result:raise HTTPException(404,'Workflow not found')
    row,versions,latest=result
    return {'workflow':workflow_row(row),'versions':[version_row(v) for v in versions],'latestVersion':version_row(latest,True) if latest else None}

@router.patch('/api/workflows/{workflow_id}',dependencies=[Depends(admin_auth)])
async def update_workflow(workflow_id:str,req:WorkflowUpdateRequest):
    data=req.model_dump(exclude_unset=True)
    if 'practice_area_id' in data:data['practice_area_id']=uid(data['practice_area_id'],'practice area') if data['practice_area_id'] else None
    if data.get('name') is not None:data['name']=data['name'].strip()
    try:result=await repo.update(uid(workflow_id,'workflow'),data,set(data.keys()))
    except WorkflowDefinitionError as exc:raise HTTPException(422,str(exc)) from exc
    if not result:raise HTTPException(404,'Workflow or practice area not found')
    row,version=result;return {'workflow':workflow_row(row),'draftVersion':version_row(version,True)}

@router.post('/api/workflows/{workflow_id}/publish',dependencies=[Depends(admin_auth)])
async def publish_workflow(workflow_id:str):
    try:row=await repo.publish(uid(workflow_id,'workflow'))
    except WorkflowDefinitionError as exc:raise HTTPException(422,str(exc)) from exc
    if not row:raise HTTPException(404,'Workflow not found')
    return version_row(row,True)

@router.post('/api/workflows/{workflow_id}/sessions',dependencies=[Depends(api_auth)])
async def start_workflow_session(workflow_id:str,req:WorkflowSessionCreateRequest,request:Request):
    result=await repo.create_session(uid(workflow_id,'workflow'),matter_id=uid(req.matter_id,'matter') if req.matter_id else None,expires_days=req.expires_in_days,metadata=req.metadata)
    if not result:raise HTTPException(404,'Published workflow or matter not found')
    row,workflow,version,token=result
    payload={'session':session_row(row),'workflow':workflow_row(workflow),'version':version_row(version,True)}
    if token:payload['shareUrl']=str(request.base_url).rstrip('/')+f'/workflow/{token}';payload['token']=token
    return payload


@router.get('/api/workflow-sessions',dependencies=[Depends(api_auth)])
async def list_workflow_sessions(limit:int=Query(default=50,ge=1,le=200),cursor:str|None=Query(default=None),workflowId:str|None=Query(default=None),matterId:str|None=Query(default=None),status:str|None=Query(default=None)):
    if status and status not in {'in_progress','completed','abandoned'}:raise HTTPException(400,'Invalid workflow session status')
    t,i=decode_cursor(cursor);rows=await repo.list_sessions(limit=limit,cursor_updated_at=t,cursor_id=i,workflow_id=uid(workflowId,'workflow') if workflowId else None,matter_id=uid(matterId,'matter') if matterId else None,status=status)
    items,next_cursor=page_rows(rows,limit)
    return {'sessions':[{'id':str(r['id']),'workflowId':str(r['workflow_id']),'workflowVersionId':str(r['workflow_version_id']),'workflowVersion':r['version_number'],'workflowName':r['workflow_name'],'audience':r['audience'],'matterId':str(r['matter_id']) if r['matter_id'] else None,'status':r['status'],'currentPage':r['current_page'],'expiresAt':utc_iso(r['expires_at']) if r['expires_at'] else None,'completedAt':utc_iso(r['completed_at']) if r['completed_at'] else None,'createdAt':utc_iso(r['created_at']),'updatedAt':utc_iso(r['updated_at'])} for r in items],'nextCursor':next_cursor}

@router.get('/api/workflow-sessions/{session_id}',dependencies=[Depends(api_auth)])
async def get_workflow_session(session_id:str):
    row=await repo.session(uid(session_id,'workflow session'))
    if not row:raise HTTPException(404,'Workflow session not found')
    base=await repo.data.matter_data(row['matter_id']);base.update(dict(row['answers'] or {}))
    try:evaluation=evaluate_workflow(row['definition'],base)
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    return {'session':session_row(row),'workflow':{'id':str(row['workflow_id']),'name':row['name'],'audience':row['audience']},'version':row['version_number'],'definition':row['definition'],'evaluation':evaluation_payload(evaluation)}

@router.patch('/api/workflow-sessions/{session_id}',dependencies=[Depends(api_auth)])
async def update_workflow_session(session_id:str,req:WorkflowSessionUpdateRequest):
    try:result=await repo.update_session(uid(session_id,'workflow session'),answers=req.answers,current_page=req.current_page,metadata=req.metadata)
    except WorkflowAnswerValidationError as exc:raise answer_validation_http(exc) from exc
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    if not result:raise HTTPException(409,'Workflow session is missing or no longer editable')
    row,_,evaluation=result;return {'session':session_row(row),'evaluation':evaluation_payload(evaluation)}

@router.post('/api/workflow-sessions/{session_id}/complete',dependencies=[Depends(api_auth)])
async def complete_workflow_session(session_id:str):
    try:result=await repo.complete_session(uid(session_id,'workflow session'))
    except WorkflowAnswerValidationError as exc:raise answer_validation_http(exc) from exc
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    if not result:raise HTTPException(409,'Workflow session is missing or no longer editable')
    if result.get('missing') is not None:raise HTTPException(422,detail={'message':'Required workflow answers are missing','fields':result['missing']})
    return {'session':session_row(result['row']),'evaluation':evaluation_payload(result['evaluation'])}

@router.post('/api/workflow-sessions/{session_id}/approve-for-generation')
async def approve_workflow_session_for_generation(session_id:str,ctx=Depends(lawyer_auth)):
    row=await repo.approve_for_generation(uid(session_id,'workflow session'),user_id=ctx.user_id)
    if not row:raise HTTPException(409,'Workflow session must be completed before approval')
    return {'approved':True,'session':session_row(row)}

@router.post('/api/workflow-sessions/{session_id}/apply-to-matter',dependencies=[Depends(lawyer_auth)])
async def apply_workflow_session_to_matter(session_id:str):
    """Explicitly promote completed workflow data into canonical matter fields.

    Client/internal workflow answers are intentionally *not* written to matter data
    on completion.  A lawyer invokes this endpoint after review.  Only semantic keys
    that already have active matter-scoped field definitions are eligible; AutoDraft
    never invents canonical fields from unreviewed workflow input.
    """
    sid=uid(session_id,'workflow session')
    row=await repo.session(sid)
    if not row:raise HTTPException(404,'Workflow session not found')
    if row['status']!='completed':raise HTTPException(409,'Workflow session must be completed before applying data')
    if not row['matter_id']:raise HTTPException(409,'Workflow session is not attached to a matter')
    definitions=await field_repo.definitions(scope='matter',include_inactive=False)
    by_key={str(d['semantic_key']):d for d in definitions}
    values={**dict(row['answers'] or {}),**dict(row['calculations'] or {})}
    applied=[];conflicts=[];skipped=[];rejected=[]
    for key,value in values.items():
        definition=by_key.get(str(key))
        if not definition:
            skipped.append({'semanticKey':str(key),'reason':'No active matter field definition'})
            continue
        try:
            result=await field_repo.propose_matter_value(
                row['matter_id'],definition['id'],value=value,source='workflow',status='confirmed',
                provenance={'workflowSessionId':str(sid),'workflowId':str(row['workflow_id']),'workflowVersion':row['version_number']},
            )
        except ValueError as exc:
            rejected.append({'semanticKey':str(key),'reason':str(exc)})
            continue
        if result:
            if result.get('status')=='conflict':
                conflicts.append({'semanticKey':str(key),'fieldDefinitionId':str(definition['id']),'conflictId':str(result['conflict_id'])})
            else:
                applied.append({'semanticKey':str(key),'fieldDefinitionId':str(definition['id'])})
    return {'matterId':str(row['matter_id']),'applied':applied,'conflicts':conflicts,'skipped':skipped,'rejected':rejected}

async def _public(raw_token:str):
    row=await repo.public_session(raw_token)
    if not row:raise HTTPException(404,'Workflow session not found')
    if row.get('expired'):raise HTTPException(410,'Workflow session expired')
    set_request_organization(str(row['organization_id']))
    return row

@router.get('/api/workflows/public/{token}')
async def public_workflow(token:str):
    row=await _public(token)
    if row['status']!='in_progress':return {'status':row['status'],'workflow':{'name':row['name']},'sessionId':str(row['id'])}
    base=await repo.data.matter_data(row['matter_id']);base.update(dict(row['answers'] or {}))
    try:evaluation=evaluate_workflow(row['definition'],base)
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    return {'status':row['status'],'workflow':{'name':row['name'],'version':row['version_number']},'sessionId':str(row['id']),'answers':row['answers'] or {},'evaluation':evaluation_payload(evaluation)}

@router.patch('/api/workflows/public/{token}')
async def update_public_workflow(token:str,req:WorkflowSessionUpdateRequest):
    row=await _public(token)
    try:result=await repo.update_session(row['id'],answers=req.answers,current_page=req.current_page,metadata={})
    except WorkflowAnswerValidationError as exc:raise answer_validation_http(exc) from exc
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    if not result:raise HTTPException(409,'Workflow session is no longer editable')
    updated,_,evaluation=result;return {'session':session_row(updated),'evaluation':evaluation_payload(evaluation)}

@router.post('/api/workflows/public/{token}/complete')
async def complete_public_workflow(token:str):
    row=await _public(token)
    try:result=await repo.complete_session(row['id'])
    except WorkflowAnswerValidationError as exc:raise answer_validation_http(exc) from exc
    except WorkflowEvaluationError as exc:raise evaluation_http(exc) from exc
    if not result:raise HTTPException(409,'Workflow session is no longer editable')
    if result.get('missing') is not None:raise HTTPException(422,detail={'message':'Required workflow answers are missing','fields':result['missing']})
    return {'completed':True,'evaluation':evaluation_payload(result['evaluation'])}


@router.get('/workflow/{token}',response_class=HTMLResponse)
async def public_workflow_page(token:str, request:Request):
    # The page never embeds lawyer/client values in HTML. It loads the token-scoped
    # JSON endpoint and renders labels with textContent to avoid HTML injection.
    html="""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>AutoDraft Workflow</title><style>
body{font-family:system-ui;background:#f5f6f8;color:#202124;margin:0}main{max-width:820px;margin:30px auto;background:white;padding:26px;border-radius:12px;box-shadow:0 2px 14px #0001}.page{border-top:1px solid #eee;padding-top:18px;margin-top:18px}.q{margin:14px 0}label{display:block;font-weight:650;margin-bottom:5px}input,textarea,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cbd5e1;border-radius:6px}textarea{min-height:100px}.repeat{border:1px solid #d7e2ee;border-radius:8px;padding:10px;margin:8px 0}.row{display:flex;gap:8px;flex-wrap:wrap}button{border:0;border-radius:7px;padding:10px 14px;background:#0f6cbd;color:white;font-weight:650;cursor:pointer}button.secondary{background:#e8eef5;color:#123}.muted{color:#667085;font-size:12px}.error{color:#a4262c}.ok{color:#137333}</style></head><body><main><h1 id='title'>Loading…</h1><div id='status' class='muted'></div><div id='form'></div><div class='row'><button id='save'>Save & refresh logic</button><button id='complete'>Complete workflow</button></div><p id='message'></p></main><script nonce='__NONCE__'>
const TOKEN=decodeURIComponent(location.pathname.split('/').filter(Boolean).pop()||'');let state={answers:{},evaluation:null};const $=id=>document.getElementById(id);
const api=async(path,opts={})=>{const r=await fetch(path,{headers:{'Content-Type':'application/json'},...opts});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail?.message||j.detail||j.error?.message||('Request failed '+r.status));return j};
function optionParts(o){if(o&&typeof o==='object'&&!Array.isArray(o)){let v;for(const k of['value','id','key','label']){if(Object.prototype.hasOwnProperty.call(o,k)){v=o[k];break}}const label=Object.prototype.hasOwnProperty.call(o,'label')?o.label:v;return {value:String(v??''),label:String(label??'')}}return {value:String(o??''),label:String(o??'')}}
function inputFor(q,get,set){if(q.type==='display'){const p=document.createElement('p');p.textContent=q.helpText||q.label;return p}if(q.type==='boolean'){const i=document.createElement('input');i.type='checkbox';i.checked=Boolean(get());i.style.width='auto';i.onchange=()=>set(i.checked);return i}if(q.type==='select'||q.type==='multi_select'){const s=document.createElement('select');s.multiple=q.type==='multi_select';const selected=Array.isArray(get())?get().map(x=>String(x)):[];for(const o of(q.options||[])){const n=optionParts(o);const op=document.createElement('option');op.value=n.value;op.textContent=n.label;if(q.type==='multi_select'&&selected.includes(n.value))op.selected=true;if(q.type==='select'&&String(get()??'')===n.value)op.selected=true;s.appendChild(op)}s.onchange=()=>set(s.multiple?Array.from(s.selectedOptions).map(x=>x.value):s.value);return s}const i=document.createElement(q.type==='textarea'?'textarea':'input');if(i.tagName==='INPUT')i.type=({date:'date',datetime:'datetime-local',number:'number',currency:'number',email:'email',phone:'tel'}[q.type]||'text');i.value=get()??'';i.oninput=()=>set(i.value);return i}
function renderQuestion(q,container,object){const wrap=document.createElement('div');wrap.className='q';const lab=document.createElement('label');lab.textContent=q.label+(q.required?' *':'');wrap.appendChild(lab);if(q.helpText){const sm=document.createElement('div');sm.className='muted';sm.textContent=q.helpText;wrap.appendChild(sm)}const key=q.semanticKey;if(q.type==='repeater'){let arr=Array.isArray(object[key])?object[key]:[];const holder=document.createElement('div');const repaint=()=>{holder.innerHTML='';arr.forEach((item,idx)=>{const box=document.createElement('div');box.className='repeat';const top=document.createElement('div');top.className='row';const txt=document.createElement('strong');txt.textContent=(q.label||'Item')+' '+(idx+1);const rem=document.createElement('button');rem.className='secondary';rem.textContent='Remove';rem.onclick=()=>{arr.splice(idx,1);object[key]=arr;repaint()};top.append(txt,rem);box.appendChild(top);for(const child of(q.children||[]))renderQuestion(child,box,item);holder.appendChild(box)});const add=document.createElement('button');add.className='secondary';add.textContent='Add '+(q.label||'item');add.onclick=()=>{arr.push({});object[key]=arr;repaint()};holder.appendChild(add)};repaint();wrap.appendChild(holder)}else wrap.appendChild(inputFor(q,()=>object[key],v=>object[key]=v));container.appendChild(wrap)}
function render(data){$('title').textContent=data.workflow?.name||'Workflow';$('status').textContent=data.status==='in_progress'?'You can save and return before completion.':'Status: '+data.status;state.answers=data.answers||state.answers||{};state.evaluation=data.evaluation||state.evaluation;const form=$('form');form.innerHTML='';for(const page of(state.evaluation?.visiblePages||[])){const box=document.createElement('section');box.className='page';const h=document.createElement('h2');h.textContent=page.title||page.id;box.appendChild(h);if(page.description){const p=document.createElement('p');p.className='muted';p.textContent=page.description;box.appendChild(p)}for(const q of(page.questions||[]))renderQuestion(q,box,state.answers);form.appendChild(box)}}
async function load(){try{const data=await api('/api/workflows/public/'+TOKEN);if(data.status!=='in_progress'){render(data);$('save').disabled=true;$('complete').disabled=true;return}render(data)}catch(e){$('message').className='error';$('message').textContent=e.message}}
$('save').onclick=async()=>{try{const r=await api('/api/workflows/public/'+TOKEN,{method:'PATCH',body:JSON.stringify({answers:state.answers})});state.evaluation=r.evaluation;render({workflow:{name:$('title').textContent},status:'in_progress',answers:r.session.answers,evaluation:r.evaluation});$('message').className='ok';$('message').textContent='Saved.'}catch(e){$('message').className='error';$('message').textContent=e.message}};
$('complete').onclick=async()=>{try{await api('/api/workflows/public/'+TOKEN,{method:'PATCH',body:JSON.stringify({answers:state.answers})});await api('/api/workflows/public/'+TOKEN+'/complete',{method:'POST'});$('message').className='ok';$('message').textContent='Completed. Your responses were submitted.';$('save').disabled=true;$('complete').disabled=true}catch(e){$('message').className='error';$('message').textContent=e.message}};load();
</script></body></html>"""
    return HTMLResponse(html.replace("__NONCE__",getattr(request.state,"csp_nonce","")))
