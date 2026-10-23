"""章节叙述者候选：只提供给分段模型参考，不直接覆盖整章归属。"""
from __future__ import annotations

import json
import re
from audiobook_generator.utils.deepseek_config import deepseek_completion_options


def source_name_match(name, source, *, case_sensitive=False):
    """返回带单词边界的原文匹配，供调用方恢复原文大小写。"""
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    left = r'(?<![A-Za-z0-9_])' if name[0].isascii() and name[0].isalnum() else ''
    right = r'(?![A-Za-z0-9_])' if name[-1].isascii() and name[-1].isalnum() else ''
    return re.search(left + re.escape(name) + right, source,
                     0 if case_sensitive else re.IGNORECASE)


def name_in_source(name, source, *, case_sensitive=False):
    """英文短名不能命中另一单词的内部。"""
    return source_name_match(name, source, case_sensitive=case_sensitive) is not None


def grounded_entities(entities, chapters):
    """旧人物库不自动成为事实：原名或人工确认的别名必须出现于本书正文。"""
    sources = [text for _title, text in chapters]
    return {key: entity for key, entity in entities.items() if key == 'narrator' or any(
        name_in_source(name, source)
        for name in [entity.canonical_name] + [a.text for a in entity.aliases if a.status == 'confirmed']
        for source in sources)}


def local_character_hint(person, source):
    """全书人物存在不代表本章叙述者；别名由调用方限定为人工确认项。"""
    return any(name_in_source(name, source)
               for name in [person.get('display_name'), *person.get('aliases', [])])


