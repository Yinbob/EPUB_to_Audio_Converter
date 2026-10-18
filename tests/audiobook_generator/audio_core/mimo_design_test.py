import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from dataclasses import replace
from audiobook_generator.role_script.models import VoiceProfile, RoleDefinition
from audiobook_generator.tts_providers.mimo_voice import resolve_voice
from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
from audiobook_generator.audio_core.models import ResourceLimits
from audiobook_generator.audio_core.store import ArtifactStore
from tests.test_utils import get_openai_config
from tests.audiobook_generator.tts_providers.openai_tts_provider_test import _wav_bytes


def card():
    return {'voice_mode': 'design', 'voice_description': 'Low, round resonant voice with clear English consonants.',
            'voice_profile_id': 'book_guest', 'voice_version': 'v1', 'voice_language': 'en'}


class DesignRoutingTests(unittest.TestCase):
    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_actual_sdk_payload_and_all_entrypoints(self, credentials):
        config = get_openai_config()
        config.language, config.stream = 'en-US', True
        provider = OpenAITTSProvider(config)
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(audio=SimpleNamespace(data=base64.b64encode(_wav_bytes()).decode())))])
        fake = MagicMock()
        fake.chat.completions.create.return_value = response
        route = provider.resolve_voice(card(), tone='calm')
        provider._request_mimo_chunk('Exact source.', voice=None, instructions=route['instructions'], request=route, client=fake)
        payload = fake.chat.completions.create.call_args.kwargs
        self.assertEqual(payload['model'], 'mimo-v2.5-tts-voicedesign')
        self.assertEqual(payload['audio'], {'format': 'wav', 'optimize_text_preview': False})
        self.assertNotIn('stream', payload)
        self.assertEqual(payload['messages'][1], {'role': 'assistant', 'content': 'Exact source.'})
        self.assertIn('Low, round', payload['messages'][0]['content'])
        self.assertIn('calm', payload['messages'][0]['content'])
        self.assertEqual(config.model_name, 'mimo-v2.5-tts')
        with tempfile.TemporaryDirectory() as root, patch.object(provider, '_request_mimo_chunk', return_value=_wav_bytes()) as request:
            store = ArtifactStore(Path(root) / 'observed')
            run = store.start_run(ResourceLimits(max_requests=5, max_seconds=60))
            profile = VoiceProfile('guest', 'guest', card())
            provider.synthesize_observed_chunk('Exact source.', profile, store, run)
            provider.synthesize_observed_chunk('Exact source.', profile, store, run)
            self.assertEqual(request.call_count, 1)
            provider.synthesize_observed_chunk('Exact source.', profile, store, run, resample=True)
            self.assertEqual(request.call_count, 2)
            changed = replace(profile, provider_params={**card(), 'voice_version': 'v2'})
            provider.synthesize_observed_chunk('Exact source.', changed, store, run)
            self.assertEqual(request.call_count, 3)
            provider.synthesize_segment('Exact source.', profile, root)
            self.assertEqual(request.call_args.kwargs['request']['model'], payload['model'])
            self.assertEqual(request.call_args.kwargs['voice'], None)

    def test_invalid_never_falls_back(self):
        config = get_openai_config()
        for params in ({'voice_mode': 'x'}, {'voice_mode': 'design'}, {**card(), 'voice': 'Mia'}):
            with self.assertRaises(ValueError):
                resolve_voice(config, params)
        config.model_name = 'arbitrary'
        with self.assertRaises(ValueError):
            resolve_voice(config)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_plain_design_uses_instructions_as_description(self, credentials):
        config = get_openai_config()
        config.model_name = 'mimo-v2.5-tts-voicedesign'
        config.instructions = 'A low resonant voice with crisp consonants.'
        provider = OpenAITTSProvider(config)
        route = provider.resolve_voice()
        self.assertEqual(route['model'], config.model_name)
        self.assertIsNone(route['voice'])


