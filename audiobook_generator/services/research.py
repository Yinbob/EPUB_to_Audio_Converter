"""研究项目单快照事务；沿用 Projects 的锁和版本约束。"""
import copy
import uuid
from pathlib import Path
from .common import ServiceError, atomic_json, read_json
from audiobook_generator.role_script.research_io import (
    confirmation_digest, create_state, digest, input_digest, segments, validate_state,
)
from audiobook_generator.role_script.research_review import apply_decision, project
from audiobook_generator.role_script.review_policy import recommendation, review_queue


class ResearchService:
    def __init__(self, projects):
        self.projects = projects
        self.root = projects.root / '.studio' / 'research'

    def path(self, key):
        if not key or any(c not in '0123456789abcdef' for c in key) or len(key) != 32:
            raise ServiceError('project_missing', '找不到角色项目。', 404)
        return self.root / key / 'state.json'

    def exists(self, key):
        return self.path(key).is_file()

    def read(self, key):
        if not self.exists(key):
            raise ServiceError('research_disabled', '请先为此项目启用研究审阅。', 409)
        return validate_state(read_json(self.path(key)))

    def save(self, state):
        state = validate_state(state)
        atomic_json(self.path(state['id']), state)
        return state

    def check(self, key, revision, operation_id=None):
        state = self.read(key)
        if operation_id and operation_id in state['operations']:
            return state, True
        if revision != state['revision']:
            raise ServiceError('revision_conflict', '项目已变化，请刷新后重新检查本次选择。', 409)
        if self.projects.manager:
            self.projects.manager.require_idle()
        return state, False

    def enable(self, key, revision, operation_id):
        with self.projects.lock:
            if self.exists(key):
                return self.view(key)
            value = self.projects.check_revision(key, revision)
            if self.projects.manager:
                self.projects.manager.require_idle()
            state = create_state(key, revision, value['script'])
            state['operations'][operation_id] = {'revision': state['revision'], 'action': 'enable'}
            self.save(state)
            return self.view(key)

    def project_view(self, key):
        state = self.read(key)
        export = self.path(key).parent / 'exports' / f'script-{state["revision"]}.json'
        if not export.exists():
            atomic_json(export, state['script'])
        return {'id': key, 'revision': state['revision'], 'script': state['script'],
                'confirmed': state['confirmed'] == confirmation_digest(state),
                'research_pending': len(review_queue(state)),
                'research_enabled': True, 'file': self.projects.files.register(export)}

    def view(self, key):
        with self.projects.lock:
            state = self.read(key)
            queue = review_queue(state)
            return {'state': state, 'summary': {'pending': len(queue),
                'stale': sum(d['status'] == 'stale' for d in state['decisions'].values()),
                'conflicts': sum(c['status'] == 'open' for c in state['conflicts']),
                'context_checks': len(state['context_checks']),
                'unconfigured': len(state['unconfigured_entities'])}, 'project': self.project_view(key)}

    def queue(self, key, offset=0, limit=50, strategy='impact', session_id=None):
        with self.projects.lock:
            state = self.read(key)
            queue = review_queue(state, strategy)
            session = state['sessions'].get(session_id) if session_id else None
            return {'revision': state['revision'], 'total': len(queue), 'items': queue[offset:offset + limit],
                    'recommendation': recommendation(state, session) if session and not session.get('ended') and
                        session['elapsed_seconds'] < session['budget_seconds'] else None}

    def decide(self, key, revision, operation_id, action, data, *, preview=False):
        with self.projects.lock:
            state, repeated = self.check(key, revision, operation_id)
            if repeated:
                return self.view(key)
            updated = apply_decision(state, action, data, operation_id)
            if preview:
                result = updated['operations'][operation_id]
                return {**result, 'revision': state['revision'],
                    'chapters': sorted({segments(updated)[sid]['source_span']['chapter_index']
                                       for sid in result['affected_segments']}), 'preview': True}
            self.save(updated)
            return self.view(key)

    def put_script(self, key, script, *, operation='replace', confirmed=False, configured_role=None):
        """旧编辑入口也必须记录修订，不能写回启用前备份。"""
        state = self.read(key)
        old = state['script']
        if script['book_sha256'] != old['book_sha256'] or script['provider'] != old['provider']:
            raise ServiceError('project_identity', '不能改变研究项目的书籍或提供商。')
        if set(s['segment_id'] for c in script['chapters'] for s in c['segments']) != set(segments(state)) or any(
                s['text'] != segments(state)[s['segment_id']]['text'] or s['source_span'] != segments(state)[s['segment_id']]['source_span']
                for c in script['chapters'] for s in c['segments']):
            raise ServiceError('research_resplit', '研究项目请保留原文和分段；重新拆分请建立独立项目。', 409)
        state['script'] = copy.deepcopy(script)
        if configured_role in state['unconfigured_entities']:
            state['unconfigured_entities'].remove(configured_role)
        state['revision'] += 1
        state['confirmed'] = ''
        old_rows = {r['segment_id']: r for c in old['chapters'] for r in c['segments']}
        for sid, s in segments(state).items():
            before = old_rows[sid]
            if s['role_id'] != before['role_id']:
                state['decisions'][sid].update(entity_id=s['role_id'], candidates=[s['role_id']], status='human')
            eid = s['role_id']
            if eid in state['unconfigured_entities'] and old['roles'][eid]['provider_params'] != script['roles'][eid]['provider_params']:
                state['unconfigured_entities'].remove(eid)
        for p in state['proposals'].values():
            if p['status'] in ('ready', 'partial'):
                p['status'] = 'stale'
        operation_id = uuid.uuid4().hex
        state['events'].append({'operation_id': operation_id, 'action': operation, 'data': {},
                                'revision': state['revision'], 'changes': []})
        if confirmed:
            state['confirmed'] = confirmation_digest(state)
        self.save(state)
        return self.project_view(key)

    def confirm(self, key):
        state = self.read(key)
        self.gate(state)
        state['confirmed'] = confirmation_digest(state)
        self.save(state)
        return self.project_view(key)

    def gate(self, state, chapter_start=1, chapter_end=None):
        rows = segments(state)
        selected = {sid for sid, s in rows.items() if s['source_span']['chapter_index'] >= chapter_start and
                    (chapter_end is None or s['source_span']['chapter_index'] <= chapter_end)}
        if any(state['decisions'][sid]['status'] == 'stale' for sid in selected):
            raise ServiceError('research_stale', '目标章节有过期判断，请重新分析或逐段确认。', 409)
        if any(rows[sid]['role_id'] in state['unconfigured_entities'] for sid in selected):
            raise ServiceError('research_voice_required', '请先为新人物配置声音。', 409)
        if any(c['status'] == 'open' and c['kind'] == 'source_invalid' for c in state['conflicts']):
            raise ServiceError('research_source_invalid', '原文引用已失效，请重新建立项目。', 409)

    def store_proposal(self, key, revision, proposal):
        # 仅调度器在 worker 退出后持锁调用，任务自身仍为 running。
        state = self.read(key)
        if state['revision'] != revision or proposal['input_digest'] != input_digest(state):
            raise ServiceError('proposal_stale', '分析期间项目已变化，草稿不再适用。', 409)
        from audiobook_generator.role_script.research_analysis import validate_proposal
        validate_proposal(proposal, state)
        state['proposals'][proposal['id']] = proposal
        self.save(state)
        return {'proposal_id': proposal['id'], 'project_id': key}

    def apply_proposal(self, key, revision, operation_id, proposal_id, selected):
        with self.projects.lock:
            state, repeated = self.check(key, revision, operation_id)
            if repeated:
                return self.view(key)
            p = state['proposals'][proposal_id]
            if p['status'] not in ('ready', 'partial') or p['base_revision'] != revision or p['input_digest'] != input_digest(state):
                raise ServiceError('proposal_stale', '草稿已过期，请重新分析。', 409)
            selected = set(selected)
            available = {c['segment_id'] for c in p['changes']} - set(p['applied_segments'])
            if not selected or not selected <= available:
                raise ValueError('请选择草稿中尚未应用的片段。')
            human = {sid for sid in selected if state['decisions'][sid]['status'] == 'human'}
            if human:
                raise ServiceError('human_confirmation', '已人工确认的片段请使用逐段修改，不能由草稿覆盖。', 409)
            conflict_refs = {ref for c in p['conflicts'] if c['status'] == 'open' for ref in c['refs']}
            for change in p['changes']:
                if change['segment_id'] in selected and conflict_refs & ({change['segment_id'], change['decision']['entity_id']} |
                        {e['upstream_id'] for e in change['dependencies']}):
                    raise ServiceError('proposal_conflict', '选中的建议有未解决冲突，请先人工处理，再重新分析。', 409)
            for mention in p['mentions']:
                state['mentions'][mention['id']] = mention
            for claim in p['claims']:
                if claim['id'] not in state['claims']:
                    state['claims'][claim['id']] = claim
            for change in p['changes']:
                sid = change['segment_id']
                if sid not in selected:
                    continue
                state['decisions'][sid] = change['decision']
                state['dependencies'] = [e for e in state['dependencies'] if e['decision_id'] != sid]
                state['dependencies'].extend(change['dependencies'])
                state['context_checks'] = [s for s in state['context_checks'] if s != sid]
            state['conflicts'].extend(c for c in p['conflicts'] if not any(old['id'] == c['id'] for old in state['conflicts']))
            p['applied_segments'] = sorted(set(p['applied_segments']) | selected)
            p['status'] = 'applied' if len(p['applied_segments']) == len(p['changes']) else 'partial'
            state['revision'] += 1
            state['confirmed'] = ''
            project(state)
            # 部分应用后的剩余建议仍来自同一次分析，绑定到本次原子提交。
            p['base_revision'] = state['revision']
            p['input_digest'] = input_digest(state)
            for other in state['proposals'].values():
                if other['id'] != p['id'] and other['status'] in ('ready', 'partial'):
                    other['status'] = 'stale'
            state['events'].append({'operation_id': operation_id, 'action': 'apply_proposal',
                'data': {'proposal_id': proposal_id, 'segment_ids': sorted(selected)},
                'revision': state['revision'], 'changes': [c for c in p['changes'] if c['segment_id'] in selected]})
            state['operations'][operation_id] = {'revision': state['revision'], 'action': 'apply_proposal'}
            self.save(state)
            return self.view(key)

    def session(self, key, revision, operation_id, budget_seconds, strategy, seed, audit_every):
        with self.projects.lock:
            state, repeated = self.check(key, revision, operation_id)
            if repeated:
                return state['sessions'][state['operations'][operation_id]['session_id']]
            sid = uuid.uuid4().hex
            value = {'id': sid, 'budget_seconds': budget_seconds, 'elapsed_seconds': 0., 'strategy': strategy,
                'seed': seed, 'audit_every': audit_every, 'skipped': [], 'answers': [], 'events': [], 'ended': False, 'paused': False}
            state['sessions'][sid] = value
            state['operations'][operation_id] = {'session_id': sid}
            self.save(state)
            return value

    def session_event(self, key, revision, operation_id, session_id, event):
        with self.projects.lock:
            state, repeated = self.check(key, revision, operation_id)
            if repeated:
                return state['sessions'][session_id]
            session = state['sessions'][session_id]
            if event['kind'] == 'resume':
                session['budget_seconds'] += 600
                session['ended'] = False
                session['paused'] = False
            elif event['kind'] in ('pause', 'continue'):
                session['paused'] = event['kind'] == 'pause'
            elif event['kind'] == 'end':
                session['ended'] = True
            elif event['kind'] == 'skip':
                session['skipped'].append(event['task_id'])
                session['answers'].append(event['task_id'])
            elif event['kind'] == 'answered':
                session['answers'].append(event['task_id'])
            session['elapsed_seconds'] += event.get('elapsed_seconds', 0)
            if event['kind'] == 'shown':
                item = recommendation(state, session)
                if item and item['id'] == event['task_id']:
                    event = {**event, 'audit': item['audit'], 'sampling_probability': item['sampling_probability'], 'selection': 'recommended'}
                elif any(q['id'] == event['task_id'] for q in review_queue(state)):
                    event = {**event, 'audit': False, 'sampling_probability': None, 'selection': 'manual'}
                else:
                    raise ValueError('展示条目已失效，请刷新队列。')
            session['events'].append({**event, 'queue_version': revision})
            state['operations'][operation_id] = {'session_id': session_id}
            self.save(state)
            return session

    def export(self, key, revision, operation_id, mode):
        with self.projects.lock:
            state, _ = self.check(key, revision)
            def sanitize(value):
                if isinstance(value, dict):
                    return {k: sanitize(v) for k, v in value.items() if not any(t in k.lower() for t in ('api_key', 'password', 'secret'))}
                if isinstance(value, list):
                    return [sanitize(v) for v in value]
                if isinstance(value, str) and Path(value).is_absolute():
                    return {'local_resource_name': Path(value).name}
                return value
            path = self.path(key).parent / 'exports' / f'{mode}-{revision}.json'
            atomic_json(path, sanitize(state if mode == 'snapshot' else {'events': state['events'], 'sessions': state['sessions']}))
            return self.projects.files.register(path)
