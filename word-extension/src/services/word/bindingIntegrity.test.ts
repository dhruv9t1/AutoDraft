import { describe, expect, it } from "vitest";
import { exactOccurrenceIndex, sha256Hex, textMatchesRecordedOffset } from "./bindingIntegrity";

describe("binding integrity helpers", () => {
  it("uses the same exact semantics for occurrence counting and selection", () => {
    const text = "Party A; Party A / PARTY A / Party  A";
    expect(exactOccurrenceIndex(text, "Party A", 0)).toBe(0);
    expect(exactOccurrenceIndex(text, "Party A", 9)).toBe(1);
  });

  it("does not silently treat case, punctuation, or spacing variants as the same occurrence", () => {
    expect(() => exactOccurrenceIndex("ABC abc", "ABC", 4)).toThrow(/exact source offset/);
    expect(() => exactOccurrenceIndex("A-B A B", "A-B", 4)).toThrow(/exact source offset/);
    expect(() => exactOccurrenceIndex("A B A  B", "A B", 4)).toThrow(/exact source offset/);
  });

  it("hashes exact raw text so normalized-equal strings still differ", async () => {
    const upper = await sha256Hex("Party A");
    const lower = await sha256Hex("party a");
    const spaced = await sha256Hex("Party  A");
    expect(upper).not.toBe(lower);
    expect(upper).not.toBe(spaced);
    expect(upper).toMatch(/^[0-9a-f]{64}$/);
  });

  it("verifies a control is still at its recorded paragraph offset", () => {
    expect(textMatchesRecordedOffset("Label: Alice; next", "Alice", 7)).toBe(true);
    expect(textMatchesRecordedOffset("Alice Label: ; next", "Alice", 7)).toBe(false);
  });
});
