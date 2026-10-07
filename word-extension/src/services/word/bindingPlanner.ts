import type { Variable } from "../types";
import type {
  DocumentSegment,
  DocumentStructure,
  DocumentSourceLocation,
} from "./documentStructure";
import { normalizeShadowText } from "./documentStructure";

export interface BindingEndpoint {
  segmentId: string;
  offset: number;
  source: DocumentSourceLocation;
}
export interface BindingSourceRange {
  start: BindingEndpoint;
  end: BindingEndpoint;
}
export interface BindingOperation {
  operationId: string;
  bindingId: string;
  fieldId?: string;
  semanticKey: string;
  displayLabel: string;
  expectedText: string;
  occurrenceId: string;
  source: BindingSourceRange;
  globalStart: number;
  globalEnd: number;
}
export type BindingConflictCode =
  | "not_found"
  | "ambiguous"
  | "overlap"
  | "existing_control"
  | "duplicate_binding"
  | "unsupported_segment";
export interface BindingConflict {
  code: BindingConflictCode;
  message: string;
  bindingId?: string;
  blocking: boolean;
}
export interface BindingPlan {
  operations: readonly BindingOperation[];
  conflicts: readonly BindingConflict[];
  canCommit: boolean;
  alreadyBound: number;
}

const STORY_BOUNDARY = "\uE000";
function id(prefix: string): string {
  try {
    return `${prefix}:${crypto.randomUUID()}`;
  } catch {
    return `${prefix}:${Date.now()}:${Math.random().toString(16).slice(2)}`;
  }
}

function internalFlat(structure: DocumentStructure): string {
  let out = "";
  let previous: DocumentSegment | null = null;
  for (const segment of structure.segments) {
    if (previous) out += previous.groupKey === segment.groupKey ? "\n" : STORY_BOUNDARY;
    out += segment.text;
    previous = segment;
  }
  return out;
}

function normalizeWithMap(text: string): { text: string; map: number[] } {
  let out = "";
  const map: number[] = [];
  let space = false;
  const digit: Record<string, string> = {
    "૦": "0",
    "૧": "1",
    "૨": "2",
    "૩": "3",
    "૪": "4",
    "૫": "5",
    "૬": "6",
    "૭": "7",
    "૮": "8",
    "૯": "9",
    "०": "0",
    "१": "1",
    "२": "2",
    "३": "3",
    "४": "4",
    "५": "5",
    "६": "6",
    "७": "7",
    "८": "8",
    "९": "9",
  };
  for (let i = 0; i < text.length; i++) {
    let ch = text[i];
    if (ch === STORY_BOUNDARY) {
      out += ch;
      map.push(i);
      space = false;
      continue;
    }
    ch = digit[ch] || ch;
    if (/[\u00A0\u2007\u202F\s]/.test(ch)) {
      if (!space && out.length) {
        out += " ";
        map.push(i);
      }
      space = true;
      continue;
    }
    space = false;
    if (/[“”„‟]/.test(ch)) ch = '"';
    else if (/[‘’‚‛]/.test(ch)) ch = "'";
    else if (/[‐‑‒–—―]/.test(ch)) ch = "-";
    out += ch;
    map.push(i);
  }
  const left = out.length - out.trimStart().length;
  const rightTrimmed = out.trimEnd().length;
  return { text: out.slice(left, rightTrimmed), map: map.slice(left, rightTrimmed) };
}

function allHits(
  haystack: string,
  needle: string
): Array<{ start: number; end: number; tier: "exact" | "normalized" }> {
  const hits: Array<{ start: number; end: number; tier: "exact" | "normalized" }> = [];
  if (!needle) return hits;
  let at = 0;
  while ((at = haystack.indexOf(needle, at)) !== -1) {
    hits.push({ start: at, end: at + needle.length, tier: "exact" });
    at += Math.max(1, needle.length);
  }
  if (hits.length) return hits;
  const hv = normalizeWithMap(haystack);
  const nv = normalizeShadowText(needle);
  if (!nv) return hits;
  let ni = 0;
  while ((ni = hv.text.indexOf(nv, ni)) !== -1) {
    const start = hv.map[ni];
    const last = hv.map[Math.min(hv.map.length - 1, ni + nv.length - 1)];
    if (start !== undefined && last !== undefined)
      hits.push({ start, end: last + 1, tier: "normalized" });
    ni += Math.max(1, nv.length);
  }
  return hits;
}

function segmentAt(structure: DocumentStructure, offset: number): DocumentSegment | null {
  for (const s of structure.segments)
    if (offset >= s.globalStart && offset <= s.globalEnd) return s;
  return null;
}

function valueKey(v: Variable): string {
  return normalizeShadowText(v.originalText || "").toLowerCase();
}

