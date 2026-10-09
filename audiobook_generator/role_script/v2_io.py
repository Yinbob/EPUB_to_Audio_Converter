"""RoleScriptV2 的严格解析与 JSON 序列化。"""
from __future__ import annotations

import math
from typing import Any, Optional

from .errors import ValidationReport
from .models import (
    AliasRecord, CharacterEntity, ChapterScript, EvidenceSpan, RoleScriptV1,
    RoleScriptV2, SegmentScript, SourceSpan, SpeakerDecision,
)


def _fields(raw: Any, allowed: set[str], required: set[str], path: str, report: ValidationReport) -> bool:
    if not isinstance(raw, dict):
        report.error("invalid_type", path, "必须是 JSON 对象")
        return False
    for name in raw.keys() - allowed:
        report.error("unknown_field", f"{path}.{name}", f"未知字段：{name}")
    for name in required - raw.keys():
        report.error("missing_field", f"{path}.{name}", f"缺少必填字段：{name}")
    return True


def _span(raw: Any, path: str, report: ValidationReport) -> Optional[SourceSpan]:
    if not _fields(raw, {"chapter_index", "start", "end"}, {"chapter_index", "start", "end"}, path, report):
        return None
    values = (raw.get("chapter_index"), raw.get("start"), raw.get("end"))
    if any(type(value) is not int for value in values) or values[0] < 1 or values[1] < 0 or values[2] <= values[1]:
        report.error("invalid_span", path, "原文区间必须是有效的章节号和左闭右开字符偏移")
        return None
    return SourceSpan(*values)


def _confidence(value: Any, path: str, report: ValidationReport) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        report.error("invalid_confidence", path, "置信度必须在 0..1，或为 null")
        return None
    return float(value)


