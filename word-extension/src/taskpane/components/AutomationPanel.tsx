import * as React from "react";
import { useEffect, useState } from "react";
import { Button, Input, Textarea } from "@fluentui/react-components";
import type { TemplateAutomationBlueprint, WorkflowDefinition, WorkflowSummary } from "../../services/types";
import {
  applyWorkflowSessionToMatter, approveWorkflowSessionForGeneration, bootstrapTemplateAutomation, createWorkflow, generateHeadless, getTemplateAutomation, getWorkflow, listWorkflows,
  preflightTemplateAutomation, publishTemplateAutomation, publishWorkflow, saveTemplateAutomation, startWorkflowSession, updateWorkflow,
} from "../../services/autodraftWorkspaceService";
import { listTemplates, type TemplateSummary } from "../../services/templateService";
import { createAutomationRegion } from "../../services/word/automationRegionService";
import { openDocumentFromBase64 } from "../../services/word/documentSnapshot";

const box:React.CSSProperties={border:"1px solid #d8d8d8",borderRadius:8,padding:12,marginTop:12};
const row:React.CSSProperties={display:"flex",gap:8,flexWrap:"wrap",marginTop:8};
const select:React.CSSProperties={width:"100%",padding:8,border:"1px solid #c8c8c8",borderRadius:6,background:"white"};
const emptyBlueprint=():TemplateAutomationBlueprint=>({bindings:[],conditions:[],repeaters:[],retainControls:false});
const emptyWorkflow=():WorkflowDefinition=>({pages:[{id:"matter_details",title:"Matter details",questions:[]}],calculations:[]});

