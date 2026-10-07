/**
 * AI Variable Identification Service
 * Following NestJS architecture pattern adapted for React/TypeScript
 * Handles API calls to Python/FastAPI backend for AI variable identification
 */

import { API_BASE_URL, apiHeaders } from "./config";
import { log } from "./logger";
import { getLastExtractedSegments } from "./documentExtraction";
import { Variable, VariableIdentificationRequest, VariableIdentificationResponse } from "./types";

/**
 * Callbacks fired by identifyVariablesStreaming as SSE events arrive.
 * Variables stream in via onChunkDone; onComplete carries the deduped/sorted
 * authoritative list (use this as the source of truth for persistence).
 */
export interface StreamingCallbacks {
  onChunkDone?: (chunkIndex: number, totalChunks: number, variables: Variable[]) => void;
  onProgress?: (completed: number, total: number) => void;
  onChunkError?: (chunkIndex: number, message: string) => void;
  onComplete: (response: VariableIdentificationResponse) => void;
  onError: (err: Error) => void;
}

/**
 * Returns true if the current runtime supports streaming response bodies via
 * fetch + ReadableStream + TextDecoder. Older/non-streaming Office hosts fail
 * this check; callers fall back to identifyVariables() in that case.
 */
const FORCE_NON_STREAMING = process.env.AUTODRAFT_FORCE_NON_STREAMING === "1";

export function supportsResponseStreaming(): boolean {
  if (FORCE_NON_STREAMING) return false;
  return (
    typeof fetch !== "undefined" &&
    typeof ReadableStream !== "undefined" &&
    typeof TextDecoder !== "undefined"
  );
}
const API_TIMEOUT = 500000; // ~8.3 minutes; allows large legal-document inference
const MAX_RETRIES = 3;
const RETRY_DELAYS = [1000, 2000, 4000]; // Exponential backoff: 1s, 2s, 4s
const LARGE_DOCUMENT_STREAMING_CHAR_LIMIT = 50_000;

/**
 * Custom exception classes following NestJS pattern
 */
export class AiServiceException extends Error {
  constructor(
    message: string,
    public code?: string,
    public statusCode?: number
  ) {
    super(message);
    this.name = "AiServiceException";
  }
}

export class AiTimeoutException extends AiServiceException {
  constructor(message: string = "AI service request timed out") {
    super(message, "TIMEOUT", 408);
    this.name = "AiTimeoutException";
  }
}

export class AiRetryExhaustedException extends AiServiceException {
  constructor(message: string = "AI service retry attempts exhausted") {
    super(message, "RETRY_EXHAUSTED", 503);
    this.name = "AiRetryExhaustedException";
  }
}

/**
 * Sleep utility for retry delays
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Creates a timeout promise that rejects after specified milliseconds
 */
