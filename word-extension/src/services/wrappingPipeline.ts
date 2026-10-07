/**
 * Word variable binding support.
 *
 * The exported flat-text helpers below are retained for compatibility and
 * focused tests. Production wrapping uses `wrapVariablesWithBindingPlan`,
 * which extracts the structural document model, creates an immutable binding
 * plan, and commits only the safely grounded operations.
 *
 * Logging prefixes: `[FlatWrap]` for legacy helpers and `[BindingPlan]` for
 * the production planner/committer path.
 */

import { log } from "./logger";
import type { Variable } from "./types";
import { extractDocumentStructure } from "./word/documentStructure";
import { buildBindingPlan } from "./word/bindingPlanner";
import { commitBindingPlan } from "./word/bindingService";

export interface ParagraphMapEntry {
  paragraphIndex: number;
  startOffset: number;
  length: number;
}

export interface DocumentTextMap {
  flatText: string;
  paragraphs: ParagraphMapEntry[];
  paragraphRefs: Word.Paragraph[];
}

export interface FlatTextHit {
  globalStart: number;
  globalEnd: number;
  tier: "exact" | "ci" | "ws-tolerant";
}

/**
 * Build a normalized view that collapses every whitespace run (spaces,
 * tabs, `\n`, `\r`) to a single space. Returns the normalized string
 * AND a parallel `map` array of length `normalized.length` where
 * `map[i]` is the index in the ORIGINAL text that produced normalized
 * char `i`. Used by `findVariableInFlatText` tier 3 to translate hits
 * back to original offsets for `rangeFromGlobalOffsets`.
 */
// Matches all Unicode whitespace per ECMAScript spec, including
// non-breaking space (U+00A0), figure space, etc. Word docs commonly
// contain U+00A0 between words; the previous narrow ASCII-only check
// missed those and left multi-paragraph parents un-wrapped.
const WS_RE = /\s/;

export function buildNormalizedView(text: string): { normalized: string; map: number[] } {
  let normalized = "";
  const map: number[] = [];
  let lastWasSpace = true; // simulates leading-trim
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const isSpace = WS_RE.test(ch);
    if (isSpace) {
      if (!lastWasSpace) {
        normalized += " ";
        map.push(i);
      }
      lastWasSpace = true;
    } else {
      normalized += ch;
      map.push(i);
      lastWasSpace = false;
    }
  }
  return { normalized, map };
}

const WORD_SEARCH_MAX = 200;
const STORY_BOUNDARY = "\uE000"; // non-whitespace sentinel: matching must never cross Word stories/cells

/**
 * One pass over body.paragraphs. Loads `.text` for every paragraph in
 * one batched sync, then concatenates with `\n` joiners. The joiner is
 * exactly one char so any later `\n→space` swap preserves offsets.
 *
 * Body paragraphs, table-cell paragraphs, and primary headers/footers are
 * included. Paragraphs in the same Word story use `\n`; unrelated stories
 * (body→table, separate table cells, headers, footers) use a non-whitespace
 * sentinel so whitespace-normalized matching can never bridge those boundaries.
 */
