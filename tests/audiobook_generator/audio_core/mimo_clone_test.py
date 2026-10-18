"""克隆配置、真实请求结构与缓存来源的离线检验；不调用外部模型。"""
import base64
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
from audiobook_generator.audio_core.store import ArtifactStore
from audiobook_generator.role_script.models import RoleDefinition, VoiceProfile
from audiobook_generator.tts_providers.mimo_voice import resolve_voice, CLONE_DEFAULT_EN
from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
from tests.test_utils import get_openai_config
from tests.audiobook_generator.tts_providers.openai_tts_provider_test import _wav_bytes


class CloneRoutingTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.audio = self.root / 'reference.wav'
        self.audio.write_bytes(_wav_bytes())
        self.params = {'voice_mode': 'clone', 'voice_profile_id': 'book_bryce_clone',
            'voice_version': 'v1', 'voice_language': 'en', 'reference_audio_path': str(self.audio),
            'reference_audio_sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest()}

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_sdk_receives_reference_only_in_audio_and_exact_body_in_assistant(self, credentials):
        config = get_openai_config(); config.stream = True
        provider = OpenAITTSProvider(config)
        route = provider.resolve_voice(self.params)
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(audio=SimpleNamespace(data=base64.b64encode(_wav_bytes()).decode())))])
        result = provider._request_mimo_chunk('Exact source.', voice=None,
            instructions=route['instructions'], client=client, request=route)
        self.assertEqual(result, _wav_bytes())
        payload = client.chat.completions.create.call_args.kwargs
        self.assertEqual(payload['model'], 'mimo-v2.5-tts-voiceclone')
        self.assertNotIn('stream', payload)
        self.assertEqual(set(payload['audio']), {'format', 'voice'})
        self.assertEqual(payload['audio']['format'], 'wav')
        self.assertTrue(payload['audio']['voice'].startswith('data:audio/wav;base64,'))
        self.assertEqual(base64.b64decode(payload['audio']['voice'].split(',', 1)[1]), self.audio.read_bytes())
        self.assertEqual(payload['messages'], [{'role': 'user', 'content': CLONE_DEFAULT_EN},
            {'role': 'assistant', 'content': 'Exact source.'}])
        self.assertNotIn('data:audio', json.dumps(route))

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_observed_cache_identity_repeat_and_mutation_before_cache_hit(self, credentials):
        provider = OpenAITTSProvider(get_openai_config())
        store = ArtifactStore(self.root / 'project'); run = store.start_run(ResourceLimits(max_requests=6))
        profile = VoiceProfile('bryce', 'Bryce', self.params)
        with patch.object(provider, '_request_mimo_chunk', return_value=_wav_bytes()) as request:
            first = provider.synthesize_observed_chunk('Exact source.', profile, store, run)
            self.assertEqual(first, provider.synthesize_observed_chunk('Exact source.', profile, store, run))
            second = provider.synthesize_observed_chunk('Exact source.', profile, store, run, resample=True)
            self.assertNotEqual(first, second)
            updated = replace(profile, provider_params={**self.params, 'voice_version': 'v2'})
            provider.synthesize_observed_chunk('Exact source.', updated, store, run)
            self.assertEqual(request.call_count, 3)
            self.audio.write_bytes(_wav_bytes(duration_ms=80))
            changed = replace(updated, provider_params={**updated.provider_params,
                'reference_audio_sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest()})
            provider.synthesize_observed_chunk('Exact source.', changed, store, run)
            self.assertEqual(request.call_count, 4)
            self.audio.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '指纹'):
                provider.synthesize_observed_chunk('Exact source.', profile, store, run)
            self.assertEqual(len(store.request_events(run_id=run)), 4)
            self.assertEqual(request.call_count, 4)
        for path in (store.root / 'requests').glob('*.json'):
            self.assertNotIn('data:audio', path.read_text())

    def test_invalid_modes_and_reference_files_never_fall_back(self):
        config = get_openai_config()
        cases = [{**self.params, 'voice': 'Mia'}, {**self.params, 'voice_description': 'young'},
            {**self.params, 'reference_audio_sha256': '0' * 64},
            {**self.params, 'reference_audio_path': 'relative.wav'},
            {**self.params, 'voice_profile_id': ''}, {**self.params, 'voice_language': 'auto'},
            {'voice': 'Mia', 'reference_audio_path': str(self.audio)},
            {**self.params, 'voice_mode': 'design', 'voice_description': 'young'}]
        for params in cases:
            with self.subTest(params=params), self.assertRaises(ValueError):
                resolve_voice(config, params)
        with patch('audiobook_generator.tts_providers.mimo_reference.MAX_ENCODED_REFERENCE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, '10MB'):
                resolve_voice(config, self.params)

    def test_validator_and_locked_hybrid_preservation(self):
        from audiobook_generator.role_script.validator import validate_role_script
        from audiobook_generator.audio_core.hybrid_casting import hybrid_casting, apply_hybrid
        from tests.audiobook_generator.audio_core.hybrid_casting_test import confirmed_v2_fixture, bank
        script = confirmed_v2_fixture()
        roles = dict(script.roles); roles['lead'] = replace(roles['lead'], provider_params=self.params)
        script = replace(script, roles=roles)
        self.assertTrue(validate_role_script(script).ok)
        manifest = hybrid_casting(script, bank(), language='en', full_book=True)
        self.assertEqual(manifest['profiles']['lead']['model'], 'mimo-v2.5-tts-voiceclone')
        cards = {r: {'voice_description': 'A clear steady adult voice.'}
            for r, p in manifest['profiles'].items() if p['voice_mode'] == 'design' and not p['locked']}
        applied = apply_hybrid(script, manifest, cards)
        self.assertEqual(applied.roles['lead'].provider_params, self.params)
        self.assertEqual(applied.chapters, script.chapters)
        bad_roles = {**roles, 'lead': replace(roles['lead'], provider_params={**self.params, 'voice': 'Mia'})}
        self.assertFalse(validate_role_script(replace(script, roles=bad_roles)).ok)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_reference_is_rechecked_at_the_sdk_boundary(self, credentials):
        provider = OpenAITTSProvider(get_openai_config())
        route = provider.resolve_voice(self.params)
        self.audio.write_bytes(_wav_bytes(duration_ms=80))
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, '指纹'):
            provider._request_mimo_chunk('Exact source.', voice=None,
                instructions=route['instructions'], client=client, request=route)
        client.chat.completions.create.assert_not_called()

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_pipeline_does_not_bootstrap_first_clone_as_verified_identity(self, credentials):
        import numpy as np
        from audiobook_generator.audio_core.pipeline import run_chapter
        from audiobook_generator.audio_core.quality import QualityEvaluator
        from audiobook_generator.core.audio_tags import AudioTags
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        text = 'Please wait beside the bridge until I arrive.'
        plan = plan_for((text,))
        unit = replace(plan.units[0], profile=VoiceProfile('narrator', 'Bryce', self.params))
        plan = replace(plan, units=(unit,))
        provider = OpenAITTSProvider(get_openai_config())
        options = CoreOptions(language='en')
        with patch.object(provider, '_request_mimo_chunk', return_value=_wav_bytes()) as request:
            for n in (1, 8):
                current = replace(plan, chapter_index=n)
                evaluator = QualityEvaluator(options, transcribe=lambda _: text, speaker=lambda _: np.array([1., 0.]))
                result = run_chapter(current, provider, self.root/f'chapter{n}.wav',
                    AudioTags('test', 'a', 'b', n), self.root/'project', options=options, evaluator=evaluator)
                self.assertEqual(result['chunks'][0]['report']['metrics']['consistency_reference'], 'not_available')
            self.assertEqual(request.call_count, 1)
        with ArtifactStore(self.root/'project').connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM role_anchors').fetchone()[0], 0)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_pipeline_compares_chapters_to_clone_input_and_prefers_reviewed_registry(self, credentials):
        import numpy as np
        import soundfile as sf
        from audiobook_generator.audio_core.pipeline import run_chapter
        from audiobook_generator.audio_core.quality import QualityEvaluator
        from audiobook_generator.core.audio_tags import AudioTags
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        sf.write(self.audio, .1 * np.sin(np.arange(64000) * .1), 16000, subtype='PCM_16')
        params = {**self.params, 'reference_audio_sha256': hashlib.sha256(self.audio.read_bytes()).hexdigest()}
        text = 'Please wait beside the bridge until I arrive.'
        plan = plan_for((text,))
        plan = replace(plan, units=(replace(plan.units[0], profile=VoiceProfile('narrator', 'Bryce', params)),))
        provider = OpenAITTSProvider(get_openai_config())
        output = self.root / 'generated.wav'
        sf.write(output, .1 * np.sin(np.arange(64000) * .2), 16000, subtype='PCM_16')
        options = CoreOptions(language='en')
        with patch.object(provider, '_request_mimo_chunk', return_value=output.read_bytes()) as request:
            for chapter in (1, 8):
                result = run_chapter(replace(plan, chapter_index=chapter), provider, self.root/f'chapter{chapter}.wav',
                    AudioTags('test', 'a', 'b', chapter), self.root/'project', options=options,
                    evaluator=QualityEvaluator(options, transcribe=lambda _: text, speaker=lambda _: np.array([1., 0.])))
                metrics = result['chunks'][0]['report']['metrics']
                self.assertEqual(metrics['consistency_reference']['path'], str(self.audio.resolve()))
                self.assertEqual(metrics['consistency_reference']['kind'], 'clone_conditioning_reference')
                self.assertIn('speaker_distance', metrics)
                self.assertNotIn('rate_drift', [i['code'] for i in result['chunks'][0]['report']['issues']])
            self.assertEqual(request.call_count, 1)
            reviewed = (str(self.audio), {'fixed_reference_kind': 'human_confirmed_fixed_reference',
                                        'fixed_reference_sha256': params['reference_audio_sha256']})
            with patch('audiobook_generator.audio_core.role_references.load_reference', return_value=reviewed), \
                 patch('audiobook_generator.audio_core.role_references.clone_conditioning_reference') as fallback:
                fixed_options = replace(options, role_references='reviewed.json')
                result = run_chapter(plan, provider, self.root/'fixed.wav', AudioTags('test', 'a', 'b', 1),
                    self.root/'project', options=fixed_options,
                    evaluator=QualityEvaluator(fixed_options, transcribe=lambda _: text, speaker=lambda _: np.array([1., 0.])))
                self.assertEqual(result['chunks'][0]['report']['metrics']['consistency_reference']['kind'],
                                 'human_confirmed_fixed_reference')
                fallback.assert_not_called()
        with ArtifactStore(self.root/'project').connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM role_anchors').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
