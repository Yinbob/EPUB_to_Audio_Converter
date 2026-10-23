"""离线审阅实验：金标准只进入模拟审阅者与评估器，不进入排序或分析器。"""
import argparse
import copy
import csv
import json
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from .research_io import digest, segments
from .research_analysis import analyze
from .review_policy import recommendation


def recording_key(request):
    return digest([request['segment_id'], request['text'], sorted(c['id'] for c in request['claims'])])


class RecordedClient:
    def __init__(self, recordings):
        self.recordings, self.calls = recordings, 0
        self.base_url = 'offline://recorded-research-v1'
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        request = json.loads(kwargs['messages'][1]['content'])
        key = recording_key(request)
        if key not in self.recordings:
            raise ValueError(f'缺少录制响应：{key}；不会用金标准补造模型输出。')
        self.calls += 1
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(self.recordings[key], ensure_ascii=False)))])


def deterministic_response(request):
    """仅匹配输入人物卡中的明确说话标记，供流程测试，不读金标准。"""
    matches = []
    for card in request['entities']:
        match = re.search(re.escape(card['name']) + r'(?:说|说道|自述)', request['text'])
        if match:
            matches.append((match.start(), card['id'], match))
    match = min(matches, default=None, key=lambda item: (item[0], item[1]))
    entity = match[1] if match else ('narrator' if request['text'].startswith(('林远与', '林远转向', '林远和', '林远叫', '这一版', '林远说过')) else None)
    evidence = [] if not match else [{'span': {'chapter_index': request['chapter_index'],
        'start': request['start'] + match[2].start(), 'end': request['start'] + match[2].end()},
        'quote': match[2].group(), 'kind': 'explicit_speech_tag'}]
    return {'decisions': [{'segment_id': request['segment_id'], 'entity_id': entity,
        'candidates': [entity] if entity else [], 'evidence': evidence, 'against': [], 'depends_on': []}],
        'mentions': [], 'claims': [], 'conflicts': []}


class DeterministicClient:
    base_url = 'offline://deterministic-research-v1'

    def __init__(self):
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        request = json.loads(kwargs['messages'][1]['content'])
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(deterministic_response(request), ensure_ascii=False)))])


def errors(state, gold):
    rows = segments(state)
    return {sid for sid, entity in gold['segments'].items() if rows[sid]['role_id'] != entity}


