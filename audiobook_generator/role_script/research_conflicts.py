"""只把程序能验证的互斥关系作为结构冲突，文学解释保留为候选。"""
from .research_io import digest


def overlap(a, b):
    if a.get('kind') == 'book':
        return b
    if b.get('kind') == 'book':
        return a
    if a.get('chapter_index') == b.get('chapter_index'):
        start, end = max(a['start'], b['start']), min(a['end'], b['end'])
        if start < end:
            return {'chapter_index': a['chapter_index'], 'start': start, 'end': end}
    return None


def detect_conflicts(state):
    found = []
    def add(kind, refs, evidence):
        found.append({'id': digest([kind, sorted(refs)])[:24], 'kind': kind,
                      'refs': refs, 'evidence': evidence, 'status': 'open'})
    claims = [c for c in state['claims'].values() if c['status'] == 'accepted']
    for i, left in enumerate(claims):
        for right in claims[i + 1:]:
            pair = {left['kind'], right['kind']}
            if pair == {'same_entity', 'distinct_entity'} and {
                    left['subject'], left['entity_id']} == {right['subject'], right['entity_id']} and overlap(left['scope'], right['scope']):
                add('identity_conflict', [left['id'], right['id']], left['evidence'] + right['evidence'])
            if left['kind'] == right['kind'] == 'mention_entity' and (
                    left['subject'] == right['subject'] and left['entity_id'] != right['entity_id'] and overlap(left['scope'], right['scope'])):
                add('mention_conflict', [left['id'], right['id']], left['evidence'] + right['evidence'])
            if left['kind'] == right['kind'] == 'narrator_entity' and left['entity_id'] != right['entity_id']:
                a, b = left['scope'], right['scope']
                if a.get('chapter_index') == b.get('chapter_index') and max(a.get('start', 0), b.get('start', 0)) < min(a.get('end', 0), b.get('end', 0)):
                    add('narrator_conflict', [left['id'], right['id']], left['evidence'] + right['evidence'])
    # 同一人物关系具有传递性；沿路径求范围交集，避免把不同时段的关系误判成冲突。
    same = [c for c in claims if c['kind'] == 'same_entity']
    for claim in (c for c in claims if c['kind'] == 'distinct_entity'):
        pending = [(claim['subject'], claim['scope'], [])]
        seen = set()
        while pending:
            entity, scope, path = pending.pop()
            token = (entity, digest(scope))
            if token in seen:
                continue
            seen.add(token)
            if entity == claim['entity_id']:
                refs = [c['id'] for c in path] + [claim['id']]
                if len(path) > 1:
                    add('identity_conflict', refs, claim['evidence'] + [e for c in path for e in c['evidence']])
                break
            for relation in same:
                if entity not in (relation['subject'], relation['entity_id']):
                    continue
                shared = overlap(scope, relation['scope'])
                if shared:
                    other = relation['entity_id'] if entity == relation['subject'] else relation['subject']
                    pending.append((other, shared, path + [relation]))
    # 人工冲突、模型线索与来源失效需要显式处理，不能由一次队列刷新抹除。
    structural = {'identity_conflict', 'mention_conflict', 'narrator_conflict'}
    return [c for c in state['conflicts'] if c['kind'] not in structural] + found
