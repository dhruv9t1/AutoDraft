import {
  AUTODRAFT_MANIFEST_SCHEMA_VERSION,
  readAutoDraftManifest,
  type AutoDraftManifestBinding,
} from "../documentManifest";
import { normalizeBindingText, sha256Hex } from "./bindingIntegrity";
import { resolveParagraph } from "./locationResolver";
import { runWordOperation } from "./operationQueue";

export type ReconciliationIssueCode =
  | "broken_binding"
  | "unexpected_control"
  | "outdated_manifest"
  | "duplicate_binding"
  | "binding_metadata_missing"
  | "binding_identity_mismatch"
  | "binding_text_mismatch"
  | "binding_exact_text_mismatch"
  | "binding_text_unverified"
  | "binding_title_mismatch"
  | "binding_location_mismatch"
  | "binding_location_unverified";

export interface ReconciliationIssue {
  code: ReconciliationIssueCode;
  bindingId?: string;
  occurrenceId?: string;
  message: string;
}

export interface ReconciliationResult {
  status: "healthy" | "needs_repair" | "degraded" | "unmanaged";
  issues: ReconciliationIssue[];
  liveBindings: string[];
  expectedBindings: string[];
}

interface LiveControl {
  id: number;
  tag: string;
  title: string;
  text: string;
}

function groupByTag<T extends { tag?: string; bindingId?: string }>(
  rows: T[],
  field: "tag" | "bindingId"
): Map<string, T[]> {
  const out = new Map<string, T[]>();
  for (const row of rows) {
    const value = String(row[field] || "").trim();
    if (!value) continue;
    const key = value.toLowerCase();
    const values = out.get(key) || [];
    values.push(row);
    out.set(key, values);
  }
  return out;
}

function hasCompleteEvidence(binding: AutoDraftManifestBinding): boolean {
  return (
    !!binding.occurrenceId &&
    binding.controlId !== undefined &&
    !!binding.expectedTextNormalized &&
    !!binding.expectedTextSha256 &&
    binding.expectedTextLength !== undefined &&
    !!binding.expectedTitle &&
    !!binding.location
  );
}

async function paragraphContainsControlId(
  context: Word.RequestContext,
  paragraph: Word.Paragraph,
  controlId: number
): Promise<boolean | null> {
  try {
    const range: any = paragraph.getRange();
    // `contentControls` is a navigation collection that is loaded explicitly on the
    // next line; the office-addins rules cannot model this duck-typed compatibility
    // path (some Word builds do not expose Range.contentControls at all).
    // eslint-disable-next-line office-addins/call-sync-before-read, office-addins/load-object-before-read -- navigation collection loaded via controls.load("items") below
    const controls: any = range.contentControls;
    if (!controls || typeof controls.load !== "function") return null;
    controls.load("items");
    await context.sync();

    for (const control of controls.items || []) control.load("id");
    await context.sync();
    return (controls.items || []).some((control: any) => Number(control.id) === controlId);
  } catch {
    // Some Word builds do not expose range.contentControls. Offset/text
    // verification below still provides a deterministic structural check.
    return null;
  }
}

async function verifyLocation(
  context: Word.RequestContext,
  binding: AutoDraftManifestBinding,
  control: LiveControl
): Promise<"verified" | "mismatch" | "unverified"> {
  if (!binding.location) return "mismatch";
  try {
    const startParagraph = await resolveParagraph(context, binding.location.source);
    startParagraph.load("text");
    await context.sync();
    const startText = startParagraph.text || "";
    const crossParagraph = !!binding.location.endSource;

    if (!crossParagraph) {
      const observed = startText.slice(
        binding.location.startOffset,
        binding.location.startOffset + (control.text || "").length
      );
      if (observed !== (control.text || "")) return "mismatch";
    } else {
      const startFragment = startText.slice(binding.location.startOffset);
      if (!startFragment || !(control.text || "").startsWith(startFragment)) return "mismatch";
    }

    const startMembership = await paragraphContainsControlId(context, startParagraph, control.id);
    if (startMembership === false) return "mismatch";
    let degraded = startMembership === null;

    if (binding.location.endSource) {
      const endParagraph = await resolveParagraph(context, binding.location.endSource);
      endParagraph.load("text");
      await context.sync();
      const endOffset = binding.location.endOffset;
      if (endOffset === undefined || endOffset < 0) return "mismatch";
      const endFragment = (endParagraph.text || "").slice(0, endOffset);
      if (!endFragment || !(control.text || "").endsWith(endFragment)) return "mismatch";
      const endMembership = await paragraphContainsControlId(context, endParagraph, control.id);
      if (endMembership === false) return "mismatch";
      degraded = degraded || endMembership === null;
    }
    return degraded ? "unverified" : "verified";
  } catch {
    return "mismatch";
  }
}

