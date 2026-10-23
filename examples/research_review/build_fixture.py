"""生成作者编写的中文测试故事；响应与金标准分别写入，实验运行时不互相读取。"""
import json
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from audiobook_generator.role_script.research_io import create_state, digest
from audiobook_generator.role_script.research_experiment import recording_key, deterministic_response
from audiobook_generator.role_script.research_review import project


def build(output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    corpus, gold, recordings = {'schema_version': 'research-corpus-v1', 'synthetic': True, 'cases': []}, {}, {}
    stories = {
        'same_name': '林远与林岳都被称作林先生，今天他们同时来到书店。',
        'kinship': '林远叫林岳“父亲”；林岳叫林森“父亲”。同一称谓指向不同的人。',
        'wrong_merge': '林远和林岳是两个不同的人，各自拿着一本书。',
        'narrator_shift': '这一章由林远自述，我终于找到了那本书。',
        'human_conflict': '林远说过的话已经由编辑确认，不能随身份合并改写。',
        'source_changed': '这一版原文增加了人物说明，上一版的定位已失效。',
    }
    for case_id, intro in stories.items():
        roles = {eid: {'display_name': name, 'provider_params': {'voice': voice, 'speed': 1}}
                 for eid, name, voice in [('narrator', '旁白', '冰糖'), ('person_a', '林远', '茉莉'), ('person_b', '林岳', '冰糖')]}
        entities = {eid: {'canonical_name': r['display_name'], 'aliases': [], 'voice_locked': False} for eid, r in roles.items()}
        if case_id == 'kinship':
            roles['person_c'] = {'display_name': '林森', 'provider_params': {'voice': '茉莉', 'speed': 1}}
            entities['person_c'] = {'canonical_name': '林森', 'aliases': [], 'voice_locked': False}
        text, rows = '', []
        for i, value in enumerate([intro] + [f'林远说：“这是我第{i}次来这里，我还记得那本书。”' for i in range(1, 13)]):
            eid = 'narrator' if i == 0 else 'person_b'
            rows.append({'segment_id': f'ch1_s{i}', 'text': value, 'role_id': eid, 'text_kind': 'narration' if i == 0 else 'dialogue',
                'source_span': {'chapter_index': 1, 'start': len(text), 'end': len(text) + len(value)},
                'speaker': {'entity_id': eid, 'status': 'proposed', 'confidence': None, 'evidence': [], 'confidence_kind': 'uncalibrated'}})
            text += value
        script = {'schema_version': 2, 'provider': 'openai', 'book_sha256': digest(case_id), 'default_pause_after_ms': 250,
                  'roles': roles, 'entities': entities, 'chapters': [{'chapter_index': 1, 'title': case_id, 'segments': rows}]}
        s = create_state(digest(case_id)[:32], 1, script)
        cid = 'claim_' + case_id
        s['claims'][cid] = {'id': cid, 'kind': 'same_entity', 'subject': 'person_a', 'entity_id': 'person_b',
            'scope': {'kind': 'book'}, 'status': 'proposed', 'evidence': [], 'source': 'model', 'created_revision': 2, 'revoked_revision': None}
        if case_id == 'narrator_shift':
            s['claims'][cid].update(kind='narrator_entity', subject='narrator', scope={'chapter_index': 1, 'start': 0, 'end': len(intro)})
            s['decisions']['ch1_s0']['entity_id'] = 'person_b'
        if case_id == 'kinship':
            for i, target in enumerate(['person_b', 'person_c']):
                start = intro.index('父亲') if i == 0 else intro.rindex('父亲')
                mention = f'father_{i}'
                span = {'chapter_index': 1, 'start': start, 'end': start + 2}
                s['mentions'][mention] = {'id': mention, 'span': span, 'text': '父亲', 'block_id': 'ch1_s0'}
                s['claims']['truth_' + mention] = {**s['claims'][cid], 'id': 'truth_' + mention,
                    'kind': 'mention_entity', 'subject': mention, 'entity_id': target, 'scope': span,
                    'status': 'accepted', 'source': 'human', 'evidence': [{'span': span, 'quote': '父亲', 'kind': 'address'}]}
        if case_id in ('wrong_merge', 'human_conflict'):
            s['claims'][cid]['status'] = 'accepted'
            if case_id == 'wrong_merge':
                s['claims']['truth_distinct'] = {**s['claims'][cid], 'id': 'truth_distinct', 'kind': 'distinct_entity', 'source': 'human'}
        for row in rows if case_id == 'narrator_shift' else rows[1:]:
            s['dependencies'].append({'decision_id': row['segment_id'], 'upstream_id': cid, 'kind': 'depends_on'})
        if case_id == 'human_conflict':
            s['decisions']['ch1_s1'].update(status='human', entity_id='person_a')
            rows = s['script']['chapters'][0]['segments']
            rows[1]['role_id'] = 'person_a'
            rows[1]['speaker'].update(entity_id='person_a', status='confirmed', confidence_kind='human')
        project(s)
        rows = s['script']['chapters'][0]['segments']
        case = {'id': case_id, 'state': s, 'chapters': [['第一章', text]]}
        if case_id == 'source_changed':
            case['chapters'][0][1] += '新增的结尾。'
            case['expected_analysis_error'] = '原书正文'
        corpus['cases'].append(case)
        gold[case_id] = {'segments': {row['segment_id']: 'narrator' if i == 0 and case_id != 'narrator_shift' else 'person_a' for i, row in enumerate(rows)},
                         'claims': {cid: 'revoke' if s['claims'][cid]['status'] == 'accepted' else 'reject'}}
        recordings[case_id] = {}
        # 固定测试分析器在该故事上输出说话动作对应的人物，不读金标准文件。
        for row in rows:
            request = {'segment_id': row['segment_id'], 'text': row['text'], 'start': row['source_span']['start'],
                'chapter_index': 1, 'entities': [{'id': eid, 'name': e['canonical_name']} for eid, e in entities.items()]}
            response = deterministic_response(request)
            for active_claims in itertools.chain.from_iterable(itertools.combinations(s['claims'], size) for size in range(len(s['claims']) + 1)):
                request['claims'] = [{'id': cid} for cid in active_claims]
                recordings[case_id][recording_key(request)] = response
    for filename, value in [('input.json', corpus), ('gold.json', gold), ('recordings.json', recordings)]:
        (output / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    build(Path(__file__).parent)
