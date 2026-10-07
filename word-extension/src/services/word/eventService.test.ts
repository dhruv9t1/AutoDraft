import { describe, expect, it } from "vitest";
import { isLegacyAutoDraftBindingTag } from "./eventService";

describe("AutoDraft event tag ownership", () => {
  it("accepts only the deliberate legacy AutoDraft namespace", () => {
    expect(isLegacyAutoDraftBindingTag("autodraft:550e8400-e29b-41d4-a716-446655440000")).toBe(
      true
    );
    expect(isLegacyAutoDraftBindingTag("550e8400-e29b-41d4-a716-446655440000")).toBe(false);
    expect(isLegacyAutoDraftBindingTag("third-party-tag")).toBe(false);
    expect(isLegacyAutoDraftBindingTag("autodraft-tx:550e8400-e29b-41d4-a716-446655440000")).toBe(
      false
    );
  });
});
