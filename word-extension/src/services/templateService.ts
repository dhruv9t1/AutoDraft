/**
 * Template Service
 * Handles API calls to Python/FastAPI backend for template creation
 */

import pako from "pako";
import { API_BASE_URL, apiHeaders } from "./config";
import { error as logError, log, warn } from "./logger";
import { TemplateMetadata, Variable } from "./types";
import { captureCompressedDocument } from "./word/documentSnapshot";

export interface CreateTemplateRequest {
  name: string;
  type: string;
  subtype: string;
  description: string;
  variables: Variable[];
}

export interface CreateTemplateResponse {
  id: string;
  name: string;
  type: string;
  subtype: string;
  description: string;
  variablesCount: number;
  createdAt: string;
}

export interface GetTemplateResponse {
  id: string;
  name: string;
  type: string;
  subtype: string;
  description: string;
  variables: Variable[];
  createdAt: string;
}

export interface GetTemplateContentResponse {
  bodyOoxml: string | null;
  docxBase64?: string | null;
  snapshotKind?: "full_docx" | "body_ooxml" | string;
  currentVersion?: number;
}

export interface TemplateSummary {
  id: string;
  name: string;
  type: string;
  subtype: string;
  description: string;
  createdAt: string;
}

export interface UpdateVariableRequest {
  name: string;
}

export interface UpdateVariableResponse {
  id: string;
  name: string;
  originalText: string;
  position: number;
  confidenceScore?: number;
  currentValue?: string;
  bindingId?: string;
}

export interface AddTemplateVariableRequest {
  name: string;
  originalText: string;
  position: number;
  confidenceScore?: number;
  bindingId?: string;
}

export interface SaveVariableValuesRequest {
  values: Array<{ variableName: string; currentValue: string }>;
}

export interface SaveVariableValuesResponse {
  updatedCount: number;
}

export interface ListTemplatesResponse {
  templates: TemplateSummary[];
}

export class TemplateServiceException extends Error {
  constructor(
    message: string,
    public code?: string,
    public statusCode?: number
  ) {
    super(message);
    this.name = "TemplateServiceException";
  }
}

/**
 * Creates a new template with metadata and variables (fast). Body OOXML is uploaded
 * separately via updateTemplateContent in the background after create.
 *
 * @param metadata - Template metadata (name, type, subtype, description)
 * @param variables - Array of variables to save with the template
 * @returns Promise with template creation results
 */
export async function createTemplate(
  metadata: TemplateMetadata,
  variables: Variable[]
): Promise<CreateTemplateResponse> {
  // Validate input
  if (!metadata.name.trim()) {
    throw new TemplateServiceException("Template name is required", "INVALID_INPUT");
  }

  const request: CreateTemplateRequest = {
    name: metadata.name.trim(),
    type: metadata.type || "",
    subtype: metadata.subtype || "",
    description: metadata.description || "",
    variables: variables,
  };

  // If API_BASE_URL is empty, use relative path (webpack proxy will handle it)
  const apiUrl = API_BASE_URL ? `${API_BASE_URL}/api/templates` : "/api/templates";

  const t0 = performance.now();
  log(`[TemplateService] Creating template (${request.variables.length} variables)`);

  try {
    const response = await fetch(apiUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));

      if (response.status === 409) {
        throw new TemplateServiceException(
          errorData.message || `Template with name "${request.name}" already exists`,
          "DUPLICATE_TEMPLATE",
          response.status
        );
      }

      throw new TemplateServiceException(
        errorData.message || `Template creation failed with status ${response.status}`,
        errorData.code,
        response.status
      );
    }

    const data: CreateTemplateResponse = await response.json();
    const elapsed = (performance.now() - t0).toFixed(0);
    log(`[TemplateService] Template created (${data.variablesCount} variables) in ${elapsed}ms`);
    return data;
  } catch (error) {
    if (error instanceof TemplateServiceException) throw error;
    const msg = error instanceof Error ? error.message : "Unknown error";
    throw new TemplateServiceException(`Template creation failed: ${msg}`, "UNKNOWN_ERROR");
  }
}

/**
 * Gets a template by ID with its variables
 *
 * @param templateId - Template ID to fetch
 * @returns Promise with template data including variables
 */
