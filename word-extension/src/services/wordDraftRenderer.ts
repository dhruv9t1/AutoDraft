import { runWordOperation } from "./word/operationQueue";
import { getWordCapabilities } from "./word/capabilityService";

export type DraftInsertMode = "replace_document" | "insert_at_cursor" | "append";

let previousBodyOoxml: string | null = null;

export function hasUndoSnapshot(): boolean {
  return previousBodyOoxml !== null;
}

export async function documentHasText(): Promise<boolean> {
  return runWordOperation(async (context) => {
    const body = context.document.body;
    body.load("text");
    await context.sync();
    return Boolean((body.text || "").trim());
  });
}

export async function captureBodySnapshot(): Promise<string> {
  return runWordOperation(async (context) => {
    const result = context.document.body.getOoxml();
    await context.sync();

    previousBodyOoxml = result.value;
    // getOoxml() returns a ClientResult<string> whose value is populated by the
    // sync() above; ClientResult has no loadable properties, so the rule does not apply.
    // eslint-disable-next-line office-addins/load-object-before-read -- ClientResult value populated by sync()
    return result.value;
  });
}

export async function restoreLastBodySnapshot(): Promise<boolean> {
  if (!previousBodyOoxml) return false;
  const snapshot = previousBodyOoxml;
  await runWordOperation(async (context) => {
    context.document.body.insertOoxml(snapshot, Word.InsertLocation.replace);
    await context.sync();
  });
  previousBodyOoxml = null;
  return true;
}

type HeadingLevel = 0 | 1 | 2;

function normalizeDraft(text: string): string {
  return (text || "").replace(/\r\n?/g, "\n").trim();
}

function classifyLine(raw: string): { text: string; heading: HeadingLevel } {
  const line = raw.trim();
  if (!line) return { text: "", heading: 0 };

  const markdownHeading = line.match(/^(#{1,2})\s+(.+)$/);
  if (markdownHeading) {
    return {
      text: markdownHeading[2].trim(),
      heading: markdownHeading[1].length === 1 ? 1 : 2,
    };
  }

  const numberedHeading = line.match(/^((?:\d+|[IVXLC]+)[.)])\s+(.+)$/i);
  if (numberedHeading && line.length <= 110) {
    return { text: line, heading: 2 };
  }

  const letters = line.replace(/[^A-Za-z]/g, "");
  if (line.length <= 90 && letters.length >= 4 && letters === letters.toUpperCase()) {
    return { text: line, heading: 1 };
  }

  return { text: line, heading: 0 };
}

function applyHeading(paragraph: Word.Paragraph, heading: HeadingLevel): void {
  if (heading === 1) paragraph.styleBuiltIn = Word.BuiltInStyleName.heading1;
  else if (heading === 2) paragraph.styleBuiltIn = Word.BuiltInStyleName.heading2;
}

async function styleInsertedRange(
  context: Word.RequestContext,
  range: Word.Range,
  sourceLines: string[]
): Promise<void> {
  const paragraphs = range.paragraphs;
  paragraphs.load("items");
  await context.sync();

  for (let i = 0; i < paragraphs.items.length; i++) {
    const raw = sourceLines[Math.min(i, sourceLines.length - 1)] || "";
    applyHeading(paragraphs.items[i], classifyLine(raw).heading);
  }

  await context.sync();
}

export async function insertStructuredDraft(
  draft: string,
  mode: DraftInsertMode,
  trackChanges = false
): Promise<void> {
  const normalized = normalizeDraft(draft);
  if (!normalized) throw new Error("Draft is empty.");

  const classified = normalized.split("\n").map(classifyLine);
  const plainLines = classified.map((x) => x.text);
  const wordText = plainLines.join("\r");

  if (mode === "replace_document") {
    await captureBodySnapshot();
  } else {
    // A restore snapshot only belongs to the immediately preceding whole-document replacement.
    previousBodyOoxml = null;
  }

  await runWordOperation(async (context) => {
    if (trackChanges) {
      if (!getWordCapabilities().desktopTrackChanges)
        throw new Error("Track Changes insertion is not supported by this Word host.");
      const document = context.document as any;
      document.trackRevisions = true;
      await context.sync();
    }

    let inserted: Word.Range;

    if (mode === "replace_document") {
      inserted = context.document.body.insertText(wordText, Word.InsertLocation.replace);
    } else if (mode === "append") {
      const body = context.document.body;
      body.load("text");
      await context.sync();
      const prefix = (body.text || "").trim() ? "\r" : "";
      inserted = body.insertText(prefix + wordText, Word.InsertLocation.end);
    } else {
      inserted = context.document.getSelection().insertText(wordText, Word.InsertLocation.replace);
    }

    await styleInsertedRange(context, inserted, plainLines);
  });
}
