import type { Variable } from "./types";
import { log } from "./logger";
import { wordOperationQueue } from "./word/operationQueue";
import {
  normalizeBindingText,
  sha256Hex,
  type BindingLocationEvidence,
} from "./word/bindingIntegrity";

export const AUTODRAFT_MANIFEST_NAMESPACE = "urn:autodraft:document:v1";
export const AUTODRAFT_MANIFEST_SCHEMA_VERSION = 3;

export interface AutoDraftManifestBinding {
  bindingId: string;
  fieldId?: string;
  semanticKey?: string;
  /** Stable occurrence identity produced by the immutable binding plan. */
  occurrenceId?: string;
  /** Word's exact content-control identifier for this occurrence. */
  controlId?: number;
  /** Current AutoDraft-approved text for integrity reconciliation. */
  expectedTextNormalized?: string;
  /** SHA-256 of the exact raw Word text; catches case/spacing/punctuation drift hidden by normalization. */
  expectedTextSha256?: string;
  /** Raw current text length, used to shift later structural offsets after intentional edits. */
  expectedTextLength?: number;
  /** Expected Word content-control title/display label. */
  expectedTitle?: string;
  /** Structural source evidence used to detect movement/copy-paste corruption. */
  location?: BindingLocationEvidence;
}

export interface AutoDraftDocumentManifest {
  schemaVersion: number;
  documentId: string;
  templateId?: string;
  matterId?: string;
  bindings: AutoDraftManifestBinding[];
}