export async function buildDocumentTextMap(context: Word.RequestContext): Promise<DocumentTextMap> {
  const body = context.document.body;
  const paragraphs = body.paragraphs;
  paragraphs.load("items");
  await context.sync();

  const items = paragraphs.items;
  for (const p of items) p.load("text");
  await context.sync();

  let flatText = "";
  const map: ParagraphMapEntry[] = [];
  const refs: Word.Paragraph[] = [];

  const appendParagraph = (
    paragraph: Word.Paragraph,
    text: string,
    startsNewStory = false
  ): void => {
    if (refs.length > 0) flatText += startsNewStory ? STORY_BOUNDARY : "\n";
    map.push({
      paragraphIndex: refs.length,
      startOffset: flatText.length,
      length: text.length,
    });
    refs.push(paragraph);
    flatText += text;
  };

  for (const item of items) {
    appendParagraph(item, item.text || "");
  }

  // Scan table cells — body.paragraphs does not include table cell content.
  // Wrapped in try/catch: if the Word API doesn't support table traversal
  // or a collection load fails, we still keep the body paragraphs.
  let cellCount = 0;
  try {
    const tables = context.document.body.tables;
    tables.load("items");
    await context.sync();

    if (tables.items.length > 0) {
      for (const table of tables.items) {
        table.rows.load("items");
      }
      await context.sync();

      for (const table of tables.items) {
        for (const row of table.rows.items) {
          row.cells.load("items");
        }
      }
      await context.sync();

      for (const table of tables.items) {
        for (const row of table.rows.items) {
          for (const cell of row.cells.items) {
            cell.body.paragraphs.load("items");
          }
        }
      }
      await context.sync();

      const cellParaRefs: Array<{ paragraph: Word.Paragraph; startsNewStory: boolean }> = [];
      for (const table of tables.items) {
        for (const row of table.rows.items) {
          for (const cell of row.cells.items) {
            const cpItems = cell.body.paragraphs.items;
            for (let i = 0; i < cpItems.length; i++) {
              cpItems[i].load("text");
              cellParaRefs.push({ paragraph: cpItems[i], startsNewStory: i === 0 });
            }
          }
        }
      }
      await context.sync();

      for (const entry of cellParaRefs) {
        appendParagraph(entry.paragraph, entry.paragraph.text || "", entry.startsNewStory);
      }
      cellCount = cellParaRefs.length;
    }
  } catch (e) {
    log("[FlatWrap] table scan failed (non-fatal)", e);
  }

  // Scan headers and footers — keep the exact loaded collection proxies.
  let hfCount = 0;
  try {
    const sections = context.document.sections;
    sections.load("items");
    await context.sync();

    const hfCollections: Array<{ paragraphs: Word.ParagraphCollection; startsNewStory: boolean }> =
      [];
    for (const section of sections.items) {
      const headerParagraphs = section.getHeader("Primary").paragraphs;
      const footerParagraphs = section.getFooter("Primary").paragraphs;
      headerParagraphs.load("items");
      footerParagraphs.load("items");
      hfCollections.push({ paragraphs: headerParagraphs, startsNewStory: true });
      hfCollections.push({ paragraphs: footerParagraphs, startsNewStory: true });
    }
    await context.sync();

    const hfParaRefs: Array<{ paragraph: Word.Paragraph; startsNewStory: boolean }> = [];
    for (const collection of hfCollections) {
      const paras = collection.paragraphs.items;
      for (let i = 0; i < paras.length; i++) {
        paras[i].load("text");
        hfParaRefs.push({ paragraph: paras[i], startsNewStory: i === 0 });
      }
    }
    await context.sync();

    let forceBoundary = true;
    for (const entry of hfParaRefs) {
      const text = entry.paragraph.text || "";
      if (!text.trim()) {
        if (entry.startsNewStory) forceBoundary = true;
        continue;
      }
      appendParagraph(entry.paragraph, text, forceBoundary || entry.startsNewStory);
      forceBoundary = false;
      hfCount++;
    }
  } catch (e) {
    log("[FlatWrap] header/footer scan failed (non-fatal)", e);
  }

  log(
    `[FlatWrap] buildDocumentTextMap: ${items.length} body + ${cellCount} cell + ${hfCount} hf paragraphs, ${flatText.length} chars`
  );
  return { flatText, paragraphs: map, paragraphRefs: refs };
}

/**
 * Locate ALL occurrences of `needle` in `flatText`. Tiered fallback:
 * use the highest-priority tier that has at least one hit. Returning
 * every hit (not just the first) is what makes "TOPS TEXTILES"
 * appearing in two sections of the doc both get wrapped — legacy
 * `replaceVariablesInDocument` looped over every body.search() result
 * and we restore that behaviour here.
 */
export function findAllVariableInFlatText(flatText: string, needle: string): FlatTextHit[] {
  if (!needle) return [];

  // Tier 1: exact substring, all occurrences.
  const exactHits: FlatTextHit[] = [];
  let from = 0;
  while (from <= flatText.length) {
    const idx = flatText.indexOf(needle, from);
    if (idx === -1) break;
    exactHits.push({
      globalStart: idx,
      globalEnd: idx + needle.length,
      tier: "exact",
    });
    from = idx + 1;
  }
  if (exactHits.length > 0) return exactHits;

  // Tier 2: case-insensitive, all occurrences. Same length math (case
  // fold is 1:1 for ASCII; non-ASCII edge cases accepted as v1
  // limitation).
  const lcFlat = flatText.toLowerCase();
  const lcNeedle = needle.toLowerCase();
  const ciHits: FlatTextHit[] = [];
  from = 0;
  while (from <= lcFlat.length) {
    const idx = lcFlat.indexOf(lcNeedle, from);
    if (idx === -1) break;
    ciHits.push({
      globalStart: idx,
      globalEnd: idx + needle.length,
      tier: "ci",
    });
    from = idx + 1;
  }
  if (ciHits.length > 0) return ciHits;

  // Tier 3: whitespace-tolerant. Collapse runs in both views, search,
  // translate back to original offsets via the index map.
  const flatView = buildNormalizedView(flatText);
  const needleView = buildNormalizedView(needle);
  if (!needleView.normalized) return [];
  const lcFlatNorm = flatView.normalized.toLowerCase();
  const lcNeedleNorm = needleView.normalized.toLowerCase();
  const wsHits: FlatTextHit[] = [];
  from = 0;
  while (from <= lcFlatNorm.length) {
    const idx = lcFlatNorm.indexOf(lcNeedleNorm, from);
    if (idx === -1) break;
    const lastNormIdx = idx + lcNeedleNorm.length - 1;
    wsHits.push({
      globalStart: flatView.map[idx],
      globalEnd: flatView.map[lastNormIdx] + 1,
      tier: "ws-tolerant",
    });
    from = idx + 1;
  }
  return wsHits;
}