export async function reconcileAutoDraftDocument(): Promise<ReconciliationResult> {
  const manifest = await readAutoDraftManifest();
  if (!manifest) return { status: "unmanaged", issues: [], liveBindings: [], expectedBindings: [] };

  const live = await runWordOperation(async (context) => {
    const controls = context.document.contentControls;
    controls.load("items");
    await context.sync();
    for (const control of controls.items) control.load("id,tag,text,title");
    await context.sync();
    return controls.items.map(
      (control) =>
        ({
          id: Number((control as any).id),
          tag: (control.tag || "").trim(),
          title: control.title || "",
          text: control.text || "",
        }) satisfies LiveControl
    );
  });

  const expected = manifest.bindings.filter((binding) => !!binding.bindingId);
  const liveByTag = groupByTag(live, "tag");
  const expectedByTag = groupByTag(expected, "bindingId");
  const liveById = new Map<number, LiveControl>();
  for (const control of live) if (Number.isFinite(control.id)) liveById.set(control.id, control);
  const issues: ReconciliationIssue[] = [];

  if (manifest.schemaVersion !== AUTODRAFT_MANIFEST_SCHEMA_VERSION) {
    issues.push({
      code: "outdated_manifest",
      message: `Document manifest schema ${manifest.schemaVersion} is not current (${AUTODRAFT_MANIFEST_SCHEMA_VERSION}). Re-link fields to capture integrity evidence.`,
    });
  }

  for (const [tagKey, expectedOccurrences] of expectedByTag) {
    const bindingId = expectedOccurrences[0].bindingId;
    const liveOccurrences = liveByTag.get(tagKey) || [];
    if (!liveOccurrences.length) {
      issues.push({
        code: "broken_binding",
        bindingId,
        message: `Expected AutoDraft binding ${bindingId} is missing from Word.`,
      });
      continue;
    }
    if (liveOccurrences.length !== expectedOccurrences.length) {
      issues.push({
        code: "duplicate_binding",
        bindingId,
        message: `AutoDraft binding ${bindingId} expects ${expectedOccurrences.length} occurrence(s), but Word contains ${liveOccurrences.length}.`,
      });
    }

    for (const binding of expectedOccurrences) {
      if (!hasCompleteEvidence(binding)) {
        issues.push({
          code: "binding_metadata_missing",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} does not contain complete occurrence/control/location integrity evidence.`,
        });
        continue;
      }
      const control = liveById.get(binding.controlId!);
      if (!control || control.tag.toLowerCase() !== tagKey) {
        issues.push({
          code: "binding_identity_mismatch",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} is no longer the exact Word control recorded by AutoDraft.`,
        });
        continue;
      }
      if (normalizeBindingText(control.text) !== binding.expectedTextNormalized) {
        issues.push({
          code: "binding_text_mismatch",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} contains text that was not written/approved by AutoDraft.`,
        });
      }
      try {
        const exactHash = await sha256Hex(control.text || "");
        if (binding.expectedTextSha256 && exactHash !== binding.expectedTextSha256) {
          issues.push({
            code: "binding_exact_text_mismatch",
            bindingId,
            occurrenceId: binding.occurrenceId,
            message: `Binding ${bindingId} occurrence ${binding.occurrenceId} differs from the exact AutoDraft-approved text (case/spacing/punctuation included).`,
          });
        }
      } catch {
        issues.push({
          code: "binding_text_unverified",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} exact-text SHA-256 could not be verified on this Word host.`,
        });
      }
      if (binding.expectedTitle && control.title !== binding.expectedTitle) {
        issues.push({
          code: "binding_title_mismatch",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} has an unexpected content-control title.`,
        });
      }
      const locationStatus = await runWordOperation((context) =>
        verifyLocation(context, binding, control)
      );
      if (locationStatus === "mismatch") {
        issues.push({
          code: "binding_location_mismatch",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} is no longer at its recorded Word start/end story, paragraph, and offset.`,
        });
      } else if (locationStatus === "unverified") {
        issues.push({
          code: "binding_location_unverified",
          bindingId,
          occurrenceId: binding.occurrenceId,
          message: `Binding ${bindingId} occurrence ${binding.occurrenceId} text/offset matched, but this Word host could not prove content-control membership for every recorded paragraph.`,
        });
      }
    }
  }

  const expectedTagSet = new Set(expected.map((binding) => binding.bindingId.toLowerCase()));
  const looksLikeLegacyAutoDraftBindingId = (value: string) =>
    /^autodraft:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      value
    );
  for (const control of live) {
    if (
      looksLikeLegacyAutoDraftBindingId(control.tag) &&
      !expectedTagSet.has(control.tag.toLowerCase())
    ) {
      issues.push({
        code: "unexpected_control",
        bindingId: control.tag,
        message: `Word contains AutoDraft control ${control.tag} (control ${control.id}) that is not in the embedded manifest.`,
      });
    }
  }

  const degradedCodes = new Set<ReconciliationIssueCode>([
    "binding_location_unverified",
    "binding_text_unverified",
  ]);
  const hasRepairIssue = issues.some((issue) => !degradedCodes.has(issue.code));
  const hasDegradedIssue = issues.some((issue) => degradedCodes.has(issue.code));
  return {
    status: hasRepairIssue ? "needs_repair" : hasDegradedIssue ? "degraded" : "healthy",
    issues,
    liveBindings: live
      .map((control) => control.tag)
      .filter(
        (tag) =>
          !!tag && (expectedTagSet.has(tag.toLowerCase()) || looksLikeLegacyAutoDraftBindingId(tag))
      ),
    expectedBindings: expected.map((binding) => binding.bindingId),
  };
}
