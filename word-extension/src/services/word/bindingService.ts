import { recordAutoDraftBindingEvidence, type AutoDraftManifestBinding } from "../documentManifest";
import { runWordOperation } from "./operationQueue";
import type { BindingOperation, BindingPlan } from "./bindingPlanner";
import {
  exactOccurrenceIndex,
  locationEvidenceForOperation,
  normalizeBindingText,
  sha256Hex,
} from "./bindingIntegrity";
import { resolveParagraph } from "./locationResolver";
import { refreshBindingEventMonitoring } from "./eventService";

const EXACT_SEARCH_OPTIONS = {
  matchCase: true,
  matchWholeWord: false,
  matchWildcards: false,
  ignoreSpace: false,
  ignorePunct: false,
} as Word.SearchOptions;

function canonicalRangeText(value: string): string {
  return (value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n");
}

/**
 * Resolve an exact Word search hit using the same semantics used to count the
 * occurrence at the planner's grounded offset. No case/space/punctuation
 * relaxation is allowed here: if live Word no longer matches, commit fails.
 */
async function searchPickExact(
  context: Word.RequestContext,
  paragraph: Word.Paragraph,
  anchor: string,
  localOffset: number
): Promise<Word.Range> {
  paragraph.load("text");
  await context.sync();
  const paragraphText = paragraph.text || "";
  const occurrence = exactOccurrenceIndex(paragraphText, anchor, localOffset);
  const hits = paragraph.search(anchor, EXACT_SEARCH_OPTIONS);
  hits.load("items");
  await context.sync();
  if (occurrence >= hits.items.length) {
    throw new Error(`Grounded text occurrence ${occurrence + 1} is no longer present in Word.`);
  }
  const selected = hits.items[occurrence];
  selected.load("text");
  await context.sync();
  if ((selected.text || "") !== anchor) {
    throw new Error(
      "Word returned a range that does not exactly match the grounded source anchor."
    );
  }
  return selected;
}

async function verifyRange(
  context: Word.RequestContext,
  range: Word.Range,
  expected: string
): Promise<Word.Range> {
  range.load("text");
  await context.sync();
  if (canonicalRangeText(range.text || "") !== canonicalRangeText(expected)) {
    throw new Error("The selected Word range no longer matches the exact grounded source text.");
  }
  return range;
}

async function rangeForOperation(
  context: Word.RequestContext,
  operation: BindingOperation
): Promise<Word.Range> {
  const startParagraph = await resolveParagraph(context, operation.source.start.source);
  const endParagraph =
    operation.source.start.segmentId === operation.source.end.segmentId
      ? startParagraph
      : await resolveParagraph(context, operation.source.end.source);
  startParagraph.load("text");
  if (endParagraph !== startParagraph) endParagraph.load("text");
  await context.sync();

  if (startParagraph === endParagraph) {
    const paragraphText = startParagraph.text || "";
    const desired = paragraphText.slice(operation.source.start.offset, operation.source.end.offset);
    if (desired !== operation.expectedText) {
      throw new Error(
        `${operation.displayLabel}: live paragraph text has drifted from the immutable binding plan.`
      );
    }
    if (desired.length <= 180) {
      return verifyRange(
        context,
        await searchPickExact(context, startParagraph, desired, operation.source.start.offset),
        desired
      );
    }
    const startAnchor = desired.slice(0, 120);
    const endAnchor = desired.slice(-120);
    const start = await searchPickExact(
      context,
      startParagraph,
      startAnchor,
      operation.source.start.offset
    );
    const end = await searchPickExact(
      context,
      endParagraph,
      endAnchor,
      Math.max(operation.source.start.offset, operation.source.end.offset - endAnchor.length)
    );
    return verifyRange(context, start.expandTo(end), desired);
  }

  const startText = (startParagraph.text || "").slice(operation.source.start.offset);
  const endText = (endParagraph.text || "").slice(0, operation.source.end.offset);
  const startAnchor = startText.slice(0, 120);
  const endAnchor = endText.slice(-120);
  if (!startAnchor || !endAnchor) {
    throw new Error(
      `${operation.displayLabel}: cross-paragraph binding does not have a verifiable exact anchor.`
    );
  }
  const start = await searchPickExact(
    context,
    startParagraph,
    startAnchor,
    operation.source.start.offset
  );
  const end = await searchPickExact(
    context,
    endParagraph,
    endAnchor,
    Math.max(0, operation.source.end.offset - endAnchor.length)
  );
  return verifyRange(context, start.expandTo(end), operation.expectedText);
}

/** Roll back only the exact Word controls created by this transaction. */
async function rollbackExactControls(
  context: Word.RequestContext,
  createdControlIds: Set<number>,
  transactionTags: Set<string>
): Promise<void> {
  if (!createdControlIds.size && !transactionTags.size) return;
  const controls = context.document.contentControls;
  controls.load("items");
  await context.sync();
  for (const control of controls.items) control.load("id,tag");
  await context.sync();
  for (const control of controls.items) {
    const id = Number((control as any).id);
    if (createdControlIds.has(id) || transactionTags.has(control.tag || "")) control.delete(false);
  }
  await context.sync();
}

export interface BindingCommitResult {
  inserted: number;
  verified: number;
  conflicts: string[];
}

interface CommitPayload {
  result: BindingCommitResult;
  evidence: AutoDraftManifestBinding[];
  createdControlIds: number[];
}

async function rollbackCreatedControlIds(controlIds: number[]): Promise<void> {
  if (!controlIds.length) return;
  const ids = new Set(controlIds);
  await runWordOperation(async (context) => {
    const controls = context.document.contentControls;
    controls.load("items");
    await context.sync();
    for (const control of controls.items) control.load("id");
    await context.sync();
    for (const control of controls.items) {
      if (ids.has(Number((control as any).id))) control.delete(false);
    }
    await context.sync();
  });
}

/** Commit is all-or-nothing for the exact controls created by this plan. */
export async function commitBindingPlan(plan: BindingPlan): Promise<BindingCommitResult> {
  if (!plan.canCommit) {
    throw new Error(
      `Binding plan is not committable: ${plan.conflicts
        .filter((conflict) => conflict.blocking)
        .map((conflict) => conflict.message)
        .join("; ")}`
    );
  }
  if (!plan.operations.length) {
    return {
      inserted: 0,
      verified: 0,
      conflicts: plan.conflicts.map((conflict) => conflict.message),
    };
  }

  const payload = await runWordOperation<CommitPayload>(async (context) => {
    const createdControlIds = new Set<number>();
    const transactionTags = new Set<string>();
    const evidence: AutoDraftManifestBinding[] = [];
    let inserted = 0;
    try {
      for (const operation of plan.operations) {
        const range = await rangeForOperation(context, operation);
        const parent = range.parentContentControlOrNullObject;
        parent.load("isNullObject,id,tag,text,title");
        await context.sync();

        let control: Word.ContentControl;
        if (!parent.isNullObject) {
          if (parent.tag !== operation.bindingId) {
            throw new Error(
              `${operation.displayLabel}: target is already owned by content control ${parent.tag || "(untagged)"}.`
            );
          }
          if (
            normalizeBindingText(parent.text || "") !== normalizeBindingText(operation.expectedText)
          ) {
            throw new Error(
              `${operation.displayLabel}: existing control text does not match the grounded occurrence.`
            );
          }
          control = parent;
        } else {
          control = range.insertContentControl();
          // Give the new object a transaction-unique temporary tag before the
          // first sync. If Office partially applies that sync and then errors,
          // rollback can still identify this exact newly-created control without
          // touching any pre-existing control that shares the final binding tag.
          const transactionTag = `autodraft-tx:${operation.operationId}`;
          transactionTags.add(transactionTag);
          control.tag = transactionTag;
          control.title = "AutoDraft pending binding";
          control.appearance = "BoundingBox";
          control.color = "#FFFF00";
          const whole = control.getRange("Whole");
          whole.font.highlightColor = null;
          whole.font.underline = "Single";
          whole.font.underlineColor = "#1565C0";
          control.load("id,tag,text,title");
          await context.sync();
          const controlId = Number((control as any).id);
          if (!Number.isFinite(controlId)) {
            throw new Error(
              `${operation.displayLabel}: Word did not return a stable content-control ID.`
            );
          }
          createdControlIds.add(controlId);
          control.tag = operation.bindingId;
          control.title = operation.displayLabel;
          await context.sync();
          inserted += 1;
        }

        control.load("id,tag,text,title");
        await context.sync();
        const controlId = Number((control as any).id);
        if (!Number.isFinite(controlId)) {
          throw new Error(
            `${operation.displayLabel}: content-control identity could not be verified.`
          );
        }
        evidence.push({
          bindingId: operation.bindingId,
          fieldId: operation.fieldId,
          semanticKey: operation.semanticKey,
          occurrenceId: operation.occurrenceId,
          controlId,
          expectedTextNormalized: normalizeBindingText(control.text || operation.expectedText),
          expectedTextSha256: await sha256Hex(control.text || operation.expectedText),
          expectedTextLength: (control.text || operation.expectedText).length,
          expectedTitle: operation.displayLabel,
          location: locationEvidenceForOperation(operation),
        });
      }

      const controls = context.document.contentControls;
      controls.load("items");
      await context.sync();
      for (const control of controls.items) control.load("id,tag,text,title");
      await context.sync();
      const byId = new Map<number, Word.ContentControl>();
      for (const control of controls.items) byId.set(Number((control as any).id), control);

      const failures: string[] = [];
      for (const expected of evidence) {
        const control = expected.controlId === undefined ? undefined : byId.get(expected.controlId);
        if (!control) {
          failures.push(
            `${expected.bindingId}: exact content control ${expected.controlId ?? "?"} is missing`
          );
          continue;
        }
        if ((control.tag || "") !== expected.bindingId) {
          failures.push(
            `${expected.bindingId}: content control ${expected.controlId} has a different tag`
          );
        }
        if (expected.expectedTitle && (control.title || "") !== expected.expectedTitle) {
          failures.push(
            `${expected.bindingId}: content control ${expected.controlId} has a different title`
          );
        }
        if (
          expected.expectedTextNormalized &&
          normalizeBindingText(control.text || "") !== expected.expectedTextNormalized
        ) {
          failures.push(
            `${expected.bindingId}: content control ${expected.controlId} text was not verified`
          );
        }
      }
      if (failures.length) throw new Error(`Post-bind verification failed: ${failures.join("; ")}`);

      return {
        result: {
          inserted,
          verified: evidence.length,
          conflicts: plan.conflicts.map((conflict) => conflict.message),
        },
        evidence,
        createdControlIds: Array.from(createdControlIds),
      };
    } catch (error) {
      await rollbackExactControls(context, createdControlIds, transactionTags);
      throw error;
    }
  });

  // Persist occurrence/control/location evidence only after the Word mutation
  // transaction has verified successfully. If custom-XML persistence fails,
  // remove exactly the controls this commit created so document state and
  // reconciliation evidence cannot diverge.
  try {
    const manifest = await recordAutoDraftBindingEvidence(payload.evidence);
    if (!manifest) throw new Error("AutoDraft manifest evidence could not be persisted.");
    await refreshBindingEventMonitoring();
  } catch (error) {
    await rollbackCreatedControlIds(payload.createdControlIds);
    throw error;
  }
  return payload.result;
}
