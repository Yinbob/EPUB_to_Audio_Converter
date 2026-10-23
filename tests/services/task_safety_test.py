"""真实调度入口的迁移回归，不调用网络或语音模型。"""
import hashlib
import io
import os
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from audiobook_generator.api.app import create_app
from audiobook_generator.services.common import ServiceError, atomic_json, read_json
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.models import Generation, TaskRequest, ProjectEdit
from audiobook_generator.services.projects import Projects
from audiobook_generator.services.tasks import TaskManager
from tests.audiobook_generator.role_script.v2_io_test import _script


def audio_worker(payload, result_path, log_path, ready):
    os.setsid()
    ready.set()
    path = Path(result_path).with_suffix('.wav')
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0\0' * 16000)
    atomic_json(result_path, {'ok': True, 'result': {'audio_path': str(path)}})


def parsed_worker(payload, result_path, log_path, ready):
    os.setsid()
    ready.set()
    output = Path(payload['configs'][0].output_folder)
    atomic_json(output / 'manifest.json', {'book_sha256': 'a' * 64, 'status': 'parsed', 'chapter_range': [1, 1]})
    atomic_json(output / 'chapters.json', {'chapters': [{'index': 1}]})
    atomic_json(result_path, {'ok': True, 'result': {'books': [{'chapters': [{'index': 1}]}]}})


class TaskSafetyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = FileStore(self.root)
        self.projects = Projects(self.root, self.files)
        self.manager = TaskManager(self.root, self.files, self.projects, runner=audio_worker)
        self.addCleanup(self.manager.close)
        self.credentials = patch('audiobook_generator.services.tasks.require_credentials')
        self.credentials.start()
        self.addCleanup(self.credentials.stop)

    def finish(self, task):
        deadline = time.monotonic() + 10
        while self.manager.get(task['id'])['status'] in ('starting', 'running') and time.monotonic() < deadline:
            time.sleep(.02)
        result = self.manager.get(task['id'])
        self.assertEqual(result['status'], 'succeeded', result.get('error'))
        return result

    def test_minimax_default_and_custom_voice_start_without_book(self):
        for voice in ('male-qn-qingse', 'my_remote_clone'):
            task = self.manager.start(TaskRequest(request_id='minimax-' + voice, kind='preview',
                generation=Generation(engine={'provider': 'minimax', 'voice_name': voice})))
            self.assertIn('audio', self.finish(task)['result'])

    def test_generate_requires_book_and_project_preview_requires_matching_engine(self):
        with self.assertRaises(ServiceError) as missing:
            self.manager.start(TaskRequest(request_id='missing-book', generation=Generation()))
        self.assertEqual(missing.exception.code, 'book_required')
        project = self.projects.put(_script()[0])
        with self.assertRaises(ServiceError) as mismatch:
            self.manager.start(TaskRequest(request_id='wrong-engine', kind='preview', project_id=project['id'],
                revision=project['revision'], role_id='narrator', generation=Generation(engine={'provider': 'minimax'})))
        self.assertEqual(mismatch.exception.code, 'project_provider')
        self.assertIsNone(self.manager.current())

    def test_project_voice_binding_rejects_other_model_before_start(self):
        from audiobook_generator.services.portable_voices import PortableVoices
        project = self.projects.put(_script()[0])
        sample = self.root / 'confirmed.wav'
        sample.write_bytes(b'confirmed audition')
        store = PortableVoices(self.root)
        card = store.put(dict(schema_version='portable-voice-v1', id='hero', label='主角', language='zh',
            bindings=[dict(provider='mimo', model='mimo-v2.5-tts', endpoint='https://example.invalid/v1',
                params={'voice': '冰糖', 'speed': 1}, audition_sha256=store._asset(sample), confirmed=True)]))
        with patch('audiobook_generator.services.portable_voices.endpoint_for', return_value='https://example.invalid/v1'):
            project = self.projects.edit(project['id'], ProjectEdit(revision=project['revision'],
                operation='portable_voice', data={'role_id': 'char_1', 'voice_profile_id': card['id'],
                    'voice_profile_version': card['version'], 'model_name': 'mimo-v2.5-tts'}))
            with self.assertRaises(ServiceError) as mismatch:
                self.manager.start(TaskRequest(request_id='wrong-model', kind='preview', project_id=project['id'],
                    revision=project['revision'], role_id='char_1', generation=Generation(
                        engine={'provider': 'openai', 'model_name': 'different-model'})))
        self.assertEqual(mismatch.exception.code, 'voice_binding_missing')
        self.assertIsNone(self.manager.current())

    def test_task_finalization_preserves_parse_only_manifest_status(self):
        self.manager.runner = parsed_worker
        book = self.files.upload('book.epub', io.BytesIO(b'book'))
        task = self.finish(self.manager.start(TaskRequest(request_id='parse-only',
            generation=Generation(file_ids=[book['id']], preview=True))))
        output = Path(task['output_dirs'][0])
        self.assertEqual(read_json(output / 'manifest.json')['status'], 'parsed')
        self.assertEqual(read_json(output / 'timeline.json')['chapters'], [])

    def test_freeze_rejects_other_person_changed_script_and_modified_audio(self):
        project = self.projects.put(_script()[0])
        task = self.finish(self.manager.start(TaskRequest(request_id='bound-preview', kind='preview',
            project_id=project['id'], revision=project['revision'], role_id='narrator', generation=Generation())))
        path = self.manager.freeze_preview(project['id'], project['revision'], 'narrator', task['id'])
        self.assertTrue(path.is_file())
        with self.assertRaises(ServiceError):
            self.manager.freeze_preview(project['id'], project['revision'], 'char_1', task['id'])
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaises(ServiceError) as changed:
            self.manager.freeze_preview(project['id'], project['revision'], 'narrator', task['id'])
        self.assertEqual(changed.exception.code, 'preview_changed')
        self.projects.invalidate(project['id'])
        # 即便修订号未改变，改变角色参数也不能复用旧试听。
        raw = self.projects.get(project['id'])['script']
        raw['roles']['narrator']['provider_params']['speed'] = 1.2
        atomic_json(Path(self.projects.entries[project['id']]['path']), raw)
        with self.assertRaises(ServiceError):
            self.manager.freeze_preview(project['id'], project['revision'], 'narrator', task['id'])

    def test_log_history_cursor_has_no_duplicate_or_missing_lines(self):
        task = self.finish(self.manager.start(TaskRequest(request_id='log-history', kind='preview', generation=Generation())))
        path = self.manager.directory / task['id'] / 'EtA_task.log'
        lines = [f'行{i}\n' for i in range(6100)]
        path.write_text(''.join(lines), encoding='utf-8')
        latest = self.manager.logs(task['id'])
        earlier = self.manager.logs(task['id'], before=latest['start_cursor'])
        first = self.manager.logs(task['id'], before=earlier['start_cursor'])
        self.assertEqual(first['text'] + earlier['text'] + latest['text'], ''.join(lines))
        self.assertFalse(first['has_more'])
        self.assertEqual(self.manager.logs(task['id'], latest['cursor'])['text'], '')

    def test_invalid_catalog_import_does_not_save_or_report_success(self):
        with TestClient(create_app(self.root / 'api', acquire_lock=False)) as client:
            uploaded = client.post('/api/v1/uploads', files={'file': ('broken.json', b'{invalid')}).json()
            with patch('audiobook_generator.tts_providers.voice_catalog.save_user_voice_entries') as save:
                response = client.post('/api/v1/voices/import', json={'file_id': uploaded['id']})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()['error']['code'], 'voice_import_invalid')
            save.assert_not_called()