/** Pure planning stage: no Word mutation occurs here. */
export function buildBindingPlan(variables: Variable[], structure: DocumentStructure): BindingPlan {
  const flat = internalFlat(structure);
  const conflicts: BindingConflict[] = [];
  const candidates: BindingOperation[] = [];
  let alreadyBound = 0;
  const existingByTag = new Map<string, string[]>();
  for (const control of structure.segments.flatMap((s) => s.existingControls)) {
    const tag = (control.tag || "").trim().toLowerCase();
    if (!tag) continue;
    const rows = existingByTag.get(tag) || [];
    rows.push(normalizeShadowText(control.text || "").toLowerCase());
    existingByTag.set(tag, rows);
  }
  const groups = new Map<string, Variable[]>();
  for (const variable of variables) {
    const key = valueKey(variable);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(variable);
  }

  for (const variable of variables) {
    const bindingId = (variable.bindingId || "").trim();
    const original = (variable.originalText || "").trim();
    if (!bindingId || !original) {
      conflicts.push({
        code: "not_found",
        message: `${variable.name}: missing immutable binding ID or source text.`,
        bindingId,
        blocking: false,
      });
      continue;
    }
    const existingTexts = existingByTag.get(bindingId.toLowerCase());
    if (existingTexts) {
      const expected = normalizeShadowText(original).toLowerCase();
      const verified = existingTexts.some(
        (text) =>
          !!text &&
          !!expected &&
          (text === expected || text.includes(expected) || expected.includes(text))
      );
      if (verified) {
        alreadyBound += 1;
        continue;
      }
      conflicts.push({
        code: "existing_control",
        message: `${variable.name}: an existing control has this binding ID but no longer contains the expected source text.`,
        bindingId,
        blocking: true,
      });
      continue;
    }
    let hits = allHits(flat, original).filter(
      (h) => !flat.slice(h.start, h.end).includes(STORY_BOUNDARY)
    );
    if (!hits.length) {
      conflicts.push({
        code: "not_found",
        message: `${variable.name}: source text could not be grounded in Word.`,
        bindingId,
        blocking: false,
      });
      continue;
    }
    const same = groups.get(valueKey(variable)) || [];
    if (same.length > 1 && variable.position >= 0) {
      const distances = hits.map((h) => Math.abs(h.start - variable.position));
      const min = Math.min(...distances);
      const winners = hits.filter((_, i) => distances[i] === min);
      if (winners.length !== 1) {
        conflicts.push({
          code: "ambiguous",
          message: `${variable.name}: repeated value could not be tied to one occurrence.`,
          bindingId,
          blocking: false,
        });
        continue;
      }
      hits = winners;
    }
    for (const hit of hits) {
      const startSeg = segmentAt(structure, hit.start);
      const endSeg = segmentAt(structure, Math.max(hit.start, hit.end - 1));
      if (!startSeg || !endSeg || startSeg.groupKey !== endSeg.groupKey) {
        conflicts.push({
          code: "unsupported_segment",
          message: `${variable.name}: occurrence crosses an unsupported Word story boundary.`,
          bindingId,
          blocking: false,
        });
        continue;
      }
      candidates.push({
        operationId: id("bind"),
        bindingId,
        fieldId: variable.id,
        semanticKey: (variable as any).semanticKey || variable.name,
        displayLabel: variable.name,
        expectedText: flat.slice(hit.start, hit.end).replace(new RegExp(STORY_BOUNDARY, "g"), "\n"),
        occurrenceId: id("occ"),
        source: {
          start: {
            segmentId: startSeg.segmentId,
            offset: hit.start - startSeg.globalStart,
            source: startSeg.source,
          },
          end: {
            segmentId: endSeg.segmentId,
            offset: hit.end - endSeg.globalStart,
            source: endSeg.source,
          },
        },
        globalStart: hit.start,
        globalEnd: hit.end,
      });
    }
  }

  // Longest-first overlap planner. Nested/overlapping candidates are resolved
  // before mutation, never by relying on Word's GeneralException.
  candidates.sort(
    (a, b) =>
      b.globalEnd - b.globalStart - (a.globalEnd - a.globalStart) || a.globalStart - b.globalStart
  );
  const kept: BindingOperation[] = [];
  for (const op of candidates) {
    const overlap = kept.find(
      (k) => !(op.globalEnd <= k.globalStart || op.globalStart >= k.globalEnd)
    );
    if (overlap) {
      conflicts.push({
        code: "overlap",
        message: `${op.displayLabel} overlaps ${overlap.displayLabel}; longest grounded occurrence owns the span.`,
        bindingId: op.bindingId,
        blocking: false,
      });
      continue;
    }
    kept.push(op);
  }
  kept.sort((a, b) => a.globalStart - b.globalStart);
  const canCommit = !conflicts.some((c) => c.blocking);
  return Object.freeze({
    operations: Object.freeze(kept.map((x) => Object.freeze(x))),
    conflicts: Object.freeze(conflicts.map((x) => Object.freeze(x))),
    canCommit,
    alreadyBound,
  });
}