export async function getTemplate(templateId: string): Promise<GetTemplateResponse> {
  // Validate input
  if (!templateId.trim()) {
    throw new TemplateServiceException("Template ID is required", "INVALID_INPUT");
  }

  // If API_BASE_URL is empty, use relative path (webpack proxy will handle it)
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${templateId}`
    : `/api/templates/${templateId}`;

  log("[TemplateService] Fetching template");

  try {
    const response = await fetch(apiUrl, {
      method: "GET",
      headers: apiHeaders({ "Content-Type": "application/json" }),
    });

    log(`[TemplateService] Template response status=${response.status}`);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      warn(`[TemplateService] Template fetch failed status=${response.status}`);

      if (response.status === 404) {
        throw new TemplateServiceException(
          errorData.message || `Template with ID "${templateId}" not found`,
          "TEMPLATE_NOT_FOUND",
          response.status
        );
      }

      throw new TemplateServiceException(
        errorData.message || `Template fetch failed with status ${response.status}`,
        errorData.code,
        response.status
      );
    }

    const data: GetTemplateResponse = await response.json();

    log(`[TemplateService] Template fetched (${data.variables.length} variables)`);

    return data;
  } catch (error) {
    logError("[TemplateService] Template fetch failed", error);

    // Re-throw if it's already our custom exception
    if (error instanceof TemplateServiceException) {
      throw error;
    }

    // Wrap unknown errors
    const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";

    throw new TemplateServiceException(
      `Template fetch failed: ${errorMessage}. ` +
        `Request URL: ${apiUrl}. ` +
        `Please check that: 1) Backend is running on port 3001, 2) Webpack dev server is running, 3) Webpack proxy is configured correctly.`,
      "UNKNOWN_ERROR"
    );
  }
}

/**
 * Gets a template's body OOXML only (for "Use this template" / insertOoxml flow).
 * Use this instead of getTemplate when you only need the document body to insert into Word.
 *
 * @param templateId - Template ID
 * @returns Promise with { bodyOoxml: string | null }
 */
export async function getTemplateContent(templateId: string): Promise<GetTemplateContentResponse> {
  if (!templateId.trim()) {
    throw new TemplateServiceException("Template ID is required", "INVALID_INPUT");
  }

  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${templateId}/content`
    : `/api/templates/${templateId}/content`;

  try {
    const response = await fetch(apiUrl, {
      method: "GET",
      headers: apiHeaders({ "Content-Type": "application/json" }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      if (response.status === 404) {
        throw new TemplateServiceException(
          errorData.message || `Template with ID "${templateId}" not found`,
          "TEMPLATE_NOT_FOUND",
          response.status
        );
      }
      throw new TemplateServiceException(
        errorData.message || `Template content fetch failed: ${response.status}`,
        errorData.code,
        response.status
      );
    }

    const data: GetTemplateContentResponse = await response.json();
    return data;
  } catch (error) {
    if (error instanceof TemplateServiceException) throw error;
    throw new TemplateServiceException(
      `Template content fetch failed: ${error instanceof Error ? error.message : "Unknown error"}`,
      "UNKNOWN_ERROR"
    );
  }
}

/** Chunk size for OOXML upload - 500KB chunks for reliable upload */
const CHUNK_SIZE = 500 * 1024; // 500KB
/** Timeout per chunk upload */
const CHUNK_UPLOAD_TIMEOUT_MS = 30 * 1000; // 30 seconds per chunk
/** Max concurrent chunk uploads */
const MAX_CONCURRENT_UPLOADS = 3;
/** Retries for transient network failures (Load failed, etc.) */
const CHUNK_MAX_RETRIES = 3;
const CHUNK_RETRY_DELAY_MS = 1000;

function isRetriableNetworkError(e: unknown): boolean {
  const msg = e instanceof Error ? e.message : String(e);
  const s = msg.toLowerCase();
  return (
    s.includes("load failed") ||
    s.includes("failed to fetch") ||
    s.includes("networkerror") ||
    s.includes("network request failed") ||
    s.includes("econnreset") ||
    s.includes("etimedout") ||
    s.includes("aborted") ||
    (e instanceof TypeError && s.includes("fetch"))
  );
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/**
 * Compresses a string using gzip and returns base64-encoded result.
 * This reduces payload size by 70-90% for OOXML content.
 */
function compressToBase64(data: string): {
  compressed: string;
  originalSize: number;
  compressedSize: number;
} {
  const t0 = performance.now();
  const originalSize = data.length;

  // Convert string to Uint8Array
  const encoder = new TextEncoder();
  const uint8Array = encoder.encode(data);

  // Compress using pako gzip
  const compressed = pako.gzip(uint8Array);

  // Convert to base64
  let binary = "";
  const len = compressed.length;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(compressed[i]);
  }
  const base64 = btoa(binary);

  const compressedSize = base64.length;
  const ratio = ((compressedSize / originalSize) * 100).toFixed(1);
  const elapsed = (performance.now() - t0).toFixed(0);
  log(
    `[TemplateService] Compression: ${(originalSize / 1024).toFixed(0)}KB -> ${(compressedSize / 1024).toFixed(0)}KB (${ratio}% of original) in ${elapsed}ms`
  );

  return { compressed: base64, originalSize, compressedSize };
}

/**
 * Splits data into chunks of specified size
 */
function splitIntoChunks(data: string, chunkSize: number): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < data.length; i += chunkSize) {
    chunks.push(data.slice(i, i + chunkSize));
  }
  return chunks;
}

