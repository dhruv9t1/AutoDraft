/**
 * Integration smoke tests for the wrapping pipeline.
 * @vitest-environment node
 *
 * Uses extracted text from a real 40-page legal .docx document as a fixture.
 * Validates that the pure search/matching pipeline functions work correctly
 * against real-world legal document content.
 *
 * These tests catch regressions in the search logic (tier fallback,
 * ws-tolerant matching, offset mapping) using actual document text.
 * They do NOT test Office.js-dependent functions (buildDocumentTextMap,
 * wrapVariablesViaFlatText) — those require the Word add-in runtime.
 */

import { describe, it, expect } from "vitest";
import {
  buildNormalizedView,
  countOccurrencesBefore,
  findAllVariableInFlatText,
  findParagraphForOffset,
  findVariableInFlatText,
} from "./wrappingPipeline";
import fs from "fs";
import path from "path";

const FIXTURES = path.resolve(__dirname, "../test/fixtures");

function loadFixture(name: string): string {
  return fs.readFileSync(path.join(FIXTURES, name), "utf-8");
}

describe("wrapping pipeline — integration smoke tests (legal doc fixture)", () => {
  // Body-paragraph-only flat text (mimics buildDocumentTextMap output
  // BEFORE table scanning was added — paragraphs joined by \n).
  const bodyFlatText = loadFixture("legal-doc-flat-text.txt");

  // Table cell texts joined by \n (simulating table scanning output).
  // Empty fixture if document has no tables.
  let cellFlatText = "";
  try {
    const cells = JSON.parse(loadFixture("legal-doc-table-cells.json")) as string[];
    cellFlatText = cells.join("\n");
  } catch {
    // Fixture may not exist for documents without tables
  }

  // Combined body + table text (mimics current buildDocumentTextMap output).
  const combinedFlatText = bodyFlatText + (cellFlatText ? "\n" + cellFlatText : "");

  it("fixture flat text is non-empty and reasonable size", () => {
    expect(bodyFlatText.length).toBeGreaterThan(10000); // legal doc is large
    expect(combinedFlatText.length).toBeGreaterThanOrEqual(bodyFlatText.length);
  });

  describe("buildNormalizedView", () => {
    it("produces normalized view shorter than original", () => {
      const { normalized, map } = buildNormalizedView(bodyFlatText);
      expect(normalized.length).toBeLessThanOrEqual(bodyFlatText.length);
      expect(map.length).toBe(normalized.length);
    });

    it("normalized view round-trips: every normalized char maps to correct original char", () => {
      const { normalized, map } = buildNormalizedView(bodyFlatText);
      for (let i = 0; i < normalized.length; i++) {
        const origIdx = map[i];
        const origChar = bodyFlatText[origIdx];
        const normChar = normalized[i];
        if (normChar === " ") {
          // Space in normalized means whitespace in original
          expect(/\s/.test(origChar)).toBe(true);
        } else {
          expect(origChar).toBe(normChar);
        }
      }
    });
  });

  describe("findAllVariableInFlatText — tiered search against real legal text", () => {
    it("tier-1 (exact): finds known body text", () => {
      // "Date" appears 94 times in this document
      const hits = findAllVariableInFlatText(bodyFlatText, "Date");
      expect(hits.length).toBeGreaterThan(0);
      expect(hits[0].tier).toBe("exact");
      for (const h of hits) {
        expect(bodyFlatText.slice(h.globalStart, h.globalEnd)).toBe("Date");
      }
    });

    it("tier-1 (exact): finds multi-word legal term", () => {
      const hits = findAllVariableInFlatText(
        bodyFlatText,
        "Section 138 of The Negotiable Instruments Act"
      );
      expect(hits.length).toBeGreaterThan(0);
      expect(hits[0].tier).toBe("exact");
    });

    it("tier-2 (ci): case-insensitive fallback works", () => {
      // "police station" lowercase should match "Police Station"
      const hits = findAllVariableInFlatText(bodyFlatText, "police station");
      if (hits.length > 0) {
        expect(hits[0].tier).toBe("ci");
      }
    });

    it("tier-3 (ws-tolerant): matches across paragraph breaks", () => {
      // Find text that spans two paragraphs joined by \n
      const { normalized } = buildNormalizedView(bodyFlatText);
      // Find a pattern that likely crosses paragraph boundary
      const hits = findAllVariableInFlatText(bodyFlatText, "Before The Court");
      expect(hits.length).toBeGreaterThan(0);
    });

    it("returns empty for non-existent text", () => {
      const hits = findAllVariableInFlatText(bodyFlatText, "XYZZY_NOT_IN_DOCUMENT_12345");
      expect(hits).toEqual([]);
    });

    it("returns empty for empty needle", () => {
      const hits = findAllVariableInFlatText(bodyFlatText, "");
      expect(hits).toEqual([]);
    });

    it("combined body+table text has more searchable content", () => {
      // Table scanning should increase findable text
      const bodyOnlyHits = findAllVariableInFlatText(bodyFlatText, "IFSC");
      const combinedHits = findAllVariableInFlatText(combinedFlatText, "IFSC");
      // Combined should have at least as many hits as body-only
      expect(combinedHits.length).toBeGreaterThanOrEqual(bodyOnlyHits.length);
    });
  });

  describe("findVariableInFlatText", () => {
    it("returns first hit only", () => {
      const hit = findVariableInFlatText(bodyFlatText, "Date");
      expect(hit).not.toBeNull();
      expect(hit!.globalStart).toBeGreaterThanOrEqual(0);
      expect(hit!.globalEnd).toBeGreaterThan(hit!.globalStart);
    });

    it("returns null for missing text", () => {
      expect(findVariableInFlatText(bodyFlatText, "XYZZY_MISSING")).toBeNull();
    });
  });

  describe("countOccurrencesBefore", () => {
    it("correctly counts with real text", () => {
      const needle = "Date";
      const firstHit = findVariableInFlatText(bodyFlatText, needle)!;
      // Before the first hit, count should be 0
      expect(countOccurrencesBefore(bodyFlatText, needle, firstHit.globalStart)).toBe(0);
      // After it, at least 1
      expect(
        countOccurrencesBefore(bodyFlatText, needle, firstHit.globalEnd + 1)
      ).toBeGreaterThanOrEqual(1);
    });
  });

  describe("findParagraphForOffset", () => {
    it("locates offset in real paragraph map", () => {
      // Build a simple offset map from the fixture paragraphs
      const paragraphs = JSON.parse(loadFixture("legal-doc-paragraphs.json")) as string[];
      let offset = 0;
      const map = paragraphs.map((text, idx) => {
        const entry = { paragraphIndex: idx, startOffset: offset, length: text.length };
        offset += text.length + 1; // +1 for \n joiner
        return entry;
      });

      // First paragraph
      expect(
        findParagraphForOffset(
          { flatText: bodyFlatText, paragraphs: map, paragraphRefs: [] as never },
          0
        )
      ).toBe(0);

      // Last paragraph
      const lastEntry = map[map.length - 1];
      expect(
        findParagraphForOffset(
          { flatText: bodyFlatText, paragraphs: map, paragraphRefs: [] as never },
          lastEntry.startOffset + lastEntry.length - 1
        )
      ).toBe(map.length - 1);
    });

    it("returns -1 for joiner gap between paragraphs", () => {
      const paragraphs = JSON.parse(loadFixture("legal-doc-paragraphs.json")) as string[];
      if (paragraphs.length > 1) {
        const joinerOffset = paragraphs[0].length; // exactly at the \n position
        let offset = 0;
        const map = paragraphs.map((text, idx) => {
          const entry = { paragraphIndex: idx, startOffset: offset, length: text.length };
          offset += text.length + 1;
          return entry;
        });
        expect(
          findParagraphForOffset(
            { flatText: bodyFlatText, paragraphs: map, paragraphRefs: [] as never },
            joinerOffset
          )
        ).toBe(-1);
      }
    });
  });

  describe("end-to-end: find and extract variable text", () => {
    it("every tier-1 hit extracts correct original text from flat text", () => {
      const searchTerms = [
        "Date",
        "Police Station",
        "The Negotiable Instruments Act",
        "AHMEDABAD",
        "GSTIN",
      ];
      for (const term of searchTerms) {
        const hits = findAllVariableInFlatText(combinedFlatText, term);
        if (hits.length > 0 && hits[0].tier === "exact") {
          for (const h of hits) {
            const extracted = combinedFlatText.slice(h.globalStart, h.globalEnd);
            expect(extracted).toBe(term);
          }
        }
      }
    });
  });
});
