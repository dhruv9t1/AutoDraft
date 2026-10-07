/**
 * Office.js Document Content Extraction Service
 * Extracts text content from Word document for AI processing
 */

import { error as logError, log } from "./logger";
import { Variable } from "./types";
import { runWordOperation } from "./word/operationQueue";
import { extractDocumentStructure, type DocumentSegment } from "./word/documentStructure";
import {
  updateAutoDraftBindingExpectedText,
  updateAutoDraftBindingExpectedTitle,
} from "./documentManifest";

export interface DocumentContent {
  text: string;
  length: number;
  segments?: DocumentSegment[];
}
let lastExtractedSegments: DocumentSegment[] = [];
export function getLastExtractedSegments(): DocumentSegment[] {
  return lastExtractedSegments;
}

/**
 * Gets the current Word document's file name (without extension) to use as template name.
 * Falls back to empty string if Office API is not available.
 */
export function getDocumentFileName(): string {
  try {
    if (typeof Office !== "undefined" && Office.context && Office.context.document) {
      const url = Office.context.document.url;
      if (url) {
        const parts = url.replace(/\\/g, "/").split("/");
        const fileName = parts[parts.length - 1] || "";
        return decodeURIComponent(fileName.replace(/\.[^.]+$/, ""));
      }
    }
  } catch {
    // Fallback if Office API is not available
  }
  return "";
}

/**
 * Checks if Word API is available (running in Office context)
 */
function isWordApiAvailable(): boolean {
  return typeof Word !== "undefined" && Word !== null;
}

/**
 * Extracts the full text content from the current Word document
 * Uses multiple methods to ensure complete content extraction
 * @returns Promise with document content
 */
export async function extractDocumentContent(): Promise<DocumentContent> {
  if (!isWordApiAvailable())
    throw new Error("Word API is not available. This add-in must be run within Microsoft Word.");
  try {
    // The structural representation is now canonical. `text` remains byte-for-byte
    // aligned with segment offsets; normalization lives only in each shadow field.
    const structure = await extractDocumentStructure();
    lastExtractedSegments = structure.segments;
    log(
      `[Document Extraction] Structural extraction: ${structure.text.length} chars, ${structure.segments.length} location-aware segment(s)`
    );
    return { text: structure.text, length: structure.text.length, segments: structure.segments };
  } catch (error) {
    logError("[Document Extraction] Extraction failed", error);
    throw new Error(
      "Failed to extract document content: " +
        (error instanceof Error ? error.message : "Unknown error")
    );
  }
}

/**
 * Gets the OOXML (Office Open XML) of the document body.
 * Used when saving a template so it can be restored via body.insertOoxml() during apply.
 * Throws if Word API is unavailable. Returns null if the body OOXML is empty.
 *
 * @returns Promise with the OOXML string, or null if empty
 */
