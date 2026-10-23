/** 审阅计时只累计前台活动时间，不受系统时钟调整影响。 */
export function activeSeconds(
  start: number,
  end: number,
  visible: boolean,
  paused: boolean,
): number {
  return visible && !paused ? Math.max(0, (end - start) / 1000) : 0;
}

export function applicableChanges(
  proposal: any,
  decisions: Record<string, any>,
): string[] {
  const refs = new Set(
    (proposal?.conflicts || [])
      .filter((c: any) => c.status === "open")
      .flatMap((c: any) => c.refs),
  );
  return (proposal?.changes || [])
    .filter(
      (c: any) =>
        !proposal.applied_segments.includes(c.segment_id) &&
        decisions[c.segment_id]?.status !== "human" &&
        ![
          c.segment_id,
          c.decision?.entity_id,
          ...(c.dependencies || []).map((e: any) => e.upstream_id),
        ].some((ref) => refs.has(ref)),
    )
    .map((c: any) => c.segment_id);
}
