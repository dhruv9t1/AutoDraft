import { describe, it, expect } from "vitest";
import {
  dedupSubstringOverlap,
  dedupVariablesByOriginalText,
  filterListMarkerVariables,
  isListMarkerVariable,
} from "./documentExtraction";

type Var = { originalText?: string; name?: string };

describe("isListMarkerVariable", () => {
  it("flags bracketed integers", () => {
    expect(isListMarkerVariable({ originalText: "[1]" })).toBe(true);
    expect(isListMarkerVariable({ originalText: "[12]" })).toBe(true);
    expect(isListMarkerVariable({ originalText: " [3] " })).toBe(true);
  });

  it("flags parenthesized integers", () => {
    expect(isListMarkerVariable({ originalText: "(1)" })).toBe(true);
    expect(isListMarkerVariable({ originalText: "(12)" })).toBe(true);
  });

  it("flags page-marker patterns", () => {
    expect(isListMarkerVariable({ originalText: "12." })).toBe(true);
    expect(isListMarkerVariable({ originalText: "…14." })).toBe(true);
    expect(isListMarkerVariable({ originalText: ":: 3 ::" })).toBe(true);
  });

  it("does NOT flag a real 6-digit PIN code as marker", () => {
    expect(isListMarkerVariable({ originalText: "342003" })).toBe(false);
    expect(isListMarkerVariable({ originalText: "123456" })).toBe(false);
  });

  it("does NOT flag named variables with semantic name", () => {
    expect(isListMarkerVariable({ name: "Cheque Number", originalText: "000129" })).toBe(false);
  });

  it("checks both originalText and name", () => {
    expect(isListMarkerVariable({ name: "[2]" })).toBe(true);
    expect(isListMarkerVariable({ originalText: "Some text", name: "[2]" })).toBe(true);
  });
});

describe("filterListMarkerVariables", () => {
  it("drops markers, keeps real variables", () => {
    const input: Var[] = [
      { name: "PIN Code", originalText: "342003" },
      { name: "List", originalText: "[1]" },
      { name: "Cheque Number", originalText: "000129" },
      { name: "Page", originalText: "…14." },
    ];
    const out = filterListMarkerVariables(input);
    expect(out).toHaveLength(2);
    expect(out.map((v) => v.originalText)).toEqual(["342003", "000129"]);
  });

  it("returns empty for all-marker input", () => {
    const input: Var[] = [{ originalText: "(1)" }, { originalText: "[2]" }];
    expect(filterListMarkerVariables(input)).toEqual([]);
  });

  it("returns empty for empty input", () => {
    expect(filterListMarkerVariables([])).toEqual([]);
  });
});

describe("dedupVariablesByOriginalText", () => {
  it("collapses exact-equal originalText (case + whitespace insensitive)", () => {
    const input: Var[] = [
      { name: "Accused Proprietor Name", originalText: "Mr. JOHN DOE" },
      { name: "Accused Authorized Person", originalText: "Mr. JOHN DOE" },
      { name: "Accused Mr.", originalText: " mr. john doe " },
    ];
    const out = dedupVariablesByOriginalText(input);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("Accused Proprietor Name");
  });

  it("keeps distinct originalText values", () => {
    const input: Var[] = [{ originalText: "JOHN DOE" }, { originalText: "JANE ROE" }];
    expect(dedupVariablesByOriginalText(input)).toHaveLength(2);
  });

  it("preserves first occurrence", () => {
    const input: Var[] = [
      { name: "first", originalText: "X" },
      { name: "second", originalText: "X" },
    ];
    const out = dedupVariablesByOriginalText(input);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("first");
  });

  it("keeps entries with empty originalText (filtering left to other passes)", () => {
    const input: Var[] = [{ name: "x" }, { name: "y", originalText: "" }];
    expect(dedupVariablesByOriginalText(input)).toHaveLength(2);
  });
});

describe("dedupSubstringOverlap", () => {
  it("drops bare child whose originalText is a substring of a longer kept span", () => {
    const input: Var[] = [
      { name: "Complainant Name", originalText: "ASHWIN GANPATRAJ MEHTA" },
      {
        name: "Complainant Authorized Person",
        originalText: "Mr. ASHWIN GANPATRAJ MEHTA",
      },
    ];
    const out = dedupSubstringOverlap(input);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("Complainant Authorized Person");
  });

  it("does NOT drop equal-length entries (exact-equal case left to other dedup)", () => {
    const input: Var[] = [
      { name: "a", originalText: "FOO" },
      { name: "b", originalText: "FOO" },
    ];
    const out = dedupSubstringOverlap(input);
    expect(out).toHaveLength(2);
  });

  it("keeps disjoint variables", () => {
    const input: Var[] = [
      { name: "x", originalText: "alpha" },
      { name: "y", originalText: "beta" },
    ];
    expect(dedupSubstringOverlap(input)).toHaveLength(2);
  });

  it("comparison is case-insensitive", () => {
    const input: Var[] = [
      { name: "child", originalText: "john doe" },
      { name: "parent", originalText: "Mr. JOHN DOE" },
    ];
    const out = dedupSubstringOverlap(input);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("parent");
  });

  it("preserves entries with empty originalText", () => {
    const input: Var[] = [
      { name: "x", originalText: "" },
      { name: "y", originalText: "non-empty" },
    ];
    expect(dedupSubstringOverlap(input)).toHaveLength(2);
  });

  it("respects the regression: bare 6-digit PIN survives when no longer span contains it", () => {
    const input: Var[] = [
      { name: "PIN Code", originalText: "342003" },
      { name: "PIN Code 2", originalText: "123456" },
      { name: "Cheque Number", originalText: "000129" },
    ];
    expect(dedupSubstringOverlap(input)).toHaveLength(3);
  });
});
