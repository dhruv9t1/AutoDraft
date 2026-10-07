import { getWordCapabilities } from "./capabilityService";
import { extractDocumentStructure } from "./documentStructure";
import { reconcileAutoDraftDocument } from "./reconciliationService";
import { captureCompressedDocument } from "./documentSnapshot";

export interface WordSmokeResult {
  passed: boolean;
  checks: Array<{ name: string; passed: boolean; detail: string }>;
}

/** Non-destructive Word-host smoke suite. Run this inside real Word (Mac/Windows). */
export async function runWordReliabilitySmokeSuite(): Promise<WordSmokeResult> {
  const checks: WordSmokeResult["checks"] = [];
  const caps = getWordCapabilities();
  checks.push({
    name: "Word API 1.4",
    passed: caps.wordApi14,
    detail: caps.wordApi14 ? "available" : "not available",
  });
  try {
    const structure = await extractDocumentStructure();
    checks.push({
      name: "Structural extraction",
      passed: true,
      detail: `${structure.segments.length} segment(s), ${structure.text.length} characters`,
    });
  } catch (e) {
    checks.push({
      name: "Structural extraction",
      passed: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }
  try {
    const reconciliation = await reconcileAutoDraftDocument();
    checks.push({
      name: "Document reconciliation",
      passed: reconciliation.status !== "needs_repair",
      detail: reconciliation.status,
    });
  } catch (e) {
    checks.push({
      name: "Document reconciliation",
      passed: false,
      detail: e instanceof Error ? e.message : String(e),
    });
  }
  if (caps.compressedDocumentCapture) {
    try {
      const b64 = await captureCompressedDocument();
      checks.push({
        name: "Complete DOCX capture",
        passed: !!b64,
        detail: b64 ? `${Math.round((b64.length * 3) / 4 / 1024)} KB captured` : "empty snapshot",
      });
    } catch (e) {
      checks.push({
        name: "Complete DOCX capture",
        passed: false,
        detail: e instanceof Error ? e.message : String(e),
      });
    }
  } else
    checks.push({
      name: "Complete DOCX capture",
      passed: true,
      detail: "capability not expected on this host",
    });
  return { passed: checks.every((x) => x.passed), checks };
}
