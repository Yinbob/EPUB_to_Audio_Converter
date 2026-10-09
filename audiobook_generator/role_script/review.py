"""全书人物与段落归属的人工复核操作；不依赖 Gradio。"""
from __future__ import annotations

from dataclasses import replace

from .models import RoleScriptV2


def pending_segments(script: RoleScriptV2) -> list[tuple[str, int, str]]:
    rows = []
    for chapter in script.chapters:
        for segment in chapter.segments:
            if segment.speaker and segment.speaker.status != "confirmed":
                rows.append((segment.segment_id, chapter.chapter_index, segment.text[:72]))
    return rows


def confirm_segment_speaker(script: RoleScriptV2, segment_id: str, entity_id: str) -> RoleScriptV2:
    if entity_id not in script.entities or entity_id not in script.roles:
        raise ValueError("所选人物没有有效的声音配置")
    found = False
    chapters = []
    for chapter in script.chapters:
        segments = []
        for segment in chapter.segments:
            if segment.segment_id == segment_id:
                found = True
                if segment.speaker is None:
                    raise ValueError("段落缺少归属元数据")
                segment = replace(
                    segment, role_id=entity_id,
                    speaker=replace(segment.speaker, entity_id=entity_id, status="confirmed",
                                    confidence=None, confidence_kind="human"),
                )
            segments.append(segment)
        chapters.append(replace(chapter, segments=tuple(segments)))
    if not found:
        raise ValueError("找不到指定段落")
    return replace(script, chapters=tuple(chapters))


def merge_entities(script: RoleScriptV2, source_id: str, target_id: str) -> RoleScriptV2:
    """人工确认同一人后，把源 ID 并入目标 ID；目标声音保持不变。"""
    if source_id == target_id or source_id == "narrator" or target_id == "narrator":
        raise ValueError("只能合并两个不同的非旁白人物")
    if source_id not in script.entities or target_id not in script.entities:
        raise ValueError("待合并的人物不存在")
    if target_id not in script.roles or source_id not in script.roles:
        raise ValueError("待合并的人物缺少声音配置")
    source, target = script.entities[source_id], script.entities[target_id]
    if source.voice_locked and target.voice_locked and (
        script.roles[source_id].provider_params != script.roles[target_id].provider_params
    ):
        raise ValueError("两个已锁定人物的音色不同，请先解除其中一个音色锁")
    alias_map = {alias.text: alias for alias in target.aliases}
    if source.canonical_name != target.canonical_name:
        from .models import AliasRecord
        alias_map.setdefault(source.canonical_name, AliasRecord(source.canonical_name, "confirmed"))
    for alias in source.aliases:
        alias_map.setdefault(alias.text, replace(alias, status="confirmed"))
    entities = dict(script.entities)
    entities[target_id] = replace(target, aliases=tuple(alias_map.values()),
                                  voice_locked=source.voice_locked or target.voice_locked)
    del entities[source_id]
    roles = dict(script.roles)
    del roles[source_id]
    chapters = []
    for chapter in script.chapters:
        segments = []
        for segment in chapter.segments:
            if segment.role_id == source_id:
                speaker = segment.speaker
                if speaker and speaker.entity_id == source_id:
                    speaker = replace(speaker, entity_id=target_id, status="confirmed",
                                      confidence=None, confidence_kind="human")
                segment = replace(segment, role_id=target_id, speaker=speaker)
            segments.append(segment)
        chapters.append(replace(chapter, segments=tuple(segments)))
    return replace(script, entities=entities, roles=roles, chapters=tuple(chapters))


def lock_entity_voice(script: RoleScriptV2, entity_id: str, locked: bool = True) -> RoleScriptV2:
    if entity_id not in script.entities or entity_id not in script.roles:
        raise ValueError("人物不存在或缺少声音配置")
    entities = dict(script.entities)
    entities[entity_id] = replace(entities[entity_id], voice_locked=bool(locked))
    return replace(script, entities=entities)
