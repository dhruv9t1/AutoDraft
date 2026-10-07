import { afterEach, describe, expect, it, vi } from "vitest";
import { getWordCapabilities } from "./capabilityService";

describe("Word capability detection", () => {
  afterEach(() => {
    delete (globalThis as any).Office;
    vi.restoreAllMocks();
  });

  it("uses CustomXmlParts and CompressedFile Common API requirement sets", () => {
    const supported = new Set(["WordApi:1.4", "WordApi:1.5", "CustomXmlParts:", "CompressedFile:"]);
    (globalThis as any).Office = {
      PlatformType: { Mac: "Mac", PC: "PC" },
      context: {
        platform: "PC",
        requirements: {
          isSetSupported: (name: string, version?: string) =>
            supported.has(`${name}:${version || ""}`),
        },
      },
    };
    const value = getWordCapabilities();
    expect(value.customXml).toBe(true);
    expect(value.compressedDocumentCapture).toBe(true);
  });

  it("does not infer compressed capture from desktop platform alone", () => {
    (globalThis as any).Office = {
      PlatformType: { Mac: "Mac", PC: "PC" },
      context: { platform: "PC", requirements: { isSetSupported: () => false } },
    };
    expect(getWordCapabilities().compressedDocumentCapture).toBe(false);
  });
});
