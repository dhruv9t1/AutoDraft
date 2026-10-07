/**
 * Analysis Service
 * Provides document summary, risk assessment, and deadline extraction
 * using the backend LLM endpoints.
 */

import { API_BASE_URL } from "./config";
import { log } from "./logger";
import { SummaryResponse, RiskAssessmentResponse, DeadlineResponse } from "./types";

const API_TIMEOUT = 120000; // 2 minutes for analysis calls

/**
 * Creates a timeout promise
 */
function createTimeoutPromise(timeoutMs: number): Promise<never> {
  return new Promise((_, reject) => {
    setTimeout(() => {
      reject(new Error(`Analysis request timed out after ${timeoutMs / 1000}s`));
    }, timeoutMs);
  });
}

/**
 * Gets the API URL for a given path
 */
function getApiUrl(path: string): string {
  return API_BASE_URL ? `${API_BASE_URL}${path}` : path;
}

/**
 * Generate a structured document summary
 * Returns document type, key parties, dates, amounts, legal references, and urgency
 */
export async function getDocumentSummary(documentContent: string): Promise<SummaryResponse> {
  log("[Analysis] Requesting document summary...");

  const url = getApiUrl("/api/documents/summarize");
  const response = await Promise.race([
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documentContent }),
    }),
    createTimeoutPromise(API_TIMEOUT),
  ]);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      `Summary failed (${response.status}): ${errorData.message || response.statusText}`
    );
  }

  const data: SummaryResponse = await response.json();
  log(
    `[Analysis] Summary: type=${data.documentType}, urgency=${data.urgency}, ` +
      `parties=${data.keyParties.length}, dates=${data.keyDates.length}`
  );
  return data;
}

/**
 * Assess risk level of a document
 * Returns risk score, risk factors, compliance issues, and recommendations
 */
export async function getRiskAssessment(
  documentContent: string,
  documentType?: string
): Promise<RiskAssessmentResponse> {
  log("[Analysis] Requesting risk assessment...");

  const url = getApiUrl("/api/documents/risk-assessment");
  const response = await Promise.race([
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documentContent, documentType }),
    }),
    createTimeoutPromise(API_TIMEOUT),
  ]);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      `Risk assessment failed (${response.status}): ${errorData.message || response.statusText}`
    );
  }

  const data: RiskAssessmentResponse = await response.json();
  log(
    `[Analysis] Risk: score=${data.riskScore}, overall=${data.overallRisk}, ` +
      `factors=${data.riskFactors.length}, issues=${data.complianceIssues.length}`
  );
  return data;
}

/**
 * Extract deadlines and notices from a document
 * Returns deadlines with urgency levels and notices with response deadlines
 */
export async function getDeadlines(documentContent: string): Promise<DeadlineResponse> {
  log("[Analysis] Requesting deadline extraction...");

  const url = getApiUrl("/api/documents/deadlines");
  const response = await Promise.race([
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ documentContent }),
    }),
    createTimeoutPromise(API_TIMEOUT),
  ]);

  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(
      `Deadline extraction failed (${response.status}): ${errorData.message || response.statusText}`
    );
  }

  const data: DeadlineResponse = await response.json();
  log(`[Analysis] Deadlines: ${data.deadlines.length} deadlines, ${data.notices.length} notices`);
  return data;
}
