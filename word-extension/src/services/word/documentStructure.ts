import { runWordOperation } from "./operationQueue";

export type DocumentStory = "body" | "table" | "header" | "footer";

export interface ExistingControl {
  tag: string;
  title: string;
  text: string;
}

export interface DocumentSourceLocation {
  story: DocumentStory;
  paragraphIndex?: number;
  tableIndex?: number;
  rowIndex?: number;
  cellIndex?: number;
  sectionIndex?: number;
  headerFooterKind?: "Primary" | "FirstPage" | "EvenPages";
}

export interface DocumentSegment {
  segmentId: string;
  source: DocumentSourceLocation;
  text: string;
  normalizedText: string;
  existingControls: ExistingControl[];
  globalStart: number;
  globalEnd: number;
  /** Internal grouping key. Matching may span paragraphs only within one group/story. */
  groupKey: string;
}

export interface DocumentStructure {
  text: string;
  normalizedText: string;
  segments: DocumentSegment[];
}

const DIGIT_MAP: Record<string, string> = {
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

export function normalizeShadowText(value: string): string {
  return (value || "")
    .replace(/[૦-૯०-९]/g, (d) => DIGIT_MAP[d] || d)
    .replace(/[\u00A0\u2007\u202F]/g, " ")
    .replace(/[“”„‟]/g, '"')
    .replace(/[‘’‚‛]/g, "'")
    .replace(/[‐‑‒–—―]/g, "-")
    .replace(/\s+/g, " ")
    .trim();
}

interface PendingSegment {
  paragraph: Word.Paragraph;
  segmentId: string;
  source: DocumentSourceLocation;
  groupKey: string;
}

/**
 * Extracts a structural, location-preserving Word representation. Original text
 * is never rewritten; `normalizedText` is a parallel search shadow only.
 */
export async function extractDocumentStructure(): Promise<DocumentStructure> {
  return runWordOperation(async (context) => {
    const pending: PendingSegment[] = [];

    const bodyParagraphs = context.document.body.paragraphs;
    bodyParagraphs.load("items");

    const tables = context.document.body.tables;
    tables.load("items");

    const sections = context.document.sections;
    sections.load("items");

    const controls = context.document.contentControls;
    controls.load("items");
    await context.sync();

    bodyParagraphs.items.forEach((paragraph, index) => {
      paragraph.load("text");
      pending.push({
        paragraph,
        segmentId: `body:p${index}`,
        source: { story: "body", paragraphIndex: index },
        groupKey: "body",
      });
    });

    for (const table of tables.items) table.rows.load("items");
    await context.sync();
    for (let ti = 0; ti < tables.items.length; ti++) {
      const table = tables.items[ti];
      for (const row of table.rows.items) row.cells.load("items");
    }
    await context.sync();
    for (let ti = 0; ti < tables.items.length; ti++) {
      const table = tables.items[ti];
      for (let ri = 0; ri < table.rows.items.length; ri++) {
        const row = table.rows.items[ri];
        for (let ci = 0; ci < row.cells.items.length; ci++) {
          row.cells.items[ci].body.paragraphs.load("items");
        }
      }
    }
    await context.sync();
    for (let ti = 0; ti < tables.items.length; ti++) {
      const table = tables.items[ti];
      for (let ri = 0; ri < table.rows.items.length; ri++) {
        const row = table.rows.items[ri];
        for (let ci = 0; ci < row.cells.items.length; ci++) {
          const paragraphs = row.cells.items[ci].body.paragraphs.items;
          paragraphs.forEach((paragraph, pi) => {
            paragraph.load("text");
            pending.push({
              paragraph,
              segmentId: `table:t${ti}:r${ri}:c${ci}:p${pi}`,
              source: {
                story: "table",
                tableIndex: ti,
                rowIndex: ri,
                cellIndex: ci,
                paragraphIndex: pi,
              },
              groupKey: `table:t${ti}:r${ri}:c${ci}`,
            });
          });
        }
      }
    }

    const kinds: Array<"Primary" | "FirstPage" | "EvenPages"> = [
      "Primary",
      "FirstPage",
      "EvenPages",
    ];
    const hfCollections: Array<{
      collection: Word.ParagraphCollection;
      story: "header" | "footer";
      sectionIndex: number;
      kind: "Primary" | "FirstPage" | "EvenPages";
    }> = [];
    for (let si = 0; si < sections.items.length; si++) {
      const section = sections.items[si];
      for (const kind of kinds) {
        const hp = section.getHeader(kind).paragraphs;
        const fp = section.getFooter(kind).paragraphs;
        hp.load("items");
        fp.load("items");
        hfCollections.push({ collection: hp, story: "header", sectionIndex: si, kind });
        hfCollections.push({ collection: fp, story: "footer", sectionIndex: si, kind });
      }
    }
    await context.sync();
    for (const entry of hfCollections) {
      entry.collection.items.forEach((paragraph, pi) => {
        paragraph.load("text");
        pending.push({
          paragraph,
          segmentId: `${entry.story}:s${entry.sectionIndex}:${entry.kind}:p${pi}`,
          source: {
            story: entry.story,
            sectionIndex: entry.sectionIndex,
            headerFooterKind: entry.kind,
            paragraphIndex: pi,
          },
          groupKey: `${entry.story}:s${entry.sectionIndex}:${entry.kind}`,
        });
      });
    }

    for (const control of controls.items) control.load("tag,title,text");
    await context.sync();

    const controlRows: ExistingControl[] = controls.items
      .map((c) => ({ tag: c.tag || "", title: c.title || "", text: c.text || "" }))
      .filter((c) => !!c.tag);

    const segments: DocumentSegment[] = [];
    let globalOffset = 0;
    const textParts: string[] = [];
    for (const item of pending) {
      const text = item.paragraph.text || "";
      if (segments.length > 0) {
        // One-character separator keeps backend source positions aligned with
        // the planner's internal story-boundary sentinel.
        textParts.push("\n");
        globalOffset += 1;
      }
      const start = globalOffset;
      const end = start + text.length;
      const existingControls = controlRows.filter((c) => c.text && text.includes(c.text));
      segments.push({
        segmentId: item.segmentId,
        source: item.source,
        text,
        normalizedText: normalizeShadowText(text),
        existingControls,
        globalStart: start,
        globalEnd: end,
        groupKey: item.groupKey,
      });
      textParts.push(text);
      globalOffset = end;
    }

    const text = textParts.join("");
    return { text, normalizedText: normalizeShadowText(text), segments };
  });
}
