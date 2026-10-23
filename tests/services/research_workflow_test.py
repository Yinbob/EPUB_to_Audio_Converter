"""HTTP、spawn、草稿应用和章节返工的离线闭环。"""
import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from audiobook_generator.api.app import create_app
from audiobook_generator.services.projects import decode
from audiobook_generator.services.models import TaskRequest
from audiobook_generator.services.tasks import TaskManager
from audiobook_generator.services.common import atomic_json
from audiobook_generator.services.research_render import changed_chapters, prepare_regeneration
from audiobook_generator.role_script.research_analysis import analyze
from tests.audiobook_generator.role_script.research_test import state
from tests.audiobook_generator.role_script.research_analysis_test import FakeClient


def research_worker(payload, result_path, log_path, ready):
    os.setsid(); ready.set()
    Path(log_path).write_text('研究闭环离线任务\n')
    if payload['kind'] in ('research_analyze', 'research_reanalyze'):
        result = {'research_proposal': analyze(payload['research_state'], payload['chapters'],
            client=FakeClient(), model='offline', target_ids=payload.get('segment_ids'))}
    else:
        result = {'books': [], 'output_dirs': []}
        for cfg in payload['configs']:
            output = Path(cfg.output_folder)
            output.mkdir(parents=True, exist_ok=True)
            atomic_json(output / 'manifest.json', {'completed_chapters': list(range(cfg.chapter_start, cfg.chapter_end + 1)),
                'research_render_snapshot': cfg.research_render_snapshot})
            result['books'].append({'status': 'succeeded', 'output_dir': str(output)})
            result['output_dirs'].append(str(output))
    atomic_json(result_path, {'ok': True, 'result': result})


def late_research_worker(payload, result_path, log_path, ready):
    import signal
    proposal = analyze(payload['research_state'], payload['chapters'], client=FakeClient(), target_ids=payload.get('segment_ids'))
    def late(*_):
        atomic_json(result_path, {'ok': True, 'result': {'research_proposal': proposal}})
        os._exit(0)
    os.setsid()
    signal.signal(signal.SIGTERM, late)
    ready.set()
    while True:
        time.sleep(.05)


class ResearchWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.client = TestClient(create_app(self.root, acquire_lock=False))
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)
        self.app = self.client.app
        self.app.state.tasks.runner = research_worker
        self.p = self.app.state.projects.put(decode(state()['script']))
        self.key = self.p['id']
        self.base = '/api/v1/projects/' + self.key + '/research'

    def post(self, route, data=None, revision=None, operation_id=None):
        revision = revision or self.app.state.projects.get(self.key)['revision']
        body = {'revision': revision, 'operation_id': operation_id or f'operation-{time.monotonic_ns()}', **(data or {})}
        response = self.client.post(self.base + route, json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, task):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            task = self.app.state.tasks.get(task['id'])
            if task['status'] not in ('starting', 'running', 'stopping'):
                self.assertEqual(task['status'], 'succeeded', task)
                return task
            time.sleep(.03)
        self.fail('离线任务超时')

    def start(self, kind, **extra):
        project = self.app.state.projects.get(self.key)
        request = TaskRequest(request_id=f'request-{time.monotonic_ns()}', kind=kind,
            project_id=self.key, revision=project['revision'],
            generation={'file_ids': [self.file['id']], 'output_dir': str(self.root / f'run-{time.monotonic_ns()}')}, **extra)
        catalog = {'book_sha256': project['script']['book_sha256'], 'parser_fingerprint': '', 'chapters': [{'index': 1}]}
        with patch('audiobook_generator.services.tasks.require_credentials') as credential, patch(
                'audiobook_generator.services.tasks.read_book', return_value=(catalog, [('第一章', state()['sources']['1'])])):
            task = self.app.state.tasks.start(request)
        if kind.startswith('research_') and kind != 'research_regenerate':
            credential.assert_called_once_with('deepseek')
        return self.wait(task)

    def test_full_workflow_and_explanation_does_not_invalidate_audio(self):
        import io
        self.file = self.app.state.files.upload('书.epub', io.BytesIO(b'placeholder'))
        self.post('/enable')
        self.post('/decisions', {'decision': {'action': 'merge', 'source_id': 'char_1', 'target_id': 'char_2'}})
        merged = self.app.state.projects.research.read(self.key)
        claim = next(iter(merged['claims']))
        self.post('/decisions', {'decision': {'action': 'revoke', 'claim_id': claim}})
        self.assertEqual(self.app.state.projects.research.read(self.key)['decisions']['ch1_s2']['status'], 'stale')
        task = self.start('research_reanalyze')
        proposal_id = task['result']['proposal_id']
        self.assertEqual(self.app.state.projects.research.read(self.key)['decisions']['ch1_s2']['status'], 'stale')
        self.post(f'/proposals/{proposal_id}/apply', {'segment_ids': ['ch1_s2']})
        self.app.state.projects.research.confirm(self.key)
        baseline = self.start('generate')
        generation = {'file_ids': [self.file['id']]}
        catalog = {'book_sha256': baseline['render_snapshot']['book_sha256'], 'parser_fingerprint': ''}
        with patch('audiobook_generator.services.books.read_book', return_value=(catalog, [('第一章', state()['sources']['1'])])):
            preview = self.post('/render-preview', {'generation': generation, 'baseline_task_id': baseline['id']})
        self.assertTrue(preview['audio_current'])
        current = self.app.state.projects.research.read(self.key)
        # 只添加不影响合成的审阅会话，确认与合成计划均保留。
        self.post('/sessions', {'budget_seconds': 20})
        self.assertTrue(self.app.state.projects.get(self.key)['confirmed'])
        self.post('/decisions', {'decision': {'action': 'segment', 'segment_id': 'ch1_s2', 'entity_id': 'narrator'}})
        self.app.state.projects.research.confirm(self.key)
        with patch('audiobook_generator.services.books.read_book', return_value=(catalog, [('第一章', state()['sources']['1'])])):
            preview = self.post('/render-preview', {'generation': generation, 'baseline_task_id': baseline['id']})
        self.assertEqual(preview['changed_chapters'], [1])
        repaired = self.start('research_regenerate', baseline_task_id=baseline['id'])
        self.assertEqual(repaired['baseline_task_id'], baseline['id'])
        self.assertNotEqual(repaired['output_dirs'], baseline['output_dirs'])
        self.assertTrue(Path(baseline['output_dirs'][0], 'manifest.json').exists())

    def test_http_preview_idempotency_sessions_and_v2_export(self):
        enabled = self.post('/enable')
        rev = enabled['state']['revision']
        decision = {'decision': {'action': 'segment', 'segment_id': 'ch1_s2', 'entity_id': 'char_2'}}
        preview = self.post('/preview', decision, revision=rev)
        self.assertTrue(preview['preview'])
        self.assertEqual(self.app.state.projects.get(self.key)['revision'], rev)
        self.post('/decisions', decision, revision=rev, operation_id='fixed-operation')
        repeated = self.post('/decisions', decision, revision=rev, operation_id='fixed-operation')
        self.assertEqual(repeated['state']['revision'], rev + 1)
        session = self.post('/sessions', {'budget_seconds': 1})
        self.post(f'/sessions/{session["id"]}/events', {'event': {'kind': 'elapsed', 'elapsed_seconds': 2}})
        q = self.client.get(self.base + '/queue', params={'session_id': session['id']}).json()
        self.assertIsNone(q['recommendation'])
        export = self.post('/export', {'mode': 'events'})
        self.assertEqual(self.client.get('/api/v1/files/' + export['id']).status_code, 200)
        self.assertEqual(decode(self.app.state.projects.get(self.key)['script']).schema_version, 2)

    def test_partial_application_preserves_human_and_stale_draft(self):
        self.post('/enable')
        r = self.app.state.projects.research
        s = r.read(self.key)
        p = analyze(s, [('第一章', s['sources']['1'])], client=FakeClient())
        r.store_proposal(self.key, s['revision'], p)
        self.post(f'/proposals/{p["id"]}/apply', {'segment_ids': ['ch1_s1']})
        partial = r.read(self.key)['proposals'][p['id']]
        self.assertEqual(partial['status'], 'partial')
        self.post('/decisions', {'decision': {'action': 'segment', 'segment_id': 'ch1_s2', 'entity_id': 'char_2'}})
        response = self.client.post(self.base + f'/proposals/{p["id"]}/apply', json={
            'revision': r.read(self.key)['revision'], 'operation_id': 'apply-stale', 'segment_ids': ['ch1_s2']})
        self.assertEqual(response.status_code, 409)

    def test_noncontiguous_repair_ranges(self):
        from types import SimpleNamespace
        baseline = {'id': 'old', 'status': 'succeeded', 'render_snapshot': {'book_sha256': 'book',
            'chapters': {str(i): {'digest': 'old'} for i in range(1, 6)}}}
        snap = {'revision': 3, 'book_sha256': 'book', 'chapters': {str(i): {'digest': 'old' if i == 3 else 'new'} for i in range(1, 6)}}
        configs = prepare_regeneration(SimpleNamespace(output_folder=str(self.root)), snap, baseline)
        self.assertEqual([(c.chapter_start, c.chapter_end) for c in configs], [(1, 2), (4, 5)])

    def test_stopped_late_proposal_and_restart_results_never_commit(self):
        import io
        self.file = self.app.state.files.upload('书.epub', io.BytesIO(b'placeholder'))
        self.post('/enable')
        manager = self.app.state.tasks
        manager.runner = late_research_worker
        project = self.app.state.projects.get(self.key)
        request = TaskRequest(request_id='late-research-request', kind='research_analyze', project_id=self.key,
            revision=project['revision'], generation={'file_ids': [self.file['id']]})
        catalog = {'book_sha256': project['script']['book_sha256'], 'parser_fingerprint': ''}
        with patch('audiobook_generator.services.tasks.require_credentials'), patch(
                'audiobook_generator.services.tasks.read_book', return_value=(catalog, [('第一章', state()['sources']['1'])])):
            task = manager.start(request)
        self.assertTrue(manager.ready[task['id']].wait(5))
        self.assertEqual(manager.stop(task['id'])['status'], 'stopped')
        self.assertEqual(self.app.state.projects.research.read(self.key)['proposals'], {})
        self.assertEqual(self.app.state.projects.get(self.key)['revision'], project['revision'])
        # 重启仅把未完成任务标为失败，不读取留下的结果文件。
        manager.close()
        manager.tasks[task['id']]['status'] = 'running'
        manager._save(manager.tasks[task['id']])
        restarted = TaskManager(self.root, self.app.state.files, self.app.state.projects)
        self.app.state.tasks = restarted
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.get(task['id'])['status'], 'failed')
        self.assertEqual(self.app.state.projects.research.read(self.key)['proposals'], {})

    def test_old_analysis_revision_and_conflicted_suggestions_are_rejected(self):
        self.post('/enable')
        service = self.app.state.projects.research
        s = service.read(self.key)
        proposal = analyze(s, [('第一章', s['sources']['1'])], client=FakeClient(), target_ids=['ch1_s2'])
        proposal['conflicts'] = [{'id': 'conflict1', 'kind': 'literary_candidate', 'refs': ['ch1_s2'], 'evidence': [], 'status': 'open'}]
        service.store_proposal(self.key, s['revision'], proposal)
        response = self.client.post(self.base + f'/proposals/{proposal["id"]}/apply', json={
            'revision': s['revision'], 'operation_id': 'apply-conflict', 'segment_ids': ['ch1_s2']})
        self.assertEqual(response.status_code, 409)
        self.post('/decisions', {'decision': {'action': 'segment', 'segment_id': 'ch1_s2', 'entity_id': 'char_2'}})
        from audiobook_generator.services.common import ServiceError
        with self.assertRaises(ServiceError):
            service.store_proposal(self.key, s['revision'], proposal)
        self.assertEqual(service.read(self.key)['decisions']['ch1_s2']['status'], 'human')

    def test_source_changes_cannot_be_bypassed_and_paused_session_survives_reload(self):
        from audiobook_generator.services.research_render import validate_sources
        from audiobook_generator.services.common import ServiceError
        s = self.post('/enable')['state']
        catalog = {'book_sha256': s['script']['book_sha256'], 'parser_fingerprint': ''}
        with self.assertRaises(ServiceError):
            validate_sources(s, catalog, [('第一章', '改写原文')])
        session = self.post('/sessions', {})
        self.post(f'/sessions/{session["id"]}/events', {'event': {'kind': 'pause'}})
        self.assertTrue(self.client.get(self.base).json()['state']['sessions'][session['id']]['paused'])
        self.post(f'/sessions/{session["id"]}/events', {'event': {'kind': 'continue'}})
        self.assertEqual(self.client.get(self.base).json()['state']['sessions'][session['id']]['budget_seconds'], 600)
