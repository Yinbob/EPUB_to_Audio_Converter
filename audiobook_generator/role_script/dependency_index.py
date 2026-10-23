"""由快照重建反向依赖；显式依赖与上下文暴露分开计数。"""
from collections import defaultdict, deque


def validate_dependencies(state):
    known = set(state['claims']) | set(state['decisions']) | set(state['script']['entities'])
    graph = defaultdict(list)
    for edge in state['dependencies']:
        if edge['decision_id'] not in state['decisions'] or edge['upstream_id'] not in known:
            raise ValueError('判断依赖引用未知记录。')
        if edge['kind'] == 'depends_on':
            if edge['upstream_id'] in state['script']['entities']:
                raise ValueError('明确依赖必须引用关系或判断。')
            graph[edge['decision_id']].append(edge['upstream_id'])
    visiting, visited = set(), set()
    for node in list(graph):
        stack = [(node, False)]
        while stack:
            item, finished = stack.pop()
            if finished:
                visiting.discard(item); visited.add(item)
            elif item not in visited:
                if item in visiting:
                    raise ValueError('判断依赖存在循环。')
                visiting.add(item)
                stack.append((item, True))
                stack.extend((upstream, False) for upstream in graph.get(item, []))


def affected(state, roots):
    import json
    from pathlib import Path
    policy = json.loads(Path(__file__).with_name('review_policy_v1.json').read_text())
    reverse = defaultdict(list)
    for edge in state['dependencies']:
        reverse[edge['upstream_id']].append(edge)
    weights, direct = {}, set()
    queue = deque((r, 1.0, True) for r in roots)
    seen = {}
    while queue:
        root, weight, explicit = queue.popleft()
        token = (root, explicit)
        if seen.get(token, -1) >= weight:
            continue
        seen[token] = weight
        for edge in reverse[root]:
            child = edge['decision_id']
            is_explicit = explicit and edge['kind'] == 'depends_on'
            w = weight if root in roots else weight * policy['transitive_decay']
            if not is_explicit:
                w = min(w, policy['context_weight'])
            weights[child] = max(weights.get(child, 0), w)
            if is_explicit:
                direct.add(child)
            queue.append((child, w, is_explicit))
    return weights, direct
