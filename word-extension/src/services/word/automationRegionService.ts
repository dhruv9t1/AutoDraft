import { runWordOperation } from "./operationQueue";

export type AutomationRegionKind = "condition" | "repeat";

function makeId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
}

/** Wrap the current Word selection in a tagged content control used by the headless automation engine. */
export async function createAutomationRegion(
  kind: AutomationRegionKind,
  title?: string
): Promise<string> {
  const tag = `autodraft:${kind}:${makeId()}`;
  return runWordOperation(async (context) => {
    const selection = context.document.getSelection();
    selection.load("text,parentContentControlOrNullObject");
    await context.sync();
    if (!(selection.text || "").trim())
      throw new Error("Select the Word text/block that this automation rule should own.");
    const cc = selection.insertContentControl();
    cc.tag = tag;
    cc.title = title || `${kind === "condition" ? "Condition" : "Repeating region"}`;
    cc.appearance = "BoundingBox";
    cc.color = kind === "condition" ? "#6B69D6" : "#008272";
    await context.sync();
    return tag;
  });
}

export async function removeAutomationRegion(tag: string): Promise<boolean> {
  return runWordOperation(async (context) => {
    const controls = context.document.contentControls;
    controls.load("items");
    await context.sync();
    for (const cc of controls.items) cc.load("tag");
    await context.sync();
    const found = controls.items.find((cc) => (cc.tag || "") === tag);
    if (!found) return false;
    found.delete(true);
    await context.sync();
    return true;
  });
}
