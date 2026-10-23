"""可撤销人物关系的纯函数；V2 剧本只是当前身份关系的投影。"""
from copy import deepcopy
from .dependency_index import affected
from .research_io import digest, segments, validate_state
from .research_conflicts import detect_conflicts


def project(state):
    rows = segments(state)
    state['conflicts'] = [c for c in state['conflicts'] if c['kind'] != 'human_projection']
    accepted = [c for c in state['claims'].values() if c['status'] == 'accepted']
    def canonical(e, parents):
        visited = set()
        while e in parents:
            if e in visited:
                raise ValueError('人物合并关系存在循环。')
            visited.add(e); e = parents[e]
        return e
    def covers(scope, span):
        return scope.get('kind') == 'book' or (scope.get('chapter_index') == span['chapter_index'] and
            scope.get('start', 0) <= span['start'] and span['end'] <= scope.get('end', 0))
    mappings = {}
    for sid, decision in state['decisions'].items():
        s = rows[sid]
        active = [c for c in accepted if covers(c['scope'], s['source_span'])]
        identity = tuple(c['id'] for c in active if c['kind'] == 'same_entity')
        if identity not in mappings:
            parents, parent_claims = {}, {}
            for claim in active:
                if claim['kind'] == 'same_entity':
                    source, target = canonical(claim['subject'], parents), canonical(claim['entity_id'], parents)
                    if source != target:
                        parents[source] = target
                        parent_claims[source] = claim['id']
            mappings[identity] = parents, parent_claims
        parents, parent_claims = mappings[identity]
        chosen = decision['entity_id'] or 'narrator'
        derived = canonical(chosen, parents)
        if decision['status'] != 'human':
            chosen = derived
            upstream = decision['entity_id'] or 'narrator'
            while upstream in parents:
                edge = {'decision_id': sid, 'upstream_id': parent_claims[upstream], 'kind': 'depends_on'}
                if edge not in state['dependencies']:
                    state['dependencies'].append(edge)
                upstream = parents[upstream]
            for claim in active:
                scope = claim['scope']
                if claim['kind'] in ('mention_entity', 'narrator_entity'):
                    span = s['source_span']
                    uses_mention = any(e['decision_id'] == sid and e['upstream_id'] == claim['id'] and e['kind'] == 'depends_on'
                                       for e in state['dependencies'])
                    if ((claim['kind'] == 'narrator_entity' or uses_mention) and scope.get('chapter_index') == span['chapter_index'] and
                            scope.get('start', 0) <= span['start'] and span['end'] <= scope.get('end', 0) and
                            (claim['kind'] != 'narrator_entity' or s.get('text_kind') == 'narration')):
                        chosen = canonical(claim['entity_id'], parents)
                        edge = {'decision_id': sid, 'upstream_id': claim['id'], 'kind': 'depends_on'}
                        if edge not in state['dependencies']:
                            state['dependencies'].append(edge)
        elif derived != chosen:
            conflict = {'id': digest(['human_projection', sid, derived])[:24], 'kind': 'human_projection',
                        'refs': [sid] + list(identity), 'evidence': decision['evidence'], 'status': 'open'}
            if not any(c['id'] == conflict['id'] for c in state['conflicts']):
                state['conflicts'].append(conflict)
        s['role_id'] = chosen
        human = decision['status'] == 'human'
        s['speaker'].update(entity_id=chosen if decision['entity_id'] else None,
            status='confirmed' if human else ('needs_review' if decision['status'] == 'stale' else
                ('unknown' if decision['entity_id'] is None else 'proposed')),
            confidence=None, confidence_kind='human' if human else 'uncalibrated',
            evidence=deepcopy(decision['evidence']))
    state['conflicts'] = detect_conflicts(state)
    return state


