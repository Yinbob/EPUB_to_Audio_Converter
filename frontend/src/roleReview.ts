/** 人物核对共用纯函数：音色身份与语速、朗读要求分别处理。 */
export function voiceIdentity(provider: string, params: any): string {
  const mode = params.voice_mode || "preset";
  const identity =
    mode === "clone"
      ? params.reference_audio_sha256 ||
        params.reference_audio_path ||
        params.voice_profile_id
      : mode === "design"
        ? String(params.voice_description || "")
            .trim()
            .replace(/\s+/g, " ")
        : provider === "minimax"
          ? params.voice_id || params.voice
          : params.voice || params.voice_id;
  return JSON.stringify([provider, mode, identity || ""]);
}

export function voiceLabel(params: any): string {
  if (params.voice_mode === "clone") return "参考音克隆";
  if (params.voice_mode === "design")
    return `描述声音 · ${String(params.voice_description || "").slice(0, 36)}`;
  return params.voice || params.voice_id || "未指定声音";
}

export function reviewSegments(
  script: any,
  chapter: number,
  person = "",
  voice = "",
  scope = "all",
): any[] {
  const rows =
    script?.chapters?.find((c: any) => c.chapter_index === chapter)?.segments ||
    [];
  return rows.filter(
    (s: any) =>
      (!person || s.role_id === person) &&
      (!voice ||
        voiceIdentity(
          script.provider,
          script.roles[s.role_id]?.provider_params || {},
        ) === voice) &&
      (scope !== "pending" || s.speaker?.status !== "confirmed") &&
      (scope !== "dialogue" || s.text_kind === "dialogue"),
  );
}

export function segmentContext(
  segments: any[],
  segmentId: string,
  limit = 300,
): { before: string; after: string } {
  const index = segments.findIndex((s) => s.segment_id === segmentId);
  if (index < 0) return { before: "", after: "" };
  return {
    before: segments
      .slice(0, index)
      .map((s) => s.text)
      .join("")
      .slice(-limit),
    after: segments
      .slice(index + 1)
      .map((s) => s.text)
      .join("")
      .slice(0, limit),
  };
}

export function nextReviewSegment(
  before: any[],
  after: any[],
  selected: string,
): string {
  const index = before.findIndex((s) => s.segment_id === selected);
  const remaining = new Set(after.map((s) => s.segment_id));
  return (
    before.slice(index + 1).find((s) => remaining.has(s.segment_id))
      ?.segment_id ||
    after.find((s) => s.segment_id !== selected)?.segment_id ||
    ""
  );
}

export function matchingRolePreview(
  task: any,
  project: any,
  roleId: string,
): boolean {
  return !!(
    task?.kind === "preview" &&
    task.status === "succeeded" &&
    task.result?.audio &&
    project &&
    task.project_id === project.id &&
    task.revision === project.revision &&
    task.role_id === roleId
  );
}

export function scriptLanguage(script: any): string {
  const text = (script?.chapters || [])
    .flatMap((c: any) => c.segments || [])
    .map((s: any) => s.text)
    .join("")
    .slice(0, 50000);
  const chinese = (text.match(/[\u3400-\u9fff]/g) || []).length;
  const latin = (text.match(/[A-Za-z]/g) || []).length;
  if (chinese >= 20 && chinese * 2 >= latin) return "zh";
  if (latin >= 20 && latin >= chinese * 4) return "en";
  return chinese >= latin ? "zh" : "en";
}