/** Single-hit shim for callers that only want the first match. */
export function findVariableInFlatText(flatText: string, needle: string): FlatTextHit | null {
  const hits = findAllVariableInFlatText(flatText, needle);
  return hits.length > 0 ? hits[0] : null;
}

export function findParagraphForOffset(map: DocumentTextMap, offset: number): number {
  for (let i = 0; i < map.paragraphs.length; i++) {
    const p = map.paragraphs[i];
    if (offset >= p.startOffset && offset < p.startOffset + p.length) return i;
  }
  if (map.paragraphs.length > 0) {
    const last = map.paragraphs[map.paragraphs.length - 1];
    if (offset === last.startOffset + last.length) {
      return map.paragraphs.length - 1;
    }
  }
  return -1;
}

export function countOccurrencesBefore(text: string, needle: string, position: number): number {
  if (!needle || position <= 0) return 0;
  let count = 0;
  let from = 0;
  while (from < position) {
    const idx = text.indexOf(needle, from);
    if (idx === -1 || idx >= position) break;
    count++;
    from = idx + 1;
  }
  return count;
}

/**
 * Translate `(globalStart, globalEnd)` flat-text offsets back into a
 * Word.Range that spans the same characters in the live document.
 *
 *   - Single-paragraph hit: search the whole variable text within the
 *     start paragraph, pick the Nth occurrence by local offset.
 *   - Cross-paragraph hit: search a prefix anchor inside the start
 *     paragraph and a suffix anchor inside the end paragraph, then
 *     `expandTo` to bridge the paragraph boundary that `body.search()`
 *     refuses to cross.
 */
export async function rangeFromGlobalOffsets(
  context: Word.RequestContext,
  map: DocumentTextMap,
  globalStart: number,
  globalEnd: number
): Promise<Word.Range | null> {
  const startIdx = findParagraphForOffset(map, globalStart);
  const endIdx = findParagraphForOffset(map, globalEnd - 1);
  if (startIdx === -1 || endIdx === -1) {
    log(`[FlatWrap] rangeFromGlobalOffsets: paragraph lookup failed (${globalStart}-${globalEnd})`);
    return null;
  }

  const startEntry = map.paragraphs[startIdx];
  const endEntry = map.paragraphs[endIdx];
  const startPara = map.paragraphRefs[startIdx];
  const endPara = map.paragraphRefs[endIdx];
  const startParaText = map.flatText.slice(
    startEntry.startOffset,
    startEntry.startOffset + startEntry.length
  );
  const endParaText = map.flatText.slice(
    endEntry.startOffset,
    endEntry.startOffset + endEntry.length
  );
  const localStart = globalStart - startEntry.startOffset;
  const localEnd = globalEnd - endEntry.startOffset;

  if (startIdx === endIdx) {
    const variableText = map.flatText.slice(globalStart, globalEnd);
    if (variableText.length <= WORD_SEARCH_MAX) {
      const results = startPara.getRange().search(variableText, {
        matchCase: false,
        matchWholeWord: false,
        matchWildcards: false,
        ignoreSpace: true,
        ignorePunct: true,
      });
      results.load("items");
      await context.sync();
      if (results.items.length === 0) {
        log("[FlatWrap] single-paragraph search miss");
        return null;
      }
      const occ = countOccurrencesBefore(startParaText, variableText, localStart);
      const pick = Math.min(occ, results.items.length - 1);
      return results.items[pick];
    }
    log(
      `[FlatWrap] single-para variable ${variableText.length} > ${WORD_SEARCH_MAX} chars; falling through to anchor path`
    );
  }

  const prefixText = startParaText.slice(localStart);
  const suffixText = endParaText.slice(0, localEnd);
  const startAnchor =
    prefixText.length > WORD_SEARCH_MAX ? prefixText.slice(0, WORD_SEARCH_MAX) : prefixText;
  const endAnchor =
    suffixText.length > WORD_SEARCH_MAX ? suffixText.slice(-WORD_SEARCH_MAX) : suffixText;
  if (!startAnchor.trim() || !endAnchor.trim()) {
    log(`[FlatWrap] empty anchor (start="${startAnchor}", end="${endAnchor}")`);
    return null;
  }

  const startResults = startPara.getRange().search(startAnchor, {
    matchCase: false,
    matchWholeWord: false,
    matchWildcards: false,
    ignoreSpace: true,
    ignorePunct: true,
  });
  const endResults = endPara.getRange().search(endAnchor, {
    matchCase: false,
    matchWholeWord: false,
    matchWildcards: false,
    ignoreSpace: true,
    ignorePunct: true,
  });
  startResults.load("items");
  endResults.load("items");
  await context.sync();

  if (startResults.items.length === 0 || endResults.items.length === 0) {
    log(
      `[FlatWrap] anchor miss (startHits=${startResults.items.length}, endHits=${endResults.items.length}, startAnchor="${startAnchor.slice(0, 30)}…")`
    );
    return null;
  }

  const startOcc = countOccurrencesBefore(startParaText, startAnchor, localStart);
  const endAnchorLocalStart = Math.max(0, localEnd - endAnchor.length);
  const endOcc = countOccurrencesBefore(endParaText, endAnchor, endAnchorLocalStart);

  const startRange = startResults.items[Math.min(startOcc, startResults.items.length - 1)];
  const endRange = endResults.items[Math.min(endOcc, endResults.items.length - 1)];

  try {
    return startRange.expandTo(endRange);
  } catch (e) {
    log(`[FlatWrap] expandTo failed: ${e}`);
    return null;
  }
}

