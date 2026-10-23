"""研究快照校验、来源绑定与稳定摘要。"""
import hashlib
import json
from copy import deepcopy
from .research_models import ResearchState


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def segments(state):
    return {s['segment_id']: s for c in state['script']['chapters'] for s in c['segments']}


def input_digest(state):
    return digest({'script': state['script'], 'sources': state['sources'],
                   'claims': state['claims'], 'decisions': state['decisions']})


def confirmation_digest(state):
    return digest({'script': state['script'], 'claims': state['claims'],
                   'unconfigured_entities': state['unconfigured_entities']})


def create_state(key, revision, script):
    if script['schema_version'] != 2:
        raise ValueError('研究审阅需要 V2 剧本，请先重新拆分。')
    state = ResearchState(id=key, revision=revision + 1, script=deepcopy(script), sources={}).model_dump()
    for chapter in script['chapters']:
        text = ''
        for segment in chapter['segments']:
            span = segment['source_span']
            if span['start'] != len(text) or span['end'] - span['start'] != len(segment['text']):
                raise ValueError('研究审阅需要完整且连续的原文区间，请重新拆分。')
            text += segment['text']
            speaker = segment['speaker']
            human = speaker['status'] == 'confirmed' and speaker.get('confidence_kind') == 'human'
            sid = segment['segment_id']
            state['decisions'][sid] = {'id': sid, 'segment_id': sid,
                'entity_id': speaker.get('entity_id'), 'candidates': [segment['role_id']],
                'evidence': deepcopy(speaker.get('evidence', [])), 'against': [],
                'status': 'human' if human else ('unknown' if speaker.get('entity_id') is None else 'proposed'),
                'analyzer_version': 'legacy'}
        expected = script.get('chapter_hashes', {}).get(str(chapter['chapter_index']))
        if expected and hashlib.sha256(text.encode()).hexdigest() != expected:
            raise ValueError('剧本正文摘要不匹配，不能建立研究快照。')
        state['sources'][str(chapter['chapter_index'])] = text
    return validate_state(state)


def validate_evidence(evidence, sources):
    for item in evidence:
        span = item.get('span', {})
        chapter, start, end = span.get('chapter_index'), span.get('start'), span.get('end')
        if any(type(n) is not int for n in (chapter, start, end)):
            raise ValueError('原文证据坐标无效。')
        text = sources.get(str(chapter), '')
        if not 0 <= start < end <= len(text) or text[start:end] != item.get('quote'):
            raise ValueError('原文证据越界或引文不匹配。')


def validate_state(raw):
    state = ResearchState.model_validate(raw).model_dump()
    from audiobook_generator.services.projects import decode
    decode(state['script'])
    from .dependency_index import validate_dependencies
    rows = segments(state)
    entities = state['script']['entities']
    if set(rows) != set(state['decisions']):
        raise ValueError('研究判断必须完整覆盖固定分段。')
    if set(state['claims']) & (set(rows) | set(entities)):
        raise ValueError('关系 ID 与已有记录冲突。')
    for chapter in state['script']['chapters']:
        text = state['sources'].get(str(chapter['chapter_index']))
        if text is None:
            raise ValueError('缺少研究项目原文。')
        for s in chapter['segments']:
            span = s['source_span']
            if text[span['start']:span['end']] != s['text']:
                raise ValueError('研究项目的片段与原文不匹配。')
    for key, mention in state['mentions'].items():
        if key != mention['id']:
            raise ValueError('提及 ID 不匹配。')
        validate_evidence([{'span': mention['span'], 'quote': mention['text']}], state['sources'])
    for key, claim in state['claims'].items():
        if key != claim['id'] or claim['entity_id'] not in entities:
            raise ValueError('身份关系引用未知人物。')
        if claim['kind'] in ('same_entity', 'distinct_entity') and claim['subject'] not in entities:
            raise ValueError('身份关系引用未知人物。')
        if claim['kind'] == 'mention_entity' and claim['subject'] not in state['mentions']:
            raise ValueError('身份关系引用未知提及。')
        scope = claim['scope']
        if scope != {'kind': 'book'}:
            chapter, start, end = scope.get('chapter_index'), scope.get('start'), scope.get('end')
            if any(type(n) is not int for n in (chapter, start, end)) or not 0 <= start < end <= len(state['sources'].get(str(chapter), '')):
                raise ValueError('身份关系作用范围无效。')
        elif claim['kind'] in ('mention_entity', 'narrator_entity'):
            raise ValueError('称谓与叙述身份需要明确原文范围。')
        validate_evidence(claim['evidence'], state['sources'])
    for key, decision in state['decisions'].items():
        if key != decision['id'] or decision['segment_id'] not in rows:
            raise ValueError('归属判断引用未知片段。')
        if any(e not in entities for e in decision['candidates']) or (
                decision['entity_id'] is not None and decision['entity_id'] not in entities):
            raise ValueError('归属判断引用未知人物。')
        validate_evidence(decision['evidence'] + decision['against'], state['sources'])
    validate_dependencies(state)
    return state