class FixedReferenceTests(unittest.TestCase):
    def test_reference_requires_human_and_rejects_audio_mutation(self):
        import hashlib, json
        from audiobook_generator.audio_core.role_references import make_reference, load_reference
        config = get_openai_config()
        profile = card()
        route = resolve_voice(config, profile)
        with tempfile.TemporaryDirectory() as root:
            audio = Path(root) / 'a.wav'
            audio.write_bytes(_wav_bytes())
            metrics = {'peak': .5, 'clipped_fraction': 0}
            review = {'audio_sha256': hashlib.sha256(audio.read_bytes()).hexdigest(),
                      'role_id': 'guest', 'voice_version': 'v1', 'content_complete': True,
                      'signal_acceptable': True, 'identity_accepted': True}
            with self.assertRaises(ValueError):
                make_reference('guest', profile, 'en', route, audio, metrics, {})
            key, record = make_reference('guest', profile, 'en', route, audio, metrics, review)
            registry = Path(root) / 'refs.json'
            registry.write_text(json.dumps({'schema_version': 'mimo-role-references-v1', 'references': {key: record}}))
            self.assertEqual(load_reference(registry, 'guest', profile, 'en', route)[1]['fixed_reference_kind'], 'human_confirmed_fixed_reference')
            self.assertIsNone(load_reference(registry, 'guest', {**profile, 'voice_version': 'v2'}, 'en', route))
            audio.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                load_reference(registry, 'guest', profile, 'en', route)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_design_requires_fixed_reference_and_reuses_it_across_chapters(self, credentials):
        import io, json, hashlib
        import numpy as np
        import soundfile as sf
        from dataclasses import replace
        from audiobook_generator.audio_core.models import CoreOptions
        from audiobook_generator.audio_core.pipeline import run_chapter
        from audiobook_generator.audio_core.quality import QualityEvaluator
        from audiobook_generator.audio_core.role_references import make_reference
        from audiobook_generator.core.audio_tags import AudioTags
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        config = get_openai_config()
        config.language = 'en-US'
        provider = OpenAITTSProvider(config)
        text = 'Please wait beside the bridge until I arrive.'
        plan = plan_for((text,))
        unit = replace(plan.units[0], role_id='guest', profile=VoiceProfile('guest', 'guest', card()))
        plan = replace(plan, units=(unit,))
        buf = io.BytesIO()
        sf.write(buf, .1 * np.sin(np.arange(48000) * .08), 16000, format='WAV')
        options = CoreOptions(language='en')
        with tempfile.TemporaryDirectory() as root, patch.object(provider, '_request_mimo_chunk', return_value=buf.getvalue()) as request:
            root = Path(root)
            def evaluator():
                return QualityEvaluator(options, transcribe=lambda _: text, speaker=lambda _: np.array([1., 0.]))
            first = run_chapter(plan, provider, root/'one.wav', AudioTags('one', 'a', 'b', 1), root/'project', options=options, evaluator=evaluator())
            self.assertEqual(first['chunks'][0]['report']['metrics']['consistency_reference'], 'not_available')
            store = ArtifactStore(root/'project')
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM role_anchors').fetchone()[0], 0)
            path = first['chunks'][0]['rendered_path']
            review = {'audio_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                'role_id': 'guest', 'voice_version': 'v1', 'content_complete': True,
                'signal_acceptable': True, 'identity_accepted': True}
            key, record = make_reference('guest', card(), 'en', provider.resolve_voice(card()), path,
                first['chunks'][0]['report']['metrics'], review)
            registry = root/'refs.json'
            registry.write_text(json.dumps({'schema_version': 'mimo-role-references-v1', 'references': {key: record}}))
            options.role_references = str(registry)
            for chapter_index in (2, 8):
                next_buffer = io.BytesIO()
                sf.write(next_buffer, (.1 + chapter_index * .001) * np.sin(np.arange(48000) * .08), 16000, format='WAV')
                request.return_value = next_buffer.getvalue()
                current_unit = replace(unit, text=text + ' Now.')
                current = replace(plan, chapter_index=chapter_index, units=(current_unit,))
                result = run_chapter(current, provider, root/f'{chapter_index}.wav', AudioTags('next', 'a', 'b', chapter_index), root/'project', options=options, evaluator=evaluator())
                reference = result['chunks'][0]['report']['metrics']['consistency_reference']
                self.assertEqual(reference['path'], path)
                self.assertEqual(reference['kind'], 'human_confirmed_fixed_reference')


class ProbeTests(unittest.TestCase):
    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_exact_six_independent_observed_requests_and_rerun_guard(self, credentials):
        from tests.audiobook_generator.audio_core.hybrid_casting_test import fixture
        from audiobook_generator.audio_core.hybrid_probe import run_probe
        script = fixture()
        script = replace(script, roles={r: RoleDefinition(r, {**card(), 'voice_profile_id': r}) for r in script.roles})
        provider = OpenAITTSProvider(get_openai_config())
        with tempfile.TemporaryDirectory() as root, patch.object(provider, '_request_mimo_chunk', return_value=_wav_bytes()) as request:
            manifest = run_probe(script, provider, root, ['lead', 'guest'])
            self.assertEqual(len(manifest['probes']), 6)
            self.assertEqual(request.call_count, 6)
            self.assertNotEqual(manifest['probes'][0]['path'], manifest['probes'][2]['path'])
            self.assertEqual(len(ArtifactStore(Path(root)/'project').request_events(run_id=manifest['run_id'])), 6)
            with self.assertRaises(ValueError):
                run_probe(script, provider, root, ['lead', 'guest'])
            self.assertEqual(request.call_count, 6)