/**
 * Build an immutable binding plan from the same structural document text sent
 * to the backend, then commit the non-conflicting operations. Ungroundable,
 * ambiguous, or unsupported individual variables are counted and skipped;
 * integrity conflicts involving an existing binding ID remain blocking.
 */
export interface WrappingStats {
  wrapped: number;
  missedFlat: number;
  missedRange: number;
  skippedAlreadyWrapped: number;
  errors: number;
  total: number;
}

export async function wrapVariablesWithBindingPlan(variables: Variable[]): Promise<WrappingStats> {
  if (!variables?.length) {
    return {
      wrapped: 0,
      missedFlat: 0,
      missedRange: 0,
      skippedAlreadyWrapped: 0,
      errors: 0,
      total: 0,
    };
  }

  // Lawyer-firm-inspired CHECK THESE behavior: uncertain semantic candidates
  // stay visible in the form but never mutate Word until a lawyer intentionally
  // adds/approves them. Rejected candidates are defensive no-ops here.
  const eligible = variables.filter(
    (v) => v.reviewState !== "needs_review" && v.reviewState !== "rejected"
  );
  const reviewOnly = variables.length - eligible.length;
  if (!eligible.length) {
    log(`[FlatWrap] ${reviewOnly} candidate(s) require review; no Word mutation performed.`);
    return {
      wrapped: 0,
      missedFlat: 0,
      missedRange: 0,
      skippedAlreadyWrapped: reviewOnly,
      errors: 0,
      total: variables.length,
    };
  }

  // The vNext pipeline is explicitly two-phase: build and validate an immutable
  // plan without modifying Word, then commit it as one serialized operation.
  // A blocking integrity conflict means zero Word mutations.
  const structure = await extractDocumentStructure();
  const plan = buildBindingPlan(eligible, structure);
  const blocking = plan.conflicts.filter((c) => c.blocking);
  if (!plan.canCommit) {
    log(`[BindingPlan] blocked: ${blocking.map((c) => c.message).join(" | ")}`);
    throw new Error(
      `AutoDraft could not safely link all detected fields. Word was left unchanged. ${blocking.map((c) => c.message).join(" ")}`
    );
  }

  const result = await commitBindingPlan(plan);
  const missedFlat = plan.conflicts.filter((conflict) => conflict.code === "not_found").length;
  const missedRange = plan.conflicts.filter(
    (conflict) => conflict.code === "ambiguous" || conflict.code === "unsupported_segment"
  ).length;
  const skippedOverlaps = plan.conflicts.filter((conflict) => conflict.code === "overlap").length;
  log(
    `[BindingPlan] committed=${result.verified}, already-bound=${plan.alreadyBound}, ` +
      `missedFlat=${missedFlat}, missedRange=${missedRange}, advisory-conflicts=${result.conflicts.length}`
  );
  return {
    wrapped: result.verified,
    missedFlat,
    missedRange,
    skippedAlreadyWrapped: plan.alreadyBound + skippedOverlaps + reviewOnly,
    errors: 0,
    total: variables.length,
  };
}

/**
 * Compatibility export retained for older callers. New production code should
 * use wrapVariablesWithBindingPlan; wrapping is now driven by the immutable
 * structural binding plan rather than the legacy flat-text mutator.
 */
export const wrapVariablesViaFlatText = wrapVariablesWithBindingPlan;
