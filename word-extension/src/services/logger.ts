/**
 * Privacy-safe frontend diagnostic logger.
 *
 * Security invariants:
 * - disabled in production builds;
 * - disabled unless explicitly enabled for loopback development;
 * - remote forwarding is a separate opt-in and loopback-only;
 * - arbitrary objects/document values are never serialized;
 * - error context contains class/type only, never raw messages/stacks.
 */

type LogLevel = "log" | "info" | "warn" | "error" | "debug";

interface LogEntry {
  level: LogLevel;
  message: string;
  timestamp: string;
  context?: Record<string, unknown>;
}

const isProductionBuild = process.env.NODE_ENV === "production";
const isLoopbackHost =
  typeof window !== "undefined" &&
  (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1");
const diagnosticEnabled =
  !isProductionBuild &&
  isLoopbackHost &&
  process.env.REACT_APP_ENABLE_DIAGNOSTIC_LOGGING === "true";
const remoteEnabled = diagnosticEnabled && process.env.REACT_APP_ENABLE_REMOTE_LOGGING === "true";
const configuredLoggerUrl = String(process.env.REACT_APP_LOGGER_URL || "").trim();

function safeLocalLoggerUrl(value: string): string | null {
  if (!value || typeof window === "undefined") return null;
  try {
    const url = new URL(value, window.location.origin);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") return null;
    if (url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

const SENSITIVE_MARKERS = [
  "existing values",
  "filtered values",
  "original text",
  "document text",
  "document content",
  "matter facts",
  "known facts",
  "manual variable",
  "docxbase64",
  "bodyooxml",
  "answers:",
  "replacement text",
  "placeholder text",
  "currentvalue",
  "variable values",
  "response data",
  "error data",
];

function sanitizeMessage(message: string): string {
  let value = String(message || "").replace(/[\r\n\t]+/g, " ");
  const lower = value.toLowerCase();
  if (SENSITIVE_MARKERS.some((marker) => lower.includes(marker))) {
    const prefixEnd = value.indexOf(":");
    value = `${prefixEnd >= 0 ? value.slice(0, prefixEnd + 1) : "[Diagnostic]"} [REDACTED]`;
  }
  value = value.replace(/(Bearer\s+)[A-Za-z0-9._~-]+/gi, "$1[REDACTED]");
  value = value.replace(/\/(intake|workflow)\/[A-Za-z0-9_-]{12,}/gi, "/$1/[REDACTED]");
  value = value.replace(/[A-Za-z0-9+/]{160,}={0,2}/g, "[LARGE_DATA_REDACTED]");
  // Email and common phone-number forms are never useful in diagnostics.
  value = value.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, "[EMAIL_REDACTED]");
  value = value.replace(/(?:\+?\d[\d\s().-]{8,}\d)/g, "[PHONE_REDACTED]");
  return value.slice(0, 600);
}

function safeContext(args: unknown[]): Record<string, unknown> | undefined {
  if (!args.length) return undefined;
  return {
    argumentTypes: args.map((arg) => {
      if (arg instanceof Error) return `Error:${arg.name}`;
      if (arg === null) return "null";
      if (Array.isArray(arg)) return "array";
      return typeof arg;
    }),
  };
}

class FrontendLogger {
  private enabled = diagnosticEnabled;
  private remoteUrl = remoteEnabled ? safeLocalLoggerUrl(configuredLoggerUrl) : null;

  setEnabled(enabled: boolean): void {
    // Runtime callers can only disable logging; production cannot be enabled at runtime.
    this.enabled = diagnosticEnabled && enabled;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  private async forward(entry: LogEntry): Promise<void> {
    if (!this.enabled || !this.remoteUrl) return;
    try {
      await fetch(this.remoteUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(entry),
        mode: "cors",
        credentials: "omit",
        cache: "no-store",
        referrerPolicy: "no-referrer",
      });
    } catch {
      // Diagnostic transport failure must never affect drafting/document flows.
    }
  }

  private emit(level: LogLevel, message: string, args: unknown[]): void {
    if (!this.enabled) return;
    const safeMessage = sanitizeMessage(message);
    const method = level === "log" ? "log" : level;
    const consoleMethod = (console as any)?.[method];
    if (typeof consoleMethod === "function") consoleMethod.call(console, safeMessage);
    void this.forward({
      level,
      message: safeMessage,
      timestamp: new Date().toISOString(),
      context: safeContext(args),
    });
  }

  log(message: string, ...args: unknown[]): void {
    this.emit("log", message, args);
  }
  info(message: string, ...args: unknown[]): void {
    this.emit("info", message, args);
  }
  warn(message: string, ...args: unknown[]): void {
    this.emit("warn", message, args);
  }
  error(message: string, ...args: unknown[]): void {
    this.emit("error", message, args);
  }
  debug(message: string, ...args: unknown[]): void {
    this.emit("debug", message, args);
  }
}

const logger = new FrontendLogger();
export default logger;
export const log = logger.log.bind(logger);
export const info = logger.info.bind(logger);
export const warn = logger.warn.bind(logger);
export const error = logger.error.bind(logger);
export const debug = logger.debug.bind(logger);
export const diagnosticsEnabled = () => logger.isEnabled();