def parse_role_script_v2(raw: Any, report: ValidationReport) -> Optional[RoleScriptV2]:
    """用 V1 结构解析复用现有严格校验，再解析 V2 的人物和证据字段。"""
    from .loader import parse_role_script

    if not _fields(
        raw,
        {"schema_version", "provider", "book_sha256", "default_pause_after_ms", "roles", "chapters",
         "entities", "parser_fingerprint", "chapter_hashes", "registry_complete"},
        {"schema_version", "provider", "book_sha256", "default_pause_after_ms", "roles", "chapters", "entities"},
        "$", report,
    ):
        return None
    if raw.get("schema_version") != 2:
        report.error("unsupported_schema_version", "$.schema_version", "仅支持 schema_version=2")
        return None
    chapters_raw = raw.get("chapters")
    if not isinstance(chapters_raw, list):
        report.error("invalid_type", "$.chapters", "chapters 必须是数组")
        return None
    stripped = {key: raw.get(key) for key in
                ("schema_version", "provider", "book_sha256", "default_pause_after_ms", "roles")}
    stripped["schema_version"] = 1
    stripped["chapters"] = []
    for index, chapter in enumerate(chapters_raw):
        if not isinstance(chapter, dict):
            report.error("invalid_chapter", f"$.chapters[{index}]", "章节必须是对象")
            continue
        segments = chapter.get("segments")
        if not isinstance(segments, list):
            report.error("invalid_segments", f"$.chapters[{index}].segments", "segments 必须是数组")
            continue
        clean_chapter = {key: chapter.get(key) for key in ("chapter_index", "title")}
        clean_chapter["segments"] = [
            {key: segment[key] for key in ("role_id", "text", "tone", "pause_after_ms") if key in segment}
            if isinstance(segment, dict) else segment
            for segment in segments
        ]
        stripped["chapters"].append(clean_chapter)
    base = parse_role_script(stripped, report)
    report.schema_version = 2
    if base is None:
        return None

    entities: dict[str, CharacterEntity] = {}
    raw_entities = raw.get("entities")
    if not isinstance(raw_entities, dict):
        report.error("invalid_entities", "$.entities", "entities 必须是对象")
    else:
        for entity_id, item in raw_entities.items():
            path = f"$.entities.{entity_id}"
            if not isinstance(entity_id, str) or not entity_id or not _fields(
                item, {"canonical_name", "aliases", "voice_profile_id", "voice_locked", "gender"},
                {"canonical_name", "aliases"}, path, report,
            ):
                continue
            aliases = []
            for pos, alias in enumerate(item.get("aliases") if isinstance(item.get("aliases"), list) else []):
                alias_path = f"{path}.aliases[{pos}]"
                if not _fields(alias, {"text", "status", "source_span", "confidence"}, {"text", "status"}, alias_path, report):
                    continue
                if not isinstance(alias.get("text"), str) or not alias["text"].strip() or alias.get("status") not in {"proposed", "confirmed", "rejected"}:
                    report.error("invalid_alias", alias_path, "别名文本或状态无效")
                    continue
                aliases.append(AliasRecord(
                    alias["text"], alias["status"],
                    _span(alias["source_span"], f"{alias_path}.source_span", report) if "source_span" in alias else None,
                    _confidence(alias.get("confidence"), f"{alias_path}.confidence", report),
                ))
            if not isinstance(item.get("aliases"), list):
                report.error("invalid_aliases", f"{path}.aliases", "aliases 必须是数组")
            if not isinstance(item.get("canonical_name"), str) or not item["canonical_name"].strip():
                report.error("invalid_entity_name", f"{path}.canonical_name", "人物名必须是非空字符串")
                continue
            if item.get("voice_profile_id") is not None and not isinstance(item["voice_profile_id"], str):
                report.error("invalid_voice_profile_id", f"{path}.voice_profile_id", "音色配置 ID 必须是字符串")
            if item.get("gender") is not None and (
                not isinstance(item["gender"], str) or item["gender"] not in {"male", "female", "unknown"}
            ):
                report.error("invalid_entity_gender", f"{path}.gender", "人物性别值无效")
            if type(item.get("voice_locked", False)) is not bool:
                report.error("invalid_voice_lock", f"{path}.voice_locked", "voice_locked 必须是布尔值")
                continue
            entities[entity_id] = CharacterEntity(
                canonical_name=item["canonical_name"], aliases=tuple(aliases),
                voice_profile_id=item.get("voice_profile_id"),
                voice_locked=item.get("voice_locked", False), gender=item.get("gender"),
            )

    chapters = []
    for chapter_pos, (chapter, chapter_raw) in enumerate(zip(base.chapters, chapters_raw)):
        segments = []
        for segment_pos, (segment, item) in enumerate(zip(chapter.segments, chapter_raw["segments"])):
            path = f"$.chapters[{chapter_pos}].segments[{segment_pos}]"
            _fields(item, {"role_id", "text", "tone", "pause_after_ms", "segment_id", "source_span", "speaker"},
                    {"role_id", "text", "segment_id", "source_span", "speaker"}, path, report)
            span = _span(item.get("source_span"), f"{path}.source_span", report)
            speaker_raw = item.get("speaker")
            speaker = None
            if _fields(speaker_raw, {"entity_id", "status", "confidence", "evidence", "model", "confidence_kind"},
                       {"entity_id", "status", "confidence", "evidence"}, f"{path}.speaker", report):
                if speaker_raw.get("entity_id") is not None and not isinstance(speaker_raw["entity_id"], str):
                    report.error("invalid_speaker_entity", f"{path}.speaker.entity_id", "人物 ID 必须是字符串或 null")
                if not isinstance(speaker_raw.get("status"), str):
                    report.error("invalid_speaker_status", f"{path}.speaker.status", "归属状态必须是字符串")
                if speaker_raw.get("model") is not None and not isinstance(speaker_raw["model"], str):
                    report.error("invalid_model", f"{path}.speaker.model", "模型名必须是字符串")
                confidence_kind = speaker_raw.get("confidence_kind", "uncalibrated")
                if not isinstance(confidence_kind, str) or confidence_kind not in {"uncalibrated", "calibrated", "human"}:
                    report.error("invalid_confidence_kind", f"{path}.speaker.confidence_kind", "置信度类型无效")
                evidence = []
                if not isinstance(speaker_raw.get("evidence"), list):
                    report.error("invalid_evidence", f"{path}.speaker.evidence", "evidence 必须是数组")
                else:
                    for evidence_pos, evidence_raw in enumerate(speaker_raw["evidence"]):
                        evidence_path = f"{path}.speaker.evidence[{evidence_pos}]"
                        if not _fields(evidence_raw, {"span", "kind", "quote", "relation"},
                                       {"span", "kind", "quote"}, evidence_path, report):
                            continue
                        ev_span = _span(evidence_raw.get("span"), f"{evidence_path}.span", report)
                        if not isinstance(evidence_raw.get("kind"), str) or not isinstance(evidence_raw.get("quote"), str) or not evidence_raw["quote"]:
                            report.error("invalid_evidence", evidence_path, "证据类型与原文引文必须是非空字符串")
                            continue
                        if not isinstance(evidence_raw.get("relation", "said-by"), str):
                            report.error("invalid_evidence_relation", evidence_path, "证据关系必须是字符串")
                            continue
                        if ev_span is not None:
                            evidence.append(EvidenceSpan(ev_span, evidence_raw.get("kind"),
                                                         evidence_raw.get("quote"), evidence_raw.get("relation", "said-by")))
                speaker = SpeakerDecision(
                    speaker_raw.get("entity_id"), speaker_raw.get("status"),
                    _confidence(speaker_raw.get("confidence"), f"{path}.speaker.confidence", report),
                    tuple(evidence), speaker_raw.get("model"),
                    speaker_raw.get("confidence_kind", "uncalibrated"),
                )
            if not isinstance(item.get("segment_id"), str) or not item["segment_id"]:
                report.error("invalid_segment_id", f"{path}.segment_id", "段落 ID 必须是非空字符串")
            segments.append(SegmentScript(segment.role_id, segment.text, segment.tone,
                                          segment.pause_after_ms, item.get("segment_id"), span, speaker))
        chapters.append(ChapterScript(chapter.chapter_index, chapter.title, tuple(segments)))

    hashes = raw.get("chapter_hashes", {})
    if not isinstance(hashes, dict):
        report.error("invalid_chapter_hashes", "$.chapter_hashes", "chapter_hashes 必须是对象")
        hashes = {}
    normalized_hashes = {}
    for key, value in hashes.items():
        if not isinstance(key, str) or not key.isdecimal() or int(key) < 1 or not isinstance(value, str):
            report.error("invalid_chapter_hash", f"$.chapter_hashes.{key}", "章节指纹键和值无效")
        else:
            normalized_hashes[int(key)] = value
    if not isinstance(raw.get("parser_fingerprint", ""), str):
        report.error("invalid_parser_fingerprint", "$.parser_fingerprint", "解析配置指纹必须是字符串")
    if type(raw.get("registry_complete", False)) is not bool:
        report.error("invalid_registry_complete", "$.registry_complete", "registry_complete 必须是布尔值")
    if report.errors:
        return None
    return RoleScriptV2(2, base.provider, base.book_sha256, base.default_pause_after_ms,
                        base.roles, tuple(chapters), entities, raw.get("parser_fingerprint", ""),
                        normalized_hashes, raw.get("registry_complete", False))


