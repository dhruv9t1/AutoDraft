import { apiRequest } from "./api/apiClient";
import { API_BASE_URL, apiHeaders } from "./config";
import type {
  DraftingResponse,
  IntakeDefinition,
  MatterDetail,
  MatterSummary,
  MatterDocument,
  VerificationReport,
  Variable,
} from "./types";

export function verifyFinalDocument(
  documentContent: string,
  variables: Variable[],
  currentValues: Record<string, string>,
  legalMode = true
) {
  return apiRequest<VerificationReport>("/api/documents/verify", {
    method: "POST",
    body: JSON.stringify({ documentContent, variables, currentValues, legalMode }),
  });
}

export function draftingChat(input: {
  message: string;
  matterType: string;
  facts: Record<string, string>;
  researchOptIn: boolean;
  mode?: "answer" | "complete_document";
  conversation?: Array<{ role: "user" | "assistant"; content: string }>;
  retrievedAuthorities?: Array<{
    title: string;
    citation?: string;
    court?: string;
    date?: string;
    sourceUrl?: string;
    excerpt?: string;
  }>;
}) {
  return apiRequest<DraftingResponse>("/api/drafting/chat", {
    method: "POST",
    body: JSON.stringify({
      ...input,
      mode: input.mode || "answer",
      retrievedAuthorities: input.retrievedAuthorities || [],
    }),
  });
}

export function generateIntake(matterType: string, knownFacts: Record<string, string> = {}) {
  return apiRequest<IntakeDefinition>("/api/intake/generate", {
    method: "POST",
    body: JSON.stringify({ matterType, knownFacts }),
  });
}
export function shareIntake(definition: IntakeDefinition, templateId?: string) {
  return apiRequest<{ token: string; shareUrl: string }>("/api/intake/share", {
    method: "POST",
    body: JSON.stringify({
      title: definition.title,
      matterType: definition.matterType,
      questions: definition.questions,
      templateId,
    }),
  });
}
export interface IntakeReviewAnswer {
  questionId: string;
  label: string;
  mapsTo: string;
  answer: unknown;
  reviewStatus?: string;
  file?: {
    id: string;
    filename: string;
    mimeType: string;
    sizeBytes: number;
    sha256: string;
  } | null;
}
export function getIntake(token: string) {
  return apiRequest<{
    title?: string;
    matterType?: string;
    questions?: IntakeDefinition["questions"];
    answers: IntakeReviewAnswer[] | Record<string, string>;
    submittedAt?: string | null;
    templateId?: string | null;
  }>("/api/intake/" + token, { method: "GET" });
}
export async function downloadIntakeFile(
  token: string,
  questionId: string,
  filename: string
): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/intake/${encodeURIComponent(token)}/files/${encodeURIComponent(questionId)}`,
    { headers: apiHeaders() }
  );
  if (!response.ok) throw new Error(`File download failed (${response.status})`);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename || "intake-file";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}
export function revokeIntake(token: string) {
  return apiRequest<{ revoked: boolean }>("/api/intake/" + token + "/revoke", { method: "POST" });
}

async function collectCursorPages<T>(path: string, key: string): Promise<T[]> {
  const all: T[] = [];
  let cursor: string | undefined;
  do {
    const sep = path.includes("?") ? "&" : "?";
    const url = `${path}${sep}limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
    const page = await apiRequest<any>(url, { method: "GET" });
    all.push(...((page?.[key] || []) as T[]));
    cursor = page?.nextCursor || undefined;
  } while (cursor);
  return all;
}