class MixedSceneTests(unittest.TestCase):
    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials', return_value=('fake', 'https://example.invalid/v1'))
    def test_reference_gate_then_small_mixed_run(self, credentials):
        import io, json, hashlib
        import numpy as np
        import soundfile as sf
        from audiobook_generator.audio_core.hybrid_casting import hybrid_casting, apply_hybrid
        from audiobook_generator.audio_core.hybrid_scenes import run_scenes
        from audiobook_generator.audio_core.role_references import make_reference
        from audiobook_generator.audio_core.quality import QualityEvaluator
        from audiobook_generator.audio_core.models import CoreOptions
        from tests.audiobook_generator.audio_core.hybrid_casting_test import fixture, bank
        script = fixture()
        manifest = hybrid_casting(script, bank(), language='en', full_book=True)
        script = apply_hybrid(script, manifest, {r: {'voice_description': 'Mid-low resonant clear English voice.'}
            for r, p in manifest['profiles'].items() if p['voice_mode'] == 'design'})
        script = replace(script, chapters=script.chapters[:1] + script.chapters[5:6])
        config = get_openai_config()
        config.language, config.output_format = 'en-US', 'wav'
        provider = OpenAITTSProvider(config)
        buf = io.BytesIO()
        sf.write(buf, .1 * np.sin(np.arange(48000) * .08), 16000, format='WAV')
        with tempfile.TemporaryDirectory() as root, patch.object(provider, '_request_mimo_chunk', return_value=buf.getvalue()) as request:
            root = Path(root)
            registry = root/'refs.json'
            registry.write_text(json.dumps({'schema_version': 'mimo-role-references-v1', 'references': {}}))
            with self.assertRaises(ValueError):
                run_scenes(script, provider, registry, root/'out')
            self.assertEqual(request.call_count, 0)
            refs = {}
            path = root/'anchor.wav'
            path.write_bytes(buf.getvalue())
            for role, definition in script.roles.items():
                profile = definition.provider_params
                if profile['voice_mode'] != 'design':
                    continue
                review = {'audio_sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'role_id': role,
                    'voice_version': profile['voice_version'], 'content_complete': True,
                    'signal_acceptable': True, 'identity_accepted': True}
                key, record = make_reference(role, profile, 'en', provider.resolve_voice(profile), path,
                    {'peak': .1, 'clipped_fraction': 0}, review)
                refs[key] = record
            registry.write_text(json.dumps({'schema_version': 'mimo-role-references-v1', 'references': refs}))
            evaluator = QualityEvaluator(CoreOptions(language='en'), transcribe=lambda _: 'Good morning.', speaker=lambda _: np.array([1., 0.]))
            result = run_scenes(script, provider, registry, root/'out', evaluator=evaluator)
            self.assertEqual(len(result['chapters']), 2)
            self.assertEqual(result['status'], 'generated_pending_scene_review')
            self.assertTrue(all(Path(c['path']).exists() for c in result['chapters']))
            from audiobook_generator.audio_core.hybrid_loudness import prepare_hybrid_loudness
            from audiobook_generator.audio_core.annotations import _verify_pcm_layout
            originals = {c['path']: hashlib.sha256(Path(c['path']).read_bytes()).hexdigest() for c in result['chapters']}
            with patch('audiobook_generator.audio_core.hybrid_loudness.measure_loudness', side_effect=lambda _: {'integrated_lufs': -23., 'measurement': 'test'}):
                conditioned = prepare_hybrid_loudness(root/'out'/'manifest.json', root/'matched')
            self.assertEqual(conditioned['requests_sent'], 0)
            for path in conditioned['report_paths']:
                descriptor = json.loads(Path(path).read_text())
                self.assertEqual(descriptor['quality_status'], 'incomplete')
                self.assertTrue(all(item['voice_reference_request'] for item in descriptor['chunks']))
                _verify_pcm_layout(descriptor['output_file'], descriptor['assembly'], descriptor['chunks'])
            self.assertEqual(originals, {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in originals})
            count = request.call_count
            with self.assertRaises(ValueError):
                run_scenes(script, provider, registry, root/'out', evaluator=evaluator)
            self.assertEqual(request.call_count, count)
