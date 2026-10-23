"""按根因聚合疑点并估算审阅收益；分数不是正确概率。"""
import json
import random
from pathlib import Path
from .dependency_index import affected
from .research_io import digest, segments

POLICY = json.loads(Path(__file__).with_name('review_policy_v1.json').read_text())


def review_queue(state, strategy='impact'):
    rows = segments(state)
    conflicts = {ref for c in state['conflicts'] if c['status'] == 'open' for ref in c['refs']}
    groups, assigned = [], set()
    for key, claim in sorted(state['claims'].items()):
        if claim['status'] != 'proposed' and key not in conflicts:
            continue
        weights, _ = affected(state, [key])
        weights = {sid: w for sid, w in weights.items() if state['decisions'][sid]['status'] != 'human' or sid in conflicts}
        if not weights and claim['scope'].get('chapter_index'):
            weights = {sid: 1 for sid, s in rows.items() if s['source_span']['chapter_index'] == claim['scope']['chapter_index']
                       and s['source_span']['start'] < claim['scope'].get('end', 0)
                       and claim['scope'].get('start', 0) < s['source_span']['end']
                       and (state['decisions'][sid]['status'] != 'human' or sid in conflicts)}
        if not weights:
            continue
        groups.append((key, claim['kind'], weights, claim['evidence'], [claim['entity_id']], key in conflicts))
        assigned.update(weights)
    for sid, decision in state['decisions'].items():
        if sid in assigned or (decision['status'] == 'human' and sid not in conflicts):
            continue
        groups.append((sid, 'segment', {sid: POLICY['context_weight'] if sid in state.get('context_checks', []) else 1}, decision['evidence'] + decision['against'],
                       decision['candidates'], sid in conflicts))
    result = []
    for key, kind, weights, evidence, candidates, conflict in groups:
        decisions = [state['decisions'][sid] for sid in weights]
        risk, reason = (POLICY['risk']['explicit'], '有原文依据，尚未人工核对')
        if not evidence:
            risk, reason = POLICY['risk']['unsupported'], '缺少明确原文证据'
        if kind != 'segment' or any(d['status'] == 'stale' for d in decisions):
            risk, reason = POLICY['risk']['unresolved'], '身份关系尚未确认或判断已过期'
        if any(d['entity_id'] is None for d in decisions):
            risk, reason = POLICY['risk']['unknown'], '存在未知身份'
        if conflict:
            risk, reason = POLICY['risk']['conflict'], '存在互相矛盾的判断'
        elif key in state.get('context_checks', []):
            reason += '；曾接触已变化的人物上下文，建议检查'
        duration = min(POLICY['time_max'], max(POLICY['time_min'], POLICY['time_base'] +
            POLICY['time_per_character'] * sum(len(e.get('quote', '')) for e in evidence) + POLICY['time_per_alternative'] * len(candidates)))
        order = min((rows[s]['source_span']['chapter_index'], rows[s]['source_span']['start']) for s in weights)
        result.append({'id': key, 'kind': kind, 'segment_ids': sorted(weights),
            'chapters': sorted({rows[s]['source_span']['chapter_index'] for s in weights}),
            'evidence': evidence, 'candidates': candidates, 'reason': reason,
            'risk_score': risk, 'weighted_impact': sum(weights.values()),
            'estimated_seconds': round(duration, 2), 'score': risk * sum(weights.values()) / duration,
            'order': list(order)})
    if strategy == 'sequence':
        return sorted(result, key=lambda r: (r['order'], r['id']))
    return sorted(result, key=lambda r: (-r['risk_score'] if strategy == 'risk' else -r['score'], r['order'], r['id']))


def recommendation(state, session):
    queue = review_queue(state, session['strategy'])
    skipped = set(session.get('skipped', []))
    remaining = [r for r in queue if r['id'] not in skipped]
    if not remaining:
        return None
    index = len(session.get('answers', [])) + 1
    audit = session.get('audit_every', 10) and index % session['audit_every'] == 0
    if audit:
        rng = random.Random(digest([session['seed'], index, state['revision']]))
        item = rng.choice(remaining)
    else:
        item = remaining[0]
    return {**item, 'audit': bool(audit), 'sampling_probability': 1 / len(remaining) if audit else 1.,
            'queue_version': state['revision']}