export async function listMatters() {
  return { matters: await collectCursorPages<MatterSummary>("/api/matters", "matters") };
}
export function createMatter(
  title: string,
  matterType: string,
  input: { practiceAreaId?: string; stageId?: string; referenceCode?: string } = {}
) {
  return apiRequest<MatterSummary>("/api/matters", {
    method: "POST",
    body: JSON.stringify({ title, matterType, ...input }),
  });
}
export function updateMatter(
  matterId: string,
  input: {
    title?: string;
    matterType?: string;
    status?: "open" | "pending" | "closed" | "archived";
    practiceAreaId?: string | null;
    stageId?: string | null;
    referenceCode?: string;
  }
) {
  return apiRequest<MatterSummary>("/api/matters/" + matterId, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}
export function addMatterFact(
  matterId: string,
  input: { field: string; fact: string; source?: string; status?: string }
) {
  return apiRequest<Record<string, unknown>>("/api/matters/" + matterId + "/facts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function getMatter(matterId: string) {
  return apiRequest<MatterDetail>("/api/matters/" + matterId, { method: "GET" });
}

export function saveQuestionnaire(definition: IntakeDefinition) {
  return apiRequest<IntakeDefinition>("/api/questionnaires", {
    method: "POST",
    body: JSON.stringify({
      id: definition.id,
      title: definition.title,
      matterType: definition.matterType,
      sections: definition.sections || [],
      questions: definition.questions,
    }),
  });
}
export function publishQuestionnaire(id: string) {
  return apiRequest<IntakeDefinition>(`/api/questionnaires/${id}/publish`, { method: "POST" });
}
export function createQuestionnaireSession(id: string, matterId?: string) {
  return apiRequest<{ token: string; shareUrl: string }>(`/api/questionnaires/${id}/sessions`, {
    method: "POST",
    body: JSON.stringify({ questionnaireId: id, matterId: matterId || null, expiresInDays: 30 }),
  });
}
export function getQuestionnaire(id: string) {
  return apiRequest<IntakeDefinition>(`/api/questionnaires/${id}`, { method: "GET" });
}
export function listQuestionnaires() {
  return apiRequest<{
    questionnaires: Array<{
      id: string;
      title: string;
      matterType: string;
      status: string;
      latestVersion: number;
    }>;
  }>("/api/questionnaires", { method: "GET" });
}

function base64ToBlob(base64: string, mime: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}
async function blobToBase64(blob: Blob): Promise<string> {
  const buf = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < buf.length; i += chunk)
    binary += String.fromCharCode(...buf.subarray(i, i + chunk));
  return btoa(binary);
}
export async function createMatterDocument(
  matterId: string,
  input: { name: string; docxBase64: string; source?: string; metadata?: Record<string, unknown> }
) {
  const form = new FormData();
  form.append("name", input.name);
  form.append("source", input.source || "captured");
  form.append(
    "file",
    base64ToBlob(
      input.docxBase64,
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    input.name || "Matter document.docx"
  );
  const response = await fetch(
    `${API_BASE_URL}/api/matters/${encodeURIComponent(matterId)}/documents/file`,
    { method: "POST", headers: apiHeaders(), body: form }
  );
  if (!response.ok) throw new Error(`Matter document upload failed (${response.status})`);
  return response.json() as Promise<MatterDocument>;
}
export function getMatterDocumentContent(matterId: string, documentId: string) {
  return apiRequest<{ id: string; name: string; docxBase64: string }>(
    `/api/matters/${matterId}/documents/${documentId}`,
    { method: "GET" }
  );
}
export function renameMatterDocument(matterId: string, documentId: string, name: string) {
  return apiRequest<MatterDocument>(`/api/matters/${matterId}/documents/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}
export function archiveMatterDocument(matterId: string, documentId: string) {
  return apiRequest<{ archived: boolean }>(`/api/matters/${matterId}/documents/${documentId}`, {
    method: "DELETE",
  });
}
export function resolveFactConflict(
  matterId: string,
  conflictId: string,
  input: { factId?: string; value?: string; dismiss?: boolean }
) {
  return apiRequest<Record<string, unknown>>(
    `/api/matters/${matterId}/conflicts/${conflictId}/resolve`,
    { method: "POST", body: JSON.stringify(input) }
  );
}
export function deriveMatterFacts(matterId: string) {
  return apiRequest<{ facts: Array<Record<string, unknown>> }>(`/api/matters/${matterId}/derive`, {
    method: "POST",
  });
}
export function listDerivedFactRules() {
  return apiRequest<{
    rules: Array<{
      id: string;
      fact_key: string;
      label: string;
      value_type: string;
      expression: Record<string, unknown>;
      enabled: boolean;
    }>;
  }>("/api/derived-fact-rules", { method: "GET" });
}
export function saveDerivedFactRule(input: {
  factKey: string;
  label: string;
  valueType?: string;
  expression: Record<string, unknown>;
  enabled?: boolean;
}) {
  return apiRequest<Record<string, unknown>>("/api/derived-fact-rules", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// Clio-inspired legal data APIs
export function listPracticeAreas() {
  return apiRequest<{ practiceAreas: import("./types").PracticeArea[] }>("/api/practice-areas", {
    method: "GET",
  });
}
export function createPracticeArea(input: {
  key: string;
  name: string;
  description?: string;
  position?: number;
  active?: boolean;
}) {
  return apiRequest<import("./types").PracticeArea>("/api/practice-areas", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function listMatterStages(practiceAreaId?: string) {
  return apiRequest<{ stages: import("./types").MatterStage[] }>(
    `/api/matter-stages${practiceAreaId ? `?practiceAreaId=${encodeURIComponent(practiceAreaId)}` : ""}`,
    { method: "GET" }
  );
}
export function createMatterStage(input: {
  key: string;
  name: string;
  practiceAreaId: string;
  description?: string;
  position?: number;
  active?: boolean;
}) {
  return apiRequest<import("./types").MatterStage>("/api/matter-stages", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export async function listContacts(q = "") {
  const path = `/api/contacts${q ? `?q=${encodeURIComponent(q)}` : ""}`;
  return { contacts: await collectCursorPages<import("./types").Contact>(path, "contacts") };
}
export function createContact(input: {
  contactType: "person" | "company";
  displayName: string;
  firstName?: string;
  middleName?: string;
  lastName?: string;
  companyName?: string;
  email?: string;
  phone?: string;
  metadata?: Record<string, unknown>;
}) {
  return apiRequest<import("./types").Contact>("/api/contacts", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function listMatterParticipants(matterId: string) {
  return apiRequest<{ participants: import("./types").MatterParticipant[] }>(
    `/api/matters/${matterId}/participants`,
    { method: "GET" }
  );
}
export function addMatterParticipant(
  matterId: string,
  input: {
    contactId: string;
    roleKey: string;
    displayRole: string;
    isClient?: boolean;
    isPrimary?: boolean;
    representedByFirm?: boolean;
    position?: number;
  }
) {
  return apiRequest<import("./types").MatterParticipant>(`/api/matters/${matterId}/participants`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function removeMatterParticipant(matterId: string, participantId: string) {
  return apiRequest<void>(`/api/matters/${matterId}/participants/${participantId}`, {
    method: "DELETE",
  });
}
export function listFieldGroups() {
  return apiRequest<{ groups: import("./types").FieldGroup[] }>("/api/field-groups", {
    method: "GET",
  });
}
export function createFieldGroup(input: {
  key: string;
  label: string;
  entityScope?: "matter" | "contact";
  roleKey?: string;
  practiceAreaId?: string;
  position?: number;
}) {
  return apiRequest<import("./types").FieldGroup>("/api/field-groups", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function listFieldDefinitions(
  input: {
    scope?: string;
    practiceAreaId?: string;
    matterType?: string;
    includeInactive?: boolean;
  } = {}
) {
  const q = new URLSearchParams();
  if (input.scope) q.set("scope", input.scope);
  if (input.practiceAreaId) q.set("practiceAreaId", input.practiceAreaId);
  if (input.matterType) q.set("matterType", input.matterType);
  if (input.includeInactive) q.set("includeInactive", "true");
  return apiRequest<{ fields: import("./types").FieldDefinition[] }>(
    `/api/field-definitions${q.toString() ? `?${q}` : ""}`,
    { method: "GET" }
  );
}
export function createFieldDefinition(input: {
  semanticKey: string;
  displayLabel: string;
  description?: string;
  entityScope?: "matter" | "contact";
  valueType?: import("./types").CanonicalFieldValueType;
  repeatable?: boolean;
  required?: boolean;
  validation?: Record<string, unknown>;
  formatting?: Record<string, unknown>;
  options?: unknown[];
  aliases?: string[];
  groupId?: string;
  practiceAreaId?: string;
  matterType?: string;
  position?: number;
  active?: boolean;
}) {
  return apiRequest<import("./types").FieldDefinition>("/api/field-definitions", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export async function listMatterFieldValues(matterId: string) {
  return {
    values: await collectCursorPages<import("./types").CanonicalFieldValue>(
      `/api/matters/${matterId}/field-values`,
      "values"
    ),
  };
}
export function setMatterFieldValue(
  matterId: string,
  fieldId: string,
  value: unknown,
  source = "lawyer"
) {
  return apiRequest<import("./types").CanonicalFieldValue>(
    `/api/matters/${matterId}/field-values/${fieldId}`,
    { method: "PUT", body: JSON.stringify({ value, source, status: "confirmed" }) }
  );
}
export async function listDocumentSets() {
  return {
    documentSets: await collectCursorPages<import("./types").DocumentSetSummary>(
      "/api/document-sets",
      "documentSets"
    ),
  };
}
export function getDocumentSet(id: string) {
  return apiRequest<import("./types").DocumentSetDetail>(`/api/document-sets/${id}`, {
    method: "GET",
  });
}
export function createDocumentSet(input: {
  name: string;
  description?: string;
  practiceAreaId?: string;
  matterType?: string;
  items: Array<{ templateId: string; label?: string; position?: number; required?: boolean }>;
}) {
  return apiRequest<import("./types").DocumentSetDetail>("/api/document-sets", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function updateDocumentSet(
  id: string,
  input: {
    name?: string;
    description?: string;
    practiceAreaId?: string;
    matterType?: string;
    items?: Array<{ templateId: string; label?: string; position?: number; required?: boolean }>;
  }
) {
  return apiRequest<import("./types").DocumentSetDetail>(`/api/document-sets/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}
export function publishDocumentSet(id: string) {
  return apiRequest<import("./types").DocumentSetVersion>(`/api/document-sets/${id}/publish`, {
    method: "POST",
  });
}
export function getMatterActivity(matterId: string) {
  return apiRequest<{ events: import("./types").MatterActivityEvent[] }>(
    `/api/matters/${matterId}/activity`,
    { method: "GET" }
  );
}

export function getDocumentSetVersion(id: string, version: number) {
  return apiRequest<{
    version: import("./types").DocumentSetVersion;
    items: import("./types").DocumentSetPublishedItem[];
  }>(`/api/document-sets/${id}/versions/${version}`, { method: "GET" });
}
export function startGenerationRun(input: {
  matterId: string;
  documentSetVersionId: string;
  selectedItems?: string[];
}) {
  return apiRequest<import("./types").GenerationRun>("/api/generation-runs", {
    method: "POST",
    body: JSON.stringify(input),
  });
}
export function advanceGenerationRun(
  id: string,
  status: "selection" | "population" | "review" | "completed" | "failed",
  metadata: Record<string, unknown> = {}
) {
  return apiRequest<import("./types").GenerationRun>(`/api/generation-runs/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status, metadata }),
  });
}

// Gavel-inspired workflow/document automation APIs
export async function listWorkflows() {
  return {
    workflows: await collectCursorPages<import("./types").WorkflowSummary>(
      "/api/workflows",
      "workflows"
    ),
  };
}
export function getWorkflow(id: string) {
  return apiRequest<{
    workflow: import("./types").WorkflowSummary;
    versions: import("./types").WorkflowVersion[];
    latestVersion?: import("./types").WorkflowVersion | null;
  }>(`/api/workflows/${id}`, { method: "GET" });
}
export function createWorkflow(input: {
  name: string;
  description?: string;
  audience?: "internal" | "client" | "both";
  practiceAreaId?: string;
  matterType?: string;
  definition: import("./types").WorkflowDefinition;
}) {
  return apiRequest<{
    workflow: import("./types").WorkflowSummary;
    draftVersion: import("./types").WorkflowVersion;
  }>("/api/workflows", { method: "POST", body: JSON.stringify(input) });
}
export function updateWorkflow(
  id: string,
  input: Partial<{
    name: string;
    description: string;
    audience: "internal" | "client" | "both";
    practiceAreaId: string | null;
    matterType: string;
    definition: import("./types").WorkflowDefinition;
  }>
) {
  return apiRequest<{
    workflow: import("./types").WorkflowSummary;
    draftVersion: import("./types").WorkflowVersion;
  }>(`/api/workflows/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}
export function publishWorkflow(id: string) {
  return apiRequest<import("./types").WorkflowVersion>(`/api/workflows/${id}/publish`, {
    method: "POST",
  });
}
export function startWorkflowSession(
  id: string,
  input: { matterId?: string; expiresInDays?: number; metadata?: Record<string, unknown> }
) {
  return apiRequest<{
    session: import("./types").WorkflowSession;
    workflow: import("./types").WorkflowSummary;
    version: import("./types").WorkflowVersion;
    token?: string;
    shareUrl?: string;
  }>(`/api/workflows/${id}/sessions`, { method: "POST", body: JSON.stringify(input) });
}
export function getWorkflowSession(id: string) {
  return apiRequest<{
    session: import("./types").WorkflowSession;
    definition: import("./types").WorkflowDefinition;
    evaluation: import("./types").WorkflowEvaluation;
  }>(`/api/workflow-sessions/${id}`, { method: "GET" });
}
export function updateWorkflowSession(
  id: string,
  input: {
    answers: Record<string, unknown>;
    currentPage?: string;
    metadata?: Record<string, unknown>;
  }
) {
  return apiRequest<{
    session: import("./types").WorkflowSession;
    evaluation: import("./types").WorkflowEvaluation;
  }>(`/api/workflow-sessions/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}
export function completeWorkflowSession(id: string) {
  return apiRequest<{
    session: import("./types").WorkflowSession;
    evaluation: import("./types").WorkflowEvaluation;
  }>(`/api/workflow-sessions/${id}/complete`, { method: "POST" });
}
export function approveWorkflowSessionForGeneration(id: string) {
  return apiRequest<{ approved: boolean; session: import("./types").WorkflowSession }>(
    `/api/workflow-sessions/${id}/approve-for-generation`,
    { method: "POST" }
  );
}
export function applyWorkflowSessionToMatter(id: string) {
  return apiRequest<{
    matterId: string;
    applied: Array<{ semanticKey: string; fieldDefinitionId: string }>;
    conflicts: Array<{ semanticKey: string; fieldDefinitionId: string; conflictId: string }>;
    skipped: Array<{ semanticKey: string; reason: string }>;
    rejected: Array<{ semanticKey: string; reason: string }>;
  }>(`/api/workflow-sessions/${id}/apply-to-matter`, { method: "POST" });
}
export function getTemplateAutomation(templateId: string) {
  return apiRequest<{
    blueprint: import("./types").TemplateAutomationBlueprint;
    updatedAt?: string | null;
  }>(`/api/templates/${templateId}/automation`, { method: "GET" });
}
export function bootstrapTemplateAutomation(templateId: string) {
  return apiRequest<{
    blueprint: import("./types").TemplateAutomationBlueprint;
    unmapped: Array<{ controlTag: string; variableName: string }>;
  }>(`/api/templates/${templateId}/automation/bootstrap`, { method: "POST" });
}
export function saveTemplateAutomation(
  templateId: string,
  blueprint: import("./types").TemplateAutomationBlueprint
) {
  return apiRequest<{ blueprint: import("./types").TemplateAutomationBlueprint }>(
    `/api/templates/${templateId}/automation`,
    { method: "PUT", body: JSON.stringify({ blueprint }) }
  );
}
export function preflightTemplateAutomation(
  templateId: string,
  blueprint?: import("./types").TemplateAutomationBlueprint
) {
  return apiRequest<import("./types").TemplateAutomationPreflight>(
    `/api/templates/${templateId}/automation/preflight`,
    { method: "POST", body: blueprint ? JSON.stringify({ blueprint }) : undefined }
  );
}
export function publishTemplateAutomation(templateId: string) {
  return apiRequest<Record<string, unknown>>(`/api/templates/${templateId}/automation/publish`, {
    method: "POST",
  });
}
export async function generateHeadless(input: {
  matterId?: string;
  templateId?: string;
  templateVersion?: number;
  documentSetVersionId?: string;
  workflowSessionId?: string;
  generationRunId?: string;
  dataOverrides?: Record<string, unknown>;
  saveToMatter?: boolean;
  idempotencyKey?: string;
}) {
  const idempotencyKey =
    input.idempotencyKey ||
    (input.generationRunId
      ? `generation-run:${input.generationRunId}`
      : crypto.randomUUID?.() || `generation-${Date.now()}`);
  const initial = await apiRequest<any>("/api/generation/headless", {
    method: "POST",
    body: JSON.stringify({ ...input, idempotencyKey }),
  });
  let result = initial;
  if (initial?.queued && initial?.jobId) {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const job = await apiRequest<any>(`/api/generation/jobs/${initial.jobId}`, { method: "GET" });
      if (job.status === "completed") {
        result = job.result || {};
        break;
      }
      if (job.status === "failed" || job.status === "cancelled")
        throw new Error(job.error || `Generation ${job.status}`);
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    if (result === initial)
      throw new Error("Generation did not complete before the client timeout");
  }
  for (const artifact of result.artifacts || []) {
    if (!artifact.docxBase64 && artifact.downloadUrl) {
      const response = await fetch(`${API_BASE_URL}${artifact.downloadUrl}`, {
        headers: apiHeaders(),
      });
      if (!response.ok) throw new Error(`Generated document download failed (${response.status})`);
      artifact.docxBase64 = await blobToBase64(await response.blob());
    }
  }
  return result as {
    artifacts: import("./types").HeadlessArtifact[];
    dataKeys: string[];
    dataConflicts: Array<{
      semanticKey: string;
      source: string;
      canonicalValue: unknown;
      proposedValue: unknown;
      resolution: string;
    }>;
    idempotentReplay?: boolean;
    generationAttemptId?: string;
  };
}
