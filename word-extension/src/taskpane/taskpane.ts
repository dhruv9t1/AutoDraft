import { runWordOperation } from "../services/word/operationQueue";
import { error as logError, log } from "../services/logger";
export async function insertText(text: string) {
  // Write text to the document.
  try {
    await runWordOperation(async (context) => {
      let body = context.document.body;
      body.insertParagraph(text, Word.InsertLocation.end);
      log("[Taskpane] Text inserted");

      await context.sync();
    });
  } catch (error) {
    logError("[Taskpane] Text insertion failed", error);
  }
}