def role_script_v2_to_dict(script: RoleScriptV2) -> dict[str, Any]:
    from .deepseek_splitter import role_script_to_dict

    base = RoleScriptV1(1, script.provider, script.book_sha256, script.default_pause_after_ms,
                        script.roles, script.chapters)
    data = role_script_to_dict(base)
    data["schema_version"] = 2
    data["parser_fingerprint"] = script.parser_fingerprint
    data["chapter_hashes"] = {str(key): value for key, value in script.chapter_hashes.items()}
    data["registry_complete"] = script.registry_complete
    data["entities"] = {
        entity_id: {
            "canonical_name": entity.canonical_name,
            "aliases": [{
                "text": alias.text, "status": alias.status,
                **({"source_span": vars(alias.source_span)} if alias.source_span else {}),
                "confidence": alias.confidence,
            } for alias in entity.aliases],
            "voice_profile_id": entity.voice_profile_id,
            "voice_locked": entity.voice_locked,
            "gender": entity.gender,
        } for entity_id, entity in script.entities.items()
    }
    for chapter_dict, chapter in zip(data["chapters"], script.chapters):
        for segment_dict, segment in zip(chapter_dict["segments"], chapter.segments):
            segment_dict.update({
                "segment_id": segment.segment_id,
                "source_span": vars(segment.source_span) if segment.source_span else None,
                "speaker": ({
                    "entity_id": segment.speaker.entity_id,
                    "status": segment.speaker.status,
                    "confidence": segment.speaker.confidence,
                    "evidence": [{"span": vars(ev.span), "kind": ev.kind,
                                  "quote": ev.quote, "relation": ev.relation}
                                 for ev in segment.speaker.evidence],
                    "model": segment.speaker.model,
                    "confidence_kind": segment.speaker.confidence_kind,
                } if segment.speaker else None),
            })
    return data
