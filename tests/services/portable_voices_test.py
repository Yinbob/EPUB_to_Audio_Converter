import copy
import io
import json
import logging
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audiobook_generator.services.common import ServiceError, atomic_json
from audiobook_generator.services.portable_voices import PortableVoices
from audiobook_generator.services.minimax_clone import clone
from audiobook_generator.services.books import configs_for
from audiobook_generator.services.models import Generation
from audiobook_generator.services.files import FileStore


def wav(path, seconds=1):
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b'\0\0' * 16000 * seconds)


class PortableVoiceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = PortableVoices(self.root)
        self.audio = self.root / 'audition.wav'
        wav(self.audio)
        self.digest = self.store._asset(self.audio)

    def card(self):
        return dict(schema_version='portable-voice-v1', id='narrator', label='旁白', language='zh', bindings=[
            dict(provider='openai', model='mimo-v2.5-tts', endpoint='https://example.invalid/v1',
                 params={'voice': 'mimo_default', 'speed': 1}, audition_sha256=self.digest, confirmed=True)])

    def test_export_import_preserves_version_assets_and_provider_scope(self):
        value = self.store.put(self.card())
        self.assertEqual(value['bindings'][0]['provider'], 'mimo')
        bundle = self.store.export(value['id'], value['version'])
        destination = PortableVoices(self.root / 'another_machine')
        imported = destination.import_file(bundle)
        self.assertEqual(value, imported)
        params, snapshot = destination.resolve(value['id'], value['version'], 'openai', 'mimo-v2.5-tts', 'https://example.invalid/v1')
        self.assertEqual(params['voice'], 'mimo_default')
        self.assertEqual(snapshot['version'], value['version'])
        for provider, model, endpoint in [('minimax', 'mimo-v2.5-tts', 'https://example.invalid/v1'),
                                           ('openai', 'other-model', 'https://example.invalid/v1'),
                                           ('openai', 'mimo-v2.5-tts', 'https://another.invalid/v1')]:
            with self.assertRaises(ServiceError) as error:
                destination.resolve(value['id'], value['version'], provider, model, endpoint)
            self.assertEqual(error.exception.code, 'voice_binding_missing')

    def test_versions_are_immutable_and_assets_are_verified(self):
        first = self.store.put(self.card())
        changed = self.card()
        changed['bindings'][0]['params']['speed'] = 1.2
        second = self.store.put(changed)
        self.assertNotEqual(first['version'], second['version'])
        self.assertEqual(self.store.get('narrator', first['version']), first)
        (self.store.directory / 'assets' / self.digest).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.store.resolve('narrator', first['version'], 'openai', 'mimo-v2.5-tts', 'https://example.invalid/v1')

    def test_clone_reference_is_relocated_without_absolute_path_in_bundle(self):
        value = self.card()
        value['bindings'][0]['params'] = dict(voice_mode='clone', voice_language='zh', voice_profile_id='fixed',
            voice_version='v1', reference_audio_sha256=self.digest, speed=1)
        card = self.store.put(value)
        bundle = self.store.export(card['id'], card['version'])
        with zipfile.ZipFile(bundle) as archive:
            self.assertNotIn(str(self.root), archive.read('voice.json').decode())
        destination = PortableVoices(self.root / 'portable')
        imported = destination.import_file(bundle)
        params, _ = destination.resolve(imported['id'], imported['version'], 'openai', 'mimo-v2.5-tts', 'https://example.invalid/v1')
        self.assertTrue(Path(params['reference_audio_path']).is_file())
        self.assertTrue(params['reference_audio_path'].startswith(str((self.root / 'portable').resolve())))

    def test_bundle_rejects_paths_and_unconfirmed_bindings(self):
        value = self.card()
        value['bindings'][0]['confirmed'] = False
        with self.assertRaises(ValueError): self.store.put(value)
        value = self.card()
        value['bindings'][0]['params']['reference_audio_path'] = '/tmp/voice.wav'
        with self.assertRaises(ValueError): self.store.put(value)
        target = self.root / 'unsafe.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            archive.writestr('../outside', 'unsafe')
        with self.assertRaises(ValueError): self.store.import_file(target)
        self.assertFalse((self.root.parent / 'outside').exists())

    def test_save_uses_task_snapshot_and_requires_matching_audio(self):
        directory = self.root / 'tasks'
        files = FileStore(self.root)
        file = files.register(self.audio)
        task = {'kind': 'preview', 'status': 'succeeded', 'result': {'audio': file}}
        manager = SimpleNamespace(get=lambda key: task, directory=directory, files=files)
        binding = copy.deepcopy(self.card()['bindings'][0])
        binding.pop('confirmed'); binding.pop('audition_sha256')
        binding['provider'] = 'mimo'
        binding['audio_sha256'] = self.digest
        atomic_json(directory / 'task' / 'voice_binding.json', binding)
        with self.assertRaises(ValueError):
            self.store.from_preview(manager, 'task', key='narrator', label='旁白', language='zh', confirmed=False)
        result = self.store.from_preview(manager, 'task', key='narrator', label='旁白', language='zh', confirmed=True)
        self.assertEqual(result['bindings'][0]['params'], binding['params'])
        self.audio.write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            self.store.from_preview(manager, 'task', key='other', label='旁白', language='zh', confirmed=True)

    def test_generation_resolves_once_and_freezes_requested_version(self):
        value = self.store.put(self.card())
        files = FileStore(self.root)
        book = files.upload('book.epub', io.BytesIO(b'book'))
        with patch('audiobook_generator.services.portable_voices.endpoint_for', return_value='https://example.invalid/v1'):
            config = configs_for(Generation(file_ids=[book['id']], voice_profile_id=value['id'],
                voice_profile_version=value['version']), files, self.root)[0]
        self.assertEqual(config._portable_params, {'voice':'mimo_default', 'speed':1})
        self.assertEqual(config.portable_voice_snapshot['version'], value['version'])

    def test_minimax_clone_keeps_source_reference_in_export(self):
        files = FileStore(self.root)
        audio = files.register(self.audio)
        source = self.root / 'source.wav'
        wav(source, 10)
        manager = SimpleNamespace(get=lambda key: {'kind': 'voice_clone', 'status': 'succeeded',
            'result': {'audio': audio}}, directory=self.root / 'tasks', files=files)
        atomic_json(manager.directory / 'clone' / 'voice_binding.json', dict(provider='minimax',
            model='speech-2.8-hd', endpoint='https://api.minimaxi.com',
            params={'voice_id': 'book_voice_1', 'speed': 1},
            reference_path=str(source), audio_sha256=self.digest))
        card = self.store.from_preview(manager, 'clone', key='minimax_book', label='旁白', language='zh', confirmed=True)
        source_digest = self.store._asset(source)
        self.assertEqual(card['bindings'][0]['reference'], {'sha256': source_digest, 'format': 'wav'})
        with zipfile.ZipFile(self.store.export(card['id'], card['version'])) as archive:
            self.assertEqual(archive.read('assets/' + source_digest), source.read_bytes())
            self.assertNotIn(str(self.root), archive.read('voice.json').decode())

    def test_malformed_bundle_reports_explicit_validation_error(self):
        target = self.root / 'broken.zip'
        target.write_bytes(b'not a zip')
        with self.assertRaisesRegex(ValueError, 'ZIP'):
            self.store.import_file(target)

    def test_design_audition_becomes_fixed_clone_on_save(self):
        from audiobook_generator.role_script.planner import build_default_provider_params
        params = build_default_provider_params('openai', SimpleNamespace(
            model_name='mimo-v2.5-tts-voicedesign', instructions='温和、低沉的成年男声', language='zh-CN', speed=1))
        self.assertEqual(params['voice_mode'], 'design')
        self.assertNotIn('voice', params)
        files = FileStore(self.root)
        audio = files.register(self.audio)
        manager = SimpleNamespace(get=lambda key: {'kind': 'preview', 'status': 'succeeded',
            'result': {'audio': audio}}, directory=self.root / 'tasks', files=files)
        atomic_json(manager.directory / 'design' / 'voice_binding.json', dict(provider='mimo',
            model='mimo-v2.5-tts-voicedesign', endpoint='https://example.invalid/v1',
            params=params, audio_sha256=self.digest))
        card = self.store.from_preview(manager, 'design', key='designed', label='设计旁白', language='zh', confirmed=True)
        saved = card['bindings'][0]['params']
        self.assertEqual(saved['voice_mode'], 'clone')
        self.assertEqual(saved['reference_audio_sha256'], self.digest)
        self.assertNotIn('voice_description', saved)
        bundle = self.store.export(card['id'], card['version'])
        destination = PortableVoices(self.root / 'clone_destination')
        imported = destination.import_file(bundle)
        resolved, _ = destination.resolve(imported['id'], imported['version'], 'openai',
            'mimo-v2.5-tts-voicedesign', 'https://example.invalid/v1')
        self.assertTrue(Path(resolved['reference_audio_path']).is_file())


class MiniMaxCloneTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'reference.wav'
        wav(self.path, 10)

    def response(self, **value):
        result = Mock()
        result.json.return_value = {'base_resp': {'status_code': 0}, **value}
        return result

    def test_upload_clone_and_retry_reuses_remote_identity(self):
        session = Mock()
        session.post.side_effect = [self.response(file={'file_id':123}), self.response()]
        for _ in range(2):
            self.assertEqual(clone(self.path, 'book_voice_1', api_key='secret', root=self.root,
                log=logging.getLogger('clone-test'), session=session), 'book_voice_1')
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.post.call_args_list[0].kwargs['data'], {'purpose':'voice_clone'})
        self.assertEqual(session.post.call_args.kwargs['json']['file_id'], 123)
        self.assertNotIn('secret', next((self.root / '.studio/minimax_clones').glob('*.json')).read_text())

    def test_uncertain_write_is_not_automatically_repeated(self):
        session = Mock()
        session.post.side_effect = [self.response(file={'file_id':123}), TimeoutError('timeout')]
        with self.assertRaises(TimeoutError):
            clone(self.path, 'book_voice_1', api_key='secret', root=self.root, log=logging.getLogger('clone-test'), session=session)
        with self.assertRaisesRegex(ValueError, '不确定'):
            clone(self.path, 'book_voice_1', api_key='secret', root=self.root, log=logging.getLogger('clone-test'), session=session)
        self.assertEqual(session.post.call_count, 2)

    def test_invalid_id_or_short_reference_never_calls_remote(self):
        session = Mock()
        wav(self.path, 1)
        for voice in ('bad', 'book_voice_1'):
            with self.assertRaises(ValueError):
                clone(self.path, voice, api_key='secret', root=self.root, log=logging.getLogger('clone-test'), session=session)
        session.post.assert_not_called()
