import type { DocumentSourceLocation } from "./documentStructure";

async function collectionItem<T extends { load: (properties: string) => void }>(
  context: Word.RequestContext,
  collection: any,
  index: number
): Promise<T> {
  collection.load("items");
  await context.sync();
  if (index < 0 || index >= collection.items.length) {
    throw new Error(`Word source index ${index} is no longer available.`);
  }
  return collection.items[index] as T;
}

/** Resolve the immutable structural source location captured by the binding planner. */
export async function resolveParagraph(
  context: Word.RequestContext,
  source: DocumentSourceLocation
): Promise<Word.Paragraph> {
  const paragraphIndex = source.paragraphIndex ?? 0;
  if (source.story === "body") {
    return collectionItem<Word.Paragraph>(
      context,
      context.document.body.paragraphs,
      paragraphIndex
    );
  }
  if (source.story === "table") {
    const table = await collectionItem<any>(
      context,
      context.document.body.tables,
      source.tableIndex ?? -1
    );
    const row = await collectionItem<any>(context, table.rows, source.rowIndex ?? -1);
    const cell = await collectionItem<any>(context, row.cells, source.cellIndex ?? -1);
    return collectionItem<Word.Paragraph>(context, cell.body.paragraphs, paragraphIndex);
  }
  const section = await collectionItem<any>(
    context,
    context.document.sections,
    source.sectionIndex ?? -1
  );
  const kind = source.headerFooterKind || "Primary";
  const body = source.story === "header" ? section.getHeader(kind) : section.getFooter(kind);
  return collectionItem<Word.Paragraph>(context, body.paragraphs, paragraphIndex);
}
