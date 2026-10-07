/**
 * Health Check Service
 * Checks backend connectivity via the /health endpoint
 */

import { API_BASE_URL } from "./config";
import { log, warn } from "./logger";

const HEALTH_TIMEOUT_MS = 5000;

export interface HealthStatus {
  healthy: boolean;
  message: string;
}

/**
 * Checks backend health by calling the /health endpoint.
 * Returns { healthy, message } — never throws.
 */
export async function checkBackendHealth(): Promise<HealthStatus> {
  const healthUrl = API_BASE_URL ? `${API_BASE_URL}/health` : "/health";

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);

  try {
    log(`[HealthService] Checking backend health: ${healthUrl}`);
    const response = await fetch(healthUrl, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (response.ok) {
      log("[HealthService] Backend is healthy");
      return { healthy: true, message: "Backend is connected" };
    }

    warn(`[HealthService] Backend returned status ${response.status}`);
    return {
      healthy: false,
      message: `Backend returned status ${response.status}`,
    };
  } catch (error) {
    clearTimeout(timeout);
    const msg = error instanceof Error ? error.message : String(error);
    warn(`[HealthService] Backend health check failed: ${msg}`);
    return {
      healthy: false,
      message: `Cannot connect to backend: ${msg}`,
    };
  }
}
