const TOKEN_KEY = "autodraft.accessToken";
const EXP_KEY = "autodraft.accessTokenExp";

export function getAutoDraftAccessToken(): string {
  try {
    const token = sessionStorage.getItem(TOKEN_KEY) || "";
    const exp = Number(sessionStorage.getItem(EXP_KEY) || "0");
    if (!token || (exp && exp <= Math.floor(Date.now() / 1000) + 30)) {
      clearAutoDraftAccessToken();
      return "";
    }
    return token;
  } catch {
    return "";
  }
}

export function setAutoDraftAccessToken(token: string, expiresAt: number): void {
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(EXP_KEY, String(expiresAt || 0));
  } catch {
    // Session storage unavailable; token stays in memory only.
  }
}

export function clearAutoDraftAccessToken(): void {
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(EXP_KEY);
  } catch {
    // Session storage unavailable; nothing to clear.
  }
}

export function getAutoDraftAccessTokenExpiresAt(): number {
  try {
    return Number(sessionStorage.getItem(EXP_KEY) || "0");
  } catch {
    return 0;
  }
}
