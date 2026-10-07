import { API_BASE_URL, apiHeaders } from "./config";
import { log } from "./logger";
import { captureCompressedDocument } from "./word/documentSnapshot";

export interface DocxLegacyFontFinding {
  fontName: string;
  runCount: number;
  inheritedOnly: boolean;
}

export interface DocxDiagnostics {
  paragraphCount: number;
  storyCounts: Record<string, number>;
  legacyFonts: DocxLegacyFontFinding[];
  warnings: string[];
}

function base64ToBlob(base64: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}

/**
 * Inspect the actual DOCX package for pre-Unicode Indian fonts before semantic
 * extraction. Unsupported Word hosts simply skip this preflight; extraction
 * still runs against the structural text path.
 */
export async function diagnoseCurrentDocument(): Promise<DocxDiagnostics | null> {
  let base64: string | null = null;
  try {
    base64 = await captureCompressedDocument();
  } catch (error) {
    log(`[DocxDiagnostics] compressed capture unavailable: ${error}`);
    return null;
  }
  if (!base64) return null;

  // Avoid doubling memory for exceptionally large documents. The backend still
  // exposes the diagnostics endpoint for explicit/server-side use.
  const estimatedBytes = Math.floor((base64.length * 3) / 4);
  if (estimatedBytes > 25 * 1024 * 1024) {
    log(
      `[DocxDiagnostics] skipped automatic preflight for ${Math.round(estimatedBytes / 1024 / 1024)} MB DOCX`
    );
    return null;
  }

  const form = new FormData();
  form.append("file", base64ToBlob(base64), "document.docx");
  const response = await fetch(`${API_BASE_URL}/api/documents/docx-diagnostics`, {
    method: "POST",
    headers: apiHeaders({}),
    body: form,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message =
      body?.detail || body?.error?.message || `DOCX diagnostics failed (${response.status})`;
    throw new Error(message);
  }
  return response.json() as Promise<DocxDiagnostics>;
}

export interface UnicodeSafetyOptions {
  allowLegacyFonts?: boolean;
}

export async function assertDocumentTextIsUnicodeSafe(
  options: UnicodeSafetyOptions = {}
): Promise<DocxDiagnostics | null> {
  const diagnostics = await diagnoseCurrentDocument();
  if (!diagnostics) return null;
  const activeLegacy = diagnostics.legacyFonts.filter((font) => font.runCount > 0);
  if (activeLegacy.length) {
    const details = activeLegacy
      .map((font) => `${font.fontName} (${font.runCount} run${font.runCount === 1 ? "" : "s"})`)
      .join(", ");
    const message =
      `AutoDraft detected pre-Unicode Indian font text: ${details}. ` +
      "Word can display this text as Gujarati/Hindi while the stored characters are different ASCII glyph codes. " +
      "AutoDraft is continuing in legacy-font mode and will preserve the current Word document/fonts. " +
      "Review the detected fields carefully because Gujarati/Hindi offsets and values may not be Unicode-normalized.";
    if (options.allowLegacyFonts) {
      log(`[DocxDiagnostics] ${message}`);
    } else {
      throw new Error(
        `${message} ` +
          "Convert those runs to real Unicode text before Auto Detect if you need Unicode-normalized Gujarati/Hindi values."
      );
    }
  }
  if (diagnostics.warnings.length) {
    log(`[DocxDiagnostics] ${diagnostics.warnings.join(" | ")}`);
  }
  return diagnostics;
}
