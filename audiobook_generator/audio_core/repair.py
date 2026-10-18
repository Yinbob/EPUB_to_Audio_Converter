"""受限修复动作；不改角色声音，不需要额外文本 LLM。"""
from dataclasses import dataclass


CONTENT_PROMPT_VERSION = "literal-reading-bilingual-v2"
CONTENT_PROMPT_EN = ("Read the supplied body text completely and exactly, including repeated words and sentence beginnings and endings. "
                     "Read only the body text: do not explain, summarize, repeat it, or add an introduction. "
                     "Keep the assigned character voice, tone, and natural rhythm.")
CONTENT_PROMPT = ("本次请逐字核对并完整朗读所给正文，尤其不要省略句首、句尾和相同字词。"
                  "只朗读正文，不解释、不总结、不重复正文，不增加开场白。保持指定角色的声音、语气和自然节奏。")


def content_repair_profile(chunk, default_instructions=None):
    from audiobook_generator.role_script.models import VoiceProfile
    params = dict(chunk.profile)
    base = params.get("instructions", default_instructions)
    from .language import resolve_language
    prompt = CONTENT_PROMPT_EN if resolve_language(chunk.tts_text, chunk.language) == "en" else CONTENT_PROMPT
    params["instructions"] = "\n".join(value for value in (base, prompt) if value)
    return VoiceProfile(chunk.role_id, chunk.role_id, params, tone=chunk.tone)


def split_repair_chunk(chunk, *, dictionary=None):
    """只在原文映射可重建的标点处拆为两块，不切开规范化词条。"""
    import re
    from dataclasses import replace
    from .reading import normalize_reading_text
    text, mapping, _ = normalize_reading_text(chunk.source_text, dictionary=dictionary, language=chunk.language)
    if text != chunk.tts_text or len(text) < 40:
        return ()
    from .language import split_positions
    candidates = [cut for cut in split_positions(text, clauses=True)
                  if 12 <= cut <= len(text) - 12 and mapping[cut - 1] != mapping[cut]]
    if not candidates:
        return ()
    cut = min(candidates, key=lambda value: (abs(value - len(text) / 2), value))
    children = []
    for index, (start, end) in enumerate(((0, cut), (cut, len(text))), 1):
        source_start, source_end = mapping[start][0], mapping[end - 1][1]
        unit_start, unit_end = chunk.source_start + source_start, chunk.source_start + source_end
        children.append(replace(chunk, chunk_id=f"{chunk.chunk_id}:repair_part:{index}",
            source_text=chunk.source_text[source_start:source_end], tts_text=text[start:end],
            source_start=unit_start, source_end=unit_end, sequence_index=index, pause_after_ms=0,
            boundary_kind="repair_continuation" if index == 1 else chunk.boundary_kind,
            edits=tuple(e for e in chunk.edits if e["source_start"] < unit_end and e["source_end"] > unit_start),
            source_span={**chunk.source_span, "start": chunk.source_span["start"] + source_start,
                         "end": chunk.source_span["start"] + source_end} if chunk.source_span else None))
    return tuple(children)


@dataclass(frozen=True)
class RepairAction:
    kind: str
    reason: str
    speed_factor: float = 1.0
    edge: str = ""
    keep_silence_ms: float = 20.0


def propose_actions(report, *, max_rate=4.3, edge=None):
    codes = {issue.code for issue in report.issues}
    actions = []
    if edge in {"head", "tail"}:
        if "unexpected_gap" in codes:
            pause = report.metrics.get("features", {}).get("planned_pause_seconds", 0)
            actions.append(RepairAction("local_trim_silence", "unexpected_gap", edge=edge,
                                        keep_silence_ms=max(20, pause * 500)))
        if "boundary_click_suspected" in codes:
            actions.append(RepairAction("local_edge_fade", "boundary_click_suspected", edge=edge))
    if "too_fast" in codes:
        max_rate = report.metrics.get("rate_threshold") or max_rate
        rate = report.metrics.get("articulation_rate") or max_rate
        actions.append(RepairAction("local_speed", "too_fast", max(1 / 1.05, min(1 / 1.01, max_rate / rate))))
    if "asr_mismatch" in codes:
        actions.append(RepairAction("content_repair", "asr_mismatch"))
    if codes & {"empty_audio", "too_quiet", "clipping", "speaker_drift",
                "cutoff_suspected", "overlap", "boundary_click_suspected", "boundary_content_mismatch", "unexpected_gap"}:
        actions.append(RepairAction("resample", ",".join(sorted(codes))))
    return actions
