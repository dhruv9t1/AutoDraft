import type { BindingOperation } from "./bindingPlanner";
import { normalizeShadowText, type DocumentSourceLocation } from "./documentStructure";

export interface BindingLocationEvidence {
  segmentId: string;
  startOffset: number;
  endSegmentId?: string;
  endOffset?: number;
  source: DocumentSourceLocation;
  endSource?: DocumentSourceLocation;
}

export function normalizeBindingText(value: string): string {
  return normalizeShadowText(value || "").toLowerCase();
}

/** SHA-256 of the exact Word text. No normalization is applied. */
export async function sha256Hex(value: string): Promise<string> {
  const cryptoObject = typeof globalThis !== "undefined" ? globalThis.crypto : undefined;
  if (!cryptoObject?.subtle) {
    throw new Error(
      "This Word host does not expose Web Crypto SHA-256; exact binding integrity cannot be verified."
    );
  }
  const raw = value || "";
  const bytes =
    typeof TextEncoder !== "undefined"
      ? new TextEncoder().encode(raw)
      : new Uint8Array(Array.from(unescape(encodeURIComponent(raw))).map((ch) => ch.charCodeAt(0)));
  const digest = await cryptoObject.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Return the exact non-overlapping occurrence index at `offset`.
 * Matching rules intentionally mirror Word search in bindingService:
 * case-sensitive, punctuation-sensitive and whitespace-sensitive.
 */
export function exactOccurrenceIndex(text: string, needle: string, offset: number): number {
  if (!needle) throw new Error("Cannot locate an empty Word binding anchor.");
  if (
    offset < 0 ||
    offset + needle.length > text.length ||
    text.slice(offset, offset + needle.length) !== needle
  ) {
    throw new Error("The grounded Word anchor no longer matches its exact source offset.");
  }
  let occurrence = 0;
  let at = 0;
  while (true) {
    const found = text.indexOf(needle, at);
    if (found < 0) break;
    if (found === offset) return occurrence;
    if (found > offset) break;
    occurrence += 1;
    at = found + Math.max(1, needle.length);
  }
  throw new Error("The grounded Word anchor could not be mapped to an exact occurrence.");
}

export function locationEvidenceForOperation(operation: BindingOperation): BindingLocationEvidence {
  return {
    segmentId: operation.source.start.segmentId,
    startOffset: operation.source.start.offset,
    endSegmentId: operation.source.end.segmentId,
    endOffset: operation.source.end.offset,
    source: { ...operation.source.start.source },
    endSource:
      operation.source.end.segmentId === operation.source.start.segmentId
        ? undefined
        : { ...operation.source.end.source },
  };
}

/** Verify that the live control text still begins at the recorded structural offset. */
export function textMatchesRecordedOffset(
  paragraphText: string,
  liveControlText: string,
  startOffset: number
): boolean {
  if (startOffset < 0 || startOffset > paragraphText.length) return false;
  const observed = paragraphText.slice(startOffset, startOffset + liveControlText.length);
  return normalizeBindingText(observed) === normalizeBindingText(liveControlText);
}