def request_narration_context(client, model, chapter_index, title, source, known_characters):
    """按上下文预算扫描整章；各块独立提供身份原文证据。"""
    from .deepseek_splitter import _extract_json_object

    from .context_budget import completion, output_tokens, context_tokens, relevant_cards, ContextLimit, TruncatedCompletion, split_middle
    excerpt = source
    known_characters = relevant_cards(known_characters, source, limit=min(2048, context_tokens() // 8))
    def validate_content(content):
        value = _extract_json_object(content)
        if value.get('perspective') not in ('character', 'third_person', 'mixed', 'unknown'):
            raise ValueError('叙述视角分析未返回有效类型')
        if not isinstance(value.get('narrators'), list):
            raise ValueError('叙述视角分析未返回 narrators 数组')
        # 不可信候选仍由下面的证据过滤处理，但不能成为成功断点。
        for person in value['narrators']:
            if not isinstance(person, dict) or not isinstance(person.get('evidence'), list):
                return False
            name, role_id = person.get('display_name'), person.get('role_id')
            known = next((p for p in known_characters if p.get('role_id') == role_id), None)
            if not name_in_source(name, source) and not (known and local_character_hint(known, source)):
                return False
            if not any(isinstance(evidence, dict) and isinstance(evidence.get('quote'), str)
                       and evidence['quote'].strip() and source.count(evidence['quote']) == 1
                       for evidence in person['evidence']):
                return False
        return True
    prompt = '''识别这章小说的叙述视角，只返回JSON，不改写原文。
第一人称自述/回忆/内心叙述仍属于narration，声音身份可以是人物，不能一律分配默认旁白。
区分“谁在叙述”和“正在描写谁”：第三人称聚焦、自由间接引语、引号内的I/我均不能单独证明叙述者身份。
仅凭当前章原文中的自称、他人对叙述者的称呼及关系等语义证据判断；禁止根据书名、章节奇偶、文学常识猜测。
每章可能切换视角，不继承上一章。身份不明、多人视角或第三人称请如实标记。
返回 {"perspective":"character|third_person|mixed|unknown","narrators":[
{"role_id":"人物ID","display_name":"人物名称","gender":"male|female|unknown",
"evidence":[{"quote":"正文中逐字出现且能支持身份的短引文","kind":"narrator_identity"}]}]}。
同一人的自述和对白必须使用同一role_id及名称；已知人物表仅供身份匹配，不能当成本章视角证据。
人名必须逐字出现在正文，或严格复用已知人物的名称及ID；不得补写正文未出现的全名、编造姓名。
全书出现过的人名不能证明本章的I/我是谁：本章需出现其姓名或已确认别名，并给出与叙述者相连的身份线索。
证据不足返回空narrators；不要返回分段正文。'''
    if context_tokens() < 8192:
        prompt = ('Identify narrative perspective using ONLY source evidence. Return JSON '
                  '{"perspective":"character|third_person|mixed|unknown","narrators":'
                  '[{"role_id":"id","display_name":"verbatim name","gender":"male|female|unknown",'
                  '"evidence":[{"quote":"verbatim identity evidence","kind":"narrator_identity"}]}]}. '
                  'Who narrates differs from who is described. Quoted I does not identify narrator. '
                  'Never infer by title or chapter order. Match known identity only with local evidence. '
                  'No evidence: empty narrators. Do not emit segment text.')
    try:
        content = completion(client,
        validator=validate_content,
        **deepseek_completion_options(model), temperature=0, max_tokens=output_tokens(2048),
        response_format={'type': 'json_object'},
        messages=[{'role': 'system', 'content': '你是有声书叙述视角分析器。只输出JSON。'},
                  {'role': 'user', 'content': prompt + '\n已知人物：' + json.dumps(known_characters, ensure_ascii=False)
                   + f'\n章节：{chapter_index} {title[:256]}\n原文：\n{excerpt}'}],
    )
    except (ContextLimit, TruncatedCompletion):
        if len(source) <= 64:
            raise
        parts = [request_narration_context(client, model, chapter_index, title, part, known_characters)
                 for part in split_middle(source)]
        people = {}
        for part in parts:
            for person in part.get('narrators', []):
                key = person['role_id']
                if key in people:
                    people[key]['evidence'].extend(person['evidence'])
                else:
                    people[key] = person
        perspectives = {p['perspective'] for p in parts}
        return {'perspective': next(iter(perspectives)) if len(perspectives) == 1 else 'mixed', 'narrators': list(people.values())}
    raw = _extract_json_object(content)
    perspective = raw.get('perspective')
    if perspective not in ('character', 'third_person', 'mixed', 'unknown'):
        raise ValueError('叙述视角分析未返回有效类型')
    candidates = []
    items = raw.get('narrators')
    for item in items[:6] if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        role_id, name = item.get('role_id'), item.get('display_name')
        if (not isinstance(role_id, str) or role_id.lower() == 'narrator'
                or not re.fullmatch(r'[^\s/\\]{1,64}', role_id)
                or not isinstance(name, str) or not 1 <= len(name.strip()) <= 64):
            continue
        known = next((person for person in known_characters if person.get('role_id') == role_id), None)
        if known and name.strip() not in [known.get('display_name'), *known.get('aliases', [])]:
            continue
        if not name_in_source(name, source) and not (known and local_character_hint(known, source)):
            continue
        evidence = []
        for ev in item.get('evidence', []) if isinstance(item.get('evidence'), list) else []:
            quote = ev.get('quote') if isinstance(ev, dict) else None
            if isinstance(quote, str) and quote.strip() and len(quote) <= 400 and source.count(quote) == 1:
                evidence.append({'quote': quote, 'kind': 'narrator_identity'})
        if evidence:
            gender = item.get('gender')
            candidates.append({'role_id': role_id, 'display_name': name.strip(),
                               'gender': gender if gender in ('male', 'female') else 'unknown',
                               'evidence': evidence[:3]})
    return {'perspective': perspective,
            'narrators': candidates if perspective in ('character', 'mixed') else []}


def complete_narration_evidence(segments, source, context):
    """复用本章已定位的身份线索，只补证据，不替模型选择说话人。"""
    from dataclasses import replace

    chapter_context = context.get('chapter_narration', {})
    if chapter_context.get('perspective') not in ('character', 'mixed'):
        return list(segments)
    candidates = {}
    for item in chapter_context.get('narrators', []):
        role_id = item.get('role_id')
        if not role_id or role_id == 'narrator':
            continue
        evidence = [(ev['quote'], 'narrator_identity') for ev in item.get('evidence', [])
                    if isinstance(ev.get('quote'), str) and ev['quote'].strip()
                    and len(ev['quote']) <= 400 and source.count(ev['quote']) == 1]
        candidates.setdefault(role_id, []).extend(evidence)
    result = []
    for segment in segments:
        if segment.text_kind == 'narration' and segment.role_id in candidates:
            valid = any(kind == 'narrator_identity' and source.count(quote) == 1
                        for quote, kind in segment.evidence_candidates)
            if not valid:
                segment = replace(segment, evidence_candidates=segment.evidence_candidates
                                  + tuple(dict.fromkeys(candidates[segment.role_id]))[:3])
        result.append(segment)
    return result


def ground_narration_segments(segments, source):
    """无可定位身份引文的人物叙述退回默认旁白，保留类型以待人工复核。"""
    from dataclasses import replace

    result = []
    for segment in segments:
        if segment.text_kind == 'narration' and segment.role_id != 'narrator':
            evidence = tuple((quote, kind) for quote, kind in segment.evidence_candidates
                             if kind == 'narrator_identity' and source.count(quote) == 1)
            segment = replace(segment, evidence_candidates=evidence)
            if not evidence:
                segment = replace(segment, role_id='narrator')
        result.append(segment)
    return result
