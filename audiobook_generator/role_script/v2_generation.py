"""全书人物索引与带原文证据的自动剧本升级。"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any, Callable, Optional, Sequence

from . import deepseek_splitter as splitter
from .models import (
    AliasRecord, CharacterEntity, ChapterScript, EvidenceSpan, RoleScriptV1,
    RoleScriptV2, SegmentScript, SourceSpan, SpeakerDecision,
)
from .normalization import normalize_coverage_text
from .project_store import chapter_hashes
from .validator import validate_role_script
from .narration import ground_narration_segments

ProgressCallback = Optional[Callable[[str], None]]


def _new_entity_id() -> str:
    return "char_" + uuid.uuid4().hex[:12]


def _unique_span(text: str, quote: str, chapter_index: int, *, near: Optional[int] = None) -> Optional[SourceSpan]:
    if not quote or quote not in text:
        return None
    starts = []
    cursor = 0
    while True:
        cursor = text.find(quote, cursor)
        if cursor < 0:
            break
        starts.append(cursor)
        cursor += 1
    if near is None:
        return SourceSpan(chapter_index, starts[0], starts[0] + len(quote)) if len(starts) == 1 else None
    ranked = sorted(starts, key=lambda value: abs(value - near))
    if len(ranked) > 1 and abs(ranked[0] - near) == abs(ranked[1] - near):
        return None
    if abs(ranked[0] - near) > 600:
        return None
    return SourceSpan(chapter_index, ranked[0], ranked[0] + len(quote))


def _known_name_matches(entities: dict[str, CharacterEntity], name: str) -> list[str]:
    return [
        entity_id for entity_id, entity in entities.items()
        if name == entity.canonical_name or any(
            alias.text == name and alias.status == "confirmed" for alias in entity.aliases
        )
    ]


def _request_character_chunk(client: Any, model: str, chapter_index: int, text: str,
                             cards: dict[str, CharacterEntity]) -> list[dict[str, Any]]:
    summary = [
        {"entity_id": entity_id, "name": entity.canonical_name,
         "aliases": [alias.text for alias in entity.aliases if alias.status == "confirmed"]}
        for entity_id, entity in list(cards.items())[-30:] if entity_id != "narrator"
    ]
    prompt = (
        "从这段小说原文提取出现过的角色及原文称呼。返回 JSON 对象 characters 数组，"
        "每项包含 name、aliases（原文中实际出现的称呼）、evidence_quote（包含名字的原文短引文），"
        "可选 existing_entity_id（仅明确与已知角色为同一人物时填写）。只使用原文中能找到的称呼，"
        "不要猜测别名、性别或改写文字。已知人物卡片："
        + json.dumps(summary, ensure_ascii=False)
        + f"\n章节：{chapter_index}\n原文：\n{text}"
    )
    response = client.chat.completions.create(
        model=(model or "deepseek-chat").strip() or "deepseek-chat",
        messages=[{"role": "system", "content": "你是小说人物索引器，只返回 JSON。"},
                  {"role": "user", "content": prompt}],
        response_format={"type": "json_object"}, temperature=0, max_tokens=4096,
    )
    payload = splitter._extract_json_object(response.choices[0].message.content)
    items = payload.get("characters")
    if not isinstance(items, list):
        raise ValueError("全书人物索引未返回 characters 数组")
    return [item for item in items if isinstance(item, dict)]


def build_book_registry(
    chapters: Sequence[tuple[str, str]], *, api_key: str, base_url: str,
    model: str, previous: Optional[RoleScriptV2] = None,
    progress: ProgressCallback = None, chapter_start: int = 1, chapter_end: Optional[int] = None,
) -> dict[str, CharacterEntity]:
    """只扫描明确指定的章节；保留原书章号与证据区间。"""
    chapter_end = len(chapters) if chapter_end is None else chapter_end
    if (type(chapter_start) is not int or type(chapter_end) is not int
            or not 1 <= chapter_start <= chapter_end <= len(chapters)):
        raise ValueError("人物索引章节范围无效")
    if not api_key or not api_key.strip():
        raise ValueError("全书人物索引需要 DeepSeek API Key")
    client = splitter._create_client(api_key, base_url)
    entities = dict(previous.entities) if previous else {}
    entities.setdefault("narrator", CharacterEntity("旁白", voice_profile_id="voice_narrator", voice_locked=True))
    for chapter_index in range(chapter_start, chapter_end + 1):
        _title, text = chapters[chapter_index - 1]
        cursor = 0
        for part in splitter._split_text_chunks(text):
            part_start = cursor
            cursor += len(part)
            if not splitter._has_visible_text(part):
                continue
            if progress:
                progress(f"正在建立人物表：第 {chapter_index} 章（范围 {chapter_start}～{chapter_end}）")
            for raw in _request_character_chunk(client, model, chapter_index, part, entities):
                name = raw.get("name")
                if not isinstance(name, str) or not name.strip() or name not in part:
                    continue
                name = name.strip()
                matches = _known_name_matches(entities, name)
                entity_id = (matches[0] if len(matches) == 1 else None)
                # 模型的 existing_entity_id 只是候选，不能据此把两个人物自动合并。
                # 未经人工确认的同名/别名冲突保留为独立实体，交给复核入口处理。
                if entity_id is None:
                    entity_id = _new_entity_id()
                    entities[entity_id] = CharacterEntity(name)
                entity = entities[entity_id]
                names = [name]
                if isinstance(raw.get("aliases"), list):
                    names += [alias for alias in raw["aliases"] if isinstance(alias, str) and alias.strip()]
                old_aliases = {alias.text: alias for alias in entity.aliases}
                quote = raw.get("evidence_quote")
                for alias_text in names:
                    if alias_text not in part or alias_text == entity.canonical_name or alias_text in old_aliases:
                        continue
                    local_span = _unique_span(part, alias_text, chapter_index)
                    span = (SourceSpan(chapter_index, part_start + local_span.start, part_start + local_span.end)
                            if local_span else None)
                    old_aliases[alias_text] = AliasRecord(alias_text, "proposed", span)
                # 引文必须确实来自此块；否则该候选名仍留待复核，不赋予证据区间。
                if isinstance(quote, str) and quote and quote not in part:
                    continue
                entities[entity_id] = replace(entity, aliases=tuple(old_aliases.values()))
    return entities


def _exact_segments(source: str, segments: Sequence[SegmentScript], chapter_index: int) -> list[tuple[SegmentScript, SourceSpan]]:
    normalized, source_map = splitter._normalized_with_source_map(source)
    if "".join(normalize_coverage_text(item.text) for item in segments) != normalized:
        raise ValueError(f"第 {chapter_index} 章分段无法与原文逐字对齐")
    boundaries = [0]
    cursor = 0
    for segment in segments[:-1]:
        cursor += len(normalize_coverage_text(segment.text))
        boundaries.append(source_map[cursor] if cursor < len(source_map) else len(source))
    boundaries.append(len(source))
    if any(end <= start for start, end in zip(boundaries, boundaries[1:])):
        raise ValueError(f"第 {chapter_index} 章存在无法落在原文字符边界上的分段")
    return [
        (replace(segment, text=source[start:end]), SourceSpan(chapter_index, start, end))
        for segment, start, end in zip(segments, boundaries, boundaries[1:])
    ]


def _segment_evidence(segment: SegmentScript, span: SourceSpan, source: str) -> tuple[EvidenceSpan, ...]:
    found = []
    for quote, kind in segment.evidence_candidates:
        match = _unique_span(source, quote, span.chapter_index,
                             near=None if kind == 'narrator_identity' else span.start)
        if match is not None:
            found.append(EvidenceSpan(match, kind, quote))
    return tuple(found)


def upgrade_generated_script(
    generated: RoleScriptV1, chapters: Sequence[tuple[str, str]],
    entities: dict[str, CharacterEntity], *, parser_fingerprint: str,
    model: str, previous: Optional[RoleScriptV2] = None, registry_complete: bool = True,
) -> RoleScriptV2:
    """将已对齐的 V1 提议转为含稳定实体 ID、原文区间与证据的 V2。"""
    roles = dict(previous.roles) if previous else {}
    mapping = {"narrator": "narrator"}
    roles["narrator"] = roles.get("narrator", generated.roles["narrator"])
    for raw_id, role in generated.roles.items():
        if raw_id == "narrator":
            continue
        matches = _known_name_matches(entities, role.display_name)
        entity_id = matches[0] if len(matches) == 1 else _new_entity_id()
        if entity_id not in entities:
            entities[entity_id] = CharacterEntity(role.display_name)
        mapping[raw_id] = entity_id
        # 已确认的音色配置优先；新人物使用本次选角结果。
        roles.setdefault(entity_id, role)
        entity = entities[entity_id]
        if entity.voice_profile_id is None:
            entities[entity_id] = replace(entity, voice_profile_id=f"voice_{entity_id}")

    output_chapters = []
    previous_chapters = {chapter.chapter_index: chapter for chapter in previous.chapters} if previous else {}
    for chapter in generated.chapters:
        source = chapters[chapter.chapter_index - 1][1]
        segments = []
        grounded_segments = ground_narration_segments(chapter.segments, source)
        for offset, (segment, span) in enumerate(_exact_segments(source, grounded_segments, chapter.chapter_index), 1):
            entity_id = mapping[segment.role_id]
            evidence = _segment_evidence(segment, span, source)
            quoted_unknown = segment.role_id == "narrator" and (
                "“" in segment.text or '"' in segment.text or "「" in segment.text
            )
            narration_unknown = segment.text_kind in ('narration', 'unknown') and entity_id == 'narrator'
            if narration_unknown:
                status, speaker_id, raw_score = 'needs_review', 'narrator', 0.0
            else:
                status = 'unknown' if quoted_unknown else ('proposed' if entity_id != 'narrator' else 'confirmed')
                speaker_id = None if quoted_unknown else entity_id
                raw_score = (0.82 if evidence else 0.55) if entity_id != 'narrator' else (0.0 if quoted_unknown else 0.95)
            updated = replace(
                segment,
                role_id=entity_id,
                segment_id=f"ch{chapter.chapter_index:06d}_s{offset:05d}",
                source_span=span,
                speaker=SpeakerDecision(speaker_id, status, raw_score, evidence, model, "uncalibrated"),
                evidence_candidates=(),
            )
            # 原文区间和文字未变时保留人工确认；章节重拆不应撤销用户校对。
            for old in previous_chapters.get(chapter.chapter_index, ChapterScript(chapter.chapter_index, chapter.title)).segments:
                if (old.source_span == span and old.text == updated.text and old.speaker
                        and old.speaker.status == 'confirmed' and old.speaker.confidence_kind == 'human'):
                    updated = replace(updated, role_id=old.role_id, speaker=old.speaker)
                    break
            segments.append(updated)
        output_chapters.append(ChapterScript(chapter.chapter_index, chapter.title, tuple(segments)))
    selected = {chapter.chapter_index: chapter for chapter in output_chapters}
    if previous and previous.parser_fingerprint == parser_fingerprint and previous.chapter_hashes == chapter_hashes(chapters):
        for chapter in previous.chapters:
            selected.setdefault(chapter.chapter_index, chapter)
    result = RoleScriptV2(
        schema_version=2, provider=generated.provider, book_sha256=generated.book_sha256,
        default_pause_after_ms=generated.default_pause_after_ms, roles=roles,
        chapters=tuple(selected[index] for index in sorted(selected)), entities=entities,
        parser_fingerprint=parser_fingerprint, chapter_hashes=chapter_hashes(chapters),
        registry_complete=registry_complete,
    )
    validation = validate_role_script(
        result, chapters=chapters, expected_book_sha256=generated.book_sha256,
        chapter_start=generated.chapters[0].chapter_index,
        chapter_end=generated.chapters[-1].chapter_index,
    )
    if not validation.ok:
        raise ValueError(f"RoleScriptV2 生成后校验失败：{validation.report.to_dict()}")
    return validation.script


def generate_v2_for_book(
    chapters: Sequence[tuple[str, str]], chapter_start: int, chapter_end: int,
    provider: str, book_sha256: str, api_key: str, base_url: str, model: str,
    *, parser_fingerprint: str, previous: Optional[RoleScriptV2] = None,
    progress: ProgressCallback = None, index_full_book: bool = True,
) -> RoleScriptV2:
    """按明确范围索引、拆分并复用声音；局部索引不标为完整全书索引。"""
    if type(index_full_book) is not bool:
        raise ValueError("index_full_book 必须为布尔值")
    if (type(chapter_start) is not int or type(chapter_end) is not int
            or not 1 <= chapter_start <= chapter_end <= len(chapters)):
        raise ValueError("章节范围无效")
    registry_complete = index_full_book or (chapter_start == 1 and chapter_end == len(chapters))
    current_hashes = chapter_hashes(chapters)
    compatible = bool(previous and previous.parser_fingerprint == parser_fingerprint
                      and previous.chapter_hashes == current_hashes)
    if compatible and previous.registry_complete:
        entities = dict(previous.entities)
        registry_complete = True
        if progress:
            progress("已复用全书人物索引")
    else:
        baseline = previous
        if previous and not compatible:
            cleaned = {
                entity_id: replace(entity, aliases=tuple(replace(alias, source_span=None)
                                                         for alias in entity.aliases))
                for entity_id, entity in previous.entities.items()
            }
            baseline = replace(previous, entities=cleaned, chapters=(), chapter_hashes={})
        entities = build_book_registry(chapters, api_key=api_key, base_url=base_url,
                                       model=model, previous=baseline, progress=progress,
                                       chapter_start=1 if index_full_book else chapter_start,
                                       chapter_end=len(chapters) if index_full_book else chapter_end)
    generated = splitter.split_chapters_with_deepseek(
        list(chapters), chapter_start, chapter_end, provider, book_sha256,
        api_key, base_url, model, progress=progress, analyze_narration=True,
        known_characters=[{'role_id': entity_id, 'display_name': entity.canonical_name,
                           'aliases': [alias.text for alias in entity.aliases if alias.status == 'confirmed']}
                          for entity_id, entity in list(entities.items())[-30:] if entity_id != 'narrator'],
    )
    if previous and previous.provider != provider:
        previous = replace(previous, roles={}, entities={
            entity_id: replace(entity, voice_profile_id=None, voice_locked=False)
            for entity_id, entity in previous.entities.items()
        })
    if previous and not compatible:
        previous = replace(previous, chapters=(), chapter_hashes={})
    return upgrade_generated_script(
        generated, chapters, entities, parser_fingerprint=parser_fingerprint,
        model=model, previous=previous, registry_complete=registry_complete,
    )
