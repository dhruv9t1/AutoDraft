import { API_BASE_URL, apiHeaders } from "../config";

export interface ApiFailure {
  code?: string;
  message: string;
  recoverable?: boolean;
  requestId?: string;
  status: number;
}

export class ApiClientError extends Error {
  constructor(public readonly failure: ApiFailure) {
    super(failure.message);
    this.name = "ApiClientError";
  }
}

function requestId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `autodraft-${Date.now()}`;
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const rid = requestId();
  const response = await fetch(API_BASE_URL + path, {
    ...init,
    headers: apiHeaders({
      "Content-Type": "application/json",
      "X-Correlation-ID": rid,
      ...((init.headers as Record<string, string>) || {}),
    }),
  });
  if (!response.ok) {
    let body: any = {};
    try {
      body = await response.json();
    } catch {
      // Invalid JSON body; fall back to empty payload handling below.
    }
    const payload = body?.error || body?.detail || body || {};
    const message =
      typeof payload === "string"
        ? payload
        : payload.message || `Request failed (${response.status})`;
    throw new ApiClientError({
      code: payload.code,
      message,
      recoverable: payload.recoverable,
      requestId: payload.requestId || response.headers.get("X-Correlation-ID") || rid,
      status: response.status,
    });
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