def run_case(case, gold, recordings, arm, budget, seed, audit_every=0, analyzer='recorded'):
    from audiobook_generator.services.projects import Projects
    from audiobook_generator.services.files import FileStore
    strategies = {'A': 'sequence', 'B': 'sequence', 'C': 'risk', 'D': 'impact'}
    with tempfile.TemporaryDirectory(prefix='research-replay-') as directory:
        projects = Projects(directory, FileStore(directory))
        r = projects.research
        state = copy.deepcopy(case['state'])
        if arm == 'A':
            # 普通人物表保留初始逐段结果，不运行关系投影或依赖修复。
            state['claims'] = {}
            state['dependencies'] = []
            state['conflicts'] = []
            state['context_checks'] = []
        r.save(state)
        key = state['id']
        model = RecordedClient(recordings) if analyzer == 'recorded' else DeterministicClient()
        if case.get('expected_analysis_error'):
            try:
                analyze(state, case['chapters'], client=model, model='recorded-fixture')
            except ValueError as exc:
                if case['expected_analysis_error'] not in str(exc):
                    raise
                return {'case': case['id'], 'arm': arm, 'budget_seconds': budget, 'elapsed_seconds': 0,
                    'remaining_errors': len(errors(state, gold)), 'introduced_errors': 0, 'model_requests': model.calls,
                    'reviewed_questions': [], 'reanalyzed_segments': [], 'seed': seed, 'audit_every': audit_every,
                    'policy_version': state['policy_version'], 'trace': [], 'events': [], 'simulated': True,
                    'verified_source_rejection': True}
            raise ValueError('来源失效夹具未被拒绝。')
        clock, introduced, reviewed, reanalyzed = 0., 0, [], set()
        trace = [{'elapsed_seconds': 0., 'remaining_errors': len(errors(state, gold))}]
        session = {'strategy': strategies[arm], 'seed': seed, 'audit_every': audit_every, 'answers': [], 'skipped': []}
        while True:
            item = recommendation(state, session)
            if item is None or clock + item['estimated_seconds'] > budget:
                break
            before_errors = errors(state, gold)
            sid = item['id']
            if item['kind'] == 'segment':
                if sid not in gold['segments']:
                    raise ValueError(f'金标准缺少审阅片段 {sid}')
                action, data = 'segment', {'segment_id': sid, 'entity_id': gold['segments'][sid]}
            else:
                if sid not in gold['claims']:
                    raise ValueError(f'金标准缺少关系答案 {sid}')
                action, data = gold['claims'][sid], {'claim_id': sid}
            r.decide(key, state['revision'], f'replay-{len(reviewed):08d}', action, data)
            state = r.read(key)
            targets = [sid for sid, d in state['decisions'].items() if d['status'] == 'stale']
            if targets:
                # 模拟审阅者不向分析器提供其他片段答案。
                chapters = case['chapters']
                proposal = analyze(state, chapters, client=model, model='recorded-fixture', target_ids=targets)
                r.store_proposal(key, state['revision'], proposal)
                r.apply_proposal(key, state['revision'], f'apply-{len(reviewed):08d}', proposal['id'], targets)
                state = r.read(key)
                reanalyzed.update(targets)
            clock += item['estimated_seconds']
            introduced += len(errors(state, gold) - before_errors)
            reviewed.append(sid); session['answers'].append(sid)
            trace.append({'elapsed_seconds': round(clock, 3), 'remaining_errors': len(errors(state, gold)),
                'task_id': sid, 'sampling_probability': item['sampling_probability'], 'audit': item['audit']})
        return {'case': case['id'], 'arm': arm, 'budget_seconds': budget, 'elapsed_seconds': round(clock, 3),
            'remaining_errors': len(errors(state, gold)), 'introduced_errors': introduced,
            'reviewed_questions': reviewed, 'model_requests': model.calls, 'reanalyzed_segments': sorted(reanalyzed),
            'seed': seed, 'audit_every': audit_every, 'policy_version': state['policy_version'],
            'trace': trace, 'events': state['events'], 'simulated': True}


def run(input_file, gold_file, recordings_file, output, budgets=(300, 600, 1200), seed='research-v1', audit_every=0, analyzer='recorded'):
    if analyzer not in ('recorded', 'deterministic') or any(b <= 0 for b in budgets) or audit_every < 0:
        raise ValueError('实验分析器、预算或抽查间隔无效。')
    corpus = json.loads(Path(input_file).read_text())
    gold = json.loads(Path(gold_file).read_text())
    recordings = json.loads(Path(recordings_file).read_text()) if analyzer == 'recorded' else {}
    rows = [run_case(case, gold[case['id']], recordings.get(case['id'], {}), arm, budget, seed, audit_every, analyzer)
            for case in corpus['cases'] for arm in 'ABCD' for budget in budgets]
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    result = {'schema_version': 'research-experiment-v1', 'simulated': True,
        'notice': '合成夹具与模拟审阅结果，不代表真实模型或真人收益。',
        'analyzer': analyzer, 'input_sha256': digest(corpus), 'gold_sha256': digest(gold), 'recordings_sha256': digest(recordings) if recordings else None, 'results': rows}
    (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    fields = ['case', 'arm', 'budget_seconds', 'elapsed_seconds', 'remaining_errors', 'introduced_errors', 'model_requests', 'seed', 'audit_every', 'policy_version', 'simulated']
    with (output / 'results.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    return result


def main():
    defaults = Path(__file__).resolve().parents[2] / 'examples' / 'research_review'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', default=str(defaults / 'input.json'))
    parser.add_argument('--gold', default=str(defaults / 'gold.json'))
    parser.add_argument('--recordings', default=str(defaults / 'recordings.json'))
    parser.add_argument('--analyzer', choices=('recorded', 'deterministic'), default='recorded')
    parser.add_argument('--output', required=True)
    parser.add_argument('--budgets', default='300,600,1200')
    parser.add_argument('--seed', default='research-v1')
    parser.add_argument('--audit-every', type=int, default=0)
    args = parser.parse_args()
    run(args.input, args.gold, args.recordings, args.output,
        budgets=tuple(map(int, args.budgets.split(','))), seed=args.seed, audit_every=args.audit_every, analyzer=args.analyzer)


if __name__ == '__main__':
    main()
