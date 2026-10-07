import { describe, expect, it } from "vitest";
import { buildBindingPlan } from "./bindingPlanner";
import type { DocumentStructure } from "./documentStructure";
import type { Variable } from "../types";

const UUID = "11111111-1111-4111-8111-111111111111";

function structure(
  text: string,
  existingControls: Array<{ tag: string; title: string; text: string }> = []
): DocumentStructure {
  return {
    text,
    normalizedText: text,
    segments: [
      {
        segmentId: "body:p0",
        source: { story: "body", paragraphIndex: 0 },
        text,
        normalizedText: text,
        existingControls,
        globalStart: 0,
        globalEnd: text.length,
        groupKey: "body",
      },
    ],
  };
}

function variable(originalText: string): Variable {
  return { name: "Client", originalText, position: 3, bindingId: UUID };
}

describe("binding planner hardening", () => {
  it("preserves source offsets when normalized matching trims leading whitespace", () => {
    const doc = structure("   Client\u00a0Name: Alice");
    const plan = buildBindingPlan([variable("Client Name: Alice")], doc);
    expect(plan.canCommit).toBe(true);
    expect(plan.operations).toHaveLength(1);
    expect(plan.operations[0].globalStart).toBe(3);
    expect(plan.operations[0].source.start.offset).toBe(3);
  });

  it("skips an ungroundable variable without blocking unrelated grounded bindings", () => {
    const doc = structure("Client Name: Alice");
    const plan = buildBindingPlan(
      [
        variable("Client Name: Alice"),
        {
          ...variable("Missing value"),
          name: "Missing",
          bindingId: "22222222-2222-4222-8222-222222222222",
        },
      ],
      doc
    );

    expect(plan.canCommit).toBe(true);
    expect(plan.operations).toHaveLength(1);
    expect(plan.conflicts).toContainEqual(
      expect.objectContaining({ code: "not_found", blocking: false })
    );
  });

  it("counts verified existing controls separately from missed variables", () => {
    const doc = structure("Client Name: Alice", [
      { tag: UUID, title: "Client", text: "Client Name: Alice" },
    ]);
    const plan = buildBindingPlan([variable("Client Name: Alice")], doc);

    expect(plan.canCommit).toBe(true);
    expect(plan.operations).toHaveLength(0);
    expect(plan.alreadyBound).toBe(1);
  });

  it("blocks when an existing binding id wraps the wrong text", () => {
    const doc = structure("Client Name: Alice", [{ tag: UUID, title: "Client", text: "Bob" }]);
    const plan = buildBindingPlan([{ ...variable("Client Name: Alice"), position: 0 }], doc);
    expect(plan.canCommit).toBe(false);
    expect(plan.conflicts.some((c) => c.code === "existing_control" && c.blocking)).toBe(true);
  });
});