function createTimeoutPromise(timeoutMs: number): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => {
      reject(new AiTimeoutException(`Request timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });
}

/**
 * Makes API call with timeout and retry logic
 * Following NestJS OllamaService pattern with exponential backoff
 */
async function makeApiCallWithRetry(
  request: VariableIdentificationRequest,
  attempt: number = 0
): Promise<VariableIdentificationResponse> {
  if (attempt >= MAX_RETRIES) {
    throw new AiRetryExhaustedException(`Failed after ${MAX_RETRIES} retry attempts`);
  }

  // If API_BASE_URL is empty, use relative path (webpack proxy will handle it)
  const apiUrl = API_BASE_URL
    ? `${API_BASE_URL}/api/documents/identify-variables`
    : "/api/documents/identify-variables";

  try {
    // Create timeout promise
    const timeoutPromise = createTimeoutPromise(API_TIMEOUT);

    // Create fetch promise

    log("═══════════════════════════════════════════════════════════");
    log("📤 FRONTEND: Sending API request");
    log("═══════════════════════════════════════════════════════════");
    log(`  URL: ${apiUrl}`);
    log(`  Method: POST`);
    log(`  API_BASE_URL: "${API_BASE_URL}" (${API_BASE_URL ? "direct" : "via webpack proxy"})`);
    log(`  Document Content Length: ${request.documentContent.length} characters`);
    log(`  Template ID present: ${Boolean(request.templateId)}`);
    log(`  Template name present: ${Boolean(request.templateName)}`);
    log(`  Attempt: ${attempt + 1}/${MAX_RETRIES}`);

    // Never log legal-document text. Browser/dev-server logs are not a safe
    // storage boundary for client document contents. Keep metadata only.
    if (request.documentContent.length === 0) {
      log("  ⚠️  WARNING: Document content is empty!");
    } else {
      const lineCount = request.documentContent.split("\n").length;
      const wordCount = request.documentContent.split(/\s+/).filter((w) => w.length > 0).length;
      log(
        `  Document Stats: ${lineCount} lines, ${wordCount} words, ${(request.documentContent.length / 1024).toFixed(2)} KB`
      );
      log("  Document text logging: disabled for privacy");
    }

    const fetchPromise = fetch(apiUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(request),
    });

    // Race between fetch and timeout
    const response = await Promise.race([fetchPromise, timeoutPromise]);

    log("📥 FRONTEND: Response received from backend");
    log(`  Status: ${response.status} ${response.statusText}`);

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      log("❌ FRONTEND: API request failed");
      log(`  Status: ${response.status}`);
      log(`  Error Data:`, errorData);
      throw new AiServiceException(
        errorData.message || `API request failed with status ${response.status}`,
        errorData.code,
        response.status
      );
    }

    const data: VariableIdentificationResponse = await response.json();

    log("✅ FRONTEND: Successfully received response from backend");
    log("═══════════════════════════════════════════════════════════");
    log("📊 Response Data:");
    log(`  Variables Found: ${data.variables.length}`);
    log(`  Identification Percentage: ${data.identificationPercentage.toFixed(1)}%`);
    log(`  Status: ${data.status}`);
    log(`  Message: ${data.message || "None"}`);
    log("═══════════════════════════════════════════════════════════");
    log("🔗 CONNECTION CONFIRMED: Frontend ↔ Backend communication successful!");
    log("═══════════════════════════════════════════════════════════");

    return data;
  } catch (error) {
    // Log the error for debugging
    log(`API call error (attempt ${attempt + 1}):`, error);

    // Check for network/fetch errors
    const isNetworkError =
      error instanceof TypeError ||
      (error instanceof Error &&
        (error.message.includes("fetch") ||
          error.message.includes("Failed to fetch") ||
          error.message.includes("NetworkError") ||
          error.message.includes("Network request failed")));

    // If it's a timeout or network error, retry with exponential backoff
    if (error instanceof AiTimeoutException || isNetworkError) {
      if (attempt < MAX_RETRIES - 1) {
        const delay = RETRY_DELAYS[attempt] || RETRY_DELAYS[RETRY_DELAYS.length - 1];
        log(`API call failed (attempt ${attempt + 1}/${MAX_RETRIES}), retrying in ${delay}ms...`);
        await sleep(delay);
        return makeApiCallWithRetry(request, attempt + 1);
      } else {
        // Retries exhausted - provide a more helpful error message
        if (isNetworkError) {
          const backendUrl = API_BASE_URL
            ? API_BASE_URL
            : "http://127.0.0.1:3001 (via webpack proxy from /api/*)";
          throw new AiServiceException(
            `Unable to connect to backend server. ` +
              `Request was sent to: ${apiUrl} ` +
              `(should proxy to ${backendUrl}). ` +
              `Please ensure: 1) Backend is running on port 3001, 2) Webpack dev server is running, 3) Webpack proxy is configured correctly.`,
            "NETWORK_ERROR",
            0
          );
        }
      }
    }

    // Re-throw if it's already our custom exception or if retries exhausted
    if (error instanceof AiServiceException) {
      throw error;
    }

    // Wrap unknown errors with more context
    const errorMessage = error instanceof Error ? error.message : "Unknown error occurred";

    throw new AiServiceException(
      `API request failed: ${errorMessage}. ` +
        `Request URL: ${apiUrl}. ` +
        `Please check that: 1) Backend is running on port 3001, 2) Webpack dev server is running, 3) Webpack proxy is configured correctly.`,
      "UNKNOWN_ERROR"
    );
  }
}

/**
 * Identifies variables in document content using chunked upload
 * For large documents, splits into chunks and uploads sequentially
 *
 * @param documentContent - Full text content of the document
 * @param templateId - Optional template ID
 * @param templateName - Optional template name
 * @returns Promise with variable identification results
 */
export async function identifyVariables(
  documentContent: string,
  templateId?: string,
  templateName?: string,
  knownVariables?: Variable[]
): Promise<VariableIdentificationResponse> {
  // Validate input
  if (!documentContent || documentContent.trim().length === 0) {
    throw new AiServiceException(
      "Document content is required and cannot be empty",
      "INVALID_INPUT"
    );
  }

  // Use chunked upload for documents larger than 1MB
  const CHUNK_SIZE = 50 * 1024 * 1024; // 50MB per chunk for better performance
  const USE_CHUNKED_THRESHOLD = 1024 * 1024; // 1MB threshold

  if (documentContent.length > USE_CHUNKED_THRESHOLD) {
    log("📦 Document is large, using chunked upload with parallel processing");
    return await identifyVariablesChunked(documentContent, templateId, templateName, CHUNK_SIZE);
  } else {
    // Use single request for smaller documents
    const request: VariableIdentificationRequest = {
      documentContent,
      templateId,
      templateName,
      knownVariables,
      segments: getLastExtractedSegments() as unknown as Array<Record<string, unknown>>,
    };

    try {
      const response = await makeApiCallWithRetry(request);
      return response;
    } catch (error) {
      log("Variable identification failed:", error);
      throw error;
    }
  }
}

/**
 * Identifies variables using chunked upload
 * Splits document into chunks, uploads sequentially, then processes when complete
 * Backend now processes chunks in parallel for better performance
 */
async function identifyVariablesChunked(
  documentContent: string,
  templateId: string | undefined,
  templateName: string | undefined,
  chunkSize: number
): Promise<VariableIdentificationResponse> {
  log("═══════════════════════════════════════════════════════════");
  log("📦 Starting chunked upload process (backend will process chunks in parallel)");
  log("═══════════════════════════════════════════════════════════");
  log(`Document size: ${documentContent.length} characters`);
  log(`Chunk size: ${chunkSize} characters`);

  // Import chunking function
  const { chunkDocumentContent } = await import("./documentExtraction");

  // Split document into chunks
  const chunks = chunkDocumentContent(documentContent, chunkSize);
  log(`Document split into ${chunks.length} chunks`);

  // Step 1: Start chunked upload session
  const apiUrl = API_BASE_URL ? API_BASE_URL : "";
  const startUrl = `${apiUrl}/api/documents/start-chunked-upload`;

  log(`Starting chunked upload session...`);
  const startResponse = await fetch(startUrl, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      totalChunks: chunks.length,
      templateId,
      templateName,
    }),
  });

  if (!startResponse.ok) {
    const errorData = await startResponse.json().catch(() => ({}));
    throw new AiServiceException(
      `Failed to start chunked upload: ${startResponse.status} ${JSON.stringify(errorData)}`,
      "CHUNKED_UPLOAD_START_FAILED",
      startResponse.status
    );
  }

  const { sessionId, totalChunks } = await startResponse.json();
  log(`✅ Session created: ${sessionId}, expecting ${totalChunks} chunks`);

  // Step 2: Upload chunks sequentially (backend will process in parallel)
  log("📤 Uploading chunks sequentially (backend will process them in parallel)...");
  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i];
    log(`Uploading chunk ${i + 1}/${chunks.length} (${chunk.length} chars)...`);

    const uploadUrl = `${apiUrl}/api/documents/upload-chunk`;
    const uploadResponse = await fetch(uploadUrl, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        sessionId,
        chunkIndex: i,
        chunkContent: chunk,
      }),
    });

    if (!uploadResponse.ok) {
      const errorData = await uploadResponse.json().catch(() => ({}));
      throw new AiServiceException(
        `Failed to upload chunk ${i + 1}: ${uploadResponse.status} ${JSON.stringify(errorData)}`,
        "CHUNK_UPLOAD_FAILED",
        uploadResponse.status
      );
    }

    const uploadResult = await uploadResponse.json();
    log(
      `✅ Chunk ${i + 1} uploaded: ${uploadResult.chunksReceived}/${uploadResult.totalChunks} received`
    );

    if (uploadResult.isComplete) {
      log(`🎉 All chunks uploaded!`);
    }
  }

  // Step 3: Finalize and process
  log("🔄 Finalizing chunked upload and processing document...");
  const finalizeUrl = `${apiUrl}/api/documents/finalize-chunked-upload`;
  const finalizeResponse = await fetch(finalizeUrl, {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      sessionId,
    }),
  });

  if (!finalizeResponse.ok) {
    const errorData = await finalizeResponse.json().catch(() => ({}));
    throw new AiServiceException(
      `Failed to finalize chunked upload: ${finalizeResponse.status} ${JSON.stringify(errorData)}`,
      "CHUNKED_UPLOAD_FINALIZE_FAILED",
      finalizeResponse.status
    );
  }

  const result: VariableIdentificationResponse = await finalizeResponse.json();
  log("✅ Chunked upload processing completed");
  log(`Variables found: ${result.variables.length}`);
  log(`Identification percentage: ${result.identificationPercentage.toFixed(1)}%`);

  return result;
}

/**
 * Validates that AI identified at least 80% of variables
 * Following architecture pattern for accuracy validation
 *
 * @param response - Variable identification response
 * @returns boolean indicating if accuracy threshold is met
 */
export function validateIdentificationAccuracy(response: VariableIdentificationResponse): boolean {
  return response.identificationPercentage >= 80;
}

/**
 * Streams variable identification results from the backend SSE endpoint.
 * Each chunk_done event delivers a partial batch of validated variables that
 * the UI can render immediately; onComplete delivers the final authoritative
 * list (deduped, sorted, with identificationPercentage).
 *
 * Caller must check supportsResponseStreaming() first — non-streaming hosts fall back to
 * identifyVariables().
 *
 * Note: this does not auto-retry mid-stream. If the connection drops after
 * partial results, onError fires and the caller decides whether to use what
 * it already received via onChunkDone or restart from scratch.
 */
export async function identifyVariablesStreaming(
  documentContent: string,
  callbacks: StreamingCallbacks,
  templateId?: string,
  templateName?: string,
  knownVariables?: Variable[],
  signal?: AbortSignal
): Promise<void> {
  if (!documentContent || documentContent.trim().length === 0) {
    callbacks.onError(
      new AiServiceException("Document content is required and cannot be empty", "INVALID_INPUT")
    );
    return;
  }

  const request: VariableIdentificationRequest = {
    documentContent,
    templateId,
    templateName,
    knownVariables,
    segments: getLastExtractedSegments() as unknown as Array<Record<string, unknown>>,
  };
  const base = API_BASE_URL || "";
  let jobId = "";
  let completed = false;

  const cancelJob = async () => {
    if (!jobId) return;
    try {
      await fetch(`${base}/api/documents/identify-jobs/${jobId}`, {
        method: "DELETE",
        headers: apiHeaders(),
      });
    } catch {
      /* best effort */
    }
  };

  const abortHandler = () => {
    void cancelJob();
  };
  signal?.addEventListener("abort", abortHandler, { once: true });

  const dispatch = (event: string, payload: any) => {
    switch (event) {
      case "chunk_done":
        callbacks.onChunkDone?.(payload.chunkIndex, payload.totalChunks, payload.variables || []);
        break;
      case "progress":
        callbacks.onProgress?.(payload.completed, payload.total);
        break;
      case "error":
        callbacks.onChunkError?.(payload.chunkIndex, payload.message);
        break;
      case "complete":
        completed = true;
        callbacks.onComplete({
          variables: payload.variables || [],
          variableBlocks: payload.variableBlocks || undefined,
          identificationPercentage: payload.identificationPercentage || 0,
          status: payload.status || "completed",
          message: payload.message || undefined,
          wrappingPlan: payload.wrappingPlan || undefined,
          identificationMode: payload.identificationMode || undefined,
          coverageWarnings: payload.coverageWarnings || [],
        });
        break;
      case "fatal_error":
        throw new AiServiceException(
          payload.message || "Variable identification job failed",
          "JOB_FAILED"
        );
      default:
        // status/start events and SSE comments are informational.
        break;
    }
  };

  const pollSameJob = async (): Promise<void> => {
    log(`[AI] Polling extraction job ${jobId} (same model task)`);
    while (!completed) {
      if (signal?.aborted) return;
      const response = await fetch(`${base}/api/documents/identify-jobs/${jobId}`, {
        method: "GET",
        headers: apiHeaders({ Accept: "application/json" }),
        signal,
      });
      if (!response.ok) {
        throw new AiServiceException(
          `Extraction job status returned ${response.status}`,
          "JOB_STATUS_FAILED",
          response.status
        );
      }
      const state = await response.json();
      if (state.status === "completed" && state.result) {
        dispatch("complete", state.result);
        return;
      }
      if (state.status === "failed") {
        throw new AiServiceException(state.error || "Extraction job failed", "JOB_FAILED");
      }
      if (state.status === "cancelled") return;
      await sleep(700);
    }
  };

  const streamSameJob = async (): Promise<void> => {
    const response = await fetch(`${base}/api/documents/identify-jobs/${jobId}/events`, {
      method: "GET",
      headers: apiHeaders({ Accept: "text/event-stream" }),
      signal,
    });
    if (!response.ok || !response.body) {
      throw new AiServiceException(
        `Job event stream returned ${response.status} ${response.statusText}`,
        "STREAM_BAD_STATUS",
        response.status
      );
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    const parseFrame = (frame: string): { event: string; data: string } | null => {
      let event = "message";
      const dataLines: string[] = [];
      for (const line of frame.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        else if (field === "data") dataLines.push(value);
      }
      return dataLines.length ? { event, data: dataLines.join("\n") } : null;
    };

    try {
      while (!completed) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        while (true) {
          const lf = buffer.indexOf("\n\n");
          const crlf = buffer.indexOf("\r\n\r\n");
          let sep = -1;
          let sepLen = 0;
          if (lf !== -1 && (crlf === -1 || lf < crlf)) {
            sep = lf;
            sepLen = 2;
          } else if (crlf !== -1) {
            sep = crlf;
            sepLen = 4;
          }
          if (sep === -1) break;
          const raw = buffer.slice(0, sep);
          buffer = buffer.slice(sep + sepLen);
          const frame = parseFrame(raw);
          if (!frame) continue;
          let payload: any;
          try {
            payload = JSON.parse(frame.data);
          } catch {
            continue;
          }
          dispatch(frame.event, payload);
        }
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        /* ignore */
      }
    }
  };

  try {
    const createResponse = await fetch(`${base}/api/documents/identify-jobs`, {
      method: "POST",
      headers: apiHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(request),
      signal,
    });
    if (!createResponse.ok) {
      const errorData = await createResponse.json().catch(() => ({}));
      throw new AiServiceException(
        errorData.detail || `Could not start extraction job (${createResponse.status})`,
        "JOB_CREATE_FAILED",
        createResponse.status
      );
    }
    const created = await createResponse.json();
    jobId = created.jobId;
    if (!jobId)
      throw new AiServiceException("Backend did not return a job ID", "JOB_CREATE_FAILED");

    if (signal?.aborted) {
      await cancelJob();
      return;
    }

    const shouldStreamJobEvents = supportsResponseStreaming()
      && documentContent.length <= LARGE_DOCUMENT_STREAMING_CHAR_LIMIT;
    if (shouldStreamJobEvents) {
      try {
        await streamSameJob();
      } catch (streamError) {
        if (signal?.aborted) return;
        log(`[AI] Job event stream failed; switching to polling same job: ${String(streamError)}`);
      }
    } else if (documentContent.length > LARGE_DOCUMENT_STREAMING_CHAR_LIMIT) {
      log(
        `[AI] Large document (${documentContent.length} chars): polling extraction job instead of streaming oversized event frames`
      );
    }

    if (!completed && !signal?.aborted) {
      await pollSameJob();
    }
  } catch (err) {
    if (signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) {
      return;
    }
    callbacks.onError(
      err instanceof Error ? err : new AiServiceException(String(err), "JOB_TRANSPORT_FAILED")
    );
  } finally {
    signal?.removeEventListener("abort", abortHandler);
  }
}

/** Resolve the same resilient, single-job transport as a normal Promise. */
export function identifyVariablesViaJob(
  documentContent: string,
  templateId?: string,
  templateName?: string,
  knownVariables?: Variable[],
  signal?: AbortSignal
): Promise<VariableIdentificationResponse> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const finishResolve = (value: VariableIdentificationResponse) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      resolve(value);
    };
    const finishReject = (error: Error) => {
      if (settled) return;
      settled = true;
      signal?.removeEventListener("abort", onAbort);
      reject(error);
    };
    const onAbort = () =>
      finishReject(new DOMException("Variable identification cancelled", "AbortError"));

    if (signal?.aborted) {
      onAbort();
      return;
    }
    signal?.addEventListener("abort", onAbort, { once: true });

    void identifyVariablesStreaming(
      documentContent,
      {
        onComplete: finishResolve,
        onError: finishReject,
      },
      templateId,
      templateName,
      knownVariables,
      signal
    );
  });
}
