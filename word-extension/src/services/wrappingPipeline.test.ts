import { describe, it, expect } from "vitest";
import {
  buildNormalizedView,
  countOccurrencesBefore,
  findAllVariableInFlatText,
  findParagraphForOffset,
  findVariableInFlatText,
  wrapVariablesViaFlatText,
  type DocumentTextMap,
  type WrappingStats,
} from "./wrappingPipeline";

describe("buildNormalizedView", () => {
  it("collapses runs of ASCII whitespace into a single space", () => {
    const { normalized } = buildNormalizedView("foo   bar\t\tbaz");
    expect(normalized).toBe("foo bar baz");
  });

  it("collapses leading whitespace away (simulates leading-trim)", () => {
    const { normalized } = buildNormalizedView("   leading");
    expect(normalized).toBe("leading");
  });

  it("collapses Unicode whitespace including non-breaking space (U+00A0)", () => {
    const { normalized } = buildNormalizedView("foo  bar");
    expect(normalized).toBe("foo bar");
  });

  it("collapses paragraph joiner '\\n' into a single space", () => {
    const { normalized } = buildNormalizedView("line1\nline2");
    expect(normalized).toBe("line1 line2");
  });

  it("returns parallel index map back to original offsets", () => {
    const text = "a   b";
    const { normalized, map } = buildNormalizedView(text);
    expect(normalized).toBe("a b");
    expect(map.length).toBe(normalized.length);
    expect(text[map[0]]).toBe("a");
    expect(text[map[2]]).toBe("b");
  });

  it("collapses whitespace-only input to empty normalized", () => {
    const { normalized, map } = buildNormalizedView("   \t\n");
    expect(normalized).toBe("");
    expect(map).toEqual([]);
  });
});

describe("findAllVariableInFlatText", () => {
  it("does not match across a hard Word-story boundary", () => {
    const flat = "BODY END\uE000TABLE START";
    expect(findAllVariableInFlatText(flat, "BODY END TABLE START")).toEqual([]);
  });
  it("returns empty for empty needle", () => {
    expect(findAllVariableInFlatText("hello world", "")).toEqual([]);
  });

  it("tier-1: returns every exact occurrence", () => {
    const flat = "TOPS TEXTILES sells. Section 2 mentions TOPS TEXTILES again.";
    const hits = findAllVariableInFlatText(flat, "TOPS TEXTILES");
    expect(hits).toHaveLength(2);
    expect(hits[0].tier).toBe("exact");
    expect(hits[0].globalStart).toBe(0);
    expect(hits[0].globalEnd).toBe("TOPS TEXTILES".length);
    expect(flat.slice(hits[1].globalStart, hits[1].globalEnd)).toBe("TOPS TEXTILES");
  });

  it("tier-1 priority: case-mismatched does not fall through when exact has hits", () => {
    const flat = "PIN 123456 here and pin 123456 there";
    const hits = findAllVariableInFlatText(flat, "PIN 123456");
    expect(hits).toHaveLength(1);
    expect(hits[0].tier).toBe("exact");
  });

  it("tier-2: case-insensitive when no exact match", () => {
    const flat = "Cheque No.: 000129 in record";
    const hits = findAllVariableInFlatText(flat, "cheque no.: 000129");
    expect(hits).toHaveLength(1);
    expect(hits[0].tier).toBe("ci");
    expect(flat.slice(hits[0].globalStart, hits[0].globalEnd)).toBe("Cheque No.: 000129");
  });

  it("tier-3: ws-tolerant collapses Unicode whitespace runs", () => {
    const flat = "JAI SRI LAKSHMI  COLLECTION end";
    const hits = findAllVariableInFlatText(flat, "JAI SRI LAKSHMI COLLECTION");
    expect(hits).toHaveLength(1);
    expect(hits[0].tier).toBe("ws-tolerant");
    expect(flat.slice(hits[0].globalStart, hits[0].globalEnd)).toBe("JAI SRI LAKSHMI  COLLECTION");
  });

  it("tier-3: matches across paragraph joiner '\\n'", () => {
    const flat = "Address line one\nline two final";
    const hits = findAllVariableInFlatText(flat, "Address line one line two");
    expect(hits).toHaveLength(1);
    expect(hits[0].tier).toBe("ws-tolerant");
    expect(flat.slice(hits[0].globalStart, hits[0].globalEnd)).toBe("Address line one\nline two");
  });

  it("tier-3: returns empty when needle normalizes to empty string", () => {
    expect(findAllVariableInFlatText("anything", "   \t  ")).toEqual([]);
  });

  it("returns empty when needle absent in all tiers", () => {
    expect(findAllVariableInFlatText("hello world", "missing")).toEqual([]);
  });

  it("multi-occurrence does not double-count overlapping starts", () => {
    const flat = "aaaa";
    const hits = findAllVariableInFlatText(flat, "aa");
    expect(hits.map((h) => h.globalStart)).toEqual([0, 1, 2]);
  });
});