export default function AutomationPanel({matterId}:{matterId?:string}){
  const [workflows,setWorkflows]=useState<WorkflowSummary[]>([]);const [workflowId,setWorkflowId]=useState("");const [workflowName,setWorkflowName]=useState("Matter automation");
  const [workflowJson,setWorkflowJson]=useState(JSON.stringify(emptyWorkflow(),null,2));const [shareUrl,setShareUrl]=useState("");const [workflowSessionId,setWorkflowSessionId]=useState("");
  const [templates,setTemplates]=useState<TemplateSummary[]>([]);const [templateId,setTemplateId]=useState("");const [blueprint,setBlueprint]=useState<TemplateAutomationBlueprint>(emptyBlueprint());const [blueprintText,setBlueprintText]=useState(JSON.stringify(emptyBlueprint(),null,2));
  const [conditionJson,setConditionJson]=useState('{"eq":[{"field":"party.accused.type"},{"literal":"company"}]}');const [collectionKey,setCollectionKey]=useState("cheques");
  const [notice,setNotice]=useState("");const [error,setError]=useState("");
  const refresh=async()=>{const [w,t]=await Promise.all([listWorkflows(),listTemplates()]);setWorkflows(w.workflows||[]);setTemplates(t.templates||[]);};
  useEffect(()=>{void refresh().catch(e=>setError(e instanceof Error?e.message:String(e)));},[]);
  const selectedWorkflow=async(id:string)=>{setWorkflowId(id);if(!id)return;const d=await getWorkflow(id);setWorkflowName(d.workflow.name);setWorkflowJson(JSON.stringify((d.latestVersion?.definition||emptyWorkflow()),null,2));};
  const parseWorkflow=():WorkflowDefinition=>JSON.parse(workflowJson) as WorkflowDefinition;
  const saveWorkflow=async()=>{setError("");try{const definition=parseWorkflow();if(workflowId){await updateWorkflow(workflowId,{name:workflowName,definition});setNotice("Workflow draft saved as a new/updated immutable-version draft.");}else{const r=await createWorkflow({name:workflowName,audience:"both",definition});setWorkflowId(r.workflow.id);setNotice("Workflow created.");}await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const doPublishWorkflow=async()=>{if(!workflowId)return;try{await publishWorkflow(workflowId);setNotice("Workflow published. Future sessions are pinned to this version.");await refresh();}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const runWorkflow=async()=>{if(!workflowId)return;try{const r=await startWorkflowSession(workflowId,{matterId,expiresInDays:30});setWorkflowSessionId(r.session.id);setShareUrl(r.shareUrl||"");setNotice(r.shareUrl?"Client/internal workflow session created.":"Internal workflow session created.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const approveWorkflowData=async()=>{if(!workflowSessionId)return;try{await approveWorkflowSessionForGeneration(workflowSessionId);setNotice("Completed workflow session approved for authoritative generation.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const applyWorkflowData=async()=>{if(!workflowSessionId||!matterId)return;try{const r=await applyWorkflowSessionToMatter(workflowSessionId);setNotice(`Applied ${r.applied.length} reviewed workflow value${r.applied.length===1?"":"s"} to the matter; ${r.skipped.length} unmapped and ${r.rejected.length} rejected.`);}catch(e){setError(e instanceof Error?e.message:String(e));}};

  const setBlueprintState=(next:TemplateAutomationBlueprint)=>{setBlueprint(next);setBlueprintText(JSON.stringify(next,null,2));};
  const parseBlueprint=():TemplateAutomationBlueprint=>JSON.parse(blueprintText) as TemplateAutomationBlueprint;
  const selectTemplate=async(id:string)=>{setTemplateId(id);if(!id){setBlueprintState(emptyBlueprint());return;}try{const r=await getTemplateAutomation(id);setBlueprintState(r.blueprint||emptyBlueprint());}catch{setBlueprintState(emptyBlueprint());}};
  const bootstrap=async()=>{if(!templateId)return;try{const r=await bootstrapTemplateAutomation(templateId);setBlueprintState(r.blueprint);setNotice(`Mapped ${r.blueprint.bindings.length} existing Word bindings; ${r.unmapped.length} need semantic mapping.`);}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const persistBlueprint=async()=>{if(!templateId)return;try{const next=parseBlueprint();await saveTemplateAutomation(templateId,next);setBlueprintState(next);setNotice("Automation blueprint saved.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const addCondition=async()=>{try{const current=parseBlueprint();const expression=JSON.parse(conditionJson);const regionTag=await createAutomationRegion("condition","AutoDraft condition");const next={...current,conditions:[...current.conditions,{regionTag,expression}]};setBlueprintState(next);if(templateId)await saveTemplateAutomation(templateId,next);setNotice("Selected Word region is now conditional.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const addRepeater=async()=>{if(!collectionKey.trim())return;try{const current=parseBlueprint();const regionTag=await createAutomationRegion("repeat","AutoDraft repeating item");const next={...current,repeaters:[...current.repeaters,{regionTag,collectionKey:collectionKey.trim()}]};setBlueprintState(next);if(templateId)await saveTemplateAutomation(templateId,next);setNotice("Selected Word region is now a repeating region. Nest another repeating region inside it for nested lists.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const preflight=async()=>{if(!templateId)return;try{const next=parseBlueprint();const r=await preflightTemplateAutomation(templateId,next);setBlueprintState(next);setNotice(r.ready?"Template automation preflight passed.":r.issues.map(i=>i.message).join(" | "));}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const publish=async()=>{if(!templateId)return;try{const next=parseBlueprint();await saveTemplateAutomation(templateId,next);await publishTemplateAutomation(templateId);setBlueprintState(next);setNotice("Automation published against the current immutable template version.");}catch(e){setError(e instanceof Error?e.message:String(e));}};
  const generate=async()=>{if(!templateId)return;try{const r=await generateHeadless({matterId,templateId,saveToMatter:Boolean(matterId)});if(r.artifacts[0])await openDocumentFromBase64(r.artifacts[0].docxBase64);setNotice(`Generated ${r.artifacts.length} DOCX document${r.artifacts.length===1?"":"s"} headlessly.`);}catch(e){setError(e instanceof Error?e.message:String(e));}};

  return <div style={box}>
    <h3 style={{marginTop:0}}>Workflow & document automation</h3>
    <p style={{fontSize:12,color:"#666"}}>Gavel-style versioned workflows, branching/calculations, repeaters, template preflight and headless DOCX generation. Rules use canonical semantic field keys.</p>
    {error&&<div style={{color:"#a4262c",fontSize:12,marginBottom:8}}>{error}</div>}{notice&&<div style={{color:"#0b6a0b",fontSize:12,marginBottom:8}}>{notice}</div>}
    <div style={box}><b>Workflow builder</b>
      <select style={select} value={workflowId} onChange={e=>void selectedWorkflow(e.target.value)}><option value="">New workflow</option>{workflows.map(w=><option key={w.id} value={w.id}>{w.name} · {w.status}</option>)}</select>
      <Input style={{width:"100%",marginTop:8}} value={workflowName} onChange={(_,d)=>setWorkflowName(d.value)} placeholder="Workflow name"/>
      <Textarea style={{width:"100%",marginTop:8,minHeight:180,fontFamily:"monospace"}} value={workflowJson} onChange={(_,d)=>setWorkflowJson(d.value)} />
      <div style={row}><Button onClick={()=>void saveWorkflow()}>Save draft</Button><Button disabled={!workflowId} onClick={()=>void doPublishWorkflow()}>Publish version</Button><Button disabled={!workflowId} onClick={()=>void runWorkflow()}>Start session</Button><Button disabled={!workflowSessionId} onClick={()=>void approveWorkflowData()}>Approve for generation</Button><Button disabled={!workflowSessionId||!matterId} onClick={()=>void applyWorkflowData()}>Apply completed session to matter</Button></div>
      {shareUrl&&<Input style={{width:"100%",marginTop:8}} value={shareUrl} readOnly/>}
    </div>
    <div style={box}><b>Word template automation</b>
      <select style={select} value={templateId} onChange={e=>void selectTemplate(e.target.value)}><option value="">Select template</option>{templates.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</select>
      <div style={row}><Button disabled={!templateId} onClick={()=>void bootstrap()}>Map existing fields</Button><Button disabled={!templateId} onClick={()=>void persistBlueprint()}>Save blueprint</Button><Button disabled={!templateId} onClick={()=>void preflight()}>Preflight</Button><Button disabled={!templateId} onClick={()=>void publish()}>Publish automation</Button></div>
      <label style={{display:"block",fontSize:12,marginTop:10}}>Condition expression (JSON)</label><Textarea style={{width:"100%",fontFamily:"monospace"}} value={conditionJson} onChange={(_,d)=>setConditionJson(d.value)}/><Button style={{marginTop:6}} disabled={!templateId} onClick={()=>void addCondition()}>Wrap selected Word region as condition</Button>
      <label style={{display:"block",fontSize:12,marginTop:10}}>Repeating collection semantic key</label><Input style={{width:"100%"}} value={collectionKey} onChange={(_,d)=>setCollectionKey(d.value)}/><Button style={{marginTop:6}} disabled={!templateId} onClick={()=>void addRepeater()}>Wrap selected Word region as repeater</Button>
      <details style={{marginTop:10}}><summary>Automation blueprint</summary><Textarea style={{width:"100%",minHeight:180,fontFamily:"monospace"}} value={blueprintText} onChange={(_,d)=>setBlueprintText(d.value)}/></details>
      <Button style={{marginTop:10}} appearance="primary" disabled={!templateId} onClick={()=>void generate()}>Headless generate DOCX</Button>
    </div>
  </div>;
}