/**
 * Uploads a single chunk with retry logic
 */
async function uploadChunk(
  apiUrl: string,
  sessionId: string,
  chunkIndex: number,
  chunkData: string,
  totalChunks: number
): Promise<void> {
  let lastErr: unknown;

  for (let retry = 0; retry < CHUNK_MAX_RETRIES; retry++) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), CHUNK_UPLOAD_TIMEOUT_MS);

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          sessionId,
          chunkIndex,
          chunkData,
          totalChunks,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeout);

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(
          (err as { message?: string }).message || `Chunk upload failed: ${response.status}`
        );
      }

      return; // Success
    } catch (e) {
      clearTimeout(timeout);
      lastErr = e;

      if (retry < CHUNK_MAX_RETRIES - 1 && isRetriableNetworkError(e)) {
        await sleep(CHUNK_RETRY_DELAY_MS * (retry + 1)); // Exponential backoff
        continue;
      }
      break;
    }
  }

  throw new TemplateServiceException(
    `Chunk ${chunkIndex} upload failed: ${lastErr instanceof Error ? lastErr.message : lastErr}`,
    "CHUNK_UPLOAD_FAILED"
  );
}

/**
 * Updates a template's body OOXML using chunked upload for large files.
 * Compresses data, splits into 500KB chunks, and uploads in parallel.
 *
 * @param templateId - Template ID
 * @param bodyOoxml - OOXML string from getDocumentBodyOoxml
 * @param onProgress - Optional callback for progress updates
 */

function base64DocxBlob(base64: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}

