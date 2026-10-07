import type { DraftReviewFinding } from "../types";
import { getWordCapabilities } from "./capabilityService";
import { runWordOperation } from "./operationQueue";

export async function insertReviewComments(findings: DraftReviewFinding[]): Promise<number> {
  if (!getWordCapabilities().comments)
    throw new Error("Native Word comments are not supported by this Word host.");
  return runWordOperation(async (context) => {
    let inserted = 0;
    for (const finding of findings) {
      const needle = String(finding.location?.searchText || finding.location?.quote || "").trim();
      if (!needle) continue;
      const hits = context.document.body.search(needle.slice(0, 220), {
        matchCase: false,
        matchWholeWord: false,
        ignoreSpace: true,
        ignorePunct: true,
      });
      hits.load("items");
      await context.sync();
      if (!hits.items.length) continue;
      (hits.items[0] as any).insertComment(
        `${finding.title}\n\n${finding.detail}${finding.suggestedAction ? `\n\nSuggested action: ${finding.suggestedAction}` : ""}`
      );
      inserted++;
    }
    await context.sync();
    return inserted;
  });
}
