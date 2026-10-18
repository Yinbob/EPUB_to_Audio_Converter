"""章节叙述者候选：只提供给分段模型参考，不直接覆盖整章归属。"""
from __future__ import annotations

import json
import re


def request_narration_context(client, model, chapter_index, title, source, known_characters):
    """每章一次身份分析；长章只取首尾，缺失的中段仍由分段模型判断。"""
    from .deepseek_splitter import _extract_json_object

    excerpt = source if len(source) <= 24000 else source[:12000] + '\n[中段未提供；不得推断中段视角]\n' + source[-12000:]
    prompt = '''识别这章小说的叙述视角，只返回JSON，不改写原文。
第一人称自述/回忆/内心叙述仍属于narration，声音身份可以是人物，不能一律分配默认旁白。
区分“谁在叙述”和“正在描写谁”：第三人称聚焦、自由间接引语、引号内的I/我均不能单独证明叙述者身份。
仅凭当前章原文中的自称、他人对叙述者的称呼及关系等语义证据判断；禁止根据书名、章节奇偶、文学常识猜测。
每章可能切换视角，不继承上一章。身份不明、多人视角或第三人称请如实标记。
返回 {"perspective":"character|third_person|mixed|unknown","narrators":[
{"role_id":"人物ID","display_name":"人物名称","gender":"male|female|unknown",
"evidence":[{"quote":"正文中逐字出现且能支持身份的短引文","kind":"narrator_identity"}]}]}。
同一人的自述和对白必须使用同一role_id及名称；已知人物表仅供身份匹配，不能当成本章视角证据。
证据不足返回空narrators；不要返回分段正文。'''
    response = client.chat.completions.create(
        model=model or 'deepseek-chat', temperature=0, max_tokens=2048,
        response_format={'type': 'json_object'},
        messages=[{'role': 'system', 'content': '你是有声书叙述视角分析器。只输出JSON。'},
                  {'role': 'user', 'content': prompt + '\n已知人物：' + json.dumps(known_characters, ensure_ascii=False)
                   + f'\n章节：{chapter_index} {title}\n原文：\n{excerpt}'}],
    )
    raw = _extract_json_object(response.choices[0].message.content)
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