export async function updateTemplateContent(
  templateId: string,
  bodyOoxml: string,
  onProgress?: (progress: { stage: string; percentage: number; attempt: number }) => void
): Promise<void> {
  if (!templateId.trim()) {
    throw new TemplateServiceException("Template ID is required", "INVALID_INPUT");
  }
  if (!bodyOoxml || bodyOoxml.trim().length === 0) {
    return;
  }

  // Desktop Word/Mac: persist the complete DOCX package. Word Web and hosts
  // without compressed capture transparently retain the body-OOXML fallback.
  const fullDocx = await captureCompressedDocument().catch((error) => {
    log(`[TemplateService] Full DOCX capture unavailable; using body OOXML fallback: ${error}`);
    return null;
  });
  if (fullDocx) {
    const url = `${API_BASE_URL || ""}/api/templates/${templateId}/content/file`;
    const form = new FormData();
    form.append("bodyOoxml", bodyOoxml);
    form.append("file", base64DocxBlob(fullDocx), "template.docx");
    const response = await fetch(url, {
      method: "PUT",
      headers: apiHeaders(),
      body: form,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new TemplateServiceException(
        (body as any).message || `Full DOCX template save failed: ${response.status}`,
        "FULL_DOCX_SAVE_FAILED",
        response.status
      );
    }
    onProgress?.({ stage: "Complete DOCX template saved", percentage: 100, attempt: 0 });
    return;
  }

  const t0 = performance.now();
  const baseUrl = API_BASE_URL || "";

  // Step 1: Compress the OOXML data
  onProgress?.({ stage: "Compressing template content...", percentage: 2, attempt: 0 });

  const { compressed: compressedOoxml, originalSize, compressedSize } = compressToBase64(bodyOoxml);

  // Step 2: Split into chunks
  const chunks = splitIntoChunks(compressedOoxml, CHUNK_SIZE);
  const totalChunks = chunks.length;

  log(
    `[TemplateService] Chunked upload: ${(originalSize / 1024).toFixed(0)}KB -> ${(compressedSize / 1024).toFixed(0)}KB compressed -> ${totalChunks} chunks of ${(CHUNK_SIZE / 1024).toFixed(0)}KB`
  );

  onProgress?.({
    stage: `Uploading ${totalChunks} chunks (${(compressedSize / 1024).toFixed(0)}KB total)...`,
    percentage: 5,
    attempt: 0,
  });

  // Step 3: Start chunked upload session
  const startSessionUrl = `${baseUrl}/api/templates/${templateId}/content/chunked/start`;

  let sessionId: string;
  try {
    const startResponse = await fetch(startSessionUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ totalChunks, totalSize: compressedSize }),
    });

    if (!startResponse.ok) {
      const err = await startResponse.json().catch(() => ({}));
      throw new Error(
        (err as { message?: string }).message ||
          `Failed to start upload session: ${startResponse.status}`
      );
    }

    const sessionData = await startResponse.json();
    sessionId = sessionData.sessionId;
    log(`[TemplateService] Started chunked upload session: ${sessionId}`);
  } catch (e) {
    throw new TemplateServiceException(
      `Failed to start chunked upload: ${e instanceof Error ? e.message : e}`,
      "SESSION_START_FAILED"
    );
  }

  // Step 4: Upload chunks in parallel batches
  const chunkUploadUrl = `${baseUrl}/api/templates/${templateId}/content/chunked/upload`;
  let completedChunks = 0;

  // Process chunks in batches of MAX_CONCURRENT_UPLOADS
  for (let batchStart = 0; batchStart < totalChunks; batchStart += MAX_CONCURRENT_UPLOADS) {
    const batchEnd = Math.min(batchStart + MAX_CONCURRENT_UPLOADS, totalChunks);
    const batchPromises: Promise<void>[] = [];

    for (let i = batchStart; i < batchEnd; i++) {
      batchPromises.push(
        uploadChunk(chunkUploadUrl, sessionId, i, chunks[i], totalChunks).then(() => {
          completedChunks++;
          const progress = 10 + Math.floor((completedChunks / totalChunks) * 80); // 10% to 90%
          onProgress?.({
            stage: `Uploading chunk ${completedChunks}/${totalChunks}...`,
            percentage: progress,
            attempt: 0,
          });
        })
      );
    }

    // Wait for batch to complete
    await Promise.all(batchPromises);
    log(`[TemplateService] Uploaded chunks ${batchStart + 1}-${batchEnd} of ${totalChunks}`);
  }

  // Step 5: Finalize the upload
  onProgress?.({ stage: "Finalizing upload...", percentage: 92, attempt: 0 });

  const finalizeUrl = `${baseUrl}/api/templates/${templateId}/content/chunked/finalize`;

  try {
    const finalizeResponse = await fetch(finalizeUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ sessionId }),
    });

    if (!finalizeResponse.ok) {
      const err = await finalizeResponse.json().catch(() => ({}));
      throw new Error(
        (err as { message?: string }).message ||
          `Failed to finalize upload: ${finalizeResponse.status}`
      );
    }

    const elapsed = (performance.now() - t0).toFixed(0);
    log(
      `[TemplateService] Chunked upload SUCCESS: ${elapsed}ms total, ${totalChunks} chunks, ${(compressedSize / 1024).toFixed(0)}KB (original: ${(originalSize / 1024).toFixed(0)}KB)`
    );

    onProgress?.({ stage: "Template content uploaded successfully", percentage: 100, attempt: 0 });
  } catch (e) {
    throw new TemplateServiceException(
      `Failed to finalize chunked upload: ${e instanceof Error ? e.message : e}`,
      "FINALIZE_FAILED"
    );
  }
}

/**
 * Lists all templates from the database
 *
 * @returns Promise with list of all templates
 */