function randomId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `autodraft-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function attr(name: string, value: string | number | undefined): string {
  return value === undefined || value === "" ? "" : ` ${name}="${escapeXml(String(value))}"`;
}

function bindingXml(binding: AutoDraftManifestBinding): string {
  const location = binding.location;
  return (
    `<binding` +
    attr("id", binding.bindingId) +
    attr("fieldId", binding.fieldId) +
    attr("semanticKey", binding.semanticKey) +
    attr("occurrenceId", binding.occurrenceId) +
    attr("controlId", binding.controlId) +
    attr("expectedText", binding.expectedTextNormalized) +
    attr("expectedTextSha256", binding.expectedTextSha256) +
    attr("expectedTextLength", binding.expectedTextLength) +
    attr("expectedTitle", binding.expectedTitle) +
    attr("segmentId", location?.segmentId) +
    attr("startOffset", location?.startOffset) +
    attr("endSegmentId", location?.endSegmentId) +
    attr("endOffset", location?.endOffset) +
    attr("story", location?.source.story) +
    attr("paragraphIndex", location?.source.paragraphIndex) +
    attr("tableIndex", location?.source.tableIndex) +
    attr("rowIndex", location?.source.rowIndex) +
    attr("cellIndex", location?.source.cellIndex) +
    attr("sectionIndex", location?.source.sectionIndex) +
    attr("headerFooterKind", location?.source.headerFooterKind) +
    attr("endStory", location?.endSource?.story) +
    attr("endParagraphIndex", location?.endSource?.paragraphIndex) +
    attr("endTableIndex", location?.endSource?.tableIndex) +
    attr("endRowIndex", location?.endSource?.rowIndex) +
    attr("endCellIndex", location?.endSource?.cellIndex) +
    attr("endSectionIndex", location?.endSource?.sectionIndex) +
    attr("endHeaderFooterKind", location?.endSource?.headerFooterKind) +
    "/>"
  );
}

function toXml(manifest: AutoDraftDocumentManifest): string {
  const attrs = [
    `xmlns="${AUTODRAFT_MANIFEST_NAMESPACE}"`,
    `schemaVersion="${manifest.schemaVersion}"`,
  ].join(" ");
  const bindings = manifest.bindings
    .filter((binding) => !!binding.bindingId)
    .map(bindingXml)
    .join("");

  return (
    `<?xml version="1.0" encoding="UTF-8"?>` +
    `<autodraft ${attrs}>` +
    `<documentId>${escapeXml(manifest.documentId)}</documentId>` +
    (manifest.templateId ? `<templateId>${escapeXml(manifest.templateId)}</templateId>` : "") +
    (manifest.matterId ? `<matterId>${escapeXml(manifest.matterId)}</matterId>` : "") +
    `<bindings>${bindings}</bindings>` +
    `</autodraft>`
  );
}

function optionalNumber(node: Element, name: string): number | undefined {
  const raw = (node.getAttribute(name) || "").trim();
  if (!raw) return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function parseBinding(node: Element): AutoDraftManifestBinding | null {
  const bindingId = (node.getAttribute("id") || "").trim();
  if (!bindingId) return null;
  const story = (node.getAttribute("story") || "").trim() as
    BindingLocationEvidence["source"]["story"] | "";
  const segmentId = (node.getAttribute("segmentId") || "").trim();
  const startOffset = optionalNumber(node, "startOffset");
  const endStory = (node.getAttribute("endStory") || "").trim() as
    BindingLocationEvidence["source"]["story"] | "";
  const location =
    story && segmentId && startOffset !== undefined
      ? {
          segmentId,
          startOffset,
          endSegmentId: (node.getAttribute("endSegmentId") || "").trim() || undefined,
          endOffset: optionalNumber(node, "endOffset"),
          source: {
            story,
            paragraphIndex: optionalNumber(node, "paragraphIndex"),
            tableIndex: optionalNumber(node, "tableIndex"),
            rowIndex: optionalNumber(node, "rowIndex"),
            cellIndex: optionalNumber(node, "cellIndex"),
            sectionIndex: optionalNumber(node, "sectionIndex"),
            headerFooterKind: ((node.getAttribute("headerFooterKind") || "").trim() ||
              undefined) as BindingLocationEvidence["source"]["headerFooterKind"],
          },
          endSource: endStory
            ? {
                story: endStory,
                paragraphIndex: optionalNumber(node, "endParagraphIndex"),
                tableIndex: optionalNumber(node, "endTableIndex"),
                rowIndex: optionalNumber(node, "endRowIndex"),
                cellIndex: optionalNumber(node, "endCellIndex"),
                sectionIndex: optionalNumber(node, "endSectionIndex"),
                headerFooterKind: ((node.getAttribute("endHeaderFooterKind") || "").trim() ||
                  undefined) as BindingLocationEvidence["source"]["headerFooterKind"],
              }
            : undefined,
        }
      : undefined;
  return {
    bindingId,
    fieldId: (node.getAttribute("fieldId") || "").trim() || undefined,
    semanticKey: (node.getAttribute("semanticKey") || "").trim() || undefined,
    occurrenceId: (node.getAttribute("occurrenceId") || "").trim() || undefined,
    controlId: optionalNumber(node, "controlId"),
    expectedTextNormalized: (node.getAttribute("expectedText") || "").trim() || undefined,
    expectedTextSha256: (node.getAttribute("expectedTextSha256") || "").trim() || undefined,
    expectedTextLength: optionalNumber(node, "expectedTextLength"),
    expectedTitle: (node.getAttribute("expectedTitle") || "").trim() || undefined,
    location,
  };
}

function parseXml(xml: string): AutoDraftDocumentManifest | null {
  if (!xml || typeof DOMParser === "undefined") return null;
  try {
    const doc = new DOMParser().parseFromString(xml, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) return null;
    const root = doc.documentElement;
    if (!root || root.localName !== "autodraft") return null;
    const text = (name: string) => {
      const node = root.getElementsByTagNameNS("*", name)[0] || root.getElementsByTagName(name)[0];
      return (node?.textContent || "").trim();
    };
    const documentId = text("documentId");
    if (!documentId) return null;
    const schemaVersion = Number(root.getAttribute("schemaVersion") || 1);
    const bindingNodes = Array.from(root.getElementsByTagNameNS("*", "binding"));
    const bindings = bindingNodes
      .map(parseBinding)
      .filter((binding): binding is AutoDraftManifestBinding => !!binding);
    return {
      schemaVersion: Number.isFinite(schemaVersion) ? schemaVersion : 1,
      documentId,
      templateId: text("templateId") || undefined,
      matterId: text("matterId") || undefined,
      bindings,
    };
  } catch {
    return null;
  }
}

function customXmlParts(): any | null {
  try {
    if (typeof Office === "undefined") return null;
    const doc: any = Office.context?.document;
    return doc?.customXmlParts || null;
  } catch {
    return null;
  }
}

function getPartsByNamespace(parts: any): Promise<any[]> {
  return new Promise((resolve) => {
    try {
      parts.getByNamespaceAsync(AUTODRAFT_MANIFEST_NAMESPACE, (result: any) => {
        if (result?.status === Office.AsyncResultStatus.Succeeded && Array.isArray(result.value)) {
          resolve(result.value);
        } else {
          resolve([]);
        }
      });
    } catch {
      resolve([]);
    }
  });
}

function getPartXml(part: any): Promise<string> {
  return new Promise((resolve) => {
    try {
      part.getXmlAsync((result: any) => {
        resolve(
          result?.status === Office.AsyncResultStatus.Succeeded ? String(result.value || "") : ""
        );
      });
    } catch {
      resolve("");
    }
  });
}

function deletePart(part: any): Promise<void> {
  return new Promise((resolve) => {
    try {
      part.deleteAsync(() => resolve());
    } catch {
      resolve();
    }
  });
}

function addPart(parts: any, xml: string): Promise<any | null> {
  return new Promise((resolve) => {
    try {
      parts.addAsync(xml, (result: any) => {
        resolve(
          result?.status === Office.AsyncResultStatus.Succeeded ? result.value || null : null
        );
      });
    } catch {
      resolve(null);
    }
  });
}

/** Reads AutoDraft's document-level manifest from the DOCX custom XML store. */
async function readAutoDraftManifestInternal(): Promise<AutoDraftDocumentManifest | null> {
  const parts = customXmlParts();
  if (!parts) return null;
  const matches = await getPartsByNamespace(parts);
  for (const part of matches) {
    const parsed = parseXml(await getPartXml(part));
    if (parsed) return parsed;
  }
  return null;
}

/** Upserts document metadata while keeping the manifest inside the DOCX. */
async function upsertAutoDraftManifestInternal(
  patch: Partial<Omit<AutoDraftDocumentManifest, "schemaVersion" | "documentId">> & {
    documentId?: string;
  }
): Promise<AutoDraftDocumentManifest | null> {
  const parts = customXmlParts();
  if (!parts) return null;
  const existing = await readAutoDraftManifestInternal();
  const next: AutoDraftDocumentManifest = {
    schemaVersion: AUTODRAFT_MANIFEST_SCHEMA_VERSION,
    documentId: patch.documentId || existing?.documentId || randomId(),
    templateId: patch.templateId !== undefined ? patch.templateId : existing?.templateId,
    matterId: patch.matterId !== undefined ? patch.matterId : existing?.matterId,
    bindings: patch.bindings !== undefined ? patch.bindings : existing?.bindings || [],
  };

  // Atomic replacement: add and verify the replacement *before* deleting the
  // last known-good manifest. A host failure therefore cannot erase evidence.
  const matches = await getPartsByNamespace(parts);
  const replacement = await addPart(parts, toXml(next));
  if (!replacement) {
    log(
      "[Manifest] Word host did not accept the replacement manifest; previous manifest preserved"
    );
    return null;
  }
  const verified = parseXml(await getPartXml(replacement));
  if (
    !verified ||
    verified.documentId !== next.documentId ||
    verified.bindings.length !== next.bindings.length
  ) {
    await deletePart(replacement);
    log("[Manifest] Replacement manifest could not be verified; previous manifest preserved");
    return null;
  }
  await Promise.all(matches.map(deletePart));
  log(
    `[Manifest] Saved document identity ${next.documentId} with ${next.bindings.length} binding occurrence(s)`
  );
  return next;
}

export async function readAutoDraftManifest(): Promise<AutoDraftDocumentManifest | null> {
  return wordOperationQueue.run(readAutoDraftManifestInternal);
}

export async function upsertAutoDraftManifest(
  patch: Partial<Omit<AutoDraftDocumentManifest, "schemaVersion" | "documentId">> & {
    documentId?: string;
  }
): Promise<AutoDraftDocumentManifest | null> {
  return wordOperationQueue.run(() => upsertAutoDraftManifestInternal(patch));
}

/**
 * Sync variable membership without discarding occurrence-level integrity evidence.
 * Detailed records produced by a binding commit are preserved for every still-live
 * binding ID; only removed variables are dropped.
 */
export async function syncAutoDraftBindingManifest(
  variables: Variable[],
  patch: { templateId?: string; matterId?: string } = {}
): Promise<AutoDraftDocumentManifest | null> {
  return wordOperationQueue.run(async () => {
    const existing = await readAutoDraftManifestInternal();
    const byBindingId = new Map<string, AutoDraftManifestBinding[]>();
    for (const binding of existing?.bindings || []) {
      const key = binding.bindingId.trim().toLowerCase();
      const values = byBindingId.get(key) || [];
      values.push(binding);
      byBindingId.set(key, values);
    }

    const seen = new Set<string>();
    const bindings: AutoDraftManifestBinding[] = [];
    for (const variable of variables || []) {
      const bindingId = (variable.bindingId || "").trim();
      const key = bindingId.toLowerCase();
      if (!bindingId || seen.has(key)) continue;
      seen.add(key);
      const semanticKey =
        String((variable as any).semanticKey || variable.name || "").trim() || undefined;
      const previous = byBindingId.get(key) || [];
      if (previous.length) {
        for (const binding of previous) {
          bindings.push({
            ...binding,
            fieldId: variable.id || binding.fieldId,
            semanticKey: semanticKey || binding.semanticKey,
          });
        }
      } else {
        bindings.push({ bindingId, fieldId: variable.id || undefined, semanticKey });
      }
    }
    return upsertAutoDraftManifestInternal({ ...patch, bindings });
  });
}

/** Merge exact occurrence/control evidence after a successful binding commit. */
export async function recordAutoDraftBindingEvidence(
  evidence: AutoDraftManifestBinding[]
): Promise<AutoDraftDocumentManifest | null> {
  if (!evidence.length) return readAutoDraftManifest();
  return wordOperationQueue.run(async () => {
    const existing = await readAutoDraftManifestInternal();
    const next = [...(existing?.bindings || [])];
    for (const item of evidence) {
      const key = item.bindingId.toLowerCase();
      for (let index = next.length - 1; index >= 0; index--) {
        const candidate = next[index];
        const sameBinding = candidate.bindingId.toLowerCase() === key;
        const sameOccurrence = !!item.occurrenceId && candidate.occurrenceId === item.occurrenceId;
        const sameControl = item.controlId !== undefined && candidate.controlId === item.controlId;
        const sameLocation =
          sameBinding &&
          !!item.location &&
          !!candidate.location &&
          item.location.segmentId === candidate.location.segmentId &&
          item.location.startOffset === candidate.location.startOffset;
        const placeholder =
          sameBinding && !candidate.occurrenceId && candidate.controlId === undefined;
        if (sameOccurrence || sameControl || sameLocation || placeholder) next.splice(index, 1);
      }
      next.push({
        ...item,
        expectedTextNormalized:
          normalizeBindingText(item.expectedTextNormalized || "") || undefined,
      });
    }
    return upsertAutoDraftManifestInternal({ bindings: next });
  });
}

/** Keep reconciliation content evidence in sync with an intentional AutoDraft edit. */
export async function updateAutoDraftBindingExpectedText(
  bindingId: string,
  expectedText: string,
  expectedTitle?: string
): Promise<AutoDraftDocumentManifest | null> {
  const key = bindingId.trim().toLowerCase();
  if (!key) return readAutoDraftManifest();
  return wordOperationQueue.run(async () => {
    const existing = await readAutoDraftManifestInternal();
    if (!existing) return null;
    const normalized = normalizeBindingText(expectedText);
    const exactHash = await sha256Hex(expectedText);
    const nextLength = expectedText.length;
    const bindings = existing.bindings.map((binding) => ({
      ...binding,
      location: binding.location
        ? {
            ...binding.location,
            source: { ...binding.location.source },
            endSource: binding.location.endSource ? { ...binding.location.endSource } : undefined,
          }
        : undefined,
    }));
    const sameParagraph = (
      left: BindingLocationEvidence["source"],
      right: BindingLocationEvidence["source"]
    ) =>
      left.story === right.story &&
      left.paragraphIndex === right.paragraphIndex &&
      left.tableIndex === right.tableIndex &&
      left.rowIndex === right.rowIndex &&
      left.cellIndex === right.cellIndex &&
      left.sectionIndex === right.sectionIndex &&
      left.headerFooterKind === right.headerFooterKind;

    const affected = bindings
      .map((binding, index) => ({ binding, index }))
      .filter(({ binding }) => binding.bindingId.toLowerCase() === key)
      .sort(
        (a, b) =>
          (a.binding.location?.startOffset ?? Number.MAX_SAFE_INTEGER) -
          (b.binding.location?.startOffset ?? Number.MAX_SAFE_INTEGER)
      );
    if (!affected.length) return existing;

    for (const { index } of affected) {
      const binding = bindings[index];
      const oldLength =
        binding.expectedTextLength ?? binding.expectedTextNormalized?.length ?? nextLength;
      const delta = nextLength - oldLength;
      const location = binding.location;
      if (delta && location) {
        const originalStart = location.startOffset;
        for (let otherIndex = 0; otherIndex < bindings.length; otherIndex++) {
          if (otherIndex === index) continue;
          const other = bindings[otherIndex];
          if (!other.location || !sameParagraph(location.source, other.location.source)) continue;
          if (other.location.startOffset > originalStart) {
            other.location.startOffset += delta;
            if (
              other.location.segmentId === other.location.endSegmentId &&
              other.location.endOffset !== undefined
            ) {
              other.location.endOffset += delta;
            }
          }
        }
        if (location.segmentId === location.endSegmentId && location.endOffset !== undefined) {
          location.endOffset += delta;
        }
      }
      bindings[index] = {
        ...binding,
        expectedTextNormalized: normalized,
        expectedTextSha256: exactHash,
        expectedTextLength: nextLength,
        expectedTitle: expectedTitle || binding.expectedTitle,
      };
    }
    return upsertAutoDraftManifestInternal({ bindings });
  });
}

/** Keep reconciliation title evidence in sync with an intentional AutoDraft rename. */
export async function updateAutoDraftBindingExpectedTitle(
  bindingId: string,
  expectedTitle: string
): Promise<AutoDraftDocumentManifest | null> {
  const key = bindingId.trim().toLowerCase();
  if (!key) return readAutoDraftManifest();
  return wordOperationQueue.run(async () => {
    const existing = await readAutoDraftManifestInternal();
    if (!existing) return null;
    let changed = false;
    const bindings = existing.bindings.map((binding) => {
      if (binding.bindingId.toLowerCase() !== key) return binding;
      changed = true;
      return { ...binding, expectedTitle };
    });
    return changed ? upsertAutoDraftManifestInternal({ bindings }) : existing;
  });
}
