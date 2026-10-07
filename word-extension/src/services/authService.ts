import {
  clearAutoDraftAccessToken,
  getAutoDraftAccessToken,
  getAutoDraftAccessTokenExpiresAt,
  setAutoDraftAccessToken,
} from "./authSession";

export interface AuthenticatedUser {
  id: string;
  organizationId: string;
  email?: string | null;
  displayName?: string;
  role: string;
}

let refreshTimer: number | undefined;
let inFlight: Promise<AuthenticatedUser | null> | null = null;

function isLocalBackend(apiBaseUrl: string): boolean {
  return (
    !apiBaseUrl &&
    typeof window !== "undefined" &&
    (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1")
  );
}

function scheduleRefresh(apiBaseUrl: string, expiresAt: number): void {
  if (refreshTimer !== undefined) window.clearTimeout(refreshTimer);
  const now = Math.floor(Date.now() / 1000);
  // Refresh five minutes before expiry; never spin faster than once per minute.
  const seconds = Math.max(60, Number(expiresAt || 0) - now - 300);
  refreshTimer = window.setTimeout(() => {
    void initializeOfficeAuthentication(apiBaseUrl, true).catch(() => {
      clearAutoDraftAccessToken();
      window.dispatchEvent(new CustomEvent("autodraft-auth-required"));
    });
    // Refresher is intentionally not awaited; failures are handled by the next retry cycle.
  }, seconds * 1000);
}

async function exchangeOfficeIdentity(apiBaseUrl: string): Promise<AuthenticatedUser | null> {
  const requirements: any = (globalThis as any).Office?.context?.requirements;
  if (requirements?.isSetSupported && !requirements.isSetSupported("IdentityAPI", "1.3")) {
    throw new Error(
      "This Word host does not support the IdentityAPI 1.3 requirement needed for AutoDraft SSO."
    );
  }
  const officeAuth: any = (globalThis as any).Office?.auth;
  if (!officeAuth?.getAccessToken) {
    throw new Error(
      "Microsoft Office SSO is unavailable in this Word host. Deploy AutoDraft with an SSO-enabled manifest."
    );
  }
  const officeToken = await officeAuth.getAccessToken({
    allowSignInPrompt: true,
    allowConsentPrompt: true,
    forMSGraphAccess: false,
  });
  if (!officeToken) throw new Error("Microsoft Office did not return an identity token.");

  const response = await fetch(`${apiBaseUrl}/api/auth/office-exchange`, {
    method: "POST",
    headers: { Authorization: `Bearer ${officeToken}`, "Content-Type": "application/json" },
  });
  if (!response.ok) {
    let detail = "AutoDraft sign-in failed";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : body?.detail?.message || detail;
    } catch {
      // Non-JSON error body: keep the generic sign-in failure message.
    }
    throw new Error(detail);
  }
  const body = await response.json();
  const accessToken = String(body.accessToken || "");
  const expiresAt = Number(body.expiresAt || 0);
  setAutoDraftAccessToken(accessToken, expiresAt);
  if (!getAutoDraftAccessToken()) throw new Error("AutoDraft did not issue a usable access token.");
  scheduleRefresh(apiBaseUrl, expiresAt);
  return body.user || null;
}

/**
 * Acquire an Office/Entra access token and exchange it for a short-lived,
 * tenant-scoped AutoDraft token. The Office token is never persisted.
 * A refresh is scheduled before the AutoDraft token expires.
 */
export async function initializeOfficeAuthentication(
  apiBaseUrl: string,
  forceRefresh = false
): Promise<AuthenticatedUser | null> {
  if (isLocalBackend(apiBaseUrl)) {
    return null;
  }
  if (!forceRefresh) {
    const cached = getAutoDraftAccessToken();
    if (cached) {
      scheduleRefresh(apiBaseUrl, getAutoDraftAccessTokenExpiresAt());
      return null;
    }
  }
  if (inFlight) {
    return inFlight;
  }
  inFlight = exchangeOfficeIdentity(apiBaseUrl).finally(() => {
    inFlight = null;
  });
  return inFlight;
}