export async function listTemplates(): Promise<ListTemplatesResponse> {
  const base = API_BASE_URL ? `${API_BASE_URL}/api/templates` : "/api/templates";
  const templates: TemplateSummary[] = [];
  let cursor: string | undefined;
  log("[TemplateService] Fetching paginated templates list");
  try {
    do {
      const url = `${base}?limit=200${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
      const response = await fetch(url, {
        method: "GET",
        headers: apiHeaders({ "Content-Type": "application/json" }),
      });
      if (!response.ok)
        throw new TemplateServiceException(
          `Templates list fetch failed with status ${response.status}`,
          undefined,
          response.status
        );
      const page = (await response.json()) as ListTemplatesResponse & {
        nextCursor?: string | null;
      };
      templates.push(...(page.templates || []));
      cursor = page.nextCursor || undefined;
    } while (cursor);
    log(`[TemplateService] Templates list fetched (${templates.length} templates)`);
    return { templates };
  } catch (error) {
    logError("[TemplateService] Templates-list fetch failed", error);
    if (error instanceof TemplateServiceException) throw error;
    throw new TemplateServiceException("Failed to fetch templates list", "FETCH_ERROR");
  }
}

export async function updateTemplateMetadata(
  templateId: string,
  input: { name?: string; type?: string; subtype?: string; description?: string }
): Promise<TemplateSummary> {
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${encodeURIComponent(templateId)}`
    : `/api/templates/${encodeURIComponent(templateId)}`;
  const response = await fetch(apiUrl, {
    method: "PATCH",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new TemplateServiceException(
      errorData.detail || errorData.message || `Failed to update template: ${response.status}`,
      errorData.code || "API_ERROR",
      response.status
    );
  }
  return response.json() as Promise<TemplateSummary>;
}

export async function deleteTemplate(templateId: string): Promise<void> {
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${encodeURIComponent(templateId)}`
    : `/api/templates/${encodeURIComponent(templateId)}`;
  const response = await fetch(apiUrl, {
    method: "DELETE",
    headers: apiHeaders({ "Content-Type": "application/json" }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new TemplateServiceException(
      errorData.detail || errorData.message || `Failed to delete template: ${response.status}`,
      errorData.code || "API_ERROR",
      response.status
    );
  }
}

export async function duplicateTemplate(templateId: string): Promise<TemplateSummary> {
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${encodeURIComponent(templateId)}/duplicate`
    : `/api/templates/${encodeURIComponent(templateId)}/duplicate`;
  const response = await fetch(apiUrl, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
  });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new TemplateServiceException(
      errorData?.error?.message ||
        errorData.detail ||
        errorData.message ||
        `Failed to duplicate template: ${response.status}`,
      errorData?.error?.code || errorData.code || "API_ERROR",
      response.status
    );
  }
  return response.json() as Promise<TemplateSummary>;
}

/**
 * Update a variable's name in the database
 * @param variableId - The ID of the variable to update
 * @param newName - The new name for the variable
 * @returns Promise with the updated variable
 */
export async function updateVariable(
  variableId: string,
  newName: string
): Promise<UpdateVariableResponse> {
  const url = `${API_BASE_URL}/api/variables/${encodeURIComponent(variableId)}`;

  try {
    const response = await fetch(url, {
      method: "PUT",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        name: newName.trim(),
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      let errorMessage = `Failed to update variable: ${response.status} ${response.statusText}`;

      if (response.status === 0) {
        throw new TemplateServiceException(
          "Cannot connect to backend server. Please ensure the backend is running on port 3001.",
          "NETWORK_ERROR",
          0
        );
      }

      if (response.status >= 500) {
        throw new TemplateServiceException(
          "Backend server error. Please check backend logs.",
          "SERVER_ERROR",
          response.status
        );
      }

      if (response.status === 404) {
        throw new TemplateServiceException(
          "Variable not found in database.",
          "NOT_FOUND",
          response.status
        );
      }

      try {
        const errorJson = JSON.parse(errorText);
        errorMessage = errorJson.message || errorMessage;
      } catch {
        // If error response is not JSON, use the text as is
        if (errorText) {
          errorMessage = errorText;
        }
      }

      throw new TemplateServiceException(errorMessage, "API_ERROR", response.status);
    }

    const data: UpdateVariableResponse = await response.json();
    return data;
  } catch (error) {
    if (error instanceof TemplateServiceException) {
      throw error;
    }

    if (error instanceof TypeError && error.message.includes("fetch")) {
      throw new TemplateServiceException(
        "Cannot connect to backend server. Please ensure the backend is running on port 3001.",
        "NETWORK_ERROR",
        0
      );
    }

    throw new TemplateServiceException(
      error instanceof Error ? error.message : "Unknown error occurred while updating variable",
      "UNKNOWN_ERROR",
      0
    );
  }
}

/** Persists a variable that the user manually added after Auto Draft finished. */
export async function addTemplateVariable(
  templateId: string,
  variable: AddTemplateVariableRequest
): Promise<UpdateVariableResponse> {
  if (!templateId.trim()) {
    throw new TemplateServiceException("Template ID is required", "INVALID_INPUT");
  }
  if (!variable.name.trim() || !variable.originalText.trim()) {
    throw new TemplateServiceException(
      "Variable name and original text are required",
      "INVALID_INPUT"
    );
  }

  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${encodeURIComponent(templateId)}/variables`
    : `/api/templates/${encodeURIComponent(templateId)}/variables`;

  try {
    const response = await fetch(apiUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(variable),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new TemplateServiceException(
        errorData.message || `Failed to add variable: ${response.status}`,
        errorData.code || "API_ERROR",
        response.status
      );
    }

    return (await response.json()) as UpdateVariableResponse;
  } catch (error) {
    if (error instanceof TemplateServiceException) throw error;
    throw new TemplateServiceException(
      `Failed to add variable: ${error instanceof Error ? error.message : "Unknown error"}`,
      "UNKNOWN_ERROR"
    );
  }
}

/**
 * Save variable values in bulk for a template (persists current_value to database)
 * @param templateId - Template ID
 * @param values - Map of variable name → current value
 * @returns Promise with the count of updated variables
 */
export async function saveVariableValues(
  templateId: string,
  values: Record<string, string>
): Promise<SaveVariableValuesResponse> {
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${templateId}/variable-values`
    : `/api/templates/${templateId}/variable-values`;

  const entries = Object.entries(values)
    .filter(([, v]) => v && v.trim())
    .map(([variableName, currentValue]) => ({ variableName, currentValue }));

  if (entries.length === 0) {
    return { updatedCount: 0 };
  }

  try {
    const response = await fetch(apiUrl, {
      method: "PUT",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ values: entries }),
    });

    if (!response.ok) {
      throw new TemplateServiceException(
        `Failed to save variable values: ${response.status}`,
        "API_ERROR",
        response.status
      );
    }

    const data: SaveVariableValuesResponse = await response.json();
    log(`[TemplateService] Saved ${data.updatedCount} variable values`);
    return data;
  } catch (error) {
    if (error instanceof TemplateServiceException) throw error;
    throw new TemplateServiceException(
      `Failed to save variable values: ${error instanceof Error ? error.message : "Unknown error"}`,
      "UNKNOWN_ERROR"
    );
  }
}