export async function getDocumentBodyOoxml(): Promise<string | null> {
  if (!isWordApiAvailable()) {
    const errorMsg =
      "Word API is not available. This add-in must be run within Microsoft Word. " +
      "If you are testing in a browser, please load the add-in in Word instead.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  try {
    const t0 = performance.now();
    let ooxml = "";

    await runWordOperation(async (context) => {
      const body = context.document.body;
      const ooxmlResult = body.getOoxml();
      await context.sync();
      ooxml = ooxmlResult.value || "";
    });

    const elapsed = (performance.now() - t0).toFixed(0);
    log(`[Document Extraction] getDocumentBodyOoxml: ${elapsed}ms, ${ooxml.length} chars`);
    return ooxml || null;
  } catch (error) {
    logError("[Document Extraction] OOXML read failed", error);
    throw new Error(
      `Failed to get document body OOXML: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Captures a reusable "empty" template snapshot even if the user has already
 * started typing values into the live form while variable identification is
 * finishing.
 *
 * The current document is temporarily normalized so every AutoDraft content
 * control contains its original source value and the unfilled-field styling.
 * OOXML is captured in that state, then the user's live values/styling are
 * restored before this function returns. The visible document therefore stays
 * a working draft while the persisted template remains a clean master copy.
 */
export async function getReusableTemplateBodyOoxml(variables: Variable[]): Promise<string | null> {
  if (!isWordApiAvailable()) {
    throw new Error("Word API is not available. This add-in must be run within Microsoft Word.");
  }

  const originalByTag = new Map<string, string>();
  for (const variable of variables) {
    const tag = (variable.bindingId || variable.name || "").trim();
    if (tag && variable.originalText) {
      // Content-control identity is the immutable binding ID when available.
      // Using the display name here made renamed/stable-ID fields disappear
      // from reusable-master capture even though their controls were healthy.
      originalByTag.set(tag, variable.originalText);
    }
  }

  try {
    let snapshot = "";

    await runWordOperation(async (context) => {
      const body = context.document.body;
      const controls = body.contentControls;
      controls.load("items");
      await context.sync();

      for (const control of controls.items) {
        control.load("tag,text");
      }
      await context.sync();

      const restoreRows: Array<{
        control: Word.ContentControl;
        text: string;
        wasFilled: boolean;
      }> = [];

      for (const control of controls.items) {
        const originalText = originalByTag.get(control.tag || "");
        if (!originalText) continue;

        const liveText = control.text || "";
        const wasFilled = liveText.trim() !== originalText.trim();
        restoreRows.push({ control, text: liveText, wasFilled });

        control.insertText(originalText, Word.InsertLocation.replace);
        control.color = "#FFFF00";
        const range = control.getRange("Whole");
        range.font.highlightColor = null;
        range.font.underline = "Single";
        range.font.underlineColor = "#1565C0";
      }
      await context.sync();

      const ooxmlResult = body.getOoxml();
      await context.sync();
      snapshot = ooxmlResult.value || "";

      // Restore the user's current draft exactly enough for the live editing
      // experience: text plus the filled/unfilled visual state.
      for (const row of restoreRows) {
        row.control.insertText(row.text, Word.InsertLocation.replace);
        row.control.color = row.wasFilled ? "#107C10" : "#FFFF00";
        const range = row.control.getRange("Whole");
        range.font.highlightColor = null;
        if (row.wasFilled) {
          range.font.underline = "None";
        } else {
          range.font.underline = "Single";
          range.font.underlineColor = "#1565C0";
        }
      }
      await context.sync();
    });

    log(
      `[Document Extraction] Captured reusable template OOXML: ${snapshot.length} chars (${variables.length} variables)`
    );
    return snapshot || null;
  } catch (error) {
    logError("[Document Extraction] Reusable OOXML capture failed", error);
    throw new Error(
      `Failed to capture reusable template OOXML: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Inserts OOXML into the document body, replacing current content.
 * Used for "Use this template" to load a saved template into a new/blank document.
 *
 * @param ooxml - OOXML string from getDocumentBodyOoxml or GET /api/templates/:id/content
 */
export async function insertOoxmlIntoDocument(ooxml: string): Promise<void> {
  if (!isWordApiAvailable()) {
    const errorMsg = "Word API is not available. This add-in must be run within Microsoft Word.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }
  if (!ooxml || ooxml.trim().length === 0) {
    throw new Error("OOXML content is empty. Cannot insert into document.");
  }

  try {
    await runWordOperation(async (context) => {
      const body = context.document.body;
      body.insertOoxml(ooxml, Word.InsertLocation.replace);
      await context.sync();
    });
    log(`[Document Extraction] insertOoxmlIntoDocument: inserted ${ooxml.length} chars`);
  } catch (error) {
    logError("[Document Extraction] OOXML insertion failed", error);
    throw new Error(
      `Failed to insert template into document: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Extracts text content from a specific range in the document
 * Note: Office.js Word API doesn't support character position-based ranges directly.
 * This function gets the full text and extracts the substring in JavaScript.
 *
 * @param startPosition Start character position (optional, 0-based)
 * @param endPosition End character position (optional, exclusive)
 * @returns Promise with document content
 */
export async function extractDocumentRange(
  startPosition?: number,
  endPosition?: number
): Promise<DocumentContent> {
  try {
    // First, get the full document text using the improved extraction
    const fullDocument = await extractDocumentContent();
    let extractedText = "";

    // Then extract the range in JavaScript
    if (startPosition !== undefined && endPosition !== undefined) {
      // Validate positions
      const start = Math.max(0, Math.min(startPosition, fullDocument.text.length));
      const end = Math.max(start, Math.min(endPosition, fullDocument.text.length));
      extractedText = fullDocument.text.substring(start, end);
    } else if (startPosition !== undefined) {
      // Extract from startPosition to end of document
      const start = Math.max(0, Math.min(startPosition, fullDocument.text.length));
      extractedText = fullDocument.text.substring(start);
    } else {
      // No range specified, return full text
      extractedText = fullDocument.text;
    }

    return {
      text: extractedText,
      length: extractedText.length,
    };
  } catch (error) {
    logError("[Document Extraction] Range extraction failed", error);
    throw new Error(
      `Failed to extract document range: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Chunks document content for streaming
 * Ensures no content is skipped by using exact substring boundaries
 * @param content Full document content
 * @param chunkSize Size of each chunk in characters (default: 1MB for better reliability)
 * @returns Array of document chunks with metadata
 */
export function chunkDocumentContent(
  content: string,
  chunkSize: number = 1024 * 1024 // 1MB default for better reliability
): string[] {
  if (!content || content.length === 0) {
    return [];
  }

  if (content.length <= chunkSize) {
    return [content];
  }

  const chunks: string[] = [];
  let offset = 0;
  const totalLength = content.length;

  log(`[Chunking] Starting chunking: ${totalLength} characters, chunk size: ${chunkSize}`);

  while (offset < totalLength) {
    const end = Math.min(offset + chunkSize, totalLength);

    // Extract chunk using substring to ensure exact boundaries
    const chunk = content.substring(offset, end);

    // Verify chunk is not empty
    if (chunk.length === 0) {
      log(`[Chunking] WARNING: Empty chunk at offset ${offset}, breaking`);
      break;
    }

    chunks.push(chunk);

    log(`[Chunking] Chunk ${chunks.length}: offset ${offset} to ${end} (${chunk.length} chars)`);

    offset = end;
  }

  // Verify all content was chunked
  const totalChunkedLength = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  if (totalChunkedLength !== totalLength) {
    log(
      `[Chunking] ERROR: Content mismatch! Original: ${totalLength}, Chunked: ${totalChunkedLength}`
    );
    throw new Error(`Chunking error: ${totalLength - totalChunkedLength} characters were lost`);
  }

  log(
    `[Chunking] Successfully created ${chunks.length} chunks, total length: ${totalChunkedLength}`
  );
  return chunks;
}

/**
 * Extracts document content in chunks for streaming
 * This allows processing large documents by streaming chunks to the backend
 *
 * @param chunkSize Size of each chunk in characters (default: 10MB)
 * @param onChunkExtracted Optional callback when each chunk is extracted
 * @returns Promise with all chunks
 */
export async function extractDocumentContentInChunks(
  chunkSize: number = 10 * 1024 * 1024, // 10MB default
  onChunkExtracted?: (chunk: string, index: number, total: number) => void
): Promise<string[]> {
  // Check if Word API is available
  if (!isWordApiAvailable()) {
    const errorMsg =
      "Word API is not available. This add-in must be run within Microsoft Word. " +
      "If you are testing in a browser, please load the add-in in Word instead.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  try {
    // Extract full document content
    const documentContent = await extractDocumentContent();

    // Chunk the content
    const chunks = chunkDocumentContent(documentContent.text, chunkSize);

    // Call callback for each chunk if provided
    if (onChunkExtracted) {
      chunks.forEach((chunk, index) => {
        onChunkExtracted(chunk, index, chunks.length);
      });
    }

    log(`[Document Extraction] Split into ${chunks.length} chunk(s)`);
    return chunks;
  } catch (error) {
    logError("[Document Extraction] Chunk extraction failed", error);
    throw new Error(
      `Failed to extract document content in chunks: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Extracts all variables from the document in {variable name} format
 * This includes both AI-identified variables and manually added variables
 *
 * @returns Promise with array of variables found in the document
 */
export async function extractVariablesFromDocument(): Promise<Variable[]> {
  // Check if Word API is available
  if (!isWordApiAvailable()) {
    const errorMsg =
      "Word API is not available. This add-in must be run within Microsoft Word. " +
      "If you are testing in a browser, please load the add-in in Word instead.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  try {
    const t0 = performance.now();
    log("[Variable Extraction] Starting extraction of variables from document...");

    // Extract document content
    const documentContent = await extractDocumentContent();
    const documentText = documentContent.text;

    if (!documentText || documentText.trim().length === 0) {
      log("[Variable Extraction] Document is empty, no variables to extract");
      return [];
    }

    // Regex pattern to match {variable name} or {[variable name]} format
    // Supports: {variable}, {[variable]}, {{variable}}
    const variablePattern = /\{\[?([^}\]]+)\]?\}/g;
    const variables: Variable[] = [];
    const seenVariables = new Map<string, number>(); // Track variable names and their first position

    let match;
    let index = 0;

    while ((match = variablePattern.exec(documentText)) !== null) {
      // Strip any remaining brackets and trim
      const variableName = match[1].replace(/[[\]]/g, "").trim();

      // Skip empty variable names
      if (!variableName) {
        continue;
      }

      const position = match.index;
      const fullMatch = match[0]; // The full {variable name} text

      // If we've seen this variable name before, use the first position
      // Otherwise, add it to the map
      if (!seenVariables.has(variableName)) {
        seenVariables.set(variableName, position);

        variables.push({
          id: `var_${index + 1}`,
          name: variableName,
          originalText: fullMatch,
          position: position,
          confidenceScore: undefined, // Manually added variables don't have confidence scores
        });

        index++;
        log(`[Variable Extraction] Found variable candidate at position ${position}`);
      } else {
        // Variable already found, just log it
        log(
          `[Variable Extraction] Duplicate variable found: {${variableName}} at position ${position} (first occurrence at ${seenVariables.get(variableName)})`
        );
      }
    }

    // Sort variables by position
    variables.sort((a, b) => a.position - b.position);

    log(
      `[Variable Extraction] extractVariablesFromDocument: ${(performance.now() - t0).toFixed(0)}ms, ${variables.length} vars`
    );
    return variables;
  } catch (error) {
    logError("[Document Extraction] Variable extraction failed", error);
    throw new Error(
      `Failed to extract variables from document: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Checks if a hex color string represents a red font color.
 */
function isRedColor(color: string): boolean {
  if (!color) return false;
  const c = color.trim().toUpperCase().replace("#", "");
  if (c === "FF0000" || c === "RED") return true;
  if (c.length === 6) {
    const r = parseInt(c.substring(0, 2), 16);
    const g = parseInt(c.substring(2, 4), 16);
    const b = parseInt(c.substring(4, 6), 16);
    return r > 180 && g < 80 && b < 80;
  }
  return false;
}

/**
 * Checks if a hex color string represents a blue font color.
 * Handles Word blues: #0000FF, #0563C1, #2E74B5, #0070C0, #2F5496, #1565C0, etc.
 */
function isBlueColor(color: string): boolean {
  if (!color) return false;
  const c = color.trim().toUpperCase().replace("#", "");
  if (c === "0000FF" || c === "BLUE") return true;
  if (c.length === 6) {
    const r = parseInt(c.substring(0, 2), 16);
    const g = parseInt(c.substring(2, 4), 16);
    const b = parseInt(c.substring(4, 6), 16);
    // Blue-dominant: blue is the strongest channel and significantly higher than red
    return b > 120 && b > r && b > g * 0.8 && r < 130;
  }
  return false;
}

/**
 * Checks if text is a page marker or section number that should be skipped.
 * e.g. "…14.", ":: 14 ::", "[10]", "(1)", "...14."
 */
function isPageMarker(text: string): boolean {
  const t = text.trim();
  if (!t) return true;
  // Length-guarded: only short digit-runs are page markers. Real fields like
  // PIN codes (6 digits), GSTIN (15), account numbers, cheque numbers, etc.
  // must NOT be flagged. Mirrors backend `is_list_marker` (`t.len() <= 5`).
  if (t.length <= 5 && /^…?\.*\d+\.?$/.test(t)) return true;
  if (/^::?\s*\d+\s*::?$/.test(t)) return true;
  if (/^\[?\d+\]?$/.test(t) && t.length <= 5) return true;
  if (/^\(\d+\)$/.test(t)) return true;
  if (/^::/.test(t) && /::$/.test(t)) return true;
  return false;
}

/**
 * Returns true if the variable looks like a numbered list marker / footnote
 * reference rather than a real placeholder — e.g. `[1]`, `(2)`, `12.`, `:: 3 ::`.
 * The AI sometimes assigns semantic names (e.g. "Accused Number Placeholder")
 * to these markers because they sit inside colored runs near real placeholders,
 * so we filter by the *originalText* shape instead of trusting the name.
 */
export function isListMarkerVariable(v: { originalText?: string; name?: string }): boolean {
  const candidates = [v.originalText, v.name];
  for (const c of candidates) {
    if (typeof c !== "string") continue;
    if (isPageMarker(c)) return true;
    // Bare bracketed/parenthesized integers — covers "[1]", "[12]", "(3)", etc.
    if (/^\s*[[(]\s*\d{1,3}\s*[\])]\s*$/.test(c)) return true;
  }
  return false;
}

/**
 * Removes variables that are really list markers / footnote refs.
 * Apply to both color-detected and AI-detected variable lists.
 */
export function filterListMarkerVariables<T extends { originalText?: string; name?: string }>(
  variables: T[]
): T[] {
  const filtered: T[] = [];
  for (const v of variables) {
    if (isListMarkerVariable(v)) {
      log(
        `[Filter] Dropping list-marker variable name="${v.name}" originalText="${v.originalText}"`
      );
      continue;
    }
    filtered.push(v);
  }
  return filtered;
}

/**
 * Removes variables whose `originalText` collides with one already kept.
 * The AI sometimes returns the same span (e.g. "SOMISETTI VENKATA TIRUMALA
 * KONDAIAH") under multiple semantic names ("Accused Proprietor Name",
 * "Accused Authorized Person", …) — those become duplicate inputs in the
 * form because all of them map to the same content control. Keep the first
 * occurrence (which is typically the highest-confidence label from the AI).
 */
export function dedupVariablesByOriginalText<T extends { originalText?: string; name?: string }>(
  variables: T[]
): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const v of variables) {
    const ot = (v.originalText || "").trim().toLowerCase();
    if (!ot) {
      out.push(v);
      continue;
    }
    if (seen.has(ot)) {
      log(
        `[Dedup] Dropping duplicate-by-originalText name="${v.name}" originalText="${v.originalText}"`
      );
      continue;
    }
    seen.add(ot);
    out.push(v);
  }
  return out;
}

/**
 * Appends " 2", " 3", … to variables whose `name` collides (case-insensitive)
 * with one already kept, so every variable carries a UNIQUE name. Content
 * controls are tag-addressed by `name`, so duplicate names would otherwise
 * produce colliding CC tags (the second wrap is silently skipped by getByTag).
 *
 * Mirrors the backend `disambiguate_duplicate_names` (backend/app/post_processing.py)
 * EXACTLY so FE-incremental names track BE-final names as closely as possible:
 *   - key = (name||"").trim().toLowerCase(); empty key passes through unchanged;
 *   - first occurrence keeps its name; the Nth (n>1) becomes `${trimmed} ${n}`.
 *
 * Unlike the backend (which mutates `&mut [Variable]` in place), this returns
 * NEW objects and leaves the caller's array untouched — App.tsx keeps
 * `streamFoundRef` as the raw arrival-order accumulator and cleaning is a
 * derived view. Order is preserved, so re-running over a list that only GREW by
 * appends yields byte-identical names for the unchanged prefix (keeping
 * already-wrapped CC tags valid batch-over-batch).
 */
export function disambiguateDuplicateNames<T extends { name?: string }>(variables: T[]): T[] {
  const counts = new Map<string, number>();
  const out: T[] = [];
  for (const v of variables) {
    const key = (v.name || "").trim().toLowerCase();
    if (key === "") {
      out.push(v);
      continue;
    }
    const n = (counts.get(key) || 0) + 1;
    counts.set(key, n);
    if (n > 1) {
      const trimmed = (v.name || "").replace(/\s+$/, "");
      out.push({ ...v, name: `${trimmed} ${n}` });
    } else {
      out.push(v);
    }
  }
  return out;
}

/**
 * Composed per-batch cleanup that mirrors the backend's final-merge order
 * (list-marker filter → exact-by-originalText dedup → name disambiguation).
 * NEVER calls dedupSubstringOverlap — CLAUDE.md mandates parent + child spans
 * coexist. Used by the streaming-creation per-batch wrap path to reproduce the
 * backend cleanup over the ACCUMULATED set before each progressive wrap.
 */
export function cleanAccumulated<T extends { originalText?: string; name?: string }>(
  list: T[]
): T[] {
  return disambiguateDuplicateNames(dedupVariablesByOriginalText(filterListMarkerVariables(list)));
}

/**
 * Drops variables whose `originalText` is a contiguous substring of another
 * kept variable's `originalText` (case- and whitespace-insensitive). The AI
 * sometimes returns BOTH "Mr. ASHWIN GANPATRAJ MEHTA" (as e.g. "Complainant
 * Authorized Person Name") AND the bare "ASHWIN GANPATRAJ MEHTA" (as e.g.
 * "Complainant Name"). Both refer to the same physical span in the document,
 * so wrapping the longer one consumes every occurrence of the shorter, and
 * the shorter becomes a ghost form field that can't bind to a content control.
 *
 * Strategy: sort by `originalText` length DESCENDING, walk in order, drop any
 * entry whose normalized text is a strict substring of an already-kept entry.
 * The longer span wins because it's typically more specific (lower chance of
 * false matches elsewhere in the doc) and exists as the actual wrapped CC.
 *
 * Apply AFTER {@link dedupVariablesByOriginalText} (which handles exact dupes).
 */
export function dedupSubstringOverlap<T extends { originalText?: string; name?: string }>(
  variables: T[]
): T[] {
  const sorted = [...variables].sort(
    (a, b) => (b.originalText || "").length - (a.originalText || "").length
  );
  const keptKeys: string[] = [];
  const out: T[] = [];
  for (const v of sorted) {
    const key = (v.originalText || "").trim().toLowerCase();
    if (!key) {
      out.push(v);
      continue;
    }
    const isContainedInKept = keptKeys.some((k) => k.length > key.length && k.includes(key));
    if (isContainedInKept) {
      log(
        `[Dedup] Dropping substring-overlap variable name="${v.name}" originalText="${v.originalText}" (already covered by a longer kept span)`
      );
      continue;
    }
    keptKeys.push(key);
    out.push(v);
  }
  return out;
}

/**
 * Extracts variables from the document based on red and blue font colors.
 * Within colored text:
 *   - If {braced} patterns exist, each is extracted as a variable
 *   - If no braces, the entire colored run is the variable
 * Page markers (…14., :: 14 ::, [10], etc.) are skipped.
 *
 * @returns Promise with array of variables found by color detection
 */
export async function extractColoredTextVariables(): Promise<Variable[]> {
  if (!isWordApiAvailable()) {
    return [];
  }

  const variables: Variable[] = [];
  const seenVariables = new Map<string, number>();
  let varIndex = 0;

  const addVariable = (name: string, originalText: string, position: number): void => {
    const cleanName = name.trim();
    if (!cleanName || isPageMarker(cleanName)) return;
    const key = cleanName.toLowerCase();
    if (seenVariables.has(key)) return;
    seenVariables.set(key, position);
    variables.push({
      id: "color_" + String(++varIndex),
      name: cleanName,
      originalText: originalText,
      position: position,
    });
  };

  const processColoredRun = (text: string, position: number): void => {
    const trimmed = text.trim();
    if (!trimmed || isPageMarker(trimmed)) return;

    // Check for {braced} patterns within the colored text
    const bracedPattern = /\{([^}]+)\}/g;
    const bracedMatches: RegExpExecArray[] = [];
    let match: RegExpExecArray | null;

    match = bracedPattern.exec(trimmed);
    while (match !== null) {
      bracedMatches.push(match);
      match = bracedPattern.exec(trimmed);
    }

    if (bracedMatches.length > 0) {
      // Check how much text is OUTSIDE braces — if substantial, the entire
      // colored run is the variable (e.g. "READYMADE GARMENTS {Jodhpur}I SHERWANI...")
      // If only short prefixes like "M/s." remain, extract only braced parts.
      const textOutsideBraces = trimmed
        .replace(/\{[^}]+\}/g, "")
        .replace(/["""\s.,;:@[\]()]+/g, " ")
        .trim();

      if (textOutsideBraces.length > 10) {
        // Substantial non-braced text → entire run is one variable
        // Strip all braces from the name
        const fullName = trimmed
          .replace(/\{/g, "")
          .replace(/\}/g, "")
          .replace(/^["""\s.,;:]+|["""\s.,;:]+$/g, "")
          .trim();
        if (fullName) {
          addVariable(fullName, trimmed, position);
        }
      } else {
        // Only short labels outside braces (M/s., Mr., No.:) → extract braced parts only
        for (const m of bracedMatches) {
          const varName = m[1].replace(/[[\]]/g, "").trim();
          if (varName && !isPageMarker(varName)) {
            addVariable(varName, m[0], position + m.index);
          }
        }
      }
    } else {
      // No braces found — treat entire colored run as variable
      const cleaned = trimmed.replace(/^["""\s.,;:]+|["""\s.,;:]+$/g, "").trim();
      if (cleaned) {
        addVariable(cleaned, trimmed, position);
      }
    }
  };

  // Helper: process a RangeCollection with gap-bridging to accumulate colored runs.
  // If ≤2 consecutive non-colored words sit between colored words, bridge the gap.
  const processRangesForColor = (ranges: Word.RangeCollection, startPos: number): number => {
    var items = ranges.items;
    if (items.length === 0) return startPos;

    // First pass: determine which ranges are colored and log colors
    var colorFlags: boolean[] = [];
    var debugColors: string[] = [];
    var debugAllColors: string[] = [];
    for (var r = 0; r < items.length; r++) {
      var fontColor = items[r].font.color || "";
      var fontUnderline = String(items[r].font.underline || "None");
      var colored = isRedColor(fontColor) || isBlueColor(fontColor);

      // Detect hyperlink-styled text: Word hyperlinks are typically blue + underlined
      // but font.color may report empty or a theme-resolved color
      if (!colored && fontUnderline !== "None" && fontUnderline.toLowerCase() !== "none") {
        // Underlined text with no explicit color — check if it's a hyperlink style
        // Word hyperlinks often have underline=Single and color="" or a theme blue
        if (fontColor === "" || fontColor === "null" || fontColor === null) {
          // No explicit color but underlined — likely a hyperlink, treat as blue
          colored = true;
          debugColors.push(items[r].text + "=hyperlink(underline=" + fontUnderline + ")");
        }
      }

      // Log all non-black colors for debugging (first 30 items max)
      if (
        debugAllColors.length < 30 &&
        fontColor &&
        fontColor !== "#000000" &&
        fontColor !== "black" &&
        fontColor !== "#000000FF"
      ) {
        debugAllColors.push(items[r].text.substring(0, 20) + "=" + fontColor);
      }

      colorFlags.push(colored);
      if (colored && debugColors.length < 30) {
        debugColors.push(items[r].text + "=" + fontColor);
      }
    }

    if (debugAllColors.length > 0) {
      log("[Color Detection] Non-black colors found: " + debugAllColors.join(", "));
    }
    if (debugColors.length > 0) {
      log("[Color Detection] Colored words: " + debugColors.join(", "));
    }

    // Second pass: bridge gaps — if ≤2 non-colored words sit between colored words, mark them colored
    for (var r2 = 0; r2 < colorFlags.length; r2++) {
      if (!colorFlags[r2]) {
        // Find end of consecutive non-colored gap
        var gapEnd = r2;
        while (gapEnd < colorFlags.length && !colorFlags[gapEnd]) {
          gapEnd++;
        }
        var gapSize = gapEnd - r2;
        // Bridge if gap ≤ 2 and there's colored text on both sides
        if (
          gapSize <= 2 &&
          r2 > 0 &&
          colorFlags[r2 - 1] &&
          gapEnd < colorFlags.length &&
          colorFlags[gapEnd]
        ) {
          for (var g = r2; g < gapEnd; g++) {
            colorFlags[g] = true;
          }
          log("[Color Detection] Bridged adjacent colored-text gap");
        }
        r2 = gapEnd - 1; // skip past gap
      }
    }

    // Third pass: accumulate colored runs using bridged flags
    var coloredText = "";
    var coloredStart = startPos;
    var pos = startPos;
    for (var r3 = 0; r3 < items.length; r3++) {
      var text = items[r3].text || "";
      if (colorFlags[r3] && text.trim().length > 0) {
        if (!coloredText) {
          coloredStart = pos;
        }
        coloredText += (coloredText ? " " : "") + text.trim();
      } else {
        if (coloredText) {
          log("[Color Detection] Processing colored-text run");
          processColoredRun(coloredText, coloredStart);
          coloredText = "";
        }
      }
      pos += text.length + 1;
    }
    if (coloredText) {
      log("[Color Detection] Processing colored-text run");
      processColoredRun(coloredText, coloredStart);
    }
    return pos;
  };

  try {
    const t0 = performance.now();

    await runWordOperation(async (context) => {
      const paragraphs = context.document.body.paragraphs;
      paragraphs.load("items");
      await context.sync();

      const BATCH_SIZE = 10;
      let globalPosition = 0;

      for (let batchStart = 0; batchStart < paragraphs.items.length; batchStart += BATCH_SIZE) {
        const batchEnd = Math.min(batchStart + BATCH_SIZE, paragraphs.items.length);
        const batchRanges: Word.RangeCollection[] = [];

        for (let p = batchStart; p < batchEnd; p++) {
          const ranges = paragraphs.items[p].getTextRanges([" ", "\t"], false);
          ranges.load("text,font/color,font/underline");
          batchRanges.push(ranges);
        }
        await context.sync();

        for (let b = 0; b < batchRanges.length; b++) {
          globalPosition = processRangesForColor(batchRanges[b], globalPosition);
          globalPosition += 1; // paragraph break
        }
      }

      // Also scan tables — body.paragraphs does not include table cell content
      const tables = context.document.body.tables;
      tables.load("items");
      await context.sync();

      for (let t = 0; t < tables.items.length; t++) {
        const table = tables.items[t];
        const rows = table.rows;
        rows.load("items");
        await context.sync();

        for (let row = 0; row < rows.items.length; row++) {
          const cells = rows.items[row].cells;
          cells.load("items");
          await context.sync();

          const cellRanges: Word.RangeCollection[] = [];
          for (let cell = 0; cell < cells.items.length; cell++) {
            const cellBody = cells.items[cell].body;
            const ranges = cellBody.getRange("Whole").getTextRanges([" ", "\t"], false);
            ranges.load("text,font/color,font/underline");
            cellRanges.push(ranges);
          }
          await context.sync();

          for (let cr = 0; cr < cellRanges.length; cr++) {
            globalPosition = processRangesForColor(cellRanges[cr], globalPosition);
            globalPosition += 1;
          }
        }
      }
    });

    variables.sort((a, b) => a.position - b.position);
    const elapsed = (performance.now() - t0).toFixed(0);
    log(`[Color Detection] Found ${variables.length} variables from red/blue text in ${elapsed}ms`);
    return variables;
  } catch (error) {
    log(`[Color Detection] Error: ${error}`);
    return [];
  }
}

/**
 * Escapes characters that have special meaning in Word's wildcard search
 * (`matchWildcards: true`). Used by `buildChildAwareWildcardTarget` to keep the
 * non-child portions of the parent text matched literally while child substrings
 * become `*` wildcards.
 *
 * Word wildcard meta-characters: `?`, `*`, `[`, `]`, `{`, `}`, `<`, `>`, `(`,
 * `)`, `@`, `\`, `!`. Backslash is the escape itself.
 */
function escapeWordWildcards(text: string): string {
  return text.replace(/[?*[\]{}<>()@\\!]/g, "\\$&");
}

/**
 * Builds a Word-wildcard search pattern tolerant of two real-world divergences
 * between the LLM-extracted span and the live Word document:
 *
 * 1. **Cascade markers.** Streaming pipelines wrap shorter spans (e.g.
 *    "UCO BANK", "JODHPUR") before a longer parent span arrives. By the time
 *    the parent search runs, those children have been replaced by `{X}` /
 *    `{Y}` in the document. A literal search for the parent fails because the
 *    curly markers break the substring.
 * 2. **Whitespace divergence.** The LLM may emit `Address X PIN: 342007` with
 *    single spaces while the live document has line breaks, tabs, NBSPs, or
 *    letter-spacing (`P I N: 342007` vs `PIN: 342007`). validate_variables on
 *    the backend cannot always normalise these, so the LLM-emitted form
 *    arrives at the FE with `position: -1` and the literal search misses.
 *
 * Strategy:
 * - Replace each substring that matches another known variable's
 *   `originalText` with a `*` wildcard (matches any chars including inserted
 *   `{X}` markers).
 * - In the remaining literal segments, replace every whitespace run with `*`
 *   so document whitespace can be anything.
 * - Word-wildcard-escape every other character so it stays literal.
 *
 * Returns null only when no `*` was produced (no children, no whitespace —
 * the literal pass already covers that case).
 *
 * Exported for unit-testing in isolation.
 */
export function buildChildAwareWildcardTarget(
  parentText: string,
  otherTexts: string[]
): string | null {
  if (!parentText) return null;

  // Pre-filter to children that ACTUALLY appear in the parent and aren't the
  // parent itself. Sort longest-first so we wildcard the most specific matches
  // before they get masked by a shorter substring of themselves.
  const children = Array.from(new Set(otherTexts))
    .filter((c) => c.length > 0 && c !== parentText && parentText.includes(c))
    .sort((a, b) => b.length - a.length);

  // Whitespace tolerance alone is valuable even when there are no children to
  // wildcard, so we don't early-return on empty `children`. The bottom of this
  // function rejects patterns that produced no `*` (e.g. a parent with no
  // whitespace and no children).

  // Walk the parent left-to-right, alternating between child segments (→ `*`)
  // and literal segments (→ wildcard-escaped + whitespace-tolerant). Use a
  // unique sentinel char for child placeholders so the escape pass leaves them
  // alone.
  const SENTINEL = "";
  let working = parentText;
  for (const child of children) {
    // Replace ALL occurrences of this child substring with the sentinel.
    // Escape regex specials in `child` for the .replace search side.
    const childRe = new RegExp(child.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g");
    working = working.replace(childRe, SENTINEL);
  }

  // Within each non-child segment, also tolerate whitespace divergence between
  // the LLM-extracted text and the live document (the doc may have line breaks,
  // tabs, NBSPs, multiple spaces, or letter-spacing where the LLM emitted a
  // single space). Replace every whitespace run with a `*` wildcard so any
  // whitespace shape matches.
  const WS_SENTINEL = "\u0002";
  const transformed = working
    .split(SENTINEL)
    .map((seg) => {
      const collapsed = seg.replace(/[\s\u00A0]+/g, WS_SENTINEL);
      return collapsed
        .split(WS_SENTINEL)
        .map((piece) => escapeWordWildcards(piece))
        .join("*");
    })
    .join("*");

  if (!transformed.includes("*")) return null;
  // Collapse `**` runs to a single `*` (Word treats them the same; cleaner logs).
  return transformed.replace(/\*+/g, "*");
}

/**
 * Highlights identified variables in the Word document with orange background
 * and wraps them in Content Controls tagged with the variable name.
 * The original text is preserved — not replaced with {VariableName}.
 * Content Controls allow reliable find-by-tag updates later.
 *
 * @param variables Array of identified variables to highlight
 * @returns Promise that resolves when all highlights are complete
 */
export async function replaceVariablesInDocument(variables: Variable[]): Promise<void> {
  // Check if Word API is available
  if (!isWordApiAvailable()) {
    const errorMsg =
      "Word API is not available. This add-in must be run within Microsoft Word. " +
      "If you are testing in a browser, please load the add-in in Word instead.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  if (!variables || variables.length === 0) {
    log("[Variable Highlight] No variables to highlight");
    return;
  }

  try {
    log(`[Variable Highlight] Starting highlight of ${variables.length} variables`);

    await runWordOperation(async (context) => {
      const body = context.document.body;

      // Sort variables by originalText length descending so longer texts are wrapped first.
      // This prevents short substrings (e.g. "103") from matching inside longer values
      // (e.g. "G/1036/1998") that haven't been wrapped yet.
      const sortedVariables = [...variables].sort((a, b) => {
        const aLen = (a.originalText || a.name || "").length;
        const bLen = (b.originalText || b.name || "").length;
        return bLen - aLen;
      });

      // Pre-compute the set of OTHER originalTexts so each parent search can build a
      // child-aware wildcard variant. Streaming chunks arrive out of length order,
      // so a parent span whose children were wrapped in an earlier chunk needs a
      // search target that tolerates `{X}` markers inserted around the children.
      const allOriginalTexts: string[] = sortedVariables
        .map((v) => (v.originalText || "").trim())
        .filter((s) => s.length > 0);

      // Process each variable (longest originalText first)
      for (const variable of sortedVariables) {
        const originalText = variable.originalText?.trim();
        const variableKey = variable.name?.trim();

        // Skip if variableKey is empty (name is required)
        if (!variableKey) {
          log(
            `[Variable Highlight] Skipping variable with empty name: ${JSON.stringify(variable)}`
          );
          continue;
        }

        // Check if content controls with this tag already exist
        const existingControls = context.document.contentControls.getByTag(variableKey);
        existingControls.load("items");
        await context.sync();

        // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
        if (existingControls.items.length > 0) {
          // Update existing controls — refresh appearance and color only
          // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
          for (let i = 0; i < existingControls.items.length; i++) {
            // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
            const cc = existingControls.items[i];
            cc.appearance = "BoundingBox";
            cc.title = variableKey;
            cc.load("text");
            await context.sync();
            const currentText = cc.text || "";
            // Determine color: green if filled (text differs from variable name), yellow if unfilled
            const isFilled =
              currentText && currentText.trim() && currentText.trim() !== variableKey;
            cc.color = isFilled ? "#107C10" : "#FFFF00";
            const ccRange = cc.getRange("Whole");
            ccRange.font.highlightColor = null;
            if (isFilled) {
              ccRange.font.underline = "None";
            } else {
              ccRange.font.underline = "Single";
              ccRange.font.underlineColor = "#1565C0";
            }
          }
          await context.sync();
          log(
            // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
            `[Variable Highlight] Updated ${existingControls.items.length} existing content control(s) for "${variableKey}"`
          );
          continue;
        }

        // Determine what text to search for in the document:
        // Search with braces FIRST so we capture the full {text} and don't leave orphan braces
        const searchTargets: string[] = [];

        if (originalText) {
          // Plain original text — no brace markers expected anymore
          searchTargets.push(originalText);
          // Try with collapsed whitespace (Word may have extra spaces)
          const collapsed = originalText.replace(/\s+/g, " ").trim();
          if (collapsed !== originalText) {
            searchTargets.push(collapsed);
          }
          // Try without punctuation after key words (e.g. "Section: 138" vs "Section 138")
          const noPunct = collapsed.replace(/([A-Za-z])\s*[:;,]\s*(\d)/g, "$1 $2");
          if (noPunct !== collapsed) {
            searchTargets.push(noPunct);
          }
          // Letter-spaced variant intentionally removed: for long
          // address-style spans (80+ chars) the spaced form became 160+
          // chars which exceeded Word's body.search size limit, generating
          // a long tail of slow no-op searches per variable that froze the
          // add-in. The cascade-+-whitespace-tolerant wildcard target
          // (built by the BE wrapping_plan and applied below) already
          // covers the legitimate use case of letter-spaced IDs in docs.
        }
        // Fallback: try {VariableName} placeholder
        searchTargets.push(`{${variableKey}}`);

        // Child-aware wildcard target: streaming pipelines wrap shorter spans
        // (e.g. "UCO BANK", "JODHPUR") before a longer parent span (e.g.
        // "UCO BANK; NEAR NASRANI CINEMA, ..., JODHPUR, PIN: 342003 [RAJSTHAN]")
        // arrives. By the time the parent search runs, the document text has
        // `{UCO BANK}` and `{JODHPUR}` markers around the children, so a literal
        // search for the parent fails. Build a wildcard variant that replaces
        // each known child substring with `*`.
        const childWildcardTarget =
          originalText && originalText.length > 0
            ? buildChildAwareWildcardTarget(originalText, allOriginalTexts)
            : null;

        log(
          `[Variable Highlight] Highlighting variable "${variableKey}" (search targets: ${searchTargets.join(", ")})`
        );

        try {
          let totalWrapped = 0;

          // Build the search-pass plan: literal targets first, then a single
          // child-aware wildcard target if available.
          type SearchPass = { text: string; wildcards: boolean };
          const passes: SearchPass[] = searchTargets.map((t) => ({
            text: t,
            wildcards: false,
          }));
          if (childWildcardTarget) {
            passes.push({ text: childWildcardTarget, wildcards: true });
          }

          // Search ALL targets — don't stop after first match so we catch all occurrences
          // (e.g. {Section 138...} in one place and plain "Section: 138..." in another)
          // Word's body.search has an effective ~255 char limit; longer patterns
          // come back empty and waste a sync per attempt, so skip them.
          const WORD_SEARCH_MAX = 255;
          for (const pass of passes) {
            const searchText = pass.text;
            if (searchText.length > WORD_SEARCH_MAX) {
              log(
                `[Variable Highlight] Skipping target over ${WORD_SEARCH_MAX} chars (${searchText.length}) for "${variableKey}"`
              );
              continue;
            }
            const searchResults = body.search(searchText, {
              matchCase: false,
              matchWholeWord: false,
              matchWildcards: pass.wildcards,
            });

            searchResults.load("items");
            await context.sync();

            if (searchResults.items.length === 0) {
              log(
                `[Variable Highlight] No occurrences of "${searchText}" found${pass.wildcards ? " (wildcard pass)" : ""}, trying next target`
              );
              continue;
            }

            log(
              `[Variable Highlight] Found ${searchResults.items.length} occurrence(s) of "${searchText}"`
            );

            // Wrap ALL occurrences so updating one variable fills every instance in the document
            let wrappedInThisTarget = 0;
            // Batch-load parent CC null-status for all results in ONE sync
            // rather than one-per-result — per-result sync was the dominant
            // cause of the add-in becoming unresponsive on large docs.
            const parentChecks = searchResults.items.map((r) => {
              const p = r.parentContentControlOrNullObject;
              p.load("isNullObject");
              return p;
            });
            await context.sync();

            for (let idx = 0; idx < searchResults.items.length; idx++) {
              const range = searchResults.items[idx];

              // Already inside a content control (from a longer variable
              // that was processed earlier or an earlier search target).
              if (!parentChecks[idx].isNullObject) {
                log(
                  `[Variable Highlight] Skipping "${variableKey}" occurrence ${idx} — already inside a content control`
                );
                continue;
              }

              const cc = range.insertContentControl();
              cc.tag = variableKey;
              cc.title = variableKey;
              cc.appearance = "BoundingBox";
              cc.color = "#FFFF00"; // Yellow — identified but unfilled
              // No braces — original text stays in place inside the CC.
              // Dark blue underline for unfilled variables
              const newRange = cc.getRange("Whole");
              newRange.font.highlightColor = null;
              newRange.font.underline = "Single";
              newRange.font.underlineColor = "#1565C0";
              wrappedInThisTarget++;
            }

            if (wrappedInThisTarget > 0) {
              log(
                `[Variable Highlight] Wrapped ${wrappedInThisTarget} occurrence(s) of "${searchText}" in content controls (tag: ${variableKey})`
              );
              totalWrapped += wrappedInThisTarget;
            }

            await context.sync();
          }

          if (totalWrapped === 0) {
            log(
              `[Variable Highlight] Could not find any occurrences for variable "${variableKey}"`
            );
          } else {
            log(
              `[Variable Highlight] Total: wrapped ${totalWrapped} occurrence(s) for "${variableKey}"`
            );
          }
        } catch (searchError) {
          log(`[Variable Highlight] Error highlighting "${variableKey}": ${searchError}`);
          continue;
        }
      }

      log("[Variable Highlight] All variable highlights completed");
    });
  } catch (error) {
    logError("[Document Extraction] Variable highlighting failed", error);
    throw new Error(
      `Failed to highlight variables in document: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Applies a backend-supplied wrapping plan: the BE has already computed the
 * length-desc order and per-variable Word search targets (literal + cascade-
 * and whitespace-tolerant wildcards), so client devices skip the per-variable
 * string processing.
 *
 * Run this AFTER streaming completes — once the full variable list is known
 * the plan can mark child variables that should be absorbed into a longer
 * parent (e.g. `Ahmedabad` → absorbed by `Shop No: Ahmedabad`). For absorbed
 * entries this function:
 *   - skips the standalone wrap, so the parent's wrap subsumes the span;
 *   - unwraps any progressively-wrapped CCs that already exist for the child
 *     and now sit inside the parent's range, so the document ends up with a
 *     single clean `{Shop No: Ahmedabad}` instead of nested
 *     `{Shop No: {Ahmedabad}}`.
 *
 * Variable LIST membership is unchanged — both rows still appear in the
 * panel and persist with the template; only the document wrap is single.
 */
export async function applyWrappingPlan(
  variables: Variable[],
  plan: import("./types").WrappingPlanEntry[]
): Promise<void> {
  if (!isWordApiAvailable()) {
    throw new Error("Word API is not available. This add-in must be run within Microsoft Word.");
  }
  if (!variables.length || !plan.length) {
    log("[Wrapping Plan] No variables or empty plan — nothing to do");
    return;
  }

  // Word.body.search has an effective ~255 char limit; longer patterns come
  // back empty. Skip them defensively rather than burn a sync round-trip.
  const WORD_SEARCH_MAX = 255;

  log(`[Wrapping Plan] Applying ${plan.length} entries (${variables.length} variables)`);

  const wrapRange = (
    range: Word.Range,
    tag: string,
    _insertBraces: boolean,
    _useWildcards: boolean,
    _searchText: string
  ): void => {
    const cc = range.insertContentControl();
    cc.tag = tag;
    cc.title = tag;
    cc.appearance = "BoundingBox";
    cc.color = "#FFFF00";
    const wholeRange = cc.getRange("Whole");
    wholeRange.font.highlightColor = null;
    wholeRange.font.underline = "Single";
    wholeRange.font.underlineColor = "#1565C0";
  };

  await runWordOperation(async (context) => {
    const body = context.document.body;

    // ---------------------------------------------------------------
    // Phase 1 — wrap each plan entry, in BE-supplied order (shortest
    // first so children wrap before their parents). One body.search
    // per entry. No fallback chain. No per-result sync; parent-CC
    // null checks are batched once per entry.
    // ---------------------------------------------------------------
    for (const entry of plan) {
      const variable = variables[entry.variableIndex];
      if (!variable) continue;
      const tag = variable.name?.trim();
      if (!tag) continue;
      const searchText = (entry.searchText || "").trim();
      if (!searchText) continue;

      if (searchText.length > WORD_SEARCH_MAX) {
        log(
          `[Wrapping Plan] Skipping "${tag}" — search text ${searchText.length} chars > ${WORD_SEARCH_MAX}`
        );
        continue;
      }

      const results = body.search(searchText, {
        matchCase: false,
        matchWholeWord: false,
        matchWildcards: entry.useWildcards,
      });
      results.load("items");
      await context.sync();

      let wrappedCount = 0;

      if (results.items.length > 0) {
        // Primary search hit. Batch parent-CC null checks for ALL hits in
        // one sync.
        const parentChecks = results.items.map((r) => {
          const p = r.parentContentControlOrNullObject;
          p.load("isNullObject");
          return p;
        });
        await context.sync();

        for (let i = 0; i < results.items.length; i++) {
          if (!parentChecks[i].isNullObject) continue;
          const range = results.items[i];
          wrapRange(range, tag, entry.insertBraces, entry.useWildcards, searchText);
          wrappedCount++;
        }
        await context.sync();
      } else {
        // Primary search missed. Two failure modes we have to handle:
        //   1. Multi-paragraph spans — Word's wildcard `*` doesn't cross
        //      paragraph marks, so a long parent address comes back with
        //      0 hits even though both ends are clearly present.
        //   2. LLM typos in trailing words — e.g. originalText ends with
        //      "JODHPAR" but the doc reads "JODHPUR", so any suffix anchor
        //      that includes the typo'd word never matches.
        //
        // Fallback: build a prefix anchor and several suffix candidates
        // by progressively dropping trailing words, then expand the
        // prefix range to whichever suffix candidate matches first.
        // Even if the last few words are typo'd, an earlier suffix
        // anchor will catch most of the span.
        const variable = variables[entry.variableIndex];
        const fullText = (variable?.originalText || "").trim();
        const ANCHOR_LEN = 30;

        if (fullText.length > ANCHOR_LEN) {
          // ----- Prefix anchor (front of text, ≤ ANCHOR_LEN chars) -----
          let prefix = fullText.slice(0, ANCHOR_LEN).trim();
          const lastSpaceInPrefix = prefix.lastIndexOf(" ");
          if (lastSpaceInPrefix >= 10) prefix = prefix.slice(0, lastSpaceInPrefix);

          // ----- Suffix candidates with progressive word-drop -----
          // Each iteration peels one word off the right end of fullText
          // and uses the LAST ANCHOR_LEN chars of what remains. Up to
          // 5 candidates so a typo in the last 1-3 words still has
          // earlier anchors to fall back on.
          const suffixCandidates: string[] = [];
          let working = fullText;
          for (let i = 0; i < 5; i++) {
            let s = working.slice(-ANCHOR_LEN).trim();
            const firstSpace = s.indexOf(" ");
            if (firstSpace > 0 && firstSpace <= s.length - 8) {
              s = s.slice(firstSpace + 1);
            }
            if (
              s &&
              s !== prefix &&
              suffixCandidates.indexOf(s) === -1 &&
              s.length <= WORD_SEARCH_MAX
            ) {
              suffixCandidates.push(s);
            }
            const lastSpace = working.lastIndexOf(" ");
            if (lastSpace < 20) break;
            working = working.slice(0, lastSpace).trim();
          }

          if (prefix && prefix.length <= WORD_SEARCH_MAX && suffixCandidates.length > 0) {
            // Issue ALL searches in parallel inside one sync, then pick
            // the first candidate that has hits.
            const prefixHits = body.search(prefix, {
              matchCase: false,
              matchWholeWord: false,
              matchWildcards: false,
            });
            const suffixHitGroups = suffixCandidates.map((s) => ({
              text: s,
              hits: body.search(s, {
                matchCase: false,
                matchWholeWord: false,
                matchWildcards: false,
              }),
            }));
            prefixHits.load("items");
            for (const g of suffixHitGroups) g.hits.load("items");
            await context.sync();

            if (prefixHits.items.length > 0) {
              const prefixRange = prefixHits.items[0];
              let suffixRange: Word.Range | null = null;
              let usedSuffix = "";
              for (const g of suffixHitGroups) {
                if (g.hits.items.length > 0) {
                  // Take the LAST hit so we wrap the deepest plausible
                  // endpoint (a doc may have the prefix words in two
                  // paragraphs; the last suffix hit is likely the
                  // intended end of the variable's span).
                  suffixRange = g.hits.items[g.hits.items.length - 1];
                  usedSuffix = g.text;
                  break;
                }
              }
              if (suffixRange) {
                try {
                  const expanded = prefixRange.expandTo(suffixRange);
                  const parentCheck = expanded.parentContentControlOrNullObject;
                  parentCheck.load("isNullObject");
                  await context.sync();
                  if (parentCheck.isNullObject) {
                    wrapRange(expanded, tag, entry.insertBraces, true, searchText);
                    wrappedCount++;
                    await context.sync();
                    log(
                      `[Wrapping Plan] "${tag}": wrapped via prefix+suffix expansion (suffix="${usedSuffix}")`
                    );
                  }
                } catch (e) {
                  log("[Wrapping Plan] Range expansion failed", e);
                }
              }
            }
          }
        }
      }

      if (wrappedCount === 0) {
        log(
          `[Wrapping Plan] No match for "${tag}" (${entry.useWildcards ? "wildcard" : "literal"})`
        );
      } else {
        log(`[Wrapping Plan] Wrapped ${wrappedCount} occurrence(s)`);
      }
    }

    // Phase 2 (child absorption / unwrap) intentionally REMOVED. Hard
    // invariant: every identified variable must be visibly highlighted
    // with `{` `}` in the doc — including children that sit inside a
    // parent. The doc renders nested wraps `{Parent ... {Child} ...}`
    // so the user can confirm at a glance that every panel row maps to
    // a marker in the doc.
    log("[Wrapping Plan] Apply complete");
  });
}

/**
 * Fills variable placeholders in the Word document with actual values
 * Replaces {variable name} with the provided values
 *
 * @param variableValues Record mapping variable names to their values
 * @returns Promise that resolves when all replacements are complete
 */
export async function fillVariablesInDocument(
  variableValues: Record<string, string>
): Promise<void> {
  // Check if Word API is available
  if (!isWordApiAvailable()) {
    const errorMsg =
      "Word API is not available. This add-in must be run within Microsoft Word. " +
      "If you are testing in a browser, please load the add-in in Word instead.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  if (!variableValues || Object.keys(variableValues).length === 0) {
    log("[Variable Filling] No variable values to apply");
    return;
  }

  try {
    log(
      `[Variable Filling] Starting to fill ${Object.keys(variableValues).length} variables with values`
    );

    await runWordOperation(async (context) => {
      const body = context.document.body;

      // Process each variable
      for (const [variableName, value] of Object.entries(variableValues)) {
        // Skip empty values
        if (!value || value.trim().length === 0) {
          log("[Variable Filling] Skipping empty variable value");
          continue;
        }

        const placeholderText = `{${variableName}}`;
        const replacementText = value.trim();

        log("[Variable Filling] Replacing variable occurrence");

        try {
          // Use Word's search to find all occurrences of the placeholder
          const searchResults = body.search(placeholderText, {
            matchCase: false,
            matchWholeWord: false,
            matchWildcards: false,
          });

          searchResults.load("items");
          await context.sync();

          log(
            `[Variable Filling] Found ${searchResults.items.length} occurrence(s) of "${placeholderText}"`
          );

          // Replace each occurrence
          // Process in reverse order to maintain correct positions
          for (let i = searchResults.items.length - 1; i >= 0; i--) {
            const range = searchResults.items[i];

            // Replace the text
            range.insertText(replacementText, Word.InsertLocation.replace);
            log(`[Variable Filling] Replaced occurrence ${i + 1}`);
          }

          await context.sync();
        } catch (searchError) {
          log("[Variable Filling] Replacement failed", searchError);
          // Continue with next variable instead of failing completely
          continue;
        }
      }

      log("[Variable Filling] All variable replacements completed");
    });
  } catch (error) {
    logError("[Document Extraction] Variable filling failed", error);
    throw new Error(
      `Failed to fill variables in document: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Updates a single variable in the document using Content Controls.
 * Finds the Content Control by tag (variable name) and updates its text.
 * No text searching — uses the reliable Content Control tag lookup.
 *
 * @param variableName The variable name (matches the Content Control tag)
 * @param newValue The new value to display (empty string to revert to original text)
 * @param originalText The original text to restore when clearing (from Variable.originalText)
 */
export async function updateVariableInDocument(
  variableName: string,
  newValue: string,
  originalText?: string,
  bindingId?: string
): Promise<void> {
  if (!isWordApiAvailable())
    throw new Error("Word API is not available. This add-in must be run within Microsoft Word.");
  const trimmedNew = newValue.trim();
  const contentControlTag = bindingId || variableName;
  try {
    await runWordOperation(async (context) => {
      let controls = context.document.contentControls.getByTag(contentControlTag);
      controls.load("items");
      await context.sync();

      // Legacy-only recovery path. Immutable binding IDs must be relinked through
      // the structural binding planner so occurrence/control/location evidence
      // is captured; permissive search recovery is intentionally disabled.
      // Legacy name-tagged fields retain the older recovery behavior.
      // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
      if (controls.items.length === 0 && !bindingId && originalText && originalText.trim()) {
        const exact = context.document.body.search(originalText.trim(), {
          matchCase: false,
          matchWholeWord: false,
          matchWildcards: false,
          ignoreSpace: true,
          ignorePunct: true,
        });
        exact.load("items");
        await context.sync();
        let recoveryRanges: Word.Range[] = [...exact.items];

        if (recoveryRanges.length === 0) {
          const paragraphs = context.document.body.paragraphs;
          paragraphs.load("items");
          await context.sync();
          for (const p of paragraphs.items) p.load("text");
          await context.sync();

          const needle = originalText.trim().replace(/\s+/g, " ").toLowerCase();
          const pending: Word.RangeCollection[] = [];
          const actualSpan = (source: string): string | null => {
            let normalized = "";
            const map: number[] = [];
            let inWs = false;
            for (let i = 0; i < source.length; i++) {
              const ch = source[i];
              if (/\s/.test(ch)) {
                if (!inWs && normalized.length > 0) {
                  normalized += " ";
                  map.push(i);
                }
                inWs = true;
              } else {
                normalized += ch.toLowerCase();
                map.push(i);
                inWs = false;
              }
            }
            const at = normalized.indexOf(needle);
            if (at < 0) return null;
            const start = map[at];
            const end = map[Math.min(map.length - 1, at + needle.length - 1)] + 1;
            return source.slice(start, end);
          };

          for (const p of paragraphs.items) {
            const span = actualSpan(p.text || "");
            if (!span) continue;
            const hits = p
              .getRange()
              .search(span, { matchCase: false, matchWholeWord: false, matchWildcards: false });
            hits.load("items");
            pending.push(hits);
          }
          if (pending.length) {
            await context.sync();
            for (const hits of pending) recoveryRanges.push(...hits.items);
          }
        }

        if (recoveryRanges.length > 0) {
          for (const range of recoveryRanges) {
            const cc = range.insertContentControl();
            cc.tag = contentControlTag;
            cc.title = variableName;
            cc.appearance = "BoundingBox";
            cc.color = "#FFFF00";
          }
          await context.sync();
          controls = context.document.contentControls.getByTag(contentControlTag);
          controls.load("items");
          await context.sync();
          // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
          log(`[updateVariableInDocument] Recovered ${controls.items.length} Word control(s)`);
        }
      }

      // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
      if (controls.items.length === 0) {
        const message = `"${variableName}" is identified but not linked to a writable Word range. AutoDraft could not safely update the document.`;
        log("[updateVariableInDocument] " + message);
        throw new Error(message);
      }

      for (const cc of controls.items) {
        if (trimmedNew) {
          cc.insertText(trimmedNew, Word.InsertLocation.replace);
          cc.color = "#107C10";
          const r = cc.getRange("Whole");
          r.font.highlightColor = null;
          r.font.underline = "None";
        } else {
          const restoreText = originalText || variableName;
          cc.insertText(restoreText, Word.InsertLocation.replace);
          cc.color = "#FFFF00";
          const r = cc.getRange("Whole");
          r.font.highlightColor = null;
          r.font.underline = "Single";
          r.font.underlineColor = "#1565C0";
        }
      }
      await context.sync();
    });
    // Reconciliation treats content changes as corruption unless they were
    // performed by AutoDraft. Update the embedded expected state only after
    // the Word mutation itself has committed successfully.
    await updateAutoDraftBindingExpectedText(
      contentControlTag,
      trimmedNew ? trimmedNew : originalText || variableName,
      variableName
    );
  } catch (error) {
    logError("[Document Extraction] Variable update failed", error);
    throw new Error(
      `Failed to update variable "${variableName}" in document: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Reads the current text value of every Content Control in the document.
 * Returns a map of tag (variable name) → current text.
 * Used for Document → Form polling sync.
 */
export async function readAllContentControlValues(): Promise<Record<string, string>> {
  if (!isWordApiAvailable()) {
    return {};
  }

  try {
    let result: Record<string, string> = {};

    await runWordOperation(async (context) => {
      const controls = context.document.body.contentControls;
      controls.load("items");
      await context.sync();

      for (let i = 0; i < controls.items.length; i++) {
        controls.items[i].load("tag,title,text");
      }
      await context.sync();

      const values: Record<string, string> = {};
      for (let i = 0; i < controls.items.length; i++) {
        const cc = controls.items[i];
        if (cc.tag) {
          // If multiple controls share the same tag, use the first non-empty value
          if (!values[cc.tag] || !values[cc.tag].trim()) {
            values[cc.tag] = cc.text || "";
          }
        }
      }
      result = values;
    });

    return result;
  } catch (error) {
    log("[Doc Sync] Error reading content-control values", error);
    return {};
  }
}

/**
 * Returns content control tags (variable names) in document order.
 * Used to re-sort the variables array so form fields match document layout.
 */
export async function getContentControlsInDocumentOrder(): Promise<string[]> {
  if (!isWordApiAvailable()) {
    return [];
  }

  try {
    const orderedTags: string[] = [];

    await runWordOperation(async (context) => {
      // Preserve body order for form sorting, but reconcile against the document-
      // wide collection as well so controls in headers/footers are not reported
      // as "Needs review" merely because body.contentControls cannot see them.
      const bodyControls = context.document.body.contentControls;
      const allControls = context.document.contentControls;
      bodyControls.load("items");
      allControls.load("items");
      await context.sync();

      for (let i = 0; i < bodyControls.items.length; i++) bodyControls.items[i].load("tag");
      for (let i = 0; i < allControls.items.length; i++) allControls.items[i].load("tag");
      await context.sync();

      const seen = new Set<string>();
      for (let i = 0; i < bodyControls.items.length; i++) {
        const tag = bodyControls.items[i].tag;
        if (tag && !seen.has(tag)) {
          seen.add(tag);
          orderedTags.push(tag);
        }
      }
      // Header/footer/other-story controls follow body controls. For existence
      // checks the order is irrelevant; for form ordering this is the safest
      // deterministic fallback across Word hosts.
      for (let i = 0; i < allControls.items.length; i++) {
        const tag = allControls.items[i].tag;
        if (tag && !seen.has(tag)) {
          seen.add(tag);
          orderedTags.push(tag);
        }
      }
    });

    log(`[Document Order] Found ${orderedTags.length} content control(s)`);
    return orderedTags;
  } catch (error) {
    log("[Document Order] Error reading content-control order", error);
    return [];
  }
}

/**
 * Renames the tag (and title) of every content control currently tagged
 * `oldTag` to `newTag`. Used by the streaming-creation reconcile step: a CC
 * wrapped per-batch under an FE-disambiguated name may need to adopt the
 * backend-authoritative name so later `getByTag(newTag)` doc-writes
 * (onApply / color / scroll) reach the existing control instead of missing.
 * No-op when `oldTag === newTag` or no CC carries `oldTag`.
 */
export async function setContentControlTitleByTag(tag: string, title: string): Promise<void> {
  if (!isWordApiAvailable()) return;
  await runWordOperation(async (context) => {
    const controls = context.document.contentControls.getByTag(tag);
    controls.load("items");
    await context.sync();
    for (const cc of controls.items) cc.title = title;
    await context.sync();
  });
  await updateAutoDraftBindingExpectedTitle(tag, title);
}

export async function renameContentControlTag(oldTag: string, newTag: string): Promise<void> {
  if (!isWordApiAvailable() || !oldTag || !newTag || oldTag === newTag) {
    return;
  }

  try {
    await runWordOperation(async (context) => {
      const controls = context.document.contentControls.getByTag(oldTag);
      controls.load("items");
      await context.sync();

      // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
      for (let i = 0; i < controls.items.length; i++) {
        controls.items[i].tag = newTag;
        controls.items[i].title = newTag;
      }
      await context.sync();
    });
    log("[Doc Sync] Retagged content control(s)");
  } catch (error) {
    log("[Doc Sync] Content-control retag failed", error);
  }
}

/**
 * Scrolls the Word document to the content control with the given variable name tag.
 * Selects the content control range so it becomes visible in the viewport.
 */
export async function scrollToContentControl(variableName: string): Promise<void> {
  if (!isWordApiAvailable()) {
    return;
  }

  try {
    await runWordOperation(async (context) => {
      const controls = context.document.contentControls.getByTag(variableName);
      controls.load("items");
      await context.sync();

      // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
      if (controls.items.length > 0) {
        const cc = controls.items[0];
        // Force a deterministic scroll-to-top using Range.scrollIntoView(true).
        // Plain select() has two failure modes we hit in the field:
        //   1. If the target is already partly in view (common for fields near
        //      end-of-document), Word treats the selection change as a no-op
        //      and does NOT scroll, so the user sees no movement.
        //   2. select() also highlights the whole range, which is distracting
        //      while filling.
        // scrollIntoView(true) explicitly puts the range at the TOP of the
        // viewport regardless of current position, and select("Start") then
        // places a thin insertion point so the field isn't highlighted.
        const startRange = cc.getRange("Start");
        // Some older Word builds don't expose scrollIntoView on Range. Guard
        // it so we never break the focus handler — fall back to select() in
        // that case (still better than nothing).
        const castStartRange = startRange as unknown as {
          scrollIntoView?: (toTop?: boolean) => void;
        };
        const maybeScroll = castStartRange.scrollIntoView;
        if (typeof maybeScroll === "function") {
          maybeScroll.call(startRange, true);
        }
        cc.select("Start");
        await context.sync();
        log("[Scroll] Scrolled to content control");
      }
    });
  } catch (error) {
    log("[Scroll] Content-control scroll failed", error);
  }
}

/**
 * Sets the color of a content control by variable name.
 * Used to indicate active (orange), filled (green), or unfilled (yellow) state.
 */
export async function setContentControlColor(variableName: string, color: string): Promise<void> {
  if (!isWordApiAvailable()) {
    return;
  }

  try {
    await runWordOperation(async (context) => {
      const controls = context.document.contentControls.getByTag(variableName);
      controls.load("items");
      await context.sync();

      // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
      for (let i = 0; i < controls.items.length; i++) {
        controls.items[i].color = color;
      }
      await context.sync();
    });
  } catch (error) {
    log("[Color] Content-control color update failed", error);
  }
}

/**
 * Removes all Content Controls from the document while preserving the text content.
 * Used when the user clicks "Complete Drafting" to finalize the document —
 * orange borders and labels are removed, but filled values remain as plain text.
 */
export async function clearAllContentControls(): Promise<void> {
  if (!isWordApiAvailable()) {
    const errorMsg = "Word API is not available. This add-in must be run within Microsoft Word.";
    logError("[Document Extraction] Word API unavailable", errorMsg);
    throw new Error(errorMsg);
  }

  try {
    // Mirrors replaceVariablesInDocument: one Word.run, group by tag, one sync per tag.
    // This processes controls top-to-bottom visually and is fast (~1 sync per variable).
    await runWordOperation(async (context) => {
      const contentControls = context.document.body.contentControls;
      contentControls.load("items");
      await context.sync();

      const count = contentControls.items.length;
      log(`[Clear Controls] Found ${count} content control(s) to remove`);

      if (count === 0) {
        log("[Clear Controls] No content controls to clear");
        return;
      }

      // Step 1: Load all tags to group by variable name
      for (let i = 0; i < count; i++) {
        contentControls.items[i].load("tag");
      }
      await context.sync();

      // Collect unique tags in document order (top-to-bottom)
      const seenTags = new Set<string>();
      const orderedTags: string[] = [];
      for (let i = 0; i < count; i++) {
        const tag = contentControls.items[i].tag;
        if (tag && !seenTags.has(tag)) {
          seenTags.add(tag);
          orderedTags.push(tag);
        }
      }

      log(
        `[Clear Controls] Processing ${orderedTags.length} unique variable(s) across ${count} controls`
      );

      // Step 2: Process each variable tag — same pattern as replaceVariablesInDocument.
      // For each tag: get all controls, strip braces, clear formatting, delete, then sync once.
      for (const tag of orderedTags) {
        try {
          const tagControls = context.document.contentControls.getByTag(tag);
          tagControls.load("items");
          await context.sync();

          // Load text for all controls with this tag
          // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
          for (let i = 0; i < tagControls.items.length; i++) {
            tagControls.items[i].load("text");
          }
          await context.sync();

          // Clear formatting and delete all controls with this tag
          // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
          for (let i = tagControls.items.length - 1; i >= 0; i--) {
            // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
            const cc = tagControls.items[i];
            const ccRange = cc.getRange("Whole");
            ccRange.font.highlightColor = null;
            ccRange.font.underline = "None";
            cc.delete(true);
          }

          // One sync per variable tag — matches replaceVariablesInDocument speed
          await context.sync();
          // eslint-disable-next-line office-addins/load-object-before-read -- items loaded via load("items") + sync above
          log(`[Clear Controls] Cleared ${tagControls.items.length} occurrence(s)`);
        } catch (tagErr) {
          log("[Clear Controls] Control cleanup warning", tagErr);
        }
      }

      // Step 3: Clean up any untagged content controls
      const remaining = context.document.body.contentControls;
      remaining.load("items");
      await context.sync();

      if (remaining.items.length > 0) {
        log(`[Clear Controls] Cleaning ${remaining.items.length} untagged control(s)`);
        for (let i = 0; i < remaining.items.length; i++) {
          remaining.items[i].load("text");
        }
        await context.sync();

        for (let i = remaining.items.length - 1; i >= 0; i--) {
          const cc = remaining.items[i];
          cc.delete(true);
        }
        await context.sync();
      }

      log(`[Clear Controls] Successfully removed all content controls, text preserved`);
    });
  } catch (error) {
    logError("[Document Extraction] Content-control cleanup failed", error);
    throw new Error(
      `Failed to clear content controls: ${error instanceof Error ? error.message : "Unknown error"}`
    );
  }
}

/**
 * Replaces the current Word document body with OCR-recognised text.
 * Callers must obtain explicit confirmation first because this is destructive.
 */
export async function replaceDocumentWithOcrText(text: string): Promise<void> {
  if (!text || !text.trim()) {
    throw new Error("OCR returned no text to import.");
  }
  if (!isWordApiAvailable()) {
    throw new Error("Word API is not available. This add-in must be run within Microsoft Word.");
  }
  await runWordOperation(async (context) => {
    context.document.body.insertText(text, Word.InsertLocation.replace);
    await context.sync();
  });
}
