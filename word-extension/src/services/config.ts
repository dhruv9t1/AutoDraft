/**
 * API Configuration
 *
 * Production authentication is per-user: the Office/Entra token is exchanged
 * for a short-lived AutoDraft access token and kept only in sessionStorage.
 * No shared production bearer credential is compiled into the add-in bundle.
 */
import { getAutoDraftAccessToken } from "./authSession";

const isDev =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");
const configuredBaseUrl = process.env.REACT_APP_API_BASE_URL || "https://word-addin.duckdns.org";

export const API_BASE_URL = isDev ? "" : configuredBaseUrl.replace(/\/$/, "");

export function apiHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getAutoDraftAccessToken();
  return {
    ...extra,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}