/**
 * Clears persisted draft values for a template while preserving the variable
 * definitions and saved OOXML master. This is used when a user completes a
 * draft and chooses to keep the reusable "empty" template for future use.
 *
 * Unlike saveVariableValues(), empty strings are intentionally transmitted.
 */
export async function clearVariableValues(
  templateId: string,
  variableNames: string[]
): Promise<SaveVariableValuesResponse> {
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/templates/${templateId}/variable-values`
    : `/api/templates/${templateId}/variable-values`;

  const uniqueNames = Array.from(
    new Set(variableNames.map((name) => name.trim()).filter((name) => name.length > 0))
  );

  if (uniqueNames.length === 0) {
    return { updatedCount: 0 };
  }

  try {
    const response = await fetch(apiUrl, {
      method: "PUT",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        values: uniqueNames.map((variableName) => ({
          variableName,
          currentValue: "",
        })),
      }),
    });

    if (!response.ok) {
      throw new TemplateServiceException(
        `Failed to clear variable values: ${response.status}`,
        "API_ERROR",
        response.status
      );
    }

    const data: SaveVariableValuesResponse = await response.json();
    log(`[TemplateService] Cleared ${data.updatedCount} variable values`);
    return data;
  } catch (error) {
    if (error instanceof TemplateServiceException) throw error;
    throw new TemplateServiceException(
      `Failed to clear variable values: ${error instanceof Error ? error.message : "Unknown error"}`,
      "UNKNOWN_ERROR"
    );
  }
}