describe("findVariableInFlatText", () => {
  it("returns first hit only", () => {
    const flat = "TOPS TEXTILES and TOPS TEXTILES";
    const hit = findVariableInFlatText(flat, "TOPS TEXTILES");
    expect(hit).not.toBeNull();
    expect(hit!.globalStart).toBe(0);
  });

  it("returns null when no hit", () => {
    expect(findVariableInFlatText("foo", "bar")).toBeNull();
  });
});

describe("countOccurrencesBefore", () => {
  it("counts non-overlapping occurrences before position", () => {
    const text = "ab ab ab end";
    expect(countOccurrencesBefore(text, "ab", 0)).toBe(0);
    expect(countOccurrencesBefore(text, "ab", 3)).toBe(1);
    expect(countOccurrencesBefore(text, "ab", 9)).toBe(3);
  });

  it("returns 0 for empty needle or non-positive position", () => {
    expect(countOccurrencesBefore("ab ab", "", 5)).toBe(0);
    expect(countOccurrencesBefore("ab ab", "ab", 0)).toBe(0);
    expect(countOccurrencesBefore("ab ab", "ab", -1)).toBe(0);
  });

  it("does not count occurrence starting at position", () => {
    expect(countOccurrencesBefore("abXab", "ab", 3)).toBe(1);
  });
});

describe("findParagraphForOffset", () => {
  const buildMap = (lengths: number[]): DocumentTextMap => {
    let off = 0;
    const paragraphs = lengths.map((length, paragraphIndex) => {
      const entry = { paragraphIndex, startOffset: off, length };
      off += length + 1;
      return entry;
    });
    return {
      flatText: "x".repeat(off),
      paragraphs,
      paragraphRefs: [] as never,
    };
  };

  it("locates offset inside a paragraph", () => {
    const map = buildMap([5, 10, 3]);
    expect(findParagraphForOffset(map, 0)).toBe(0);
    expect(findParagraphForOffset(map, 4)).toBe(0);
    expect(findParagraphForOffset(map, 6)).toBe(1);
    expect(findParagraphForOffset(map, 17)).toBe(2);
  });

  it("returns -1 for offset within joiner gap", () => {
    const map = buildMap([5, 5]);
    expect(findParagraphForOffset(map, 5)).toBe(-1);
  });

  it("treats end-of-document offset as last paragraph", () => {
    const map = buildMap([5, 5]);
    const eof = 5 + 1 + 5;
    expect(findParagraphForOffset(map, eof)).toBe(1);
  });

  it("returns -1 for empty document", () => {
    const map: DocumentTextMap = {
      flatText: "",
      paragraphs: [],
      paragraphRefs: [] as never,
    };
    expect(findParagraphForOffset(map, 0)).toBe(-1);
  });
});

describe("wrapVariablesViaFlatText", () => {
  it("returns zero stats for empty array", async () => {
    const stats = await wrapVariablesViaFlatText([]);
    const expected: WrappingStats = {
      wrapped: 0,
      missedFlat: 0,
      missedRange: 0,
      skippedAlreadyWrapped: 0,
      errors: 0,
      total: 0,
    };
    expect(stats).toEqual(expected);
  });

  it("returns zero stats for null/undefined input", async () => {
    const stats = await wrapVariablesViaFlatText(null as any);
    expect(stats.total).toBe(0);
    expect(stats.wrapped).toBe(0);
    expect(stats.errors).toBe(0);
  });

  it("throws when Word API is unavailable and variables are non-empty", async () => {
    // Word global is not mocked in test setup, so it's undefined
    await expect(
      wrapVariablesViaFlatText([{ name: "Test", originalText: "test", position: 0 }])
    ).rejects.toThrow("Word API is not available");
  });
});