def apply_decision(original, action, data, operation_id):
    state = deepcopy(original)
    rows = segments(state)
    roots = []
    if action in ('merge', 'distinct'):
        source, target = data['source_id'], data['target_id']
        if source == target or 'narrator' in (source, target) or any(e not in state['script']['entities'] for e in (source, target)):
            raise ValueError('请选择两个不同的有效人物。')
        roles = state['script']['roles']
        entities = state['script']['entities']
        if action == 'merge' and all(entities[e].get('voice_locked') for e in (source, target)) and roles[source]['provider_params'] != roles[target]['provider_params']:
            raise ValueError('两个人物都已锁定且声音不同，请先解除一个声音锁。')
        key = 'claim_' + digest(operation_id)[:20]
        state['claims'][key] = {'id': key, 'kind': 'same_entity' if action == 'merge' else 'distinct_entity',
            'subject': source, 'entity_id': target, 'scope': {'kind': 'book'}, 'status': 'accepted',
            'evidence': [], 'source': 'human', 'created_revision': state['revision'] + 1, 'revoked_revision': None}
    elif action in ('accept', 'reject', 'revoke'):
        claim = state['claims'][data['claim_id']]
        previous = claim['status']
        claim['status'] = {'accept': 'accepted', 'reject': 'rejected', 'revoke': 'revoked'}[action]
        if action == 'revoke':
            claim['revoked_revision'] = state['revision'] + 1
        elif action == 'accept':
            claim['revoked_revision'] = None
        if previous != claim['status']:
            roots = [claim['id']]
    elif action in ('segment', 'narrator', 'create_entity'):
        if action == 'create_entity':
            name = data['name'].strip()
            if not name:
                raise ValueError('请填写人物名称。')
            entity = 'person_' + digest(operation_id)[:20]
            state['script']['entities'][entity] = {'canonical_name': name, 'aliases': [], 'voice_profile_id': None,
                                                  'voice_locked': False, 'gender': 'unknown'}
            state['script']['roles'][entity] = {'display_name': name,
                'provider_params': deepcopy(state['script']['roles']['narrator']['provider_params']), 'gender': 'unknown'}
            state['unconfigured_entities'].append(entity)
            ids = data['segment_ids']
        else:
            entity = data['entity_id']
            ids = [data['segment_id']] if action == 'segment' else [sid for sid, s in rows.items()
                if s['source_span']['chapter_index'] == data['chapter_index'] and s.get('text_kind') == 'narration']
        if entity not in state['script']['entities'] or not ids or any(sid not in rows for sid in ids):
            raise ValueError('请选择有效人物与原文片段。')
        for sid in ids:
            state['decisions'][sid].update(entity_id=entity, candidates=[entity], status='human')
            state['context_checks'] = [s for s in state['context_checks'] if s != sid]
            roots.append(sid)
            for conflict in state['conflicts']:
                if sid in conflict['refs']:
                    conflict['status'] = 'resolved'
    else:
        raise ValueError('不支持的研究审阅操作。')
    weights, explicit = affected(state, roots)
    state['context_checks'] = sorted(set(state['context_checks']) | {
        sid for sid in set(weights) - explicit if state['decisions'][sid]['status'] != 'human'})
    for sid in explicit:
        if state['decisions'][sid]['status'] != 'human':
            state['decisions'][sid]['status'] = 'stale'
        else:
            state['conflicts'].append({'id': digest([operation_id, sid])[:24], 'kind': 'human_dependency',
                'refs': [sid], 'evidence': [], 'status': 'open'})
    state['revision'] += 1
    state['confirmed'] = ''
    project(state)
    before, after = segments(original), segments(state)
    for sid, row in after.items():
        if row['role_id'] != before[sid]['role_id']:
            weights[sid] = max(1, weights.get(sid, 0))
    changes = [{'segment_id': sid, 'before': row['role_id'], 'after': after[sid]['role_id']}
               for sid, row in before.items() if row['role_id'] != after[sid]['role_id']]
    state['events'].append({'operation_id': operation_id, 'action': action, 'data': deepcopy(data),
                            'revision': state['revision'], 'changes': changes})
    state['operations'][operation_id] = {'revision': state['revision'], 'action': action,
                                        'affected_segments': sorted(weights), 'changes': changes}
    for proposal in state['proposals'].values():
        if proposal['status'] in ('ready', 'partial'):
            proposal['status'] = 'stale'
    return validate_state(state)
