import { API_BASE_URL, apiHeaders } from "./config";
import { OcrDependencyStatus, OcrJobResult } from "./types";

const base = () => API_BASE_URL || "";
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function apiError(response: Response, fallback: string): Promise<Error> {
  const payload = await response.json().catch(() => ({}));
  return new Error(payload.detail || payload.error || fallback);
}

export async function getOcrStatus(signal?: AbortSignal): Promise<OcrDependencyStatus> {
  const response = await fetch(`${base()}/api/ocr/status`, {
    headers: apiHeaders({ Accept: "application/json" }),
    signal,
  });
  if (!response.ok) throw await apiError(response, "Could not check local OCR dependencies.");
  return response.json();
}

export async function startOcrJob(file: File, signal?: AbortSignal): Promise<OcrJobResult> {
  const form = new FormData();
  form.append("file", file, file.name);
  const response = await fetch(`${base()}/api/ocr/jobs`, {
    method: "POST",
    headers: apiHeaders(),
    body: form,
    signal,
  });
  if (!response.ok) throw await apiError(response, `Could not start OCR (${response.status}).`);
  return response.json();
}

export async function getOcrJob(jobId: string, signal?: AbortSignal): Promise<OcrJobResult> {
  const response = await fetch(`${base()}/api/ocr/jobs/${jobId}`, {
    headers: apiHeaders({ Accept: "application/json" }),
    signal,
  });
  if (!response.ok) throw await apiError(response, `Could not read OCR job (${response.status}).`);
  return response.json();
}

export async function processOcrFile(file: File, signal?: AbortSignal): Promise<OcrJobResult> {
  const created = await startOcrJob(file, signal);
  try {
    while (true) {
      if (signal?.aborted) throw new DOMException("OCR cancelled", "AbortError");
      const job = await getOcrJob(created.jobId, signal);
      if (job.status === "completed") return job;
      if (job.status === "failed") throw new Error(job.error || "OCR failed.");
      if (job.status === "cancelled") throw new Error("OCR was cancelled.");
      await sleep(800);
    }
  } catch (error) {
    if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      await cancelOcrJob(created.jobId);
    }
    throw error;
  }
}

export async function cancelOcrJob(jobId: string): Promise<void> {
  await fetch(`${base()}/api/ocr/jobs/${jobId}`, {
    method: "DELETE",
    headers: apiHeaders(),
  }).catch(() => undefined);
}

export async function downloadSearchablePdf(jobId: string, filename: string): Promise<void> {
  const response = await fetch(`${base()}/api/ocr/jobs/${jobId}/searchable-pdf`, {
    headers: apiHeaders({ Accept: "application/pdf" }),
  });
  if (!response.ok) throw await apiError(response, "Could not download searchable PDF.");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    const stem = filename.replace(/\.[^.]+$/, "") || "document";
    anchor.download = `${stem}-searchable.pdf`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
