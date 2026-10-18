"""真实 PCM/编码及任务序列化；只替换外部合成请求。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.core.audiobook_generator import AudiobookGenerator
from audiobook_generator.audio_core.store import ArtifactStore
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake
from tests.audiobook_generator.core import role_script_e2e_test as legacy


class IntegratedProvider(ObservedFake):
    def get_break_string(self):
        return "   "

    def get_output_file_extension(self):
        return "wav"


class IntegrationTest(unittest.TestCase):
    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake', 'https://example.invalid/v1'))
    def test_mixed_role_json_and_ui_reference_settings_survive_main_conversion(self, credentials):
        import hashlib
        import io
        import numpy as np
        import soundfile as sf
        from audiobook_generator.role_script.models import RoleScriptV1, RoleDefinition, ChapterScript, SegmentScript
        from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
        from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
        from audiobook_generator.audio_core.role_references import make_reference
        from audiobook_generator.ui.audio_quality import apply_quality_settings
        from tests.audiobook_generator.audio_core.mimo_design_test import card
        import audiobook_generator.core.audiobook_generator as core

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = legacy.RoleScriptEndToEndTest()._config(directory, role_mode=False)
            config.language, config.voice_name = 'en-US', 'Mia'
            config.audio_core_enabled = True
            config.audio_core_no_asr = config.audio_core_no_speaker = True
            roles = {'narrator': RoleDefinition('Narrator', {'voice': 'Mia', 'voice_mode': 'preset',
                         'voice_language': 'en', 'voice_profile_id': 'narrator', 'voice_version': 'v1'}),
                     'guest': RoleDefinition('Guest', card())}
            chapters = tuple(ChapterScript(i, f'Chapter {i}', (
                SegmentScript('narrator', f'The travelers arrived on day {i}. '),
                SegmentScript('guest', f'Please wait beside the bridge on day {i}.', pause_after_ms=0)))
                for i in (1, 2))
            script = RoleScriptV1(1, 'openai', hashlib.sha256(Path(config.input_file).read_bytes()).hexdigest(),
                                  200, roles, chapters)
            script_path = root / 'mixed.roles.json'
            script_path.write_text(json.dumps(role_script_to_dict(script)))
            config.role_script = str(script_path)
            provider = OpenAITTSProvider(config)
            buffer = io.BytesIO()
            sf.write(buffer, .1 * np.sin(np.arange(48000) * .08), 16000, format='WAV', subtype='PCM_16')
            audio_bytes = buffer.getvalue()
            reference_audio = root / 'reference.wav'
            reference_audio.write_bytes(audio_bytes)
            digest = hashlib.sha256(reference_audio.read_bytes()).hexdigest()
            review = {'audio_sha256': digest, 'role_id': 'guest', 'voice_version': 'v1',
                      'content_complete': True, 'signal_acceptable': True, 'identity_accepted': True}
            # 测试夹具只验证接线；这些确认不写入真实先导记录。
            key, record = make_reference('guest', card(), 'en', provider.resolve_voice(card()),
                                         reference_audio, {'peak': .5, 'clipped_fraction': 0}, review)
            registry = root / 'references.json'
            registry.write_text(json.dumps({'schema_version': 'mimo-role-references-v1',
                                            'references': {key: record}}))
            settings = root / 'settings.json'
            settings.write_text(json.dumps({'role_references': str(registry)}))
            apply_quality_settings(config, settings)
            parser = legacy._FakeBookParser([(c.title, ''.join(s.text for s in c.segments)) for c in chapters])
            with patch.object(core, 'get_book_parser', return_value=parser), \
                    patch.object(core, 'get_tts_provider', return_value=provider), \
                    patch.object(core.multiprocessing, 'get_context', return_value=legacy._SerialContext()), \
                    patch.object(provider, '_request_mimo_chunk', return_value=audio_bytes) as request:
                self.assertTrue(AudiobookGenerator(config).run())
            routes = [call.kwargs['request'] for call in request.call_args_list]
            self.assertEqual([r['mode'] for r in routes], ['preset', 'design', 'preset', 'design'])
            self.assertTrue(all(r['model'] == 'mimo-v2.5-tts-voicedesign' and r['voice'] is None
                                for r in routes if r['mode'] == 'design'))
            reports = [json.loads(p.read_text()) for p in Path(config.output_folder).rglob('quality.json')]
            self.assertEqual(len(reports), 2)
            for report in reports:
                self.assertEqual(report['reading_configuration']['role_references'], str(registry))
                guest = next(c for c in report['chunks'] if c['chunk']['role_id'] == 'guest')
                self.assertEqual(guest['chunk']['profile'], card())
                reference = guest['report']['metrics']['consistency_reference']
                self.assertEqual(reference['kind'], 'human_confirmed_fixed_reference')
                self.assertEqual(reference['sha256'], digest)
                self.assertEqual(reference['path'], str(reference_audio.resolve()))
                self.assertTrue(Path(report['output_file']).is_file())
            self.assertEqual(hashlib.sha256(reference_audio.read_bytes()).hexdigest(), digest)

    def execute(self, root, *, roles=False, chapters=None, request_limit=10, preview=False):
        config = legacy.RoleScriptEndToEndTest()._config(root, role_mode=roles)
        config.audio_core_enabled = True
        config.audio_core_no_asr = config.audio_core_no_speaker = True
        config.audio_core_max_requests = request_limit
        config.preview = preview
        config.no_prompt = True
        provider = IntegratedProvider()
        parser = legacy._FakeBookParser(chapters or [("第一章", "开场。你好。")])
        import audiobook_generator.core.audiobook_generator as core
        with patch.object(core, "get_book_parser", return_value=parser), \
                patch.object(core, "get_tts_provider", return_value=provider), \
                patch.object(core.multiprocessing, "get_context", return_value=legacy._SerialContext()):
            result = AudiobookGenerator(config).run()
        reports = [json.loads(p.read_text()) for p in Path(config.output_folder).rglob("quality.json")]
        return result, config, provider, reports

    def test_normal_and_role_modes_use_observed_pipeline_and_persist_reports(self):
        for roles in (False, True):
            with self.subTest(roles=roles), tempfile.TemporaryDirectory() as root:
                success, config, provider, reports = self.execute(root, roles=roles)
                self.assertTrue(success)
                self.assertEqual(len(reports), 1)
                self.assertEqual(len(provider.calls), 2 if roles else 1)
                self.assertEqual(reports[0]["provider"], "openai")
                self.assertTrue(Path(reports[0]["output_file"]).is_file())
                expected_scope = "unit" if roles else "chapter"  # V1 剧本没有章节原文区间。
                self.assertTrue(all(c["chunk"]["source_scope"] == expected_scope for c in reports[0]["chunks"]))
                from mutagen.wave import WAVE
                self.assertEqual(WAVE(reports[0]["output_file"]).tags["TALB"].text[0], "测试书名")

    def test_request_limit_is_shared_across_chapters_and_failure_is_returned(self):
        with tempfile.TemporaryDirectory() as root:
            success, config, provider, reports = self.execute(root, request_limit=1,
                chapters=[("第一章", "开场。"), ("第二章", "接着讲述。")])
            self.assertFalse(success)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(len(reports), 2)
            failed = next(r for r in reports if r["generation_status"] == "failed")
            self.assertEqual(failed["error_type"], "ResourceExhausted")
            summary = ArtifactStore(config.audio_core_project_root).summary(config.audio_core_run_id)
            self.assertEqual(sum(s["requests"] for s in summary.values()), 1)

    def test_preview_does_not_send_requests(self):
        with tempfile.TemporaryDirectory() as root:
            success, _, provider, reports = self.execute(root, preview=True)
            self.assertTrue(success)
            self.assertEqual(provider.calls, [])
            self.assertEqual(reports, [])
