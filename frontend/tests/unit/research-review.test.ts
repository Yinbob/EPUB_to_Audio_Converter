import { describe, expect, it } from "vitest";
import { activeSeconds, applicableChanges } from "../../src/researchReview";

describe("研究审阅", () => {
  it("只累计前台未暂停的时间", () => {
    expect(activeSeconds(1000, 4000, true, false)).toBe(3);
    expect(activeSeconds(1000, 4000, false, false)).toBe(0);
    expect(activeSeconds(1000, 4000, true, true)).toBe(0);
    expect(activeSeconds(4000, 1000, true, false)).toBe(0);
  });
  it("草稿选择排除已应用和人工确认", () => {
    const proposal = {
      changes: [{ segment_id: "a" }, { segment_id: "b" }, { segment_id: "c" }],
      applied_segments: ["a"],
    };
    expect(
      applicableChanges(proposal, {
        b: { status: "human" },
        c: { status: "proposed" },
      }),
    ).toEqual(["c"]);
  });
  it("冲突关系影响的建议需要人工处理", () => {
    const proposal = {
      changes: [
        {
          segment_id: "a",
          decision: { entity_id: "person" },
          dependencies: [{ upstream_id: "relation" }],
        },
      ],
      applied_segments: [],
      conflicts: [{ status: "open", refs: ["relation"] }],
    };
    expect(applicableChanges(proposal, {})).toEqual([]);
  });
});
