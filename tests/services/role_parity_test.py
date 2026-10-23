"""角色迁移操作回归：只使用临时 WAV 和服务，不加载模型。"""
import hashlib
import tempfile
import unittest
import wave
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from audiobook_generator.services.common import ServiceError, read_json
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.models import ProjectEdit
from audiobook_generator.services.projects import Projects
from tests.audiobook_generator.role_script.v2_io_test import _script


class RoleParityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.files = FileStore(self.root)
        self.projects = Projects(self.root, self.files)
        script, _ = _script()
        roles = dict(script.roles)
        roles['char_1'] = replace(roles['char_1'], provider_params={
            'voice': '茉莉', 'speed': 1.15, 'voice_language': 'en', 'instructions': 'Read naturally.'})
        self.project = self.projects.put(replace(script, roles=roles), confirmed=True)
        self.wav = self.root / 'preview.wav'
        with wave.open(str(self.wav), 'wb') as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24000)
            stream.writeframes(b'\0\0' * 24000 * 3)

    def freeze(self, **data):
        return self.projects.edit(self.project['id'], ProjectEdit(
            revision=self.project['revision'], operation='freeze_preview',
            data={'role_id': 'char_1', 'task_id': 'preview-task', **data}))

    def test_freeze_calls_binding_validation_and_preserves_performance(self):
        manager = Mock()
        manager.freeze_preview.return_value = self.wav
        self.projects.manager = manager
        result = self.freeze()
        manager.freeze_preview.assert_called_once_with(
            self.project['id'], self.project['revision'], 'char_1', 'preview-task')
        params = result['script']['roles']['char_1']['provider_params']
        self.assertEqual(params['voice_mode'], 'clone')
        self.assertEqual(params['voice_language'], 'en')
        self.assertEqual(params['speed'], 1.15)
        self.assertEqual(params['instructions'], 'Read naturally.')
        self.assertEqual(params['reference_audio_sha256'], hashlib.sha256(self.wav.read_bytes()).hexdigest())
        self.assertEqual(Path(params['reference_audio_path']).parent, self.root / '.voice_references')
        self.assertEqual(result['revision'], self.project['revision'] + 1)
        self.assertFalse(result['confirmed'])
        self.assertEqual(result['script']['chapters'], self.project['script']['chapters'])

    def test_rejected_binding_does_not_change_project(self):
        manager = Mock()
        manager.freeze_preview.side_effect = ServiceError('preview_stale', '请重新试听', 409)
        self.projects.manager = manager
        with self.assertRaises(ServiceError):
            self.freeze()
        current = self.projects.get(self.project['id'])
        self.assertEqual(current['revision'], self.project['revision'])
        self.assertEqual(current['script'], self.project['script'])
        self.assertTrue(current['confirmed'])
        self.assertFalse((self.root / '.voice_references').exists())

    def test_freeze_requires_current_role_and_task_manager(self):
        with self.assertRaises(ServiceError) as missing_manager:
            self.freeze()
        self.assertEqual(missing_manager.exception.code, 'preview_reference')
        self.projects.manager = Mock()
        with self.assertRaises(ServiceError) as missing_role:
            self.freeze(role_id='missing')
        self.assertEqual(missing_role.exception.code, 'role_missing')
        self.projects.manager.freeze_preview.assert_not_called()

    def test_uploaded_reference_still_works_without_preview(self):
        audio = self.files.register(self.wav)
        result = self.projects.edit(self.project['id'], ProjectEdit(
            revision=self.project['revision'], operation='voice', data={
                'role_id': 'char_1', 'mode': 'clone', 'reference_id': audio['id'],
                'language': 'en', 'speed': 1.1}))
        self.assertEqual(result['script']['roles']['char_1']['provider_params']['voice_mode'], 'clone')

    def test_portable_binding_locks_role_and_preserves_version_snapshot(self):
        from audiobook_generator.services.portable_voices import PortableVoices
        store = PortableVoices(self.root)
        card = store.put(dict(schema_version='portable-voice-v1', id='hero', label='主角', language='zh',
            bindings=[dict(provider='mimo', model='mimo-v2.5-tts', endpoint='https://example.invalid/v1',
                params={'voice': '冰糖', 'speed': 1}, audition_sha256=store._asset(self.wav), confirmed=True)]))
        with patch('audiobook_generator.services.portable_voices.endpoint_for', return_value='https://example.invalid/v1'):
            result = self.projects.edit(self.project['id'], ProjectEdit(revision=self.project['revision'],
                operation='portable_voice', data={'role_id': 'char_1', 'voice_profile_id': card['id'],
                    'voice_profile_version': card['version'], 'model_name': 'mimo-v2.5-tts'}))
        self.assertTrue(result['script']['entities']['char_1']['voice_locked'])
        self.assertEqual(result['script']['roles']['char_1']['provider_params'], card['bindings'][0]['params'])
        saved = read_json(self.root / '.studio/project_voice_bindings' / self.project['id'] / 'char_1.json')
        self.assertEqual(saved['snapshot'], card)

