import { describe, expect, it } from "vitest";
import {
  matchingRolePreview,
  nextReviewSegment,
  reviewSegments,
  scriptLanguage,
  segmentContext,
  voiceIdentity,
} from "../../src/roleReview";

const script = {
  provider: "openai",
  roles: {
    narrator: { provider_params: { voice: "茉莉", speed: 1 } },
    first: {
      provider_params: { voice: "茉莉", speed: 1.3, instructions: "平静" },
    },
    second: { provider_params: { voice: "冰糖" } },
  },
  chapters: [
    {
      chapter_index: 1,
      segments: [
        {
          segment_id: "a",
          role_id: "narrator",
          text: "开头",
          text_kind: "narration",
          speaker: { status: "confirmed" },
        },
        {
          segment_id: "b",
          role_id: "first",
          text: "你好",
          text_kind: "dialogue",
          speaker: { status: "proposed" },
        },
        {
          segment_id: "c",
          role_id: "second",
          text: "再见",
          text_kind: "dialogue",
          speaker: { status: "unknown" },
        },
      ],
    },
  ],
};

describe("角色逐段复核", () => {
  it("同一音色忽略语速和朗读要求；不同克隆参考仍分别显示", () => {
    expect(voiceIdentity("openai", script.roles.first.provider_params)).toBe(
      voiceIdentity("openai", script.roles.narrator.provider_params),
    );
    expect(
      voiceIdentity("openai", {
        voice_mode: "clone",
        reference_audio_sha256: "a",
        speed: 1,
      }),
    ).not.toBe(
      voiceIdentity("openai", {
        voice_mode: "clone",
        reference_audio_sha256: "b",
        speed: 1,
      }),
    );
    expect(
      voiceIdentity("openai", {
        voice_mode: "design",
        voice_description: "温柔  女声",
        speed: 1,
      }),
    ).toBe(
      voiceIdentity("openai", {
        voice_mode: "design",
        voice_description: "温柔 女声",
        speed: 2,
      }),
    );
  });
  it("对白、人物、音色和待复核条件能组合", () => {
    expect(
      reviewSegments(script, 1, "", "", "dialogue").map((s) => s.segment_id),
    ).toEqual(["b", "c"]);
    const voice = voiceIdentity(
      "openai",
      script.roles.narrator.provider_params,
    );
    expect(
      reviewSegments(script, 1, "", voice, "pending").map((s) => s.segment_id),
    ).toEqual(["b"]);
    expect(reviewSegments(script, 1, "second", voice, "all")).toEqual([]);
  });
  it("保存待复核项后进入下一项，最后一项完成后清空", () => {
    const before = reviewSegments(script, 1, "", "", "pending");
    expect(nextReviewSegment(before, before.slice(1), "b")).toBe("c");
    expect(nextReviewSegment(before.slice(1), [], "c")).toBe("");
  });
  it("全部段落模式也前进；上下文跨多个短段拼接", () => {
    const rows = reviewSegments(script, 1);
    expect(nextReviewSegment(rows, rows, "a")).toBe("b");
    expect(segmentContext(rows, "c")).toEqual({
      before: "开头你好",
      after: "",
    });
    expect(segmentContext(rows, "a", 3)).toEqual({
      before: "",
      after: "你好再",
    });
  });
  it("旧英文剧本默认语言从正文恢复", () => {
    expect(
      scriptLanguage({
        chapters: [
          {
            segments: [
              { text: "Please wait beside the bridge until I arrive." },
            ],
          },
        ],
      }),
    ).toBe("en");
    expect(scriptLanguage(script)).toBe("zh");
  });
});

describe("固定试听的页面有效性", () => {
  const project = { id: "project", revision: 4 };
  const task = {
    id: "preview",
    kind: "preview",
    status: "succeeded",
    project_id: "project",
    revision: 4,
    role_id: "first",
    result: { audio: { id: "audio" } },
  };
  it("只允许当前项目、修订和人物的成功试听", () => {
    expect(matchingRolePreview(task, project, "first")).toBe(true);
    expect(matchingRolePreview(task, project, "second")).toBe(false);
    expect(
      matchingRolePreview(task, { ...project, revision: 5 }, "first"),
    ).toBe(false);
    expect(
      matchingRolePreview(task, { ...project, id: "other" }, "first"),
    ).toBe(false);
    expect(
      matchingRolePreview({ ...task, kind: "generate" }, project, "first"),
    ).toBe(false);
    expect(
      matchingRolePreview({ ...task, status: "failed" }, project, "first"),
    ).toBe(false);
    expect(
      matchingRolePreview({ ...task, role_id: null }, project, "first"),
    ).toBe(false);
  });
});
